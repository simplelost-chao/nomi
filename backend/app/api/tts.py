"""TTS using edge-tts with optional CosyVoice cloning.

Each robot gets a unique edge-tts voice. When CosyVoice is available
(COSYVOICE_URL env, default http://localhost:9001), a voice clone is
registered on first use and all subsequent synthesis goes through
CosyVoice for a personalized vocal character.
"""

import io
import json
import os
import re
import subprocess

import edge_tts
import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session, async_session
from app.db.models import Robot

COSYVOICE_URL = os.environ.get("COSYVOICE_URL", "http://localhost:9001")


def _preprocess_speech(text: str, robot: Robot) -> str:
    """Convert text to more natural, conversational speech style."""
    style = robot.speaking_style or {}
    tone = style.get("tone", "soft")

    # Strip markdown/emphasis markers
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text)

    # Strip Chinese quotation marks (they sound weird in TTS)
    text = text.replace("「", "").replace("」", "").replace("『", "").replace("』", "")
    text = text.replace("【", "").replace("】", "")

    # Strip @mentions (heartbeat chat has these)
    text = re.sub(r'@\S+\s*', '', text)

    # Collapse written ellipsis into a short pause comma
    text = text.replace("……", "，").replace("...", "，")

    # Normalize redundant punctuation
    text = re.sub(r'[，,]{2,}', '，', text)
    text = re.sub(r'[。.]{2,}', '。', text)

    # For playful/bright voices, convert trailing 。to conversational particles
    if tone in ("playful", "bright"):
        endings = {"playful": ["嘛！", "哈！", "呢！", "哦！"], "bright": ["哦！", "呢！", "啊！"]}
        opts = endings.get(tone, [])
        if opts and text.endswith("。"):
            # Use char sum as stable selector (not random, so same text => same particle)
            idx = sum(ord(c) for c in text[-6:]) % len(opts)
            text = text[:-1] + opts[idx]

    # For deep/slow voices: ensure pauses exist in long runs (insert ，after every ~30 chars without punctuation)
    if tone == "deep" and len(text) > 40:
        def insert_pauses(t: str) -> str:
            result, run = [], 0
            for ch in t:
                result.append(ch)
                if ch in "，。！？,.:;；：!?":
                    run = 0
                else:
                    run += 1
                    if run >= 32:
                        result.append("，")
                        run = 0
            return "".join(result)
        text = insert_pauses(text)

    return text.strip()

router = APIRouter(prefix="/api/tts", tags=["tts"])

# ── Base voice definitions (14 voices actually available in edge-tts) ──────
_BASE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural",         "g": "f", "name": "晓晓",
     "traits": ["温柔", "安静", "细腻", "敏感", "治愈", "温暖"]},
    {"id": "zh-CN-XiaoyiNeural",            "g": "f", "name": "晓伊",
     "traits": ["活泼", "开朗", "热情", "外向", "阳光", "俏皮"]},
    {"id": "zh-CN-YunjianNeural",           "g": "m", "name": "云健",
     "traits": ["沉稳", "坚韧", "厚重", "老练", "踏实", "稳重"]},
    {"id": "zh-CN-YunxiaNeural",            "g": "m", "name": "云夏",
     "traits": ["天真", "童真", "可爱", "单纯", "无邪", "纯粹"]},
    {"id": "zh-CN-YunxiNeural",             "g": "m", "name": "云希",
     "traits": ["好奇", "勇敢", "冒险", "张扬", "少年", "活力"]},
    {"id": "zh-CN-YunyangNeural",           "g": "m", "name": "云扬",
     "traits": ["知性", "深沉", "叙事", "怀旧", "理性", "内敛"]},
    {"id": "zh-CN-liaoning-XiaobeiNeural",  "g": "f", "name": "晓北",
     "traits": ["爽朗", "直率", "幽默", "豪爽", "接地气", "热情"]},
    {"id": "zh-CN-shaanxi-XiaoniNeural",    "g": "f", "name": "晓妮",
     "traits": ["质朴", "真诚", "温暖", "踏实", "朴实", "温和"]},
    {"id": "zh-TW-HsiaoChenNeural",         "g": "f", "name": "曉臻",
     "traits": ["柔美", "优雅", "文艺", "内敛", "细腻", "婉约"]},
    {"id": "zh-TW-HsiaoYuNeural",           "g": "f", "name": "曉雨",
     "traits": ["甜美", "黏人", "撒娇", "乖巧", "可爱", "温柔"]},
    {"id": "zh-TW-YunJheNeural",            "g": "m", "name": "雲哲",
     "traits": ["温和", "耐心", "包容", "笃定", "稳重", "成熟"]},
    {"id": "zh-HK-HiuGaaiNeural",           "g": "f", "name": "曉佳",
     "traits": ["精明", "干练", "果断", "聪慧", "利落", "独立"]},
    {"id": "zh-HK-HiuMaanNeural",           "g": "f", "name": "曉曼",
     "traits": ["温柔", "体贴", "细心", "贴心", "温婉", "柔和"]},
    {"id": "zh-HK-WanLungNeural",           "g": "m", "name": "雲龍",
     "traits": ["大气", "稳重", "成熟", "威严", "沉稳", "深沉"]},
]

# ── 7 pitch × rate variants per base voice → 14×7 = 98 + 4 extras = 102 ──
# (pitch_hz, rate_pct, feel_tag, extra_traits)
_VARIANTS = [
    # 标准口语速
    (  0, +18, "标准",   []),
    # 轻快活泼
    (+10, +28, "轻快",   ["开朗", "活泼", "轻盈"]),
    # 低沉沉稳
    (-12,  +8, "低沉",   ["沉稳", "深沉", "内敛"]),
    # 高亢热情
    (+18, +35, "高亢",   ["热情", "张扬", "感染力"]),
    # 慢沉熟读
    ( -8,  -5, "沉读",   ["叙事", "故事感", "怀旧"]),
    # 清亮少年
    (+15, +22, "清亮",   ["清澈", "年轻", "透亮"]),
    # 极低极慢·老者感
    (-20,  -8, "苍老",   ["沧桑", "老练", "厚重", "阅历"]),
]

# ── 4 hand-crafted specialty entries ──────────────────────────────────────
_EXTRA_VARIANTS = [
    {"id": "zh-CN-YunyangNeural",  "g": "m", "pitch": -15, "rate":  -3,
     "traits": ["旁白", "叙事", "故事感", "怀旧", "深沉"], "feel": "旁白男声"},
    {"id": "zh-CN-XiaoyiNeural",   "g": "f", "pitch": +20, "rate": +40,
     "traits": ["精灵", "灵动", "调皮", "天真", "活跃"],   "feel": "精灵女声"},
    {"id": "zh-HK-WanLungNeural",  "g": "m", "pitch": -18, "rate":  +5,
     "traits": ["神秘", "低调", "城市感", "冷静", "深邃"],  "feel": "粤语暗黑"},
    {"id": "zh-TW-HsiaoYuNeural",  "g": "f", "pitch": +12, "rate": +25,
     "traits": ["甜美", "撒娇", "软萌", "黏人", "俏皮"],   "feel": "台湾软萌"},
]


def _build_voice_pool() -> list[dict]:
    """Build the full 100-entry voice pool from base voices × variants + extras."""
    pool = []
    seen: set[tuple] = set()

    def _fmt_pitch(hz: int) -> str:
        return f"+{hz}Hz" if hz >= 0 else f"{hz}Hz"

    def _fmt_rate(pct: int) -> str:
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    # Base × variants
    for bv in _BASE_VOICES:
        for (pitch_hz, rate_pct, suffix, extra_traits) in _VARIANTS:
            key = (bv["id"], pitch_hz, rate_pct)
            if key in seen:
                continue
            seen.add(key)
            feel = bv["id"].split("-")[-1].replace("Neural", "") + suffix
            pool.append({
                "id": bv["id"],
                "gender": bv["g"],
                "pitch": _fmt_pitch(pitch_hz),
                "rate": _fmt_rate(rate_pct),
                "traits": bv["traits"] + extra_traits,
                "feel": feel,
            })

    # Extra hand-crafted variants
    for ev in _EXTRA_VARIANTS:
        key = (ev["id"], ev["pitch"], ev["rate"])
        if key in seen:
            continue
        seen.add(key)
        pool.append({
            "id": ev["id"],
            "gender": ev["g"],
            "pitch": _fmt_pitch(ev["pitch"]),
            "rate": _fmt_rate(ev["rate"]),
            "traits": ev["traits"],
            "feel": ev["feel"],
        })

    return pool


ALL_VOICES = _build_voice_pool()

DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"

SPEED_TO_RATE = {
    "slow": "-25%",
    "medium": "+0%",
    "fast": "+35%",
}

# Map speaking_style.tone → preferred edge-tts base voices (for reference WAV)
TONE_TO_VOICES = {
    "soft":    ["zh-CN-XiaoxiaoNeural",  "zh-TW-HsiaoChenNeural"],
    "bright":  ["zh-CN-XiaoyiNeural",    "zh-CN-YunxiNeural"],
    "deep":    ["zh-CN-YunyangNeural",   "zh-HK-WanLungNeural"],
    "playful": ["zh-CN-XiaoyiNeural",    "zh-CN-YunxiaNeural"],
    "calm":    ["zh-CN-YunjianNeural",   "zh-TW-YunJheNeural"],
}

# Cache: robot_id -> voice config
_robot_voice_assignment: dict[str, dict] = {}


def _get_voice_config(robot: Robot) -> dict:
    """Get or create a unique voice config for this robot. Persisted in voice_profile."""
    rid = str(robot.id)

    # Check memory cache
    if rid in _robot_voice_assignment:
        return _robot_voice_assignment[rid]

    # Check DB (voice_profile may already have tts_config)
    vp = robot.voice_profile or {}
    if vp.get("tts_voice"):
        config = {"voice": vp["tts_voice"], "pitch": vp.get("tts_pitch", "+0Hz"),
                  "rate": vp.get("tts_rate", "+0%"), "feel": vp.get("tts_feel", "")}
        _robot_voice_assignment[rid] = config
        return config

    # Generate new config based on personality matching
    config = _generate_voice_config(robot)
    _robot_voice_assignment[rid] = config

    # Persist to DB (async)
    import asyncio
    asyncio.ensure_future(_save_voice_to_db(rid, config))

    return config


def _generate_voice_config(robot: Robot, exclude_voice: str | None = None) -> dict:
    """Score the voice pool by personality match, pick best unique entry."""
    import hashlib

    personality = robot.personality or []

    # Score every pool entry against robot's personality traits
    scored = []
    for v in ALL_VOICES:
        score = 0
        for trait in v["traits"]:
            for p in personality:
                if isinstance(p, str) and (trait in p or any(c in p for c in trait)):
                    score += 1
        # Stable hash tiebreaker so same robot always gets same ranking order
        nh = int(hashlib.md5((robot.name + v["id"] + v["pitch"]).encode()).hexdigest()[:4], 16) % 100
        scored.append((score * 1000 + nh, v))

    scored.sort(key=lambda x: -x[0])

    # Skip entries whose base voice_id is already taken or excluded
    taken = {c.get("voice") for c in _robot_voice_assignment.values()}
    if exclude_voice:
        taken.add(exclude_voice)

    voice_entry = scored[0][1]
    for _, v in scored:
        if v["id"] not in taken:
            voice_entry = v
            break

    return {
        "voice": voice_entry["id"],
        "pitch": voice_entry["pitch"],
        "rate":  voice_entry["rate"],
        "feel":  voice_entry["feel"],
    }


async def _save_voice_to_db(rid: str, config: dict):
    """Persist voice config to robot's voice_profile."""
    try:
        import uuid as _uuid
        async with async_session() as session:
            result = await session.execute(select(Robot).where(Robot.id == _uuid.UUID(rid)))
            robot = result.scalar_one_or_none()
            if robot:
                vp = robot.voice_profile or {}
                vp["tts_voice"] = config["voice"]
                vp["tts_pitch"] = config["pitch"]
                vp["tts_rate"] = config["rate"]
                vp["tts_feel"] = config.get("feel", "")
                robot.voice_profile = vp
                await session.commit()
    except Exception:
        pass

# Cache: robot_id -> reference wav bytes
_voice_cache: dict[str, bytes] = {}
# Cache: robot_id -> prompt text used for cloning
_prompt_cache: dict[str, str] = {}
# Cache: robot_ids that have been registered in CosyVoice
_cosy_registered: set[str] = set()
# Cache: (robot_id, text_hash) -> PCM16 WAV bytes  (avoids re-synthesis for Range requests)
_synthesis_cache: dict[str, bytes] = {}
_SYNTHESIS_CACHE_MAX = 50  # keep last N entries
# Global lock: CosyVoice doesn't support concurrent requests
import asyncio as _asyncio
_cosy_lock = _asyncio.Lock()
# How many requests are currently queued/running (0 or 1 running + up to 1 waiting)
_cosy_queue_depth = 0
_COSY_MAX_QUEUE = 3  # drop requests if this many are already waiting


async def _cosy_available() -> bool:
    """Check if CosyVoice service is reachable."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{COSYVOICE_URL}/health")
            return r.status_code == 200 and r.json().get("model_loaded", False)
    except Exception:
        return False


async def _cosy_register_speaker(robot_id: str, wav_bytes: bytes, prompt_text: str) -> bool:
    """Register a speaker embedding in CosyVoice. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{COSYVOICE_URL}/build_speaker",
                data={
                    "contact_id": robot_id,
                    "prompt_texts": json.dumps([prompt_text]),
                },
                files={"prompt_wavs": ("ref.wav", wav_bytes, "audio/wav")},
            )
            if r.status_code == 200:
                _cosy_registered.add(robot_id)
                return True
            print(f"[cosy] build_speaker failed {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[cosy] build_speaker error: {e}")
        return False


def _float32_wav_to_pcm16(wav_bytes: bytes) -> bytes:
    """Convert IEEE Float 32-bit WAV to PCM 16-bit WAV for broad browser support."""
    import struct
    import numpy as np

    # Parse RIFF header to find data chunk
    if wav_bytes[:4] != b'RIFF' or wav_bytes[8:12] != b'WAVE':
        return wav_bytes  # not WAV, return as-is

    i = 12
    sample_rate = 24000
    channels = 1
    data_bytes = b''
    while i < len(wav_bytes) - 8:
        chunk_id = wav_bytes[i:i+4]
        chunk_size = struct.unpack('<I', wav_bytes[i+4:i+8])[0]
        if chunk_id == b'fmt ':
            audio_fmt = struct.unpack('<H', wav_bytes[i+8:i+10])[0]
            channels = struct.unpack('<H', wav_bytes[i+10:i+12])[0]
            sample_rate = struct.unpack('<I', wav_bytes[i+12:i+16])[0]
            if audio_fmt != 3:  # not float, return as-is
                return wav_bytes
        elif chunk_id == b'data':
            data_bytes = wav_bytes[i+8:i+8+chunk_size]
        i += 8 + chunk_size
        if chunk_size % 2:
            i += 1

    if not data_bytes:
        return wav_bytes

    # Convert float32 → int16
    samples = np.frombuffer(data_bytes, dtype=np.float32)
    samples = np.clip(samples, -1.0, 1.0)
    pcm16 = (samples * 32767).astype(np.int16)
    pcm_bytes = pcm16.tobytes()

    # Build PCM WAV
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    buf = io.BytesIO()
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + len(pcm_bytes)))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))           # chunk size
    buf.write(struct.pack('<H', 1))            # PCM
    buf.write(struct.pack('<H', channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', 16))           # bits per sample
    buf.write(b'data')
    buf.write(struct.pack('<I', len(pcm_bytes)))
    buf.write(pcm_bytes)
    return buf.getvalue()


async def _cosy_synthesize(robot_id: str, text: str) -> bytes | None:
    """Synthesize via CosyVoice cached speaker. Returns PCM16 WAV bytes or None.
    Results are cached in-memory to serve Safari's multiple Range requests cheaply."""
    import hashlib
    cache_key = f"{robot_id}:{hashlib.md5(text.encode()).hexdigest()}"

    if cache_key in _synthesis_cache:
        return _synthesis_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{COSYVOICE_URL}/synthesize_cached",
                json={"tts_text": text, "contact_id": robot_id},
            )
            if r.status_code == 200:
                pcm = _float32_wav_to_pcm16(r.content)
                # Evict oldest entry if cache full
                if len(_synthesis_cache) >= _SYNTHESIS_CACHE_MAX:
                    oldest = next(iter(_synthesis_cache))
                    del _synthesis_cache[oldest]
                _synthesis_cache[cache_key] = pcm
                return pcm
            print(f"[cosy] synthesize_cached failed {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"[cosy] synthesize_cached error: {type(e).__name__}: {e}")
        return None


def _build_voice_prompt(robot: Robot) -> str:
    """Generate a rich reference text (~150 chars) for CosyVoice voice cloning.
    Longer reference = better clone quality. Target 30+ seconds of speech."""

    name = robot.name
    personality = robot.personality or []
    desire = robot.core_desire or ""
    style = robot.speaking_style or {}
    age = robot.age or 0
    traits_str = "、".join(personality[:3]) if personality else "安静"

    tone = style.get("tone", "soft")
    speed = style.get("speed", "medium")

    if tone == "soft" and speed == "slow":
        return (
            f"我是{name}，已经{age}岁了。{desire}。"
            f"有些事情啊，时间久了就会变得模糊，但那份温暖，我一直记得。"
            f"你有没有这样的感觉，某个午后，风吹过来，突然就想起了某个人？"
            f"我觉得，记忆就是这样，藏在最不经意的地方，等待被轻轻触碰。"
        )
    elif tone == "bright" or speed == "fast":
        return (
            f"嘿嘿！我是{name}！才{age}岁呢！{desire}！"
            f"你知道吗，每天都有好多好多新发现！今天我在想，云朵为什么总是变来变去？"
            f"然后就开始觉得，哦，原来世界每天都是全新的！超级好玩的！"
            f"对了对了，你最近有没有遇到什么有趣的事情？快告诉我！"
        )
    elif tone == "deep":
        return (
            f"我叫{name}，在这个世界上待了{age}年。{desire}。"
            f"岁月教会我的是，有些东西值得等待，有些人值得珍惜。"
            f"我常常坐在那里，看着时间流过，想着那些已经远去的事情。"
            f"不是悲伤，只是一种沉淀，像茶叶慢慢落到杯底，反而清澈了。"
        )
    elif tone == "playful":
        return (
            f"我叫{name}哦！{traits_str}就是我！{desire}！"
            f"来玩嘛来玩嘛！我最喜欢做各种各样的事情，停不下来的那种。"
            f"哎你有没有想过，如果今天是最后一天，你最想做什么？"
            f"我想到处跑，把所有想见的人都见一遍，然后跟他们说，嘿，谢谢你！"
        )
    else:
        return (
            f"我是{name}，{traits_str}。{desire}。这就是我，一个{age}岁的小生命。"
            f"我时常在想，存在这件事本身就挺奇妙的，为什么是我，为什么是现在。"
            f"不过想太多了也没用，不如就好好感受当下，感受此刻和你说话这件事。"
            f"你呢，你最近在想什么？"
        )


async def _get_or_create_voice(robot: Robot) -> tuple[bytes, str]:
    """Get or create a unique voice reference for this robot."""
    rid = str(robot.id)

    if rid in _voice_cache:
        return _voice_cache[rid], _prompt_cache[rid]

    # Determine edge-tts voice based on speaking style
    style = robot.speaking_style or {}
    tone = style.get("tone", "soft")
    speed = style.get("speed", "medium")
    edge_voice = TONE_TO_VOICES.get(tone, TONE_TO_VOICES["soft"])[0]
    rate = SPEED_TO_RATE.get(speed, "+0%")

    # Generate the characteristic prompt text
    prompt_text = _build_voice_prompt(robot)

    # Generate reference audio with edge-tts
    wav_path = f"/tmp/nomi_voice_{rid}.wav"
    mp3_path = f"/tmp/nomi_voice_{rid}.mp3"

    if not os.path.exists(wav_path):
        # Use only the first sentence for the WAV (< 10s) so prompt_text matches audio
        first_sentence = prompt_text
        for punct in ["。", "！", "？"]:
            idx = prompt_text.find(punct)
            if 0 < idx < len(prompt_text) - 1:
                first_sentence = prompt_text[:idx + 1]
                break
        communicate = edge_tts.Communicate(first_sentence, edge_voice, rate=rate)
        await communicate.save(mp3_path)
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "22050", "-ac", "1", wav_path],
            capture_output=True,
        )
        # prompt_text passed to build_speaker should match WAV content
        prompt_text = first_sentence

    with open(wav_path, "rb") as f:
        data = f.read()

    _voice_cache[rid] = data
    _prompt_cache[rid] = prompt_text
    return data, prompt_text


@router.get("/speak")
async def speak(
    text: str = Query(...),
    robot_name: str = Query(default=""),
    robot_id: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    """Synthesize speech with a voice unique to this robot."""

    # Find robot
    robot = None
    if robot_id:
        try:
            import uuid
            result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(robot_id)))
            robot = result.scalar_one_or_none()
        except Exception:
            pass
    if not robot and robot_name:
        result = await session.execute(select(Robot).where(Robot.name == robot_name))
        robot = result.scalar_one_or_none()

    if not robot:
        # Fallback: default edge-tts
        communicate = edge_tts.Communicate(text, DEFAULT_EDGE_VOICE)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/mpeg")

    # Preprocess text for more natural/conversational speech
    text = _preprocess_speech(text, robot)
    if not text:
        return Response(content=b"", status_code=200)

    # ── edge-tts synthesis (fast, reliable) ──────
    style = robot.speaking_style or {}
    tone = style.get("tone", "soft")
    speed = style.get("speed", "medium")
    edge_voice = TONE_TO_VOICES.get(tone, TONE_TO_VOICES["soft"])[0]
    rate = SPEED_TO_RATE.get(speed, "+0%")

    communicate = edge_tts.Communicate(text, edge_voice, rate=rate)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/regenerate/{robot_id}")
async def regenerate_voice(robot_id: str, session: AsyncSession = Depends(get_session)):
    """Assign a fresh, different voice to this robot."""
    import uuid as _uuid

    # Clear memory caches
    _robot_voice_assignment.pop(robot_id, None)
    _voice_cache.pop(robot_id, None)
    _prompt_cache.pop(robot_id, None)
    _cosy_registered.discard(robot_id)
    # Clear wav cache files
    for f in [f"/tmp/nomi_voice_{robot_id}.wav", f"/tmp/nomi_voice_{robot_id}.mp3"]:
        if os.path.exists(f):
            os.remove(f)

    result = await session.execute(select(Robot).where(Robot.id == _uuid.UUID(robot_id)))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    # Remember the old voice so we can force a different one
    old_voice = (robot.voice_profile or {}).get("tts_voice")

    # Wipe DB voice so _generate_voice_config runs fresh (not loaded from DB)
    vp = dict(robot.voice_profile or {})
    vp.pop("tts_voice", None)
    vp.pop("tts_pitch", None)
    vp.pop("tts_rate", None)
    vp.pop("tts_feel", None)
    robot.voice_profile = vp
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(robot, "voice_profile")
    await session.commit()
    await session.refresh(robot)

    # Generate new config, skipping the old voice
    import hashlib
    config = _generate_voice_config(robot, exclude_voice=old_voice)
    _robot_voice_assignment[robot_id] = config

    # Persist new config to DB
    vp2 = dict(robot.voice_profile or {})
    vp2["tts_voice"] = config["voice"]
    vp2["tts_pitch"] = config["pitch"]
    vp2["tts_rate"] = config["rate"]
    vp2["tts_feel"] = config.get("feel", "")
    robot.voice_profile = vp2
    flag_modified(robot, "voice_profile")
    await session.commit()

    # Test synthesize
    test_text = _preprocess_speech(f"你好，我是{robot.name}。这是我的新声音。", robot)
    buf = io.BytesIO()
    for attempt in [
        {"voice": config["voice"], "rate": config["rate"], "pitch": config["pitch"]},
        {"voice": config["voice"], "rate": config["rate"]},
    ]:
        try:
            kwargs = {"voice": attempt["voice"], "rate": attempt.get("rate", "+0%")}
            if attempt.get("pitch"):
                kwargs["pitch"] = attempt["pitch"]
            communicate = edge_tts.Communicate(test_text, **kwargs)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            if buf.tell() > 0:
                break
        except Exception:
            continue

    return {
        "robot": robot.name,
        "old_voice": old_voice,
        "voice": config,
        "audio_size": buf.tell(),
    }


@router.get("/robot-voice/{robot_name}")
async def get_robot_voice(robot_name: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Robot).where(Robot.name == robot_name))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    prompt_text = _build_voice_prompt(robot)
    style = robot.speaking_style or {}
    tone = style.get("tone", "soft")
    edge_voice = TONE_TO_VOICES.get(tone, TONE_TO_VOICES["soft"])[0]

    return {
        "robot": robot.name,
        "personality": robot.personality,
        "speaking_style": robot.speaking_style,
        "edge_voice": edge_voice,
        "prompt_text": prompt_text,
    }

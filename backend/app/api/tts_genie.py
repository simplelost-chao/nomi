"""Unified TTS endpoint — routes to CosyVoice2 or Qwen3-TTS based on global config."""
import json
import os
import subprocess
import tempfile
import time

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/tts", tags=["tts"])

# ── Paths ──────────────────────────────────────────────────────────────────
COSYVOICE_URL = os.environ.get("COSYVOICE_URL", "http://localhost:9001")
VOICES_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "desktop", "assets", "voices")
TRAINING_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "GPT-SoVITS", "feng_baobao_data")
QWEN3_VENV_PYTHON = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".venv-qwen-tts", "bin", "python"))
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tts_config.json")

# ── Voice configs (shared by all engines) ──────────────────────────────────
VOICE_CONFIGS = {
    "frieren": {
        "ref_audio": os.path.join(VOICES_BASE, "frieren", "voice_ref.wav"),
        "prompt_text": "あら、お前の前にいるのは。言っておくけど私強いよ。そう、外交ごっこはもう終わり。誰？面会時間ではない。",
        "prompt_lang": "ja",
    },
    "fengbaobao": {
        "ref_audio": os.path.join(TRAINING_BASE, "clip_06.wav"),
        "prompt_text": "过去无可挽回，未来可以改变，每一步都必须要走好",
        "prompt_lang": "zh",
    },
    "nezuko": {
        "ref_audio": os.path.join(VOICES_BASE, "nezuko", "voice_ref.wav"),
        "prompt_text": "そんなに誰かのせいにしたいの? お父さんが病気で死んだのも悪いことみたい",
        "prompt_lang": "ja",
    },
    "anya": {
        "ref_audio": os.path.join(VOICES_BASE, "anya", "voice_ref.wav"),
        "prompt_text": "アーニャがんばる！",
        "prompt_lang": "ja",
    },
}

ROBOT_VOICE_MAP = {
    "フリーレン": "frieren",
    "冯宝宝": "fengbaobao",
    "禰豆子": "nezuko",
    "Anya": "anya",
}

# ── Global TTS config ──────────────────────────────────────────────────────
_DEFAULT_CONFIG = {"engine": "qwen3", "qwen3_model": "1.7b-8bit"}

def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return {**_DEFAULT_CONFIG, **json.load(f)}
    except Exception:
        return dict(_DEFAULT_CONFIG)

def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


@router.get("/config")
async def get_tts_config():
    """Get current TTS engine config."""
    return _load_config()


@router.post("/config")
async def set_tts_config(
    engine: str = Query(default=None),
    qwen3_model: str = Query(default=None),
):
    """Update TTS engine config."""
    cfg = _load_config()
    if engine and engine in ("cosyvoice", "qwen3"):
        cfg["engine"] = engine
    if qwen3_model and qwen3_model in ("1.7b-8bit", "1.7b-bf16", "0.6b-bf16"):
        cfg["qwen3_model"] = qwen3_model
    _save_config(cfg)
    return cfg


# ── Helpers ────────────────────────────────────────────────────────────────
def _ffmpeg_to_mp3(wav_bytes: bytes) -> bytes:
    fd_in, in_path = tempfile.mkstemp(suffix=".wav")
    fd_out, out_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd_in)
    os.close(fd_out)
    try:
        with open(in_path, "wb") as f:
            f.write(wav_bytes)
        subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-acodec", "libmp3lame", "-ar", "24000", "-ac", "1", "-b:a", "128k", out_path],
            capture_output=True, timeout=30,
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in [in_path, out_path]:
            if os.path.exists(p):
                os.unlink(p)


QWEN3_MODELS = {
    "1.7b-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "1.7b-bf16": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "0.6b-bf16": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
}


async def _synthesize_cosyvoice(text: str, config: dict) -> bytes:
    """Synthesize via CosyVoice2."""
    ref_path = config["ref_audio"]
    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(ref_path, "rb") as f:
            r = await client.post(
                f"{COSYVOICE_URL}/synthesize",
                data={"tts_text": text, "prompt_text": config["prompt_text"]},
                files={"prompt_wav": ("ref.wav", f.read(), "audio/wav")},
            )
        if r.status_code != 200:
            print(f"[tts-cosyvoice] Failed: {r.status_code} {r.text[:200]}")
            return b""
        return _ffmpeg_to_mp3(r.content)


async def _synthesize_qwen3(text: str, config: dict, model_size: str) -> bytes:
    """Synthesize via Qwen3-TTS (MLX subprocess)."""
    import asyncio

    ref_audio = os.path.abspath(config["ref_audio"])
    ref_text = config["prompt_text"]
    model_id = QWEN3_MODELS.get(model_size, QWEN3_MODELS["1.7b-8bit"])

    script = f"""
import numpy as np, soundfile as sf, sys
from mlx_audio.tts.utils import load_model
model = load_model({model_id!r})
results = list(model.generate(text={text!r}, ref_audio={ref_audio!r}, ref_text={ref_text!r}))
sf.write(sys.argv[1], np.array(results[0].audio), 24000)
"""
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    mp3_path = out_path.replace(".wav", ".mp3")

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [QWEN3_VENV_PYTHON, "-c", script, out_path],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            print(f"[tts-qwen3] Error: {proc.stderr.decode()[-500:]}")
            return b""
        subprocess.run(
            ["ffmpeg", "-y", "-i", out_path, "-ar", "24000", "-ac", "1", "-b:a", "128k", mp3_path],
            capture_output=True, timeout=30,
        )
        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        for p in [out_path, mp3_path]:
            if os.path.exists(p):
                os.unlink(p)


# ── Unified speak endpoint ─────────────────────────────────────────────────
@router.get("/speak-genie")
async def speak_genie(
    text: str = Query(...),
    emotion: str = Query(default="Normal"),
    character: str = Query(default="frieren"),
    lang: str = Query(default="auto"),
):
    """Unified TTS — routes to selected engine based on global config."""
    start = time.time()
    voice_config = VOICE_CONFIGS.get(character, VOICE_CONFIGS["frieren"])

    if not os.path.exists(voice_config["ref_audio"]):
        print(f"[tts] Ref audio not found: {voice_config['ref_audio']}")
        return Response(content=b"", media_type="audio/mpeg")

    tts_config = _load_config()
    engine = tts_config["engine"]

    try:
        if engine == "cosyvoice":
            audio_bytes = await _synthesize_cosyvoice(text, voice_config)
        else:
            audio_bytes = await _synthesize_qwen3(text, voice_config, tts_config.get("qwen3_model", "1.7b-8bit"))
    except Exception as e:
        import traceback
        print(f"[tts-{engine}] Error: {e}")
        traceback.print_exc()
        return Response(content=b"", media_type="audio/mpeg")

    if not audio_bytes:
        print(f"[tts-{engine}] WARNING: empty audio returned for: {text[:30]}")

    elapsed = time.time() - start
    print(f"[tts-{engine}] {character} in {elapsed:.1f}s ({len(audio_bytes)//1024}KB): {text[:30]}...")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio_bytes)), "Cache-Control": "no-store"},
    )


# ── Direct engine endpoints (for A/B comparison in admin) ──────────────────
@router.get("/speak-qwen3")
async def speak_qwen3(
    text: str = Query(...),
    character: str = Query(default="frieren"),
    model_size: str = Query(default="1.7b-8bit"),
):
    """Direct Qwen3-TTS synthesis (for testing/comparison)."""
    start = time.time()
    config = VOICE_CONFIGS.get(character, VOICE_CONFIGS["frieren"])
    audio_bytes = await _synthesize_qwen3(text, config, model_size)
    elapsed = time.time() - start
    print(f"[tts-qwen3-direct] {character} in {elapsed:.1f}s: {text[:30]}...")
    return Response(content=audio_bytes, media_type="audio/mpeg",
                    headers={"Content-Length": str(len(audio_bytes)), "Cache-Control": "no-store"})


# ── Admin helper endpoints ─────────────────────────────────────────────────
@router.get("/voice-config/{character}")
async def get_voice_config(character: str):
    config = VOICE_CONFIGS.get(character)
    if not config:
        return Response(content=b'{"error":"Unknown character"}', status_code=404)
    return {
        "character": character,
        "ref_audio": os.path.basename(config["ref_audio"]),
        "prompt_text": config["prompt_text"],
        "prompt_lang": config.get("prompt_lang", "?"),
    }


@router.get("/voice-ref-file/{character}")
async def get_voice_ref_file(character: str):
    config = VOICE_CONFIGS.get(character)
    if not config:
        return Response(content=b"", status_code=404)
    path = os.path.abspath(config["ref_audio"])
    if not os.path.exists(path):
        return Response(content=b"", status_code=404)
    mp3_data = _ffmpeg_to_mp3(open(path, "rb").read())
    return Response(content=mp3_data, media_type="audio/mpeg",
                    headers={"Content-Length": str(len(mp3_data))})


@router.get("/training-clip/{character}/{filename}")
async def get_training_clip(character: str, filename: str):
    if character == "fengbaobao":
        base = TRAINING_BASE
    else:
        base = os.path.join(VOICES_BASE, character)
    path = os.path.join(base, filename)
    if not os.path.exists(path) or ".." in filename:
        return Response(content=b"", status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type="audio/wav", filename=filename)


@router.get("/training-clips/{character}")
async def list_training_clips(character: str):
    if character == "fengbaobao":
        base = TRAINING_BASE
    else:
        base = os.path.join(VOICES_BASE, character)
    if not os.path.exists(base):
        return []
    clips = sorted(f for f in os.listdir(base) if f.endswith(".wav"))
    return [{"filename": f} for f in clips]

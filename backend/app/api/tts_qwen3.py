"""TTS endpoint using Qwen3-TTS via mlx-audio (Apple Silicon native)."""
import os
import subprocess
import tempfile
import time

from fastapi import APIRouter, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/tts", tags=["tts-qwen3"])

QWEN3_VENV_PYTHON = os.path.join(
    os.path.dirname(__file__), "..", "..", ".venv-qwen-tts", "bin", "python"
)

VOICE_CONFIGS = {
    "frieren": {
        "ref_audio": os.path.join(os.path.dirname(__file__), "..", "..", "..", "desktop", "assets", "voices", "frieren", "voice_ref.wav"),
        "ref_text": "あら、お前の前にいるのは。言っておくけど私強いよ。そう、外交ごっこはもう終わり。誰？面会時間ではない。",
    },
    "fengbaobao": {
        "ref_audio": os.path.join(os.path.dirname(__file__), "..", "..", "..", "GPT-SoVITS", "feng_baobao_data", "clip_09.wav"),
        "ref_text": "不好走，不要开那么快你跟我不一样，不是长生不老",
    },
}


QWEN3_MODELS = {
    "1.7b-8bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    "1.7b-bf16": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "0.6b-bf16": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
}


@router.get("/speak-qwen3")
async def speak_qwen3(
    text: str = Query(...),
    character: str = Query(default="frieren"),
    model_size: str = Query(default="1.7b-8bit"),
):
    """Synthesize speech via Qwen3-TTS (MLX, Apple Silicon native)."""
    import asyncio

    start = time.time()
    config = VOICE_CONFIGS.get(character, VOICE_CONFIGS["frieren"])

    ref_audio = os.path.abspath(config["ref_audio"])
    ref_text = config["ref_text"]
    model_id = QWEN3_MODELS.get(model_size, QWEN3_MODELS["1.7b-8bit"])

    # Run in subprocess using the dedicated venv
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
            [os.path.abspath(QWEN3_VENV_PYTHON), "-c", script, out_path],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            print(f"[qwen3-tts] Error: {proc.stderr.decode()[-500:]}")
            return Response(content=b"", media_type="audio/mpeg")

        # Convert to MP3
        subprocess.run(
            ["ffmpeg", "-y", "-i", out_path, "-ar", "24000", "-ac", "1", "-b:a", "128k", mp3_path],
            capture_output=True, timeout=30,
        )
        with open(mp3_path, "rb") as f:
            mp3_data = f.read()
    finally:
        for p in [out_path, mp3_path]:
            if os.path.exists(p):
                os.unlink(p)

    elapsed = time.time() - start
    print(f"[qwen3-tts] {character} in {elapsed:.1f}s ({len(mp3_data)//1024}KB): {text[:30]}...")

    return Response(
        content=mp3_data,
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(mp3_data)), "Cache-Control": "no-store"},
    )

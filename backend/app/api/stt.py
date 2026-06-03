"""Speech-to-Text using faster-whisper (local)."""

import io
import logging

from fastapi import APIRouter, File, UploadFile

router = APIRouter(prefix="/api/stt", tags=["stt"])
logger = logging.getLogger(__name__)

# Lazy-loaded model
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.info("[stt] Loading whisper model (medium)...")
        _model = WhisperModel("medium", device="cpu", compute_type="int8")
        logger.info("[stt] Model loaded.")
    return _model


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe audio to text using local faster-whisper."""
    data = await file.read()
    model = _get_model()

    segments, info = model.transcribe(
        io.BytesIO(data),
        language="zh",
        beam_size=5,
        vad_filter=True,
    )

    text = "".join(seg.text for seg in segments).strip()
    return {"text": text, "language": info.language or ""}

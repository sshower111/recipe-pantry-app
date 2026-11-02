"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


@dataclass
class Transcript:
    text: str
    language: str
    duration: float


@lru_cache(maxsize=2)
def load_model(size: str, device: str, compute_type: str) -> "WhisperModel":
    # Imported lazily: loading ctranslate2 is slow and not needed for DB-only commands.
    from faster_whisper import WhisperModel

    log.info("Loading Whisper model %s (%s, %s)", size, device, compute_type)
    return WhisperModel(size, device=device, compute_type=compute_type)


def has_audio(path: Path) -> bool:
    """True if the file has an audio stream. Some reels are silent and Instagram then
    serves a video-only file, which faster-whisper fails on ("tuple index out of range")."""
    import av  # installed with faster-whisper

    with av.open(str(path)) as container:
        return bool(container.streams.audio)


def transcribe(
    audio_path: Path,
    *,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
) -> Transcript:
    """Transcribe an audio (or video) file. Any container PyAV can decode works."""
    model = load_model(model_size, device, compute_type)
    # VAD filtering skips background-music-only stretches common in reels.
    segments, info = model.transcribe(
        str(audio_path), language=language, beam_size=5, vad_filter=True
    )
    text = " ".join(segment.text.strip() for segment in segments)  # consumes the generator
    return Transcript(text=text.strip(), language=info.language, duration=info.duration)

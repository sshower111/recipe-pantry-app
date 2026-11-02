"""Application settings, loaded from environment variables (and an optional .env file).

Every variable is prefixed with ``RECIPE_``; see ``.env.example`` for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"RECIPE_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_bool(name: str, default: str) -> bool | None:
    """Like _env_bool, but "default" (or empty) means None: leave it to the model."""
    value = _env(name, default).strip().lower()
    return None if value in {"", "default"} else value in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in _env(name, default).split(",") if item.strip())


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = _env(name, default).strip().lower()
    if value not in choices:
        raise ValueError(f"RECIPE_{name} must be one of {', '.join(choices)}, not {value!r}")
    return value


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    downloads_dir: Path

    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    ollama_num_ctx: int
    ollama_think: bool | None

    whisper_model: str
    whisper_device: str
    whisper_compute_type: str

    prefer_captions: bool
    caption_langs: tuple[str, ...]
    max_transcript_chars: int
    keep_media: bool

    # OCR of on-screen text: "auto" (fallback when the first parse looks incomplete),
    # "always", or "off".
    ocr_mode: str
    ocr_languages: tuple[str, ...]
    ocr_gpu: bool
    ocr_fps: float
    ocr_max_frames: int

    # Fetch the recipe page a caption links to when the video's own text is incomplete.
    recipe_pages: bool

    pantry_staples: tuple[str, ...]


def load_settings() -> Settings:
    data_dir = _resolve(_env("DATA_DIR", "data"))
    return Settings(
        data_dir=data_dir,
        db_path=_resolve(_env("DB_PATH", str(data_dir / "recipes.db"))),
        downloads_dir=data_dir / "downloads",
        ollama_url=_env("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env("OLLAMA_MODEL", "qwen2.5:7b"),
        ollama_timeout=float(_env("OLLAMA_TIMEOUT", "180")),
        ollama_num_ctx=int(_env("OLLAMA_NUM_CTX", "8192")),
        ollama_think=_env_optional_bool("OLLAMA_THINK", "false"),
        whisper_model=_env("WHISPER_MODEL", "small"),
        whisper_device=_env("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=_env("WHISPER_COMPUTE_TYPE", "int8"),
        prefer_captions=_env_bool("PREFER_CAPTIONS", True),
        caption_langs=_env_list("CAPTION_LANGS", "en,en-orig,en-US,en-GB"),
        max_transcript_chars=int(_env("MAX_TRANSCRIPT_CHARS", "12000")),
        keep_media=_env_bool("KEEP_MEDIA", False),
        ocr_mode=_env_choice("OCR", "auto", ("auto", "always", "off")),
        ocr_languages=_env_list("OCR_LANGS", "en"),
        ocr_gpu=_env_bool("OCR_GPU", False),
        ocr_fps=float(_env("OCR_FPS", "1")),
        ocr_max_frames=int(_env("OCR_MAX_FRAMES", "60")),
        recipe_pages=_env_bool("RECIPE_PAGES", True),
        pantry_staples=_env_list("PANTRY_STAPLES", "salt,black pepper,water,oil"),
    )


settings = load_settings()

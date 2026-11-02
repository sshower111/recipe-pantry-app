"""End-to-end ingestion: URL -> media -> transcript -> structured recipe -> SQLite."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Literal

from config import Settings, settings as default_settings
from db import find_recipe_id, save_recipe
from pipeline.downloader import MediaAssets, download_media, download_video
from pipeline.parser import ParsedRecipe, parse_recipe
from pipeline.urls import canonical_url

log = logging.getLogger(__name__)

# Captions shorter than this are usually just "[Music]" and not worth trusting.
MIN_CAPTION_CHARS = 40
# With OCR on "auto", a parse with fewer ingredients than this triggers the OCR fallback.
MIN_INGREDIENTS = 3


@dataclass
class IngestResult:
    recipe_id: int
    source_url: str
    status: Literal["added", "updated", "skipped"]
    # The fields below are None for skipped URLs.
    recipe: ParsedRecipe | None = None
    transcript_source: str | None = None
    ingredient_sources: list[str] | None = None


def choose_transcript(media: MediaAssets, cfg: Settings) -> tuple[str, str]:
    """Return (text, source) where source is 'captions', 'whisper', or 'none'."""
    if cfg.prefer_captions and len(media.caption_text) >= MIN_CAPTION_CHARS:
        return media.caption_text, "captions"
    if media.audio_path is not None:
        from pipeline.transcriber import has_audio, transcribe

        if not has_audio(media.audio_path):
            log.info("No audio track in %s; skipping Whisper", media.audio_path.name)
            return (media.caption_text, "captions") if media.caption_text else ("", "none")
        log.info("Transcribing %s with Whisper", media.audio_path.name)
        result = transcribe(
            media.audio_path,
            model_size=cfg.whisper_model,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
        )
        if result.text:
            return result.text, "whisper"
    if media.caption_text:
        return media.caption_text, "captions"
    return "", "none"


def ingredient_sources(recipe: ParsedRecipe, transcript_source: str) -> list[str]:
    """Translate the parser's prompt sections into where the text actually came from."""
    transcript_kind = "captions" if transcript_source == "captions" else "speech"
    return [transcript_kind if s == "transcript" else s for s in recipe.sources]


def looks_incomplete(recipe: ParsedRecipe | None) -> bool:
    """True when the parse is too thin to trust: few ingredients, or no amounts at all
    (common when a video names ingredients aloud but only shows quantities on screen)."""
    if recipe is None:
        return True
    ingredients = recipe.ingredients
    return len(ingredients) < MIN_INGREDIENTS or all(i.amount is None for i in ingredients)


def read_video_text(url: str, cfg: Settings) -> str:
    """Download the video and OCR its frames. OCR is a best-effort fallback, so any
    failure (EasyOCR missing, no video stream, ffmpeg error) is logged and gives ""."""
    from pipeline.ocr import read_on_screen_text

    video = None
    try:
        log.info("Downloading video for OCR")
        video = download_video(url, cfg.downloads_dir)
        text = read_on_screen_text(
            video,
            cfg.downloads_dir,
            languages=cfg.ocr_languages,
            gpu=cfg.ocr_gpu,
            fps=cfg.ocr_fps,
            max_frames=cfg.ocr_max_frames,
        )
    except Exception as exc:
        log.warning("On-screen text OCR skipped: %s", exc)
        return ""
    finally:
        if video is not None and not cfg.keep_media:
            video.unlink(missing_ok=True)
    log.info("OCR found %d distinct lines of on-screen text", len(text.splitlines()))
    return text


def _parse(media: MediaAssets, transcript: str, on_screen: str, cfg: Settings, source: str) -> ParsedRecipe:
    extra = " + on-screen text" if on_screen else ""
    log.info("Parsing recipe with %s (transcript from %s%s)", cfg.ollama_model, source, extra)
    return parse_recipe(
        title=media.title,
        description=media.description,
        transcript=transcript,
        on_screen=on_screen,
        model=cfg.ollama_model,
        base_url=cfg.ollama_url,
        timeout=cfg.ollama_timeout,
        num_ctx=cfg.ollama_num_ctx,
        think=cfg.ollama_think,
        max_chars=cfg.max_transcript_chars,
    )


def ingest_url(
    url: str,
    conn: sqlite3.Connection,
    cfg: Settings = default_settings,
    *,
    skip_existing: bool = False,
) -> IngestResult:
    """Ingest one URL. Recipes are keyed by canonical URL, so a URL that is already
    stored is either skipped (``skip_existing``, before any download) or re-parsed and
    updated in place."""
    source_url = canonical_url(url)
    existing_id = find_recipe_id(conn, source_url)
    if existing_id is not None and skip_existing:
        log.info("Skipping %s: already stored as recipe %d", source_url, existing_id)
        return IngestResult(recipe_id=existing_id, source_url=source_url, status="skipped")

    log.info("Downloading %s", url)
    media = download_media(url, cfg.downloads_dir, caption_langs=cfg.caption_langs)
    try:
        transcript, source = choose_transcript(media, cfg)
        has_text = bool(transcript or media.description)
        on_screen: str | None = None
        recipe: ParsedRecipe | None = None

        if cfg.ocr_mode == "always" or (cfg.ocr_mode == "auto" and not has_text):
            on_screen = read_video_text(media.url or url, cfg)
        if has_text or on_screen:
            recipe = _parse(media, transcript, on_screen or "", cfg, source)

        if cfg.ocr_mode == "auto" and on_screen is None and looks_incomplete(recipe):
            log.info("Recipe looks incomplete; checking on-screen text")
            on_screen = read_video_text(media.url or url, cfg)
            if on_screen:
                retry = _parse(media, transcript, on_screen, cfg, source)
                if recipe is None or len(retry.ingredients) >= len(recipe.ingredients):
                    recipe = retry

        if recipe is None:
            raise ValueError(f"No captions, speech, description, or on-screen text found for {url}")

        sources = ingredient_sources(recipe, source)
        # Prefer yt-dlp's resolved URL (follows short links); fall back to the input.
        source_url = canonical_url(media.url or url)
        existed = find_recipe_id(conn, source_url) is not None
        recipe_id = save_recipe(
            conn,
            source_url=source_url,
            title=recipe.title or media.title,
            ingredients=[i.model_dump() for i in recipe.ingredients],
            yield_label=recipe.yield_label,
            ingredient_sources=sources,
            video_id=media.video_id,
            uploader=media.uploader,
            description=media.description,
            transcript=transcript,
            transcript_source=source,
            on_screen_text=on_screen,
            raw_llm_json=recipe.model_dump_json(),
        )
        return IngestResult(
            recipe_id=recipe_id,
            source_url=source_url,
            status="updated" if existed else "added",
            recipe=recipe,
            transcript_source=source,
            ingredient_sources=sources,
        )
    finally:
        if not cfg.keep_media:
            for path in media.files():
                path.unlink(missing_ok=True)

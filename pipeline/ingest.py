"""End-to-end ingestion: URL -> media -> transcript -> structured recipe -> SQLite."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Literal

from config import Settings, settings as default_settings
from db import find_recipe_id, get_recipe, save_recipe, set_status_note
from pipeline.downloader import MediaAssets, download_media, download_video
from pipeline.parser import ParsedRecipe, parse_recipe
from pipeline.urls import canonical_url, classify_missing_recipe, recipe_link
from pipeline.webrecipe import RecipePageError, WebRecipe, fetch_recipe_page

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
    description: str | None = None
    title: str | None = None  # as stored
    recipe_status: str | None = None  # ready | needs_recipe | not_recipe
    status_note: str | None = None


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


def read_recipe_page(description: str) -> tuple[WebRecipe | None, str | None]:
    """Fetch the recipe page the caption links to, if any. Best effort, like OCR: failures
    (no link, home-page link, site blocks bots, no recipe data) are logged, and returned as
    the second item so they can be noted on the recipe."""
    link = recipe_link(description)
    if link is None:
        return None, None
    try:
        log.info("Fetching recipe page %s", link)
        page = fetch_recipe_page(link)
    except RecipePageError as exc:
        log.warning("Recipe page skipped: %s", exc)
        return None, str(exc)
    log.info("Recipe page has %d ingredient lines", len(page.ingredients))
    return page, None


@dataclass
class ParseInputs:
    title: str
    description: str
    transcript: str
    transcript_source: str
    on_screen: str | None = None
    page: WebRecipe | None = None
    page_error: str | None = None


def _parse(inputs: ParseInputs, cfg: Settings) -> ParsedRecipe:
    extra = "".join([" + on-screen text" if inputs.on_screen else "", " + recipe page" if inputs.page else ""])
    log.info("Parsing recipe with %s (transcript from %s%s)", cfg.ollama_model, inputs.transcript_source, extra)
    return parse_recipe(
        title=inputs.title,
        description=inputs.description,
        transcript=inputs.transcript,
        on_screen=inputs.on_screen or "",
        recipe_page=inputs.page.as_text() if inputs.page else "",
        model=cfg.ollama_model,
        base_url=cfg.ollama_url,
        timeout=cfg.ollama_timeout,
        num_ctx=cfg.ollama_num_ctx,
        think=cfg.ollama_think,
        max_chars=cfg.max_transcript_chars,
    )


# Placeholders the model sometimes writes instead of an empty title.
_NO_TITLE = {"", "none", "null", "n/a", "untitled", "unknown"}


def fallback_title(parsed_title: str, media: MediaAssets) -> str:
    """Never store an empty title: the model's, else the platform's, else who posted it."""
    for title in (parsed_title, media.title):
        if title and title.strip().lower() not in _NO_TITLE:
            return title.strip()
    return f"Post by {media.uploader}" if media.uploader else f"Post {media.video_id}"


def _better(retry: ParsedRecipe, current: ParsedRecipe | None) -> ParsedRecipe:
    return retry if current is None or len(retry.ingredients) >= len(current.ingredients) else current


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
        inputs = ParseInputs(media.title, media.description, transcript, source)
        has_text = bool(transcript or media.description)
        recipe: ParsedRecipe | None = None

        if cfg.ocr_mode == "always" or (cfg.ocr_mode == "auto" and not has_text):
            inputs.on_screen = read_video_text(media.url or url, cfg)
        if has_text or inputs.on_screen:
            recipe = _parse(inputs, cfg)

        # Fallbacks for a thin parse, cheapest first: the recipe page the caption links to,
        # then the text shown in the video.
        if cfg.recipe_pages and looks_incomplete(recipe):
            inputs.page, inputs.page_error = read_recipe_page(media.description)
            if inputs.page:
                recipe = _better(_parse(inputs, cfg), recipe)
        if cfg.ocr_mode == "auto" and inputs.on_screen is None and looks_incomplete(recipe):
            log.info("Recipe looks incomplete; checking on-screen text")
            inputs.on_screen = read_video_text(media.url or url, cfg)
            if inputs.on_screen:
                recipe = _better(_parse(inputs, cfg), recipe)

        if recipe is None:
            raise ValueError(f"No captions, speech, description, or on-screen text found for {url}")

        # A post without an ingredient list has no source for one, whatever the model says.
        sources = ingredient_sources(recipe, source) if recipe.ingredients else []
        # Prefer yt-dlp's resolved URL (follows short links); fall back to the input.
        source_url = canonical_url(media.url or url)
        existed = find_recipe_id(conn, source_url) is not None
        title = fallback_title(recipe.title, media)
        status = "ready" if recipe.ingredients else classify_missing_recipe(media.description)
        note = None if recipe.ingredients else inputs.page_error
        recipe_id = save_recipe(
            conn,
            source_url=source_url,
            title=title,
            ingredients=[i.model_dump() for i in recipe.ingredients],
            yield_label=recipe.yield_label,
            ingredient_sources=sources,
            video_id=media.video_id,
            uploader=media.uploader,
            description=media.description,
            transcript=transcript,
            transcript_source=source,
            on_screen_text=inputs.on_screen,
            recipe_page_url=inputs.page.url if inputs.page else None,
            recipe_page_text=inputs.page.as_text() if inputs.page else None,
            raw_llm_json=recipe.model_dump_json(),
            status=status,
            status_note=note,
        )
        return IngestResult(
            recipe_id=recipe_id,
            source_url=source_url,
            status="updated" if existed else "added",
            recipe=recipe,
            transcript_source=source,
            ingredient_sources=sources,
            description=media.description,
            title=title,
            recipe_status=status,
            status_note=note,
        )
    finally:
        if not cfg.keep_media:
            for path in media.files():
                path.unlink(missing_ok=True)


def import_recipe_page(
    conn: sqlite3.Connection, recipe_id: int, cfg: Settings = default_settings, *, url: str | None = None
) -> IngestResult:
    """Re-parse a stored recipe with the ingredient list from its recipe web page: ``url``,
    or else the link in its caption. Uses the stored text, so nothing is downloaded again.
    Raises ValueError / RecipePageError when there is no usable page."""
    stored = get_recipe(conn, recipe_id)
    if stored is None:
        raise ValueError(f"No recipe with id {recipe_id}")
    link = url or recipe_link(stored["description"] or "")
    if link is None:
        raise ValueError(f"Recipe {recipe_id}'s caption has no recipe link; pass one with --url")
    log.info("Fetching recipe page %s", link)
    try:
        page = fetch_recipe_page(link)
    except RecipePageError as exc:
        set_status_note(conn, recipe_id, str(exc))  # remembered for `list --todo`
        raise
    inputs = ParseInputs(
        title=stored["title"],
        description=stored["description"] or "",
        transcript=stored["transcript"] or "",
        transcript_source=stored["transcript_source"] or "none",
        on_screen=stored["on_screen_text"],
        page=page,
    )
    recipe = _parse(inputs, cfg)
    if not recipe.ingredients:
        message = f"No ingredients could be read from {page.url}"
        set_status_note(conn, recipe_id, message)
        raise ValueError(message)
    sources = ingredient_sources(recipe, inputs.transcript_source)
    save_recipe(
        conn,
        source_url=stored["source_url"],
        title=recipe.title.strip() or stored["title"],
        ingredients=[i.model_dump() for i in recipe.ingredients],
        yield_label=recipe.yield_label,
        ingredient_sources=sources,
        video_id=stored["video_id"],
        uploader=stored["uploader"],
        description=stored["description"],
        transcript=stored["transcript"],
        transcript_source=stored["transcript_source"],
        on_screen_text=stored["on_screen_text"],
        recipe_page_url=page.url,
        recipe_page_text=page.as_text(),
        raw_llm_json=recipe.model_dump_json(),
    )
    return IngestResult(
        recipe_id=recipe_id,
        source_url=stored["source_url"],
        status="updated",
        recipe=recipe,
        transcript_source=inputs.transcript_source,
        ingredient_sources=sources,
        description=stored["description"],
        title=recipe.title.strip() or stored["title"],
        recipe_status="ready",
    )

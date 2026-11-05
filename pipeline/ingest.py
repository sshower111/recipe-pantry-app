"""End-to-end ingestion: URL -> media -> transcript -> structured recipe -> SQLite."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests

from config import Settings, settings as default_settings
from db import find_recipe_id, get_recipe, save_recipe, set_short_steps, set_status_note
from pipeline.downloader import MediaAssets, download_media, download_video
from pipeline.parser import (
    Ingredient, OllamaError, ParsedRecipe, VisualRecipe, ingredient_line, parse_recipe, parse_visual_recipe,
    shorten_steps,
)
from pipeline.thumbnails import save_thumbnail
from pipeline.urls import canonical_url, classify_missing_recipe, recipe_link
from pipeline.webrecipe import RecipePageError, WebRecipe, fetch_recipe_page, read_recipe_file

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


_WORD = re.compile(r"\w+")
# Whisper / auto-caption sound tags ("[Music]", "(applause)", "♪ ... ♪") that aren't speech.
_SOUND_TAG = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪")


def count_words(text: str) -> int:
    """Spoken words in a transcript, not counting sound tags like "[Music]"."""
    return len(_WORD.findall(_SOUND_TAG.sub(" ", text)))


def is_silent(transcript: str, transcript_source: str, min_words: int) -> bool:
    """True for a silent or music-only video: real captions count as speech, otherwise
    Whisper heard fewer than ``min_words`` words (often a stray "Thank you." over music)."""
    if transcript_source == "captions" and len(transcript) >= MIN_CAPTION_CHARS:
        return False
    return count_words(transcript) < min_words


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


class VideoFile:
    """The video stream, downloaded on first use and shared by OCR and the visual parse
    (``download_media`` only fetches audio). A failed download is remembered, not retried."""

    def __init__(self, url: str, cfg: Settings):
        self.url, self.cfg = url, cfg
        self._path: Path | None = None
        self._error: Exception | None = None

    def path(self) -> Path:
        if self._error is not None:
            raise self._error
        if self._path is None:
            log.info("Downloading video")
            try:
                self._path = download_video(self.url, self.cfg.downloads_dir)
            except Exception as exc:
                self._error = exc
                raise
        return self._path

    def close(self) -> None:
        if self._path is not None and not self.cfg.keep_media:
            self._path.unlink(missing_ok=True)
        self._path = None


def read_video_text(video: VideoFile, cfg: Settings) -> str:
    """OCR the video's frames. OCR is a best-effort fallback, so any failure (EasyOCR
    missing, no video stream, ffmpeg error) is logged and gives ""."""
    from pipeline.ocr import read_on_screen_text

    try:
        text = read_on_screen_text(
            video.path(),
            cfg.downloads_dir,
            languages=cfg.ocr_languages,
            gpu=cfg.ocr_gpu,
            fps=cfg.ocr_fps,
            max_frames=cfg.ocr_max_frames,
        )
    except Exception as exc:
        log.warning("On-screen text OCR skipped: %s", exc)
        return ""
    log.info("OCR found %d distinct lines of on-screen text", len(text.splitlines()))
    return text


def read_video_steps(
    video: VideoFile, cfg: Settings, *, title: str, description: str, on_screen: str, known_ingredients: list[str]
) -> VisualRecipe | None:
    """Sample timestamped keyframes and have the vision model write the method from them.
    Best effort, like OCR: any failure (no video, ffmpeg, a model without image input,
    bad output) is logged and gives None."""
    from pipeline.frames import extract_keyframes

    frames_dir = cfg.downloads_dir / "keyframes"
    try:
        path = video.path()
        frames_dir = cfg.downloads_dir / f"{path.stem}_keyframes"
        frames = extract_keyframes(
            path, frames_dir, interval=cfg.visual_interval, scene_threshold=cfg.visual_scene,
            max_frames=cfg.visual_max_frames, width=cfg.visual_frame_width,
        )
        log.info("Reading %d keyframes with %s", len(frames), cfg.visual_model)
        visual = parse_visual_recipe(
            [(f.timestamp, f.path.read_bytes()) for f in frames],
            title=title, description=description, on_screen=on_screen, known_ingredients=known_ingredients,
            model=cfg.visual_model, base_url=cfg.ollama_url, timeout=cfg.visual_timeout,
            num_ctx=cfg.visual_num_ctx, think=cfg.ollama_think,
        )
    except Exception as exc:
        log.warning("Visual step parse skipped: %s", exc)
        return None
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
    log.info("Visual parse found %d steps", len(visual.steps))
    return visual


def merge_visual(recipe: ParsedRecipe | None, visual: VisualRecipe) -> tuple[ParsedRecipe, list[float | None]]:
    """Fill what the text parse lacks from the frames: the steps (with their start times)
    when it has none, and the ingredient names the steps use (no amounts) when it has no
    ingredients. Written text wins wherever it exists. Returns the recipe and step times."""
    if recipe is None:
        recipe = ParsedRecipe(title=visual.title, sources=[], yield_label=None, ingredients=[])
    times: list[float | None] = []
    update: dict = {}
    if not recipe.steps and visual.steps:
        update["steps"] = [s.instruction for s in visual.steps]
        times = [s.timestamp_start for s in visual.steps]
    if not recipe.ingredients and visual.ingredient_names():
        update["ingredients"] = [Ingredient(name=n) for n in visual.ingredient_names()]
        update["sources"] = []  # labelled "visual" by ingredient_sources' caller
    if not recipe.title.strip() and visual.title:
        update["title"] = visual.title
    return recipe.model_copy(update=update), times


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
    page_text: str | None = None  # a previously stored recipe page, when ``page`` is None


def _parse(inputs: ParseInputs, cfg: Settings) -> ParsedRecipe:
    page_text = inputs.page.as_text() if inputs.page else (inputs.page_text or "")
    extra = "".join([" + on-screen text" if inputs.on_screen else "", " + recipe page" if page_text else ""])
    log.info("Parsing recipe with %s (transcript from %s%s)", cfg.ollama_model, inputs.transcript_source, extra)
    return parse_recipe(
        title=inputs.title,
        description=inputs.description,
        transcript=inputs.transcript,
        on_screen=inputs.on_screen or "",
        recipe_page=page_text,
        model=cfg.ollama_model,
        base_url=cfg.ollama_url,
        timeout=cfg.ollama_timeout,
        num_ctx=cfg.ollama_num_ctx,
        think=cfg.ollama_think,
        max_chars=cfg.max_transcript_chars,
    )


def short_steps(steps: list[str], ingredients: list[str], cfg: Settings) -> list[str | None]:
    """Island versions of ``steps``; a failure is logged and leaves them empty (the app
    falls back to shortening the full text itself), never failing the save."""
    if not steps:
        return []
    log.info("Shortening %d steps with %s", len(steps), cfg.ollama_model)
    try:
        return shorten_steps(
            steps, ingredients=ingredients, model=cfg.ollama_model, base_url=cfg.ollama_url,
            timeout=cfg.ollama_timeout, num_ctx=cfg.ollama_num_ctx, think=cfg.ollama_think,
        )
    except (OllamaError, requests.RequestException) as exc:
        log.warning("Steps not shortened: %s", exc)
        return []


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
    video = VideoFile(media.url or url, cfg)
    try:
        transcript, source = choose_transcript(media, cfg)
        inputs = ParseInputs(media.title, media.description, transcript, source)
        has_text = bool(transcript or media.description)
        silent = is_silent(transcript, source, cfg.visual_min_words)
        if silent:
            log.info("Little or no speech (%d words): silent/visual-only video", count_words(transcript))
        recipe: ParsedRecipe | None = None
        step_times: list[float | None] = []
        from_frames = False

        if cfg.ocr_mode == "always" or (cfg.ocr_mode == "auto" and not has_text):
            inputs.on_screen = read_video_text(video, cfg)
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
            inputs.on_screen = read_video_text(video, cfg)
            if inputs.on_screen:
                recipe = _better(_parse(inputs, cfg), recipe)
        # Last and most expensive: nobody says the method, so watch the video for it.
        if cfg.visual_mode == "auto" and silent and (recipe is None or not recipe.steps or looks_incomplete(recipe)):
            visual = read_video_steps(
                video, cfg, title=media.title, description=media.description, on_screen=inputs.on_screen or "",
                known_ingredients=[ingredient_line(i.name, i.amount, i.unit) for i in recipe.ingredients] if recipe else [],
            )
            if visual is not None and visual.steps:
                had_ingredients = bool(recipe and recipe.ingredients)
                recipe, step_times = merge_visual(recipe, visual)
                from_frames = bool(recipe.ingredients) and not had_ingredients

        if recipe is None:
            raise ValueError(f"No captions, speech, description, or on-screen text found for {url}")

        # A post without an ingredient list has no source for one, whatever the model says.
        if from_frames:
            sources = ["visual"]
        else:
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
            steps=recipe.steps,
            short_steps=short_steps(recipe.steps, [i.name for i in recipe.ingredients], cfg),
            step_times=step_times,
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
        save_thumbnail(conn, recipe_id, media.thumbnail_url, cfg.data_dir / "thumbnails")
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
        video.close()
        if not cfg.keep_media:
            for path in media.files():
                path.unlink(missing_ok=True)


def import_recipe_page(
    conn: sqlite3.Connection,
    recipe_id: int,
    cfg: Settings = default_settings,
    *,
    url: str | None = None,
    file: Path | None = None,
) -> IngestResult:
    """Re-parse a stored recipe with the ingredient list from its recipe web page: ``url``,
    or else the link in its caption. Uses the stored text, so nothing is downloaded again.

    With ``file``, the page is one the user saved (or an ingredient list they pasted into a
    text file) instead of a download; ``url``, if given, is recorded as where it came from.
    Raises ValueError / RecipePageError when there is no usable page."""
    stored = get_recipe(conn, recipe_id)
    if stored is None:
        raise ValueError(f"No recipe with id {recipe_id}")
    # An explicit --url, else the page imported before, else the link in the caption.
    link = url or stored["recipe_page_url"] or recipe_link(stored["description"] or "")
    if file is None and link is None:
        raise ValueError(f"Recipe {recipe_id}'s caption has no recipe link; pass one with --url")
    try:
        if file is not None:
            log.info("Reading saved recipe %s", file)
            page = read_recipe_file(file, url=url, name=stored["title"])
        else:
            log.info("Fetching recipe page %s", link)
            page = fetch_recipe_page(link)
    except RecipePageError as exc:
        if file is None:  # a bad local file says nothing about the post
            set_status_note(conn, recipe_id, str(exc))  # remembered for `list --todo`
        raise
    try:
        return reparse_recipe(conn, recipe_id, cfg, page=page)
    except ValueError:
        if file is None:
            set_status_note(conn, recipe_id, f"No ingredients could be read from {page.url}")
        raise


def reparse_recipe(
    conn: sqlite3.Connection, recipe_id: int, cfg: Settings = default_settings, *, page: WebRecipe | None = None
) -> IngestResult:
    """Parse a stored recipe again from its saved text (caption, transcript, on-screen text,
    recipe page), e.g. after a prompt change; nothing is downloaded. ``page`` replaces the
    stored recipe page. A parse that finds no ingredients never overwrites one that had them."""
    stored = get_recipe(conn, recipe_id)
    if stored is None:
        raise ValueError(f"No recipe with id {recipe_id}")
    inputs = ParseInputs(
        title=stored["title"],
        description=stored["description"] or "",
        transcript=stored["transcript"] or "",
        transcript_source=stored["transcript_source"] or "none",
        on_screen=stored["on_screen_text"],
        page=page,
        page_text=stored["recipe_page_text"],
    )
    recipe = _parse(inputs, cfg)
    if not recipe.ingredients and (page is not None or stored["ingredients"]):
        where = page.url or "the saved file" if page else "the saved text"
        raise ValueError(f"No ingredients could be read from {where}; recipe {recipe_id} left as it was")
    step_times: list[float | None] = []
    shorts: list[str | None] | None = None
    if not recipe.steps and any(t is not None for t in stored["step_times"]):
        # The method was read from the video's frames, which aren't saved: keep it.
        recipe = recipe.model_copy(update={"steps": stored["steps"]})
        step_times, shorts = stored["step_times"], stored["short_steps"]
    sources = ingredient_sources(recipe, inputs.transcript_source) if recipe.ingredients else []
    title = recipe.title.strip()
    if title.lower() in _NO_TITLE:
        title = stored["title"]
    status = "ready" if recipe.ingredients else classify_missing_recipe(stored["description"])
    save_recipe(
        conn,
        source_url=stored["source_url"],
        title=title,
        ingredients=[i.model_dump() for i in recipe.ingredients],
        steps=recipe.steps,
        short_steps=shorts if shorts is not None else short_steps(recipe.steps, [i.name for i in recipe.ingredients], cfg),
        step_times=step_times,
        yield_label=recipe.yield_label,
        ingredient_sources=sources,
        video_id=stored["video_id"],
        uploader=stored["uploader"],
        description=stored["description"],
        transcript=stored["transcript"],
        transcript_source=stored["transcript_source"],
        on_screen_text=stored["on_screen_text"],
        recipe_page_url=page.url if page else stored["recipe_page_url"],
        recipe_page_text=page.as_text() if page else stored["recipe_page_text"],
        raw_llm_json=recipe.model_dump_json(),
        status=status,
        status_note=None if recipe.ingredients else stored["status_note"],
    )
    return IngestResult(
        recipe_id=recipe_id,
        source_url=stored["source_url"],
        status="updated",
        recipe=recipe,
        transcript_source=inputs.transcript_source,
        ingredient_sources=sources,
        description=stored["description"],
        title=title,
        recipe_status=status,
        status_note=None if recipe.ingredients else stored["status_note"],
    )


def shorten_recipe_steps(conn: sqlite3.Connection, recipe_id: int, cfg: Settings = default_settings) -> list[str | None]:
    """Fill a stored recipe's island step versions from its saved steps; ingredients and
    the full steps are left alone. Raises ValueError / OllamaError."""
    stored = get_recipe(conn, recipe_id)
    if stored is None:
        raise ValueError(f"No recipe with id {recipe_id}")
    if not stored["steps"]:
        raise ValueError(f"Recipe {recipe_id} has no steps")
    log.info("Shortening %d steps with %s", len(stored["steps"]), cfg.ollama_model)
    shorts = shorten_steps(
        stored["steps"], ingredients=[i["raw_name"] for i in stored["ingredients"]],
        model=cfg.ollama_model, base_url=cfg.ollama_url, timeout=cfg.ollama_timeout,
        num_ctx=cfg.ollama_num_ctx, think=cfg.ollama_think,
    )
    set_short_steps(conn, recipe_id, shorts)
    return shorts


def stored_is_silent(stored: dict, cfg: Settings = default_settings) -> bool:
    """Whether a stored recipe's saved transcript counts as a silent / music-only video
    (no download needed to tell)."""
    return is_silent(stored["transcript"] or "", stored["transcript_source"] or "none", cfg.visual_min_words)


def has_video_steps(stored: dict) -> bool:
    """Whether a stored recipe's steps were read from its video (they have start times)."""
    return any(t is not None for t in stored["step_times"])


def steps_from_video(
    conn: sqlite3.Connection, recipe_id: int, cfg: Settings = default_settings, *, refresh: bool = False
) -> IngestResult:
    """Add steps read from a stored recipe's video frames (the visual fallback, for recipes
    saved before it existed). Downloads the video only: no Whisper, no text parse; stored
    ingredients are kept, and only filled from the frames when there are none. With
    ``refresh``, steps read from the video before are read again (written steps never are).
    Raises ValueError when the frames give nothing new."""
    stored = get_recipe(conn, recipe_id)
    if stored is None:
        raise ValueError(f"No recipe with id {recipe_id}")
    if refresh and has_video_steps(stored):
        stored["steps"], stored["step_times"] = [], []
    video = VideoFile(stored["source_url"], cfg)
    try:
        visual = read_video_steps(
            video, cfg, title=stored["title"], description=stored["description"] or "",
            on_screen=stored["on_screen_text"] or "", known_ingredients=[
                ingredient_line(i["raw_name"], i["amount"], i["unit"]) for i in stored["ingredients"]
            ],
        )
    finally:
        video.close()
    if visual is None or not visual.steps:
        raise ValueError(f"No steps could be read from recipe {recipe_id}'s video")

    current = ParsedRecipe(
        title=stored["title"], sources=[], yield_label=stored["yield_label"],
        ingredients=[Ingredient(name=i["raw_name"], amount=i["amount"], unit=i["unit"]) for i in stored["ingredients"]],
        steps=stored["steps"],
    )
    recipe, step_times = merge_visual(current, visual)
    if recipe.steps == current.steps and recipe.ingredients == current.ingredients:
        raise ValueError(f"Recipe {recipe_id} already has steps; left as it was")
    from_frames = bool(recipe.ingredients) and not current.ingredients
    sources = ["visual"] if from_frames else stored["ingredient_sources"]
    status = "ready" if recipe.ingredients else stored["status"]
    note = None if recipe.ingredients else stored["status_note"]
    save_recipe(
        conn,
        source_url=stored["source_url"],
        title=stored["title"],
        ingredients=[i.model_dump() for i in recipe.ingredients],
        steps=recipe.steps,
        short_steps=short_steps(recipe.steps, [i.name for i in recipe.ingredients], cfg),
        step_times=step_times,
        yield_label=stored["yield_label"],
        ingredient_sources=sources,
        video_id=stored["video_id"],
        uploader=stored["uploader"],
        description=stored["description"],
        transcript=stored["transcript"],
        transcript_source=stored["transcript_source"],
        on_screen_text=stored["on_screen_text"],
        recipe_page_url=stored["recipe_page_url"],
        recipe_page_text=stored["recipe_page_text"],
        raw_llm_json=stored["raw_llm_json"],
        status=status,
        status_note=note,
    )
    return IngestResult(
        recipe_id=recipe_id, source_url=stored["source_url"], status="updated", recipe=recipe,
        transcript_source=stored["transcript_source"], ingredient_sources=sources,
        description=stored["description"], title=stored["title"], recipe_status=status, status_note=note,
    )

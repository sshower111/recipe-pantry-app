"""Download metadata, captions, and audio for a short/reel with yt-dlp."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)


@dataclass
class MediaAssets:
    url: str
    video_id: str
    title: str
    description: str
    uploader: str | None
    duration: float | None
    audio_path: Path | None
    caption_path: Path | None
    caption_text: str

    def files(self) -> list[Path]:
        return [p for p in (self.audio_path, self.caption_path) if p is not None]


_TAG = re.compile(r"<[^>]+>")


def vtt_to_text(raw: str) -> str:
    """Flatten a WebVTT file to plain text, dropping cue timings and the
    duplicated lines that YouTube's rolling auto-captions produce."""
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if (
            not line
            or line == "WEBVTT"
            or "-->" in line
            or line.isdigit()
            or line.startswith(("Kind:", "Language:", "NOTE", "STYLE", "REGION"))
        ):
            continue
        line = html.unescape(_TAG.sub("", line)).replace(" ", " ").strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)


def _ydl_options(out_dir: Path, caption_langs: tuple[str, ...], with_captions: bool) -> dict[str, Any]:
    return {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(extractor)s_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": with_captions,
        "writeautomaticsub": with_captions,
        "subtitleslangs": list(caption_langs),
        "subtitlesformat": "vtt",
    }


def _find_caption(info: dict[str, Any], caption_langs: tuple[str, ...]) -> Path | None:
    requested = info.get("requested_subtitles") or {}
    for lang in (*caption_langs, *requested.keys()):
        sub = requested.get(lang)
        if sub and sub.get("filepath") and sub.get("ext") == "vtt" and Path(sub["filepath"]).exists():
            return Path(sub["filepath"])
    return None


def _find_download(ydl: YoutubeDL, info: dict[str, Any]) -> Path | None:
    for download in info.get("requested_downloads") or []:
        if download.get("filepath") and Path(download["filepath"]).exists():
            return Path(download["filepath"])
    candidate = Path(ydl.prepare_filename(info))
    return candidate if candidate.exists() else None


def download_video(url: str, out_dir: Path, *, max_height: int = 720) -> Path:
    """Download the video stream (for OCR). ``download_media`` only fetches audio, so this
    is a second, separate download that only runs when on-screen text is needed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "format": f"bv*[height<={max_height}]/b[height<={max_height}]/bv*/b",
        "outtmpl": str(out_dir / "%(extractor)s_%(id)s_video.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.sanitize_info(ydl.extract_info(url, download=True))
        path = _find_download(ydl, info)
    if path is None:
        raise DownloadError(f"No video file downloaded for {url}")
    return path


def download_media(
    url: str,
    out_dir: Path,
    *,
    caption_langs: tuple[str, ...] = ("en", "en-orig", "en-US", "en-GB"),
) -> MediaAssets:
    """Download audio and (if available) English captions for ``url``.

    Caption downloads fail fairly often (e.g. YouTube rate limits); in that case we
    retry without captions so transcription can fall back to Whisper.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    def run(with_captions: bool) -> tuple[YoutubeDL, dict[str, Any]]:
        ydl = YoutubeDL(_ydl_options(out_dir, caption_langs, with_captions))
        with ydl:
            info = ydl.extract_info(url, download=True)
        return ydl, ydl.sanitize_info(info)

    try:
        ydl, info = run(with_captions=True)
    except DownloadError as exc:
        if "subtitle" not in str(exc).lower():
            raise
        log.warning("Caption download failed (%s); retrying without captions", exc)
        ydl, info = run(with_captions=False)

    caption_path = _find_caption(info, caption_langs)
    caption_text = vtt_to_text(caption_path.read_text(encoding="utf-8")) if caption_path else ""

    return MediaAssets(
        url=info.get("webpage_url") or url,
        video_id=info["id"],
        title=info.get("title") or "",
        description=info.get("description") or "",
        uploader=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        audio_path=_find_download(ydl, info),
        caption_path=caption_path,
        caption_text=caption_text,
    )

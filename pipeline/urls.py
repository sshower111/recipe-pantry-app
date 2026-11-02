"""Canonical source URLs, so the same video is recognised however its link was copied."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qs, urlsplit

_INSTAGRAM = re.compile(r"^/(?:[\w.]+/)?(?:p|reel|reels|tv)/([\w-]+)")
_YOUTUBE_PATH = re.compile(r"^/(?:shorts|embed|live|v)/([\w-]{11})")
_TIKTOK = re.compile(r"^/@([\w.-]+)/video/(\d+)")
_COMMENT = re.compile(r"(?:^|\s)#.*")
# "https://..." anywhere, or a bare "host.tld/path" (the slash keeps "e.g." and "1.5" out).
_URL = re.compile(
    r"https?://[^\s<>\"'()\[\]{}]+"
    r"|(?<![\w@./-])(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s<>\"'()\[\]{}]*",
    re.IGNORECASE,
)
# Punctuation that ends a sentence rather than the URL ("see https://x.com/a.").
_TRAILING = ".,;:!?"


def canonical_url(url: str) -> str:
    """Map share-link variants of one video to a single URL.

    Instagram ``/reel/X/?igsh=...`` and ``/p/X`` -> ``https://www.instagram.com/p/X/``;
    YouTube ``youtu.be/X``, ``/shorts/X`` and ``watch?v=X&t=..`` -> ``https://www.youtube.com/watch?v=X``.
    Other URLs only lose their fragment and surrounding whitespace.
    """
    url = url.strip()
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")

    if host in ("instagram.com", "instagr.am"):
        if match := _INSTAGRAM.match(parts.path):
            return f"https://www.instagram.com/p/{match.group(1)}/"
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        video_id = (parse_qs(parts.query).get("v") or [None])[0]
        if video_id is None and (match := _YOUTUBE_PATH.match(parts.path)):
            video_id = match.group(1)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    elif host == "youtu.be":
        video_id = parts.path.strip("/").split("/")[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    elif host == "tiktok.com":
        if match := _TIKTOK.match(parts.path):
            return f"https://www.tiktok.com/@{match.group(1)}/video/{match.group(2)}"

    return parts._replace(fragment="").geturl()


def read_url_file(lines: Iterable[str]) -> tuple[list[str], int]:
    """Pull URLs out of a batch file's lines, ignoring any other text.

    Lines can mix notes and links ("Banana bread: https://..."); only the links are kept.
    Bare links ("instagram.com/p/X") get ``https://``. Text after a ``#`` at the start of
    a line or after whitespace is a comment, so a commented-out URL is skipped while URL
    fragments ("...#t=10") survive. Returns ``(urls, lines_without_urls)``, where the count
    excludes blank and comment-only lines.
    """
    urls: list[str] = []
    ignored = 0
    for line in lines:
        text = _COMMENT.sub("", line)
        found = [m.group(0).rstrip(_TRAILING) for m in _URL.finditer(text)]
        found = [u if "://" in u else f"https://{u}" for u in found if u]
        if found:
            urls.extend(found)
        elif text.strip():
            ignored += 1
    return urls, ignored


# Captions often point to the recipe instead of including it. A bare domain only counts with
# a common web TLD, so "ep.9" or "@hellotoa.official" don't match.
_SITE = re.compile(
    r"(?<![\w@./-])(?:[a-z0-9-]+\.)+(?:com|net|org|co|io|blog|me|ca|uk|au|nz|kitchen|recipes|food)"
    r"(?:/[^\s<>\"'()\[\]{}]*)?(?![\w.-])",
    re.IGNORECASE,
)
_SOCIAL_HOSTS = ("instagram.com", "instagr.am", "tiktok.com", "youtube.com", "youtu.be", "linktr.ee")
_ELSEWHERE = re.compile(
    r"link in (?:my )?bio|on (?:my|the) (?:\w+ )?(?:blog|website|site)|recipe (?:is )?(?:at|on) (?:my|the)"
    r"|comment\s+[\"'‘“]?\w+[\"'’”]?\s+(?:and|&|for|to)",
    re.IGNORECASE,
)


def recipe_link(text: str) -> str | None:
    """The first non-social web link in a caption (likely the full recipe), if any."""
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(_TRAILING)
        if not _is_social(url):
            return url if "://" in url else f"https://{url}"
    for match in _SITE.finditer(text):
        url = match.group(0).rstrip(_TRAILING)
        if not _is_social(url):
            return f"https://{url}"
    return None


def points_elsewhere(text: str) -> bool:
    """True if a caption says the recipe is somewhere else (blog, link in bio, comment-for-DM)."""
    return bool(_ELSEWHERE.search(text)) or recipe_link(text) is not None


def _is_social(url: str) -> bool:
    host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS)


def classify_missing_recipe(description: str | None) -> str:
    """Status for a post with no ingredient list: ``needs_recipe`` when the caption points to
    the recipe somewhere else, otherwise ``not_recipe`` (food vlogs, ads, technique clips)."""
    return "needs_recipe" if points_elsewhere(description or "") else "not_recipe"

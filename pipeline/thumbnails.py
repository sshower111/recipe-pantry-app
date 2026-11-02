"""Save video thumbnails locally, for the app's recipe cards and hero images.

Platform thumbnail URLs (Instagram's especially) are signed and expire, so the image itself
is kept under ``<data dir>/thumbnails/<recipe id>.<ext>`` and only the file name is stored.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import requests

from db import set_thumbnail

log = logging.getLogger(__name__)

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def download_thumbnail(image_url: str, recipe_id: int, out_dir: Path, *, timeout: float = 30) -> str:
    """Download ``image_url`` as this recipe's thumbnail and return the saved file name."""
    response = requests.get(image_url, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    extension = _EXTENSIONS.get(content_type)
    if extension is None:
        raise ValueError(f"Thumbnail is not an image ({content_type or 'no content type'})")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{recipe_id}.*"):
        old.unlink()
    file_name = f"{recipe_id}.{extension}"
    (out_dir / file_name).write_bytes(response.content)
    return file_name


def save_thumbnail(conn: sqlite3.Connection, recipe_id: int, image_url: str | None, out_dir: Path) -> bool:
    """Download and record a recipe's thumbnail. Failures are logged, never raised: a
    missing picture shouldn't fail an ingest."""
    if not image_url:
        return False
    try:
        set_thumbnail(conn, recipe_id, download_thumbnail(image_url, recipe_id, out_dir))
    except (requests.RequestException, ValueError, OSError) as exc:
        log.warning("Could not save thumbnail for recipe %d: %s", recipe_id, exc)
        return False
    return True

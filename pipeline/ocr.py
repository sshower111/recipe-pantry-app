"""Read on-screen text (ingredient overlays) from a video's frames with EasyOCR.

Used as a fallback when the description and speech don't contain a usable recipe.
EasyOCR (and PyTorch) are imported lazily: they are optional (requirements-ocr.txt)
and slow to import.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import warnings
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# One EasyOCR detection: (4 corner points, text, confidence).
Detection = tuple[Sequence[Sequence[float]], str, float]


class OcrUnavailable(RuntimeError):
    pass


def extract_frames(video: Path, out_dir: Path, *, fps: float = 1.0, max_frames: int = 60) -> list[Path]:
    """Sample frames with ffmpeg, dropping near-identical consecutive frames (mpdecimate),
    so a text card that stays up for five seconds is read once or twice, not five times.
    If more than ``max_frames`` remain, keep an evenly spaced subset."""
    if shutil.which("ffmpeg") is None:
        raise OcrUnavailable("ffmpeg is not on PATH")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(video),
            # Downscale first: OCR doesn't need more than 720px and it keeps EasyOCR fast.
            "-vf", f"fps={fps:g},scale='min(720,iw)':-2,mpdecimate",
            "-fps_mode", "vfr", "-q:v", "3",
            str(out_dir / "frame_%05d.jpg"),
        ],
        check=True,
        capture_output=True,
    )
    frames = sorted(out_dir.glob("frame_*.jpg"))
    keep = set(evenly_spaced(len(frames), max_frames))
    for index, frame in enumerate(frames):
        if index not in keep:
            frame.unlink()
    return [f for i, f in enumerate(frames) if i in keep]


def evenly_spaced(count: int, limit: int) -> list[int]:
    """Indices of at most ``limit`` items spread across ``count``, always keeping the first and last."""
    if count <= limit:
        return list(range(count))
    if limit <= 1:
        return [0] if limit == 1 else []
    step = (count - 1) / (limit - 1)
    return sorted({round(i * step) for i in range(limit)})


def group_lines(detections: Iterable[Detection], *, min_confidence: float = 0.3) -> list[str]:
    """Join EasyOCR's word boxes into text lines, top to bottom.

    EasyOCR often splits one overlay line ("1 tbsp soy sauce") into several boxes; boxes
    whose vertical centres are within half a box height of each other are one line.
    """
    boxes = []
    for points, text, confidence in detections:
        text = text.strip()
        if not text or confidence < min_confidence:
            continue
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        boxes.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text))
    boxes.sort()

    lines: list[list[tuple[float, float, float, str]]] = []
    for box in boxes:
        if lines:
            last = lines[-1]
            centre = sum(b[0] for b in last) / len(last)
            height = max(b[1] for b in last + [box])
            if abs(box[0] - centre) <= height / 2:
                last.append(box)
                continue
        lines.append([box])
    return [" ".join(b[3] for b in sorted(line, key=lambda b: b[2])) for line in lines]


_KEY = re.compile(r"[^a-z0-9]+")


def merge_frame_text(frames: Iterable[list[str]], *, min_chars: int = 2, similarity: float = 0.8) -> str:
    """Combine per-frame lines, keeping each distinct line once in first-seen order.

    Overlays persist across frames, so the same line is read many times with small OCR
    differences ("Sound up for moisture" / "Sound for meisture"); lines at least
    ``similarity`` alike (difflib ratio, ignoring case and punctuation) count as one.
    """
    seen: list[str] = []
    out: list[str] = []
    for lines in frames:
        for line in lines:
            key = _KEY.sub(" ", line.lower()).strip()
            if len(key) < min_chars or any(_similar(key, s, similarity) for s in seen):
                continue
            seen.append(key)
            out.append(line.strip())
    return "\n".join(out)


def _similar(a: str, b: str, threshold: float) -> bool:
    if a == b:
        return True
    # Lines that differ only in a number ("2 tbsp honey" / "3 tbsp honey") are different lines.
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


@lru_cache(maxsize=2)
def _reader(languages: tuple[str, ...], gpu: bool) -> Any:
    try:
        import easyocr
    except ImportError as exc:
        raise OcrUnavailable("EasyOCR is not installed: pip install -r requirements-ocr.txt") from exc
    log.info("Loading EasyOCR (%s, %s)", ",".join(languages), "gpu" if gpu else "cpu")
    with _quiet_torch():
        return easyocr.Reader(list(languages), gpu=gpu, verbose=False)


@contextmanager
def _quiet_torch() -> Iterator[None]:
    """Hide PyTorch warnings EasyOCR triggers on CPU that say nothing actionable:
    "pin_memory ... no accelerator" (once per frame) and the quantization deprecation
    (once per load)."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*pin_memory.*no accelerator", category=UserWarning)
        warnings.filterwarnings("ignore", message=r"torch\.quantize_per_tensor", category=UserWarning)
        yield


def read_on_screen_text(
    video: Path,
    work_dir: Path,
    *,
    languages: tuple[str, ...] = ("en",),
    gpu: bool = False,
    fps: float = 1.0,
    max_frames: int = 60,
) -> str:
    """OCR sampled frames of ``video`` and return the distinct text lines."""
    reader = _reader(tuple(languages), gpu)
    frames_dir = work_dir / f"{video.stem}_frames"
    try:
        frames = extract_frames(video, frames_dir, fps=fps, max_frames=max_frames)
        log.info("Running OCR on %d frames", len(frames))
        with _quiet_torch():
            per_frame = [group_lines(reader.readtext(str(frame))) for frame in frames]
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
    return merge_frame_text(per_frame)

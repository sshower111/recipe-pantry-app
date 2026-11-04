"""Keyframes with timestamps, for the model to watch a silent / music-only video.

ffmpeg picks a frame every ``interval`` seconds and at every scene change, and its
``showinfo`` filter reports each picked frame's presentation time, so every image comes
with the exact second it shows in the video.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipeline.ocr import OcrUnavailable, evenly_spaced


@dataclass(frozen=True)
class Keyframe:
    path: Path
    timestamp: float  # seconds from the start of the video


_PTS_TIME = re.compile(r"\bpts_time:\s*(-?\d+(?:\.\d+)?)")


def select_filter(interval: float, scene_threshold: float | None) -> str:
    """ffmpeg ``select`` expression: the first frame, then one at least every ``interval``
    seconds, plus any frame whose scene-change score is above ``scene_threshold``."""
    terms = ["isnan(prev_selected_t)", f"gte(t-prev_selected_t,{interval:g})"]
    if scene_threshold is not None:
        terms.append(f"gt(scene,{scene_threshold:g})")
    return f"select='{'+'.join(terms)}'"


def parse_showinfo(stderr: str) -> list[float]:
    """Presentation times (seconds) of the frames ffmpeg's showinfo filter printed, in order."""
    return [float(m.group(1)) for line in stderr.splitlines() if "showinfo" in line
            for m in [_PTS_TIME.search(line)] if m]


def extract_keyframes(
    video: Path,
    out_dir: Path,
    *,
    interval: float = 2.5,
    scene_threshold: float | None = 0.4,
    max_frames: int = 20,
    width: int = 512,
) -> list[Keyframe]:
    """Save keyframes of ``video`` as JPEGs in ``out_dir`` and return them with their times.
    More than ``max_frames`` are thinned to an evenly spaced subset (first and last kept)."""
    if shutil.which("ffmpeg") is None:
        raise OcrUnavailable("ffmpeg is not on PATH")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info", "-nostats", "-y", "-i", str(video),
            # Small images: a vision model sees enough at ~512px and each one costs context.
            "-vf", f"{select_filter(interval, scene_threshold)},scale='min({width},iw)':-2,showinfo",
            "-fps_mode", "vfr", "-q:v", "4",
            str(out_dir / "key_%05d.jpg"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    frames = sorted(out_dir.glob("key_*.jpg"))
    times = parse_showinfo(result.stderr)
    if len(times) != len(frames):
        raise RuntimeError(f"ffmpeg wrote {len(frames)} frames but reported {len(times)} timestamps")
    keep = set(evenly_spaced(len(frames), max_frames))
    for index, frame in enumerate(frames):
        if index not in keep:
            frame.unlink()
    return [Keyframe(f, round(t, 2)) for i, (f, t) in enumerate(zip(frames, times)) if i in keep]

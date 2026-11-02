import shutil
import subprocess

import pytest

from pipeline.transcriber import has_audio

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def test_has_audio_true_for_audio_file(tmp_path):
    path = tmp_path / "tone.m4a"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", path)
    assert has_audio(path)


def test_has_audio_false_for_video_only_file(tmp_path):
    # Silent reels come down as video-only .mp4 files.
    path = tmp_path / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:size=64x64:duration=1", "-pix_fmt", "yuv420p", path)
    assert not has_audio(path)

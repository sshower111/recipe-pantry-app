import shutil
import subprocess

import pytest

from pipeline import ocr
from pipeline.ocr import evenly_spaced, extract_frames, group_lines, merge_frame_text


def box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_group_lines_joins_split_boxes():
    # Shape of real EasyOCR output for "1 tbsp soy sauce" / "1 tsp grated ginger":
    # the quantity, unit and name come back as separate boxes at slightly different heights.
    detections = [
        (box(227, 586, 200, 50), "soy sauce", 0.98),
        (box(65, 499, 300, 52), "2 tbsp honey", 0.94),
        (box(70, 590, 25, 45), "1", 1.0),
        (box(99, 658, 380, 52), "tsp grated ginger", 0.94),
        (box(107, 576, 100, 60), "tbsp", 1.0),
        (box(70, 670, 25, 45), "1", 1.0),
        (box(400, 1200, 200, 30), "@chef", 0.1),  # low confidence: dropped
    ]
    assert group_lines(detections) == ["2 tbsp honey", "1 tbsp soy sauce", "1 tsp grated ginger"]


def test_group_lines_empty():
    assert group_lines([]) == []


def test_merge_frame_text_dedupes_across_frames():
    frames = [
        ["MISO GLAZED SALMON", "2 salmon fillets"],
        ["Miso glazed salmon.", "2 salmon fillets", "3 tbsp white miso"],
        ["MISO GLAZED SALMON", "x", "2 tbsp honey"],
    ]
    assert merge_frame_text(frames) == "MISO GLAZED SALMON\n2 salmon fillets\n3 tbsp white miso\n2 tbsp honey"


def test_merge_frame_text_absorbs_ocr_misreads():
    # Real EasyOCR output from one Instagram reel's caption across frames.
    frames = [["Sound uP for moisture"], ["Sound for meisture"], ["Sound for moisture"], ["Mc |do"]]
    assert merge_frame_text(frames) == "Sound uP for moisture\nMc |do"


def test_merge_frame_text_keeps_lines_that_differ_in_numbers():
    frames = [["2 tbsp honey"], ["3 tbsp honey"], ["2 tbsp honey."]]
    assert merge_frame_text(frames) == "2 tbsp honey\n3 tbsp honey"


@pytest.mark.parametrize(
    ("count", "limit", "expected"),
    [(3, 5, [0, 1, 2]), (10, 4, [0, 3, 6, 9]), (5, 1, [0]), (5, 0, []), (0, 4, [])],
)
def test_evenly_spaced(count, limit, expected):
    assert evenly_spaced(count, limit) == expected


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@needs_ffmpeg
def test_extract_frames_samples_and_caps(tmp_path):
    video = tmp_path / "clip.mp4"
    # 6 s of a moving test pattern, so frames differ and mpdecimate keeps them.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=6",
         "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    frames = extract_frames(video, tmp_path / "frames", fps=2, max_frames=5)
    assert len(frames) == 5
    assert all(f.exists() for f in frames)
    assert len(list((tmp_path / "frames").iterdir())) == 5  # extras deleted


@needs_ffmpeg
def test_extract_frames_drops_static_frames(tmp_path):
    video = tmp_path / "still.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=10:duration=6",
         "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    assert len(extract_frames(video, tmp_path / "frames", fps=2, max_frames=60)) == 1


def test_read_on_screen_text_with_fake_reader(monkeypatch, tmp_path):
    frames = []
    for i in range(3):
        frame = tmp_path / "f" / f"frame_{i}.jpg"
        frame.parent.mkdir(exist_ok=True)
        frame.write_bytes(b"")
        frames.append(frame)

    class FakeReader:
        def readtext(self, path):
            return [(box(0, 0, 100, 40), "2 tbsp honey", 0.9)]

    monkeypatch.setattr(ocr, "_reader", lambda languages, gpu: FakeReader())
    monkeypatch.setattr(ocr, "extract_frames", lambda video, out_dir, fps, max_frames: frames)
    assert ocr.read_on_screen_text(tmp_path / "v.mp4", tmp_path) == "2 tbsp honey"

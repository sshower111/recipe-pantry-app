import pytest

from pipeline import ingest


@pytest.fixture(autouse=True)
def no_step_shortening(monkeypatch):
    """Ingest and reparse also ask the model for short steps; tests that care patch
    ``ingest.shorten_steps`` themselves, the rest never reach Ollama."""
    monkeypatch.setattr(ingest, "shorten_steps", lambda steps, **kwargs: [None] * len(steps))


@pytest.fixture(autouse=True)
def no_visual_parse(monkeypatch):
    """The fake test videos have no speech, so ingest would try the visual fallback (a
    video download plus a vision-model call); tests that care patch it themselves."""
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kwargs: None)

import pytest

from pipeline import ingest


@pytest.fixture(autouse=True)
def no_step_shortening(monkeypatch):
    """Ingest and reparse also ask the model for short steps; tests that care patch
    ``ingest.shorten_steps`` themselves, the rest never reach Ollama."""
    monkeypatch.setattr(ingest, "shorten_steps", lambda steps, **kwargs: [None] * len(steps))

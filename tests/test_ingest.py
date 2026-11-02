import dataclasses

import pytest

from config import settings
from db import connect, get_recipe, list_recipes
from pipeline import ingest
from pipeline.downloader import MediaAssets
from pipeline.ingest import ingest_url, ingredient_sources, looks_incomplete
from pipeline.parser import Ingredient, ParsedRecipe


def recipe(*sources, ingredients=()):
    return ParsedRecipe(title="t", sources=list(sources), yield_label=None, ingredients=list(ingredients))


def test_ingredient_sources_names_the_transcript_kind():
    assert ingredient_sources(recipe("description", "transcript"), "whisper") == ["description", "speech"]
    assert ingredient_sources(recipe("transcript"), "captions") == ["captions"]
    assert ingredient_sources(recipe("title", "on_screen"), "none") == ["title", "on_screen"]
    assert ingredient_sources(recipe(), "whisper") == []


def test_looks_incomplete():
    full = [Ingredient(name="a", amount=1), Ingredient(name="b"), Ingredient(name="c")]
    assert not looks_incomplete(recipe(ingredients=full))
    assert looks_incomplete(None)
    assert looks_incomplete(recipe(ingredients=full[:2]))  # too few
    assert looks_incomplete(recipe(ingredients=[Ingredient(name=n) for n in "abcd"]))  # no amounts


class FakePipeline:
    """Stands in for yt-dlp, EasyOCR and Ollama.

    ``parses`` is a queue of ingredient lists the fake model returns, one per call.
    """

    def __init__(self):
        self.description = "2 slices bread, butter"
        self.on_screen = "2 slices bread\n1 tbsp butter\n1 tbsp honey"
        self.parses = []
        self.downloads = []
        self.ocr_calls = 0
        self.prompts = []

    def download(self, url, out_dir, caption_langs):
        self.downloads.append(url)
        return MediaAssets(
            url=url, video_id="X1", title="Toast video", description=self.description,
            uploader="chef", duration=30.0, audio_path=None, caption_path=None, caption_text="",
        )

    def read_video_text(self, url, cfg):
        self.ocr_calls += 1
        return self.on_screen

    def parse(self, **kwargs):
        self.prompts.append(kwargs)
        ingredients = self.parses.pop(0) if self.parses else [
            Ingredient(name="bread", amount=2), Ingredient(name="butter", amount=1), Ingredient(name="honey")
        ]
        sources = ["description", "on_screen"] if kwargs["on_screen"] else ["description"]
        return ParsedRecipe(title=f"Toast {len(self.prompts)}", sources=sources, yield_label="serves 1",
                            ingredients=ingredients)


@pytest.fixture
def fake(monkeypatch):
    pipeline = FakePipeline()
    monkeypatch.setattr(ingest, "download_media", pipeline.download)
    monkeypatch.setattr(ingest, "read_video_text", pipeline.read_video_text)
    monkeypatch.setattr(ingest, "parse_recipe", pipeline.parse)
    return pipeline


def make_cfg(tmp_path, ocr_mode="auto"):
    return dataclasses.replace(settings, downloads_dir=tmp_path / "downloads", ocr_mode=ocr_mode)


@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path)


# --- duplicates -----------------------------------------------------------------------

def test_ingest_adds_then_updates_same_post(fake, cfg):
    conn = connect(":memory:")
    first = ingest_url("https://www.instagram.com/p/X1/", conn, cfg)
    # Same post via a share link: must update the same row, not raise a UNIQUE error.
    second = ingest_url("https://www.instagram.com/reel/X1/?igsh=abc", conn, cfg)

    assert (first.status, second.status) == ("added", "updated")
    assert first.recipe_id == second.recipe_id
    assert second.source_url == "https://www.instagram.com/p/X1/"
    assert len(list_recipes(conn)) == 1
    stored = get_recipe(conn, first.recipe_id)
    assert stored["title"] == "Toast 2"
    assert stored["yield_label"] == "serves 1"
    assert stored["ingredient_sources"] == ["description"]


def test_ingest_skip_existing_does_not_download(fake, cfg):
    conn = connect(":memory:")
    added = ingest_url("https://www.instagram.com/p/X1/", conn, cfg)
    skipped = ingest_url("https://www.instagram.com/reel/X1/?igsh=abc", conn, cfg, skip_existing=True)

    assert skipped.status == "skipped"
    assert skipped.recipe_id == added.recipe_id
    assert skipped.recipe is None
    assert fake.downloads == ["https://www.instagram.com/p/X1/"]
    assert get_recipe(conn, added.recipe_id)["title"] == "Toast 1"


def test_ingest_skip_existing_still_ingests_new_urls(fake, cfg):
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, cfg, skip_existing=True)
    assert result.status == "added"
    assert len(fake.downloads) == 1


# --- OCR fallback ---------------------------------------------------------------------

def test_complete_parse_does_not_run_ocr(fake, cfg):
    result = ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert fake.ocr_calls == 0
    assert len(fake.prompts) == 1
    assert result.ingredient_sources == ["description"]


def test_incomplete_parse_falls_back_to_ocr(fake, cfg):
    fake.parses = [[Ingredient(name="bread")]]  # first parse: one ingredient, no amounts
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, cfg)

    assert fake.ocr_calls == 1
    assert [p["on_screen"] for p in fake.prompts] == ["", fake.on_screen]
    assert len(result.recipe.ingredients) == 3
    stored = get_recipe(conn, result.recipe_id)
    assert stored["on_screen_text"] == fake.on_screen
    assert stored["ingredient_sources"] == ["description", "on_screen"]


def test_ocr_retry_is_dropped_if_it_finds_less(fake, cfg):
    first = [Ingredient(name="bread"), Ingredient(name="butter")]
    fake.parses = [first, [Ingredient(name="bread")]]
    result = ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert [i.name for i in result.recipe.ingredients] == ["bread", "butter"]


def test_ocr_finding_nothing_keeps_first_parse(fake, cfg):
    fake.parses = [[Ingredient(name="bread")]]
    fake.on_screen = ""
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, cfg)
    assert fake.ocr_calls == 1
    assert len(fake.prompts) == 1  # no second parse
    assert get_recipe(conn, result.recipe_id)["on_screen_text"] == ""


def test_ocr_off_never_runs(fake, tmp_path):
    fake.parses = [[Ingredient(name="bread")]]
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, make_cfg(tmp_path, "off"))
    assert fake.ocr_calls == 0
    assert get_recipe(conn, result.recipe_id)["on_screen_text"] is None


def test_ocr_always_runs_once_before_parsing(fake, tmp_path):
    ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), make_cfg(tmp_path, "always"))
    assert fake.ocr_calls == 1
    assert [p["on_screen"] for p in fake.prompts] == [fake.on_screen]


def test_no_text_at_all_goes_straight_to_ocr(fake, cfg):
    fake.description = ""
    result = ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert fake.ocr_calls == 1
    assert [p["on_screen"] for p in fake.prompts] == [fake.on_screen]
    assert result.status == "added"


def test_no_text_and_no_ocr_text_fails(fake, cfg):
    fake.description = ""
    fake.on_screen = ""
    with pytest.raises(ValueError, match="on-screen text"):
        ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert fake.prompts == []


def test_silent_video_skips_whisper(monkeypatch, tmp_path):
    from pipeline import transcriber

    def no_whisper(*args, **kwargs):
        raise AssertionError("Whisper must not run on a file with no audio")

    monkeypatch.setattr(transcriber, "has_audio", lambda path: False)
    monkeypatch.setattr(transcriber, "transcribe", no_whisper)
    media = MediaAssets(
        url="u", video_id="v", title="", description="recipe", uploader=None, duration=10.0,
        audio_path=tmp_path / "silent.mp4", caption_path=None, caption_text="",
    )
    assert ingest.choose_transcript(media, make_cfg(tmp_path)) == ("", "none")
    media.caption_text = "short"
    assert ingest.choose_transcript(media, make_cfg(tmp_path)) == ("short", "captions")


def test_read_video_text_failures_are_not_fatal(monkeypatch, tmp_path):
    def broken(url, out_dir):
        raise RuntimeError("no video stream")

    monkeypatch.setattr(ingest, "download_video", broken)
    assert ingest.read_video_text("https://example.com/v", make_cfg(tmp_path)) == ""

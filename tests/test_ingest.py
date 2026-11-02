import dataclasses

import pytest

from config import settings
from db import connect, get_recipe, list_recipes
from pipeline import ingest
from pipeline.downloader import MediaAssets
from pipeline.ingest import ingest_url, ingredient_sources, looks_incomplete
from pipeline.parser import Ingredient, ParsedRecipe
from pipeline.webrecipe import WebRecipe


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
        self.page = None  # WebRecipe the fake recipe-page fetch returns
        self.page_error = None
        self.page_fetches = []

    def download(self, url, out_dir, caption_langs):
        self.downloads.append(url)
        return MediaAssets(
            url=url, video_id="X1", title="Toast video", description=self.description,
            uploader="chef", duration=30.0, audio_path=None, caption_path=None, caption_text="",
        )

    def read_video_text(self, url, cfg):
        self.ocr_calls += 1
        return self.on_screen

    def read_recipe_page(self, description):
        self.page_fetches.append(description)
        return self.page, self.page_error

    def parse(self, **kwargs):
        self.prompts.append(kwargs)
        ingredients = self.parses.pop(0) if self.parses else [
            Ingredient(name="bread", amount=2), Ingredient(name="butter", amount=1), Ingredient(name="honey")
        ]
        sources = ["description"] + (["on_screen"] if kwargs["on_screen"] else []) + (
            ["recipe_page"] if kwargs["recipe_page"] else [])
        return ParsedRecipe(title=f"Toast {len(self.prompts)}", sources=sources, yield_label="serves 1",
                            ingredients=ingredients)


@pytest.fixture
def fake(monkeypatch):
    pipeline = FakePipeline()
    monkeypatch.setattr(ingest, "download_media", pipeline.download)
    monkeypatch.setattr(ingest, "read_video_text", pipeline.read_video_text)
    monkeypatch.setattr(ingest, "read_recipe_page", pipeline.read_recipe_page)
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


def test_empty_recipe_records_no_sources(fake, tmp_path):
    fake.parses = [[], []]
    fake.on_screen = ""
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, make_cfg(tmp_path))
    assert result.recipe.ingredients == []
    assert result.ingredient_sources == []
    assert result.description == fake.description
    assert get_recipe(conn, result.recipe_id)["ingredient_sources"] == []


# --- recipe page fallback ---------------------------------------------------------------

PAGE = WebRecipe(url="https://blog.example.com/toast/", name="Toast", yield_text="2 slices",
                 ingredients=["2 slices bread", "1 tbsp butter", "1 tsp honey"])
FULL = [Ingredient(name="bread", amount=2), Ingredient(name="butter", amount=1), Ingredient(name="honey", amount=1)]


def test_recipe_page_is_tried_before_ocr(fake, cfg):
    fake.parses = [[], FULL]  # caption alone: nothing; with the page: complete
    fake.page = PAGE
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/X1/", conn, cfg)

    assert len(fake.page_fetches) == 1
    assert fake.ocr_calls == 0  # page made the recipe complete, so no OCR
    assert fake.prompts[1]["recipe_page"] == PAGE.as_text()
    assert result.ingredient_sources == ["description", "recipe_page"]
    stored = get_recipe(conn, result.recipe_id)
    assert stored["recipe_page_url"] == PAGE.url
    assert stored["recipe_page_text"] == PAGE.as_text()


def test_ocr_still_runs_when_page_is_unavailable(fake, cfg):
    fake.parses = [[], FULL]  # no page, so the second parse is the OCR retry
    fake.page = None
    result = ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert len(fake.page_fetches) == 1
    assert fake.ocr_calls == 1
    assert len(result.recipe.ingredients) == 3


def test_complete_parse_skips_recipe_page(fake, cfg):
    ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert fake.page_fetches == []


def test_recipe_pages_setting_off(fake, tmp_path):
    fake.parses = [[]]
    fake.page = PAGE
    cfg = dataclasses.replace(make_cfg(tmp_path, "off"), recipe_pages=False)
    ingest_url("https://www.instagram.com/p/X1/", connect(":memory:"), cfg)
    assert fake.page_fetches == []


def test_read_recipe_page_needs_a_link_and_survives_errors(monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        raise ingest.RecipePageError("blocked")

    monkeypatch.setattr(ingest, "fetch_recipe_page", fetch)
    assert ingest.read_recipe_page("Recipe on my blog, link in bio!") == (None, None)
    assert calls == []
    assert ingest.read_recipe_page("full recipe: https://blog.example.com/toast/") == (None, "blocked")
    assert calls == ["https://blog.example.com/toast/"]


def test_import_recipe_page_updates_stored_recipe(fake, cfg, monkeypatch):
    fake.parses = [[]]
    fake.description = "Recipe at https://blog.example.com/toast/ !"
    fake.on_screen = ""
    conn = connect(":memory:")
    added = ingest_url("https://www.instagram.com/p/X1/", conn, dataclasses.replace(cfg, recipe_pages=False))
    assert get_recipe(conn, added.recipe_id)["ingredients"] == []

    fetched = []
    monkeypatch.setattr(ingest, "fetch_recipe_page", lambda url: fetched.append(url) or PAGE)
    fake.parses = [FULL]
    result = ingest.import_recipe_page(conn, added.recipe_id, cfg)

    assert fetched == ["https://blog.example.com/toast/"]
    assert result.status == "updated"
    stored = get_recipe(conn, added.recipe_id)
    assert [i["name"] for i in stored["ingredients"]] == ["bread", "butter", "honey"]
    assert stored["recipe_page_url"] == PAGE.url
    assert stored["video_id"] == "X1"  # other fields kept
    assert stored["description"] == fake.description
    assert fake.prompts[-1]["recipe_page"] == PAGE.as_text()


def test_import_recipe_page_errors(fake, cfg, monkeypatch):
    fake.parses = [[]]
    fake.on_screen = ""
    conn = connect(":memory:")
    rid = ingest_url("https://www.instagram.com/p/X1/", conn, dataclasses.replace(cfg, recipe_pages=False)).recipe_id
    with pytest.raises(ValueError, match="no recipe link; pass one with --url"):
        ingest.import_recipe_page(conn, rid, cfg)
    with pytest.raises(ValueError, match="No recipe with id 99"):
        ingest.import_recipe_page(conn, 99, cfg)

    monkeypatch.setattr(ingest, "fetch_recipe_page", lambda url: PAGE)
    fake.parses = [[]]
    with pytest.raises(ValueError, match="No ingredients could be read"):
        ingest.import_recipe_page(conn, rid, cfg, url="https://blog.example.com/toast/")


def test_fallback_title():
    media = MediaAssets(url="u", video_id="X1", title="  ", description="", uploader="chef", duration=None,
                        audio_path=None, caption_path=None, caption_text="")
    assert ingest.fallback_title("Toast", media) == "Toast"
    assert ingest.fallback_title(" ", media) == "Post by chef"
    media.uploader = None
    assert ingest.fallback_title("", media) == "Post X1"
    media.title = "Video by chef"
    assert ingest.fallback_title("", media) == "Video by chef"


def test_ingest_sets_status(fake, cfg):
    conn = connect(":memory:")
    assert ingest_url("https://www.instagram.com/p/X1/", conn, cfg).recipe_status == "ready"

    fake.parses = [[], []]
    fake.on_screen = ""
    fake.description = "food vlog day 3 #eats"
    vlog = ingest_url("https://www.instagram.com/p/X2/", conn, cfg)
    assert vlog.recipe_status == "not_recipe"

    fake.parses = [[], []]
    fake.description = "Recipe at https://blog.example.com/cake/"
    fake.page_error = "blog.example.com blocks automated requests (HTTP 403)"
    cake = ingest_url("https://www.instagram.com/p/X3/", conn, cfg)
    assert (cake.recipe_status, cake.status_note) == ("needs_recipe", fake.page_error)
    stored = get_recipe(conn, cake.recipe_id)
    assert (stored["status"], stored["status_note"]) == ("needs_recipe", fake.page_error)


def test_import_page_failure_is_noted(fake, cfg, monkeypatch):
    fake.parses = [[]]
    fake.on_screen = ""
    fake.description = "Recipe at https://blog.example.com/toast/"
    conn = connect(":memory:")
    rid = ingest_url("https://www.instagram.com/p/X1/", conn, dataclasses.replace(cfg, recipe_pages=False)).recipe_id

    def blocked(url):
        raise ingest.RecipePageError("blog.example.com blocks automated requests (HTTP 403)")

    monkeypatch.setattr(ingest, "fetch_recipe_page", blocked)
    with pytest.raises(ingest.RecipePageError):
        ingest.import_recipe_page(conn, rid, cfg)
    assert get_recipe(conn, rid)["status_note"] == "blog.example.com blocks automated requests (HTTP 403)"


@pytest.mark.parametrize("placeholder", ["None", "null", " N/A ", "Untitled"])
def test_fallback_title_ignores_placeholders(placeholder):
    media = MediaAssets(url="u", video_id="X1", title="", description="", uploader="Por por and Colin",
                        duration=None, audio_path=None, caption_path=None, caption_text="")
    assert ingest.fallback_title(placeholder, media) == "Post by Por por and Colin"


def test_import_recipe_page_from_saved_file(fake, cfg, monkeypatch, tmp_path):
    fake.parses = [[]]
    fake.on_screen = ""
    fake.description = "Full recipe on my blog, link in bio!"
    conn = connect(":memory:")
    rid = ingest_url("https://www.instagram.com/p/X1/", conn, dataclasses.replace(cfg, recipe_pages=False)).recipe_id

    def no_download(url):
        raise AssertionError("--file must not download anything")

    monkeypatch.setattr(ingest, "fetch_recipe_page", no_download)
    txt = tmp_path / "toast.txt"
    txt.write_text("2 slices bread\n1 tbsp butter\n1 tsp honey\nServes 1\n", encoding="utf-8")
    fake.parses = [FULL]
    result = ingest.import_recipe_page(conn, rid, cfg, file=txt, url="https://blog.example.com/toast/")

    assert result.recipe_status == "ready"
    assert "- 2 slices bread" in fake.prompts[-1]["recipe_page"]
    stored = get_recipe(conn, rid)
    assert stored["status"] == "ready"
    assert stored["recipe_page_url"] == "https://blog.example.com/toast/"
    assert "Yield: serves 1" in stored["recipe_page_text"]


def test_import_recipe_page_bad_file_leaves_note_alone(fake, cfg, tmp_path):
    fake.parses = [[]]
    fake.on_screen = ""
    conn = connect(":memory:")
    rid = ingest_url("https://www.instagram.com/p/X1/", conn, dataclasses.replace(cfg, recipe_pages=False)).recipe_id
    empty = tmp_path / "empty.txt"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ingest.RecipePageError, match="no ingredient lines"):
        ingest.import_recipe_page(conn, rid, cfg, file=empty)
    assert get_recipe(conn, rid)["status_note"] is None

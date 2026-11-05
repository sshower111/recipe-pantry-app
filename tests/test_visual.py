"""Silent / music-only videos: keyframes with timestamps -> vision model -> steps."""

import dataclasses
import json
import shutil
import subprocess

import pytest

from config import settings
from db import connect, get_recipe, save_recipe
from pipeline import frames, ingest, parser
from pipeline.downloader import MediaAssets
from pipeline.ingest import count_words, ingest_url, is_silent, merge_visual
from pipeline.ingest import read_video_steps as real_read_video_steps  # before conftest stubs it
from pipeline.parser import Ingredient, ParsedRecipe, VisualRecipe, VisualStep, build_visual_messages


def vstep(n, t, text, *used):
    return VisualStep(step_number=n, timestamp_start=t, instruction=text, ingredients_used=list(used))


VISUAL = VisualRecipe(title="Fried Rice", steps=[
    vstep(1, 0.0, "Scramble the eggs.", "egg"),
    vstep(2, 5.0, "Fry the rice with the eggs.", "rice", "Egg"),
])


# --- silence check ----------------------------------------------------------------------------

def test_count_words_ignores_sound_tags():
    assert count_words("[Music] ♪ la la ♪ (applause)") == 0
    assert count_words("Thank you.") == 2
    assert count_words("add two cups of flour") == 5


def test_is_silent():
    assert is_silent("", "none", 5)
    assert is_silent("[Music] Thank you.", "whisper", 5)
    assert not is_silent("now add two cups of flour", "whisper", 5)
    assert not is_silent("x" * 40, "captions", 5)  # real captions are speech
    assert is_silent("[Music]", "captions", 5)  # short captions fall through to the word count


# --- keyframes --------------------------------------------------------------------------------

def test_select_filter():
    assert frames.select_filter(2.5, 0.4) == "select='isnan(prev_selected_t)+gte(t-prev_selected_t,2.5)+gt(scene,0.4)'"
    assert "scene" not in frames.select_filter(3, None)


def test_parse_showinfo():
    stderr = (
        "[Parsed_showinfo_2 @ 0x1] n:   0 pts:      0 pts_time:0       duration:512\n"
        "frame=    1 fps=0.0 q=4.0 size=N/A\n"
        "[Parsed_showinfo_2 @ 0x1] n:   1 pts:  32256 pts_time:2.52    duration:512\n"
    )
    assert frames.parse_showinfo(stderr) == [0.0, 2.52]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_extract_keyframes_on_interval_and_scene_change(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=160x120:d=4,format=yuv420p",
         "-f", "lavfi", "-i", "color=blue:s=160x120:d=4,format=yuv420p",
         "-filter_complex", "[0][1]concat=n=2:v=1", str(video)],
        check=True,
    )
    keys = frames.extract_keyframes(video, tmp_path / "out", interval=2.5, scene_threshold=0.4)
    times = [k.timestamp for k in keys]
    assert times[0] == 0.0
    assert 4.0 in times  # the cut from red to blue
    assert all(k.path.exists() for k in keys)
    assert len(list((tmp_path / "out").glob("*.jpg"))) == len(keys)

    few = frames.extract_keyframes(video, tmp_path / "few", interval=1, scene_threshold=None, max_frames=3)
    assert len(few) == 3 and few[0].timestamp == 0.0


# --- the model call ---------------------------------------------------------------------------

def test_build_visual_messages_attaches_frames_in_order():
    messages = build_visual_messages([(0.0, b"a"), (2.5, b"b")], title="T", description="rice, eggs",
                                     known_ingredients=["rice"])
    user = messages[1]
    assert user["images"] == ["YQ==", "Yg=="]  # base64, same order as the labels
    assert "Frame 1: 0.0s\nFrame 2: 2.5s" in user["content"]
    assert "INGREDIENT LIST (from the post's text):\n- rice" in user["content"]
    assert "ON-SCREEN TEXT" not in user["content"]


def test_visual_schema_requires_every_field():
    schema = VisualRecipe.output_schema()
    assert schema["required"] == ["title", "steps"]
    assert schema["$defs"]["VisualStep"]["required"] == ["step_number", "timestamp_start", "instruction", "ingredients_used"]


def test_tidy_sorts_renumbers_and_snaps_times():
    raw = VisualRecipe(title=" Rice ", steps=[vstep(2, 5.3, "Fry."), vstep(1, 0.4, "Crack eggs.")])
    tidy = raw.tidy([0.0, 2.5, 5.0])
    assert [(s.step_number, s.timestamp_start, s.instruction) for s in tidy.steps] == [(1, 0.0, "Crack eggs."), (2, 5.0, "Fry.")]
    assert tidy.title == "Rice"
    assert VISUAL.ingredient_names() == ["egg", "rice"]  # lowercased, deduped


class FakeResponse:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_parse_visual_recipe_sends_images_and_retries(monkeypatch):
    good = json.dumps({"title": "Rice", "steps": [
        {"step_number": 1, "timestamp_start": 2.4, "instruction": "Fry the rice.", "ingredients_used": ["rice"]}]})
    responses = iter([FakeResponse('{"title": "x"}'), FakeResponse(good)])
    sent = []
    monkeypatch.setattr(parser.requests, "post", lambda url, json, timeout: sent.append(json) or next(responses))

    visual = parser.parse_visual_recipe([(0.0, b"a"), (2.5, b"b")], model="qwen3.5:9b", num_ctx=16384)
    assert visual.steps[0].timestamp_start == 2.5
    assert len(sent) == 2
    assert sent[0]["model"] == "qwen3.5:9b"
    assert sent[0]["options"] == {"temperature": 0, "num_ctx": 16384}
    assert sent[0]["format"]["required"] == ["title", "steps"]
    assert len(sent[0]["messages"][1]["images"]) == 2


# --- merging into the recipe ------------------------------------------------------------------

def test_merge_visual_fills_only_what_the_text_lacks():
    text = ParsedRecipe(title="Egg Fried Rice", sources=["description"], yield_label=None,
                        ingredients=[Ingredient(name="rice", amount=2, unit="cup")])
    merged, times = merge_visual(text, VISUAL)
    assert merged.title == "Egg Fried Rice"
    assert [i.name for i in merged.ingredients] == ["rice"]  # written list kept, with amounts
    assert merged.steps == ["Scramble the eggs.", "Fry the rice with the eggs."]
    assert times == [0.0, 5.0]

    written = text.model_copy(update={"steps": ["Cook the rice."]})
    merged, times = merge_visual(written, VISUAL)
    assert (merged.steps, times) == (["Cook the rice."], [])

    merged, times = merge_visual(None, VISUAL)
    assert merged.title == "Fried Rice"
    assert [(i.name, i.amount) for i in merged.ingredients] == [("egg", None), ("rice", None)]


# --- ingest -----------------------------------------------------------------------------------

class Pipeline:
    def __init__(self, monkeypatch, *, caption="", description="rice, eggs", visual=VISUAL, ingredients=None):
        self.visual_calls = []
        self.video_downloads = []
        self.parse_calls = 0
        self.ingredients = [Ingredient(name="rice", amount=2, unit="cup"), Ingredient(name="egg", amount=2),
                            Ingredient(name="scallion", amount=1)] if ingredients is None else ingredients

        def download(url, out_dir, caption_langs):
            return MediaAssets(url=url, video_id="V1", title="Rice", description=description, uploader="chef",
                               duration=20.0, audio_path=None, caption_path=None, caption_text=caption)

        def parse(**kwargs):
            self.parse_calls += 1
            return ParsedRecipe(title="Egg Fried Rice", sources=["description"] if self.ingredients else [],
                                yield_label=None, ingredients=self.ingredients)

        def read_steps(video, cfg, **kwargs):
            self.visual_calls.append(kwargs)
            return visual

        monkeypatch.setattr(ingest, "download_media", download)
        monkeypatch.setattr(ingest, "parse_recipe", parse)
        monkeypatch.setattr(ingest, "read_video_steps", read_steps)
        monkeypatch.setattr(ingest, "read_recipe_page", lambda description: (None, None))
        monkeypatch.setattr(ingest, "download_video", lambda url, out_dir: self.video_downloads.append(url))


def cfg(tmp_path, **changes):
    return dataclasses.replace(settings, **{"downloads_dir": tmp_path, "ocr_mode": "off", "visual_mode": "auto", **changes})


def test_silent_video_gets_steps_with_times(monkeypatch, tmp_path):
    fake = Pipeline(monkeypatch)
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/V1/", conn, cfg(tmp_path))

    assert fake.visual_calls[0]["known_ingredients"] == ["2 cup rice", "2 egg", "1 scallion"]
    assert fake.visual_calls[0]["description"] == "rice, eggs"
    stored = get_recipe(conn, result.recipe_id)
    assert stored["steps"] == ["Scramble the eggs.", "Fry the rice with the eggs."]
    assert stored["step_times"] == [0.0, 5.0]
    assert [i["amount"] for i in stored["ingredients"]] == [2, 2, 1]  # text's list kept
    assert stored["ingredient_sources"] == ["description"]


def test_visual_ingredients_when_the_text_has_none(monkeypatch, tmp_path):
    Pipeline(monkeypatch, description="", ingredients=[])
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/V1/", conn, cfg(tmp_path))
    stored = get_recipe(conn, result.recipe_id)
    assert [i["name"] for i in stored["ingredients"]] == ["egg", "rice"]
    assert stored["ingredient_sources"] == ["visual"]
    assert stored["status"] == "ready"


def test_no_text_at_all_is_parsed_from_frames_alone(monkeypatch, tmp_path):
    fake = Pipeline(monkeypatch, description="")
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/V1/", conn, cfg(tmp_path))
    assert fake.parse_calls == 0  # nothing to send the text model
    assert result.title == "Fried Rice"
    assert get_recipe(conn, result.recipe_id)["ingredient_sources"] == ["visual"]


def test_spoken_video_never_reads_frames(monkeypatch, tmp_path):
    fake = Pipeline(monkeypatch, caption="first cook the rice then scramble two eggs in the wok")
    ingest_url("https://www.instagram.com/p/V1/", connect(":memory:"), cfg(tmp_path))
    assert fake.visual_calls == []


def test_visual_off_never_reads_frames(monkeypatch, tmp_path):
    fake = Pipeline(monkeypatch)
    ingest_url("https://www.instagram.com/p/V1/", connect(":memory:"), cfg(tmp_path, visual_mode="off"))
    assert fake.visual_calls == []


def test_visual_failure_keeps_the_text_parse(monkeypatch, tmp_path):
    Pipeline(monkeypatch, visual=None)
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/V1/", conn, cfg(tmp_path))
    stored = get_recipe(conn, result.recipe_id)
    assert stored["steps"] == [] and len(stored["ingredients"]) == 3


def test_read_video_steps_failures_are_not_fatal(monkeypatch, tmp_path):
    def broken(url, out_dir):
        raise RuntimeError("no video stream")

    monkeypatch.setattr(ingest, "download_video", broken)
    c = cfg(tmp_path)
    video = ingest.VideoFile("https://example.com/v", c)
    assert real_read_video_steps(video, c, title="", description="", on_screen="", known_ingredients=[]) is None


def test_video_is_downloaded_once_for_ocr_and_frames(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ingest, "download_video", lambda url, out_dir: calls.append(url) or tmp_path / "v.mp4")
    video = ingest.VideoFile("https://example.com/v", cfg(tmp_path))
    assert video.path() == video.path() == tmp_path / "v.mp4"
    assert calls == ["https://example.com/v"]


def test_reparse_keeps_steps_read_from_frames(monkeypatch):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://www.instagram.com/p/V1/", title="Rice",
                      ingredients=[{"name": "rice", "amount": 2}], description="2 cups rice",
                      steps=["Fry the rice."], short_steps=["Fry the rice"], step_times=[3.0])
    monkeypatch.setattr(ingest, "parse_recipe", lambda **kw: ParsedRecipe(
        title="Rice", sources=["description"], yield_label=None, ingredients=[Ingredient(name="rice", amount=2)]))
    ingest.reparse_recipe(conn, rid, settings)
    after = get_recipe(conn, rid)
    assert (after["steps"], after["step_times"], after["short_steps"]) == (["Fry the rice."], [3.0], ["Fry the rice"])


# --- stored recipes: video-steps --------------------------------------------------------------

def stored_db(path=":memory:"):
    conn = connect(path)
    silent = save_recipe(conn, source_url="https://www.instagram.com/p/S1/", title="Silent Rice",
                         ingredients=[{"name": "rice", "amount": 2, "unit": "cup"}], ingredient_sources=["description"],
                         description="2 cups rice", transcript="", transcript_source="none", status="ready")
    spoken = save_recipe(conn, source_url="https://www.instagram.com/p/S2/", title="Talky Toast",
                         ingredients=[{"name": "bread"}], transcript="toast the bread then butter it well",
                         transcript_source="whisper", status="ready")
    todo = save_recipe(conn, source_url="https://www.instagram.com/p/S3/", title="Post by chef", ingredients=[],
                       description="recipe on my blog", transcript="[Music]", transcript_source="whisper",
                       status="needs_recipe", status_note="HTTP 403")
    return conn, silent, spoken, todo


def test_steps_from_video_keeps_ingredients(monkeypatch, tmp_path):
    conn, silent, _, _ = stored_db()
    seen = []
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: seen.append((video.url, kw)) or VISUAL)
    ingest.steps_from_video(conn, silent, cfg(tmp_path))

    assert seen[0][0] == "https://www.instagram.com/p/S1/"
    assert seen[0][1]["known_ingredients"] == ["2 cup rice"]
    after = get_recipe(conn, silent)
    assert after["steps"] == ["Scramble the eggs.", "Fry the rice with the eggs."]
    assert after["step_times"] == [0.0, 5.0]
    assert [(i["name"], i["amount"], i["unit"]) for i in after["ingredients"]] == [("rice", 2, "cup")]
    assert after["ingredient_sources"] == ["description"]


def test_steps_from_video_fills_a_todo_post(monkeypatch, tmp_path):
    conn = connect(":memory:")
    # Saved for later from the phone; the caption doesn't point anywhere else.
    todo = save_recipe(conn, source_url="https://www.instagram.com/p/S4/", title="Post by chef", ingredients=[],
                       description="so good 😋", transcript="", transcript_source="none", status="needs_recipe",
                       status_note="HTTP 403")
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: VISUAL)
    ingest.steps_from_video(conn, todo, cfg(tmp_path))
    after = get_recipe(conn, todo)
    assert (after["status"], after["status_note"], after["ingredient_sources"]) == ("ready", None, ["visual"])


def test_steps_from_video_nothing_found_leaves_recipe(monkeypatch, tmp_path):
    conn, silent, _, _ = stored_db()
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: None)
    with pytest.raises(ValueError, match="No steps"):
        ingest.steps_from_video(conn, silent, cfg(tmp_path))
    assert get_recipe(conn, silent)["steps"] == []


def test_video_steps_command_picks_silent_recipes(monkeypatch, tmp_path, capsys):
    import main

    path = tmp_path / "r.db"
    conn, silent, spoken, todo = stored_db(path)
    conn.close()
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path, downloads_dir=tmp_path))
    read = []
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: read.append(video.url) or VISUAL)

    assert main.main(["video-steps", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2 recipes without steps: 1 silent or music-only, 1 with speech" in out
    assert "Silent Rice" in out and "Talky Toast" not in out
    assert read == []

    assert main.main(["video-steps", "--todo"]) == 0
    assert read == ["https://www.instagram.com/p/S1/"]  # S3's caption says the recipe is on a blog
    assert "Skipping 1 post whose caption says the recipe is elsewhere" in capsys.readouterr().out


def test_show_hides_step_start_times(monkeypatch, tmp_path, capsys):
    import main

    path = tmp_path / "r.db"
    conn = connect(path)
    rid = save_recipe(conn, source_url="https://www.instagram.com/p/T1/", title="Rice", ingredients=[{"name": "rice"}],
                      steps=["Rinse the rice.", "Fry it."], step_times=[0.0, 72.5])
    conn.close()
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path))
    main.main(["show", str(rid)])
    out = capsys.readouterr().out
    assert "1. Rinse the rice." in out and "2. Fry it." in out  # the user doesn't want times shown


def test_dm_for_recipe_post_is_not_read_from_video(monkeypatch, tmp_path):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://www.instagram.com/p/D1/", title="Post by chef", ingredients=[],
                      description="Comment COOKIE and I'll DM you the recipe", transcript="",
                      transcript_source="none", status="needs_recipe")
    monkeypatch.setattr(ingest, "read_video_steps", lambda *a, **k: pytest.fail("video must not be read"))
    with pytest.raises(ValueError, match="elsewhere"):
        ingest.steps_from_video(conn, rid, cfg(tmp_path))
    assert get_recipe(conn, rid)["status"] == "needs_recipe"


def test_ingest_skips_frames_for_dm_for_recipe_posts(monkeypatch, tmp_path):
    fake = Pipeline(monkeypatch, description="Comment COOKIE and I'll DM you the recipe", ingredients=[])
    conn = connect(":memory:")
    result = ingest_url("https://www.instagram.com/p/V1/", conn, cfg(tmp_path))
    assert fake.visual_calls == []
    stored = get_recipe(conn, result.recipe_id)
    assert (stored["status"], stored["ingredients"], stored["steps"]) == ("needs_recipe", [], [])



def test_ingredient_line():
    from pipeline.parser import ingredient_line
    assert ingredient_line("granulated sugar", 80.0, "g") == "80 g granulated sugar"
    assert ingredient_line("baking soda", 0.75, "tsp") == "0.75 tsp baking soda"
    assert ingredient_line("egg", 1.0) == "1 egg"
    assert ingredient_line("flaky sea salt") == "flaky sea salt"


def test_visual_prompt_rules():
    prompt = parser.VISUAL_PROMPT
    assert "gathering ingredients or equipment" in prompt
    assert '"Add 80 g granulated sugar."' in prompt
    assert "used in two or more steps" in prompt


def test_refresh_reads_video_steps_again_but_never_written_ones(monkeypatch, tmp_path):
    conn = connect(":memory:")
    from_video = save_recipe(conn, source_url="https://www.instagram.com/p/R1/", title="Rice",
                             ingredients=[{"name": "rice"}], steps=["Gather the ingredients."], step_times=[0.0])
    written = save_recipe(conn, source_url="https://www.instagram.com/p/R2/", title="Toast",
                          ingredients=[{"name": "bread"}], steps=["Toast the bread."])
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: VISUAL)

    with pytest.raises(ValueError, match="already has steps"):
        ingest.steps_from_video(conn, from_video, cfg(tmp_path))
    ingest.steps_from_video(conn, from_video, cfg(tmp_path), refresh=True)
    assert get_recipe(conn, from_video)["steps"] == ["Scramble the eggs.", "Fry the rice with the eggs."]

    with pytest.raises(ValueError, match="already has steps"):
        ingest.steps_from_video(conn, written, cfg(tmp_path), refresh=True)
    assert get_recipe(conn, written)["steps"] == ["Toast the bread."]


def test_video_steps_refresh_picks_recipes_with_video_steps(monkeypatch, tmp_path, capsys):
    import main

    path = tmp_path / "r.db"
    conn = connect(path)
    save_recipe(conn, source_url="https://www.instagram.com/p/R1/", title="Rice", ingredients=[{"name": "rice"}],
                steps=["Gather the ingredients."], step_times=[0.0])
    save_recipe(conn, source_url="https://www.instagram.com/p/R2/", title="Toast", ingredients=[{"name": "bread"}],
                steps=["Toast the bread."])
    conn.close()
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path, downloads_dir=tmp_path))
    read = []
    monkeypatch.setattr(ingest, "read_video_steps", lambda video, cfg, **kw: read.append(video.url) or VISUAL)
    assert main.main(["video-steps", "--refresh"]) == 0
    assert read == ["https://www.instagram.com/p/R1/"]

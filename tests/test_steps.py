"""Recipe steps: parsing, recipe pages, pasted text, storage, reparse and display."""

import dataclasses
import json
import sqlite3

import pytest

import main
from config import settings
from db import connect, get_recipe, save_recipe, set_short_steps
from pipeline import ingest, parser
from pipeline.parser import Ingredient, ParsedRecipe
from pipeline.webrecipe import WebRecipe, recipe_from_html, recipe_from_text


def test_parsed_recipe_steps_are_cleaned_and_optional():
    recipe = ParsedRecipe.model_validate({
        "title": "Toast", "sources": [], "yield_label": None, "ingredients": [],
        "steps": ["  Toast the bread. ", "", "Butter it.", 3],
    })
    assert recipe.steps == ["Toast the bread.", "Butter it."]
    assert ParsedRecipe(title="t", sources=[], yield_label=None, ingredients=[]).steps == []


def test_prompt_has_step_rules():
    assert "Rules for steps:" in parser.SYSTEM_PROMPT
    assert "never invent steps" in parser.SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        ("Mix.\nBake at 350F.", ["Mix.", "Bake at 350F."]),
        (["Mix.", "<p>Bake.</p>"], ["Mix.", "Bake."]),
        ([{"@type": "HowToStep", "text": "Mix."}, {"@type": "HowToStep", "text": "Bake."}], ["Mix.", "Bake."]),
        ([{"@type": "HowToSection", "name": "Dough", "itemListElement": [{"@type": "HowToStep", "text": "Knead."}]},
          {"@type": "HowToSection", "name": "Glaze", "itemListElement": [{"@type": "HowToStep", "text": "Whisk."}]}],
         ["Knead.", "Whisk."]),
        (None, []),
    ],
)
def test_recipe_page_instructions(instructions, expected):
    data = {"@type": "Recipe", "name": "X", "recipeIngredient": ["1 egg"], "recipeInstructions": instructions}
    page = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    recipe = recipe_from_html(page, url="https://blog.example.com/x/", where="x")
    assert recipe.instructions == expected
    if expected:
        assert recipe.as_text().endswith("Instructions:\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(expected, 1)))
    else:
        assert "Instructions:" not in recipe.as_text()


def test_pasted_text_with_method_section():
    recipe = recipe_from_text(
        "Ingredients:\n- 2 eggs\n- 1 tbsp butter\n\nMethod:\n1. Whisk the eggs.\n2. Cook in butter.\nServes 1\n",
        url=None,
    )
    assert recipe.ingredients == ["2 eggs", "1 tbsp butter"]
    assert recipe.instructions == ["Whisk the eggs.", "Cook in butter."]
    assert recipe.yield_text == "serves 1"


def test_steps_are_saved_replaced_and_read(tmp_path):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://example.com/t", title="Toast",
                      ingredients=[{"name": "bread"}], steps=["Toast.", " ", "Butter."])
    assert get_recipe(conn, rid)["steps"] == ["Toast.", "Butter."]
    save_recipe(conn, source_url="https://example.com/t", title="Toast", ingredients=[{"name": "bread"}],
                steps=["Just toast."])
    assert get_recipe(conn, rid)["steps"] == ["Just toast."]
    conn.execute("DELETE FROM recipes WHERE id = ?", (rid,))
    assert conn.execute("SELECT COUNT(*) FROM recipe_steps").fetchone()[0] == 0  # cascades


# --- reparse ----------------------------------------------------------------------------------

@pytest.fixture
def stored(tmp_path):
    conn = connect(":memory:")
    rid = save_recipe(
        conn, source_url="https://www.instagram.com/p/X1/", title="Banana Bread", video_id="X1", uploader="chef",
        ingredients=[{"name": "banana", "amount": 3}, {"name": "flour"}, {"name": "egg", "amount": 2}],
        description="3 bananas, flour, 2 eggs", transcript="mash the bananas then bake at 350",
        transcript_source="whisper", recipe_page_text="Recipe: Banana Bread\nIngredients:\n- 3 bananas",
        recipe_page_url="https://blog.example.com/bb/",
    )
    return conn, rid


def fake_parse(monkeypatch, result):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(ingest, "parse_recipe", parse)
    return calls


FULL = ParsedRecipe(
    title="Banana Bread", sources=["description", "transcript"], yield_label="1 loaf",
    ingredients=[Ingredient(name="banana", amount=3), Ingredient(name="flour", amount=250, unit="g"),
                 Ingredient(name="egg", amount=2)],
    steps=["Mash the bananas.", "Bake at 350°F."],
)


def test_reparse_uses_saved_text_and_adds_steps(stored, monkeypatch):
    conn, rid = stored
    calls = fake_parse(monkeypatch, FULL)
    result = ingest.reparse_recipe(conn, rid, settings)

    assert calls[0]["description"] == "3 bananas, flour, 2 eggs"
    assert calls[0]["transcript"] == "mash the bananas then bake at 350"
    assert calls[0]["recipe_page"].startswith("Recipe: Banana Bread")  # stored page re-used
    after = get_recipe(conn, rid)
    assert after["steps"] == ["Mash the bananas.", "Bake at 350°F."]
    assert after["ingredient_sources"] == ["description", "speech"]
    assert (after["video_id"], after["recipe_page_url"], after["status"]) == ("X1", "https://blog.example.com/bb/", "ready")
    assert result.recipe_status == "ready"


def test_reparse_never_wipes_existing_ingredients(stored, monkeypatch):
    conn, rid = stored
    fake_parse(monkeypatch, ParsedRecipe(title="None", sources=[], yield_label=None, ingredients=[]))
    with pytest.raises(ValueError, match="left as it was"):
        ingest.reparse_recipe(conn, rid, settings)
    assert len(get_recipe(conn, rid)["ingredients"]) == 3


def test_reparse_keeps_stored_title_over_placeholder(stored, monkeypatch):
    conn, rid = stored
    fake_parse(monkeypatch, FULL.model_copy(update={"title": "null"}))
    ingest.reparse_recipe(conn, rid, settings)
    assert get_recipe(conn, rid)["title"] == "Banana Bread"


# --- CLI ----------------------------------------------------------------------------------------

@pytest.fixture
def cli_db(monkeypatch, tmp_path):
    path = tmp_path / "recipes.db"
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path))
    conn = connect(path)
    save_recipe(conn, source_url="https://example.com/a", title="With Steps", ingredients=[{"name": "egg"}],
                steps=["Boil the egg for 7 minutes.", "Peel."])
    save_recipe(conn, source_url="https://example.com/b", title="No Steps", ingredients=[{"name": "bread"}])
    save_recipe(conn, source_url="https://example.com/c", title="Vlog", ingredients=[], status="not_recipe")
    conn.close()
    return path


def test_show_prints_numbered_steps(cli_db, capsys):
    main.main(["show", "1"])
    out = capsys.readouterr().out
    assert "\nSteps:\n  1. Boil the egg for 7 minutes.\n  2. Peel.\n" in out
    main.main(["show", "2"])
    assert "Steps: not described in the post" in capsys.readouterr().out


def test_reparse_missing_steps_picks_ready_recipes_without_steps(cli_db, monkeypatch, capsys):
    seen = []

    def fake(conn, recipe_id):
        seen.append(recipe_id)
        if recipe_id == 2:
            return ingest.IngestResult(recipe_id=2, source_url="u", status="updated", recipe=FULL,
                                       transcript_source="whisper", ingredient_sources=["description"],
                                       title="No Steps")
        raise ValueError("boom")

    monkeypatch.setattr(ingest, "reparse_recipe", fake)
    assert main.main(["reparse", "--missing-steps"]) == 0
    assert seen == [2]  # not 1 (has steps) or 3 (not a recipe)
    out = capsys.readouterr().out
    assert "1/1 UPDATED [2] No Steps (3 ingredients, 2 steps, makes 1 loaf;" in out

    assert main.main(["reparse", "3", "2", "3"]) == 1  # explicit ids, de-duplicated, failure reported
    assert seen == [2, 3, 2]
    assert "1 reparsed, 1 failed" in capsys.readouterr().out


def test_reparse_nothing_to_do(cli_db, capsys):
    conn = connect(cli_db)
    save_recipe(conn, source_url="https://example.com/b", title="No Steps", ingredients=[{"name": "bread"}],
                steps=["Toast."])
    conn.close()
    assert main.main(["reparse", "--missing-steps"]) == 0
    assert "Nothing to reparse." in capsys.readouterr().out


def test_import_page_defaults_to_previously_imported_page(stored, monkeypatch):
    conn, rid = stored
    fetched = []
    page = WebRecipe(url="https://blog.example.com/bb/", name="Banana Bread", ingredients=["3 bananas"],
                     yield_text="1 loaf", instructions=["Mash.", "Bake."])
    monkeypatch.setattr(ingest, "fetch_recipe_page", lambda url: fetched.append(url) or page)
    calls = fake_parse(monkeypatch, FULL)
    ingest.import_recipe_page(conn, rid, settings)
    assert fetched == ["https://blog.example.com/bb/"]
    assert "Instructions:\n1. Mash.\n2. Bake." in calls[0]["recipe_page"]
    assert "Instructions:" in get_recipe(conn, rid)["recipe_page_text"]


# --- short (island) steps -----------------------------------------------------------------------

def test_short_steps_are_stored_by_position(tmp_path):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://example.com/t", title="Toast", ingredients=[{"name": "bread"}],
                      steps=["Toast the bread.", "  ", "Butter it while hot."],
                      short_steps=["Toast the bread", None, "Butter it"])
    # The blank step is dropped together with its short version.
    assert get_recipe(conn, rid)["short_steps"] == ["Toast the bread", "Butter it"]
    save_recipe(conn, source_url="https://example.com/t", title="Toast", ingredients=[{"name": "bread"}],
                steps=["Toast the bread.", "Butter it while hot."])
    assert get_recipe(conn, rid)["short_steps"] == [None, None]
    set_short_steps(conn, rid, ["Toast", "Butter"])
    after = get_recipe(conn, rid)
    assert after["short_steps"] == ["Toast", "Butter"]
    assert after["steps"] == ["Toast the bread.", "Butter it while hot."]


def test_old_database_gets_short_text_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE recipes (id INTEGER PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, title TEXT NOT NULL);
        CREATE TABLE recipe_steps (recipe_id INTEGER NOT NULL, position INTEGER NOT NULL, text TEXT NOT NULL,
                                   PRIMARY KEY (recipe_id, position));
        INSERT INTO recipes VALUES (1, 'https://example.com/old', 'Old');
        INSERT INTO recipe_steps VALUES (1, 0, 'Stir.');
        """
    )
    old.close()
    conn = connect(path)
    assert get_recipe(conn, 1)["short_steps"] == [None]


class FakeResponse:
    def __init__(self, content):
        self.status_code = 200
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_shorten_steps_retries_on_wrong_count_and_cleans(monkeypatch):
    steps = ["In a bowl, mix together hoisin sauce, bean sauce, sugar and ginger powder.",
             "Bake at 170°C for 40-45 minutes until cooked through.", "Stir."]
    answers = iter([
        json.dumps({"step_1": "Mix the sauce ingredients"}),
        json.dumps({"step_1": "Mix the sauce ingredients.", "step_2": "Bake at 170°C for 40-45 min",
                    "step_3": "Stir well now"}),
    ])
    sent = []

    def fake_post(url, json, timeout):
        sent.append(json)
        return FakeResponse(next(answers))

    monkeypatch.setattr(parser.requests, "post", fake_post)
    shorts = parser.shorten_steps(steps, ingredients=["hoisin sauce", "bean sauce"])
    # Trailing period dropped; a "short" version longer than the step is not kept.
    assert shorts == ["Mix the sauce ingredients", "Bake at 170°C for 40-45 min", None]
    assert len(sent) == 2
    assert sent[0]["format"]["required"] == ["step_1", "step_2", "step_3"]
    assert sent[0]["think"] is False and sent[0]["options"]["temperature"] == 0
    user = sent[0]["messages"][1]["content"]
    assert "- hoisin sauce" in user and "STEPS (3):\n1. In a bowl" in user


def test_shorten_steps_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(parser.requests, "post",
                        lambda url, json, timeout: FakeResponse('{"step_1": "Stir"}'))
    with pytest.raises(parser.OllamaError, match="step_2"):
        parser.shorten_steps(["Stir the pot.", "Serve it hot."])
    assert parser.shorten_steps([]) == []


def test_reparse_saves_short_steps(stored, monkeypatch):
    conn, rid = stored
    fake_parse(monkeypatch, FULL)
    seen = []
    monkeypatch.setattr(ingest, "shorten_steps",
                        lambda steps, **kw: seen.append(kw["ingredients"]) or ["Mash", "Bake at 350°F"])
    ingest.reparse_recipe(conn, rid, settings)
    assert get_recipe(conn, rid)["short_steps"] == ["Mash", "Bake at 350°F"]
    assert seen == [["banana", "flour", "egg"]]


def test_shortening_failure_never_fails_reparse(stored, monkeypatch):
    conn, rid = stored
    fake_parse(monkeypatch, FULL)

    def down(steps, **kwargs):
        raise parser.OllamaError("Cannot reach Ollama")

    monkeypatch.setattr(ingest, "shorten_steps", down)
    ingest.reparse_recipe(conn, rid, settings)
    after = get_recipe(conn, rid)
    assert after["steps"] == ["Mash the bananas.", "Bake at 350°F."]
    assert after["short_steps"] == [None, None]


def test_cli_shorten_steps_fills_only_missing(monkeypatch, tmp_path, capsys):
    path = tmp_path / "recipes.db"
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path))
    conn = connect(path)
    todo = save_recipe(conn, source_url="https://example.com/a", title="Toast",
                       ingredients=[{"name": "bread", "amount": 2}], steps=["Toast the bread slices.", "Stir."])
    done = save_recipe(conn, source_url="https://example.com/b", title="Tea", ingredients=[{"name": "tea"}],
                       steps=["Steep the tea bag."], short_steps=["Steep the tea"])
    save_recipe(conn, source_url="https://example.com/c", title="No steps", ingredients=[{"name": "egg"}])
    conn.close()
    calls = []
    monkeypatch.setattr(ingest, "shorten_steps", lambda steps, **kw: calls.append(steps) or ["Toast the bread", None])

    assert main.main(["shorten-steps"]) == 0
    assert calls == [["Toast the bread slices.", "Stir."]]
    out = capsys.readouterr().out
    assert "1/1 [1] Toast" in out and "    Toast the bread" in out and "(kept: Stir.)" in out
    conn = connect(path)
    recipe = get_recipe(conn, todo)
    assert recipe["short_steps"] == ["Toast the bread", None]
    assert [(i["name"], i["amount"]) for i in recipe["ingredients"]] == [("bread", 2)]
    assert get_recipe(conn, done)["short_steps"] == ["Steep the tea"]
    conn.close()

    # The not-shortened "Stir." keeps Toast on the to-do list; ids pick recipes explicitly.
    calls.clear()
    assert main.main(["shorten-steps", str(done)]) == 0
    assert calls == [["Steep the tea bag."]]

import sqlite3

import pytest

from db import connect, find_recipes_by_pantry, get_recipe, list_recipes, save_recipe


def ing(name, amount=None, unit=None):
    return {"name": name, "amount": amount, "unit": unit}


@pytest.fixture
def conn():
    c = connect(":memory:")
    save_recipe(
        c,
        source_url="https://example.com/1",
        title="Garlic Butter Shrimp",
        ingredients=[ing("shrimp", 1, "lb"), ing("2 cloves garlic, minced"), ing("butter", 3, "Tablespoons"),
                     ing("salt"), ing("lemon")],
    )
    save_recipe(
        c,
        source_url="https://example.com/2",
        title="Scrambled Eggs",
        ingredients=[ing("Large Eggs", 3), ing("unsalted butter", 1, "tbsp"), ing("kosher salt")],
    )
    save_recipe(
        c,
        source_url="https://example.com/3",
        title="Beef Stir Fry",
        ingredients=[ing("beef"), ing("soy sauce"), ing("garlic"), ing("broccoli"), ing("ginger")],
    )
    return c


def test_save_normalizes_and_preserves_raw(conn):
    recipe = get_recipe(conn, 1)
    assert [i["name"] for i in recipe["ingredients"]] == ["shrimp", "garlic", "butter", "salt", "lemon"]
    assert recipe["ingredients"][1]["raw_name"] == "2 cloves garlic, minced"
    assert recipe["ingredients"][2]["unit"] == "tbsp"
    # "garlic" is shared between recipes 1 and 3
    assert conn.execute("SELECT COUNT(*) FROM ingredients WHERE name='garlic'").fetchone()[0] == 1


def test_save_upserts_by_url(conn):
    rid = save_recipe(conn, source_url="https://example.com/2", title="Better Eggs", ingredients=[ing("egg")])
    assert rid == 2
    recipe = get_recipe(conn, 2)
    assert recipe["title"] == "Better Eggs"
    assert [i["name"] for i in recipe["ingredients"]] == ["egg"]
    assert len(list_recipes(conn)) == 3


def test_pantry_ranks_by_selected_used_then_fewest_others(conn):
    matches = find_recipes_by_pantry(conn, ["eggs", "Butter", "garlic", "salt"])
    assert [m.title for m in matches] == ["Scrambled Eggs", "Garlic Butter Shrimp", "Beef Stir Fry"]
    eggs, shrimp, beef = matches
    assert (eggs.matched, eggs.total, eggs.missing) == (3, 3, [])
    assert shrimp.missing == ["lemon", "shrimp"]
    assert beef.missing_count == 4
    assert {m.selected for m in matches} == {4}


def test_pantry_more_selected_beats_fewer_missing(conn):
    # Stir fry uses 3 of the selection but needs 2 more; eggs use 1 and need only 2 more.
    matches = find_recipes_by_pantry(conn, ["beef", "soy sauce", "ginger", "egg"])
    assert [(m.title, m.matched, m.missing_count) for m in matches] == [
        ("Beef Stir Fry", 3, 2), ("Scrambled Eggs", 1, 2),
    ]


def test_pantry_ignores_staples(conn):
    matches = find_recipes_by_pantry(conn, ["egg", "butter"], ignore_ingredients=["sea salt"])
    eggs = next(m for m in matches if m.title == "Scrambled Eggs")
    assert (eggs.matched, eggs.total) == (2, 2)


def test_pantry_filters(conn):
    matches = find_recipes_by_pantry(conn, ["egg", "butter", "garlic", "salt"], max_missing=2)
    assert [m.title for m in matches] == ["Scrambled Eggs", "Garlic Butter Shrimp"]
    assert find_recipes_by_pantry(conn, ["chocolate"]) == []
    assert len(find_recipes_by_pantry(conn, ["garlic"], limit=1)) == 1



BANANA_BREAD = [ing("Softened unsalted butter", 170, "g"), ing("Mashed banana", 340, "g"), ing("Eggs", 2)]


def test_save_yield_and_sources(conn):
    rid = save_recipe(conn, source_url="https://example.com/bread", title="Banana Bread",
                      ingredients=BANANA_BREAD, yield_label="1 standard loaf pan",
                      ingredient_sources=["description", "speech", "description"])
    recipe = get_recipe(conn, rid)
    assert recipe["yield_label"] == "1 standard loaf pan"
    assert recipe["ingredient_sources"] == ["description", "speech"]
    listed = next(r for r in list_recipes(conn) if r["id"] == rid)
    assert (listed["ingredient_count"], listed["yield_label"]) == (3, "1 standard loaf pan")


def test_resave_replaces_yield_and_sources(conn):
    save_recipe(conn, source_url="https://example.com/bread", title="Banana Bread", ingredients=BANANA_BREAD,
                yield_label="1 loaf", ingredient_sources=["description"])
    rid = save_recipe(conn, source_url="https://example.com/bread", title="Banana Bread",
                      ingredients=[ing("banana")])
    recipe = get_recipe(conn, rid)
    assert recipe["yield_label"] is None
    assert recipe["on_screen_text"] is None
    assert recipe["ingredient_sources"] == []


def test_pantry_matches_prepared_ingredient_names(conn):
    save_recipe(conn, source_url="https://example.com/bread", title="Banana Bread", ingredients=BANANA_BREAD)
    bread = next(m for m in find_recipes_by_pantry(conn, ["butter", "banana", "egg"]) if m.title == "Banana Bread")
    assert (bread.matched, bread.total, bread.missing) == (3, 3, [])

def test_connect_migrates_old_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE recipes (id INTEGER PRIMARY KEY, source_url TEXT NOT NULL UNIQUE, video_id TEXT,
            title TEXT NOT NULL, uploader TEXT, description TEXT, transcript TEXT, transcript_source TEXT,
            raw_llm_json TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE ingredients (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE recipe_ingredients (id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL, raw_name TEXT NOT NULL, amount REAL, unit TEXT,
            position INTEGER NOT NULL);
        INSERT INTO recipes (id, source_url, title) VALUES (1, 'https://example.com/old', 'Old Toast');
        INSERT INTO ingredients (id, name) VALUES (1, 'bread');
        INSERT INTO recipe_ingredients (recipe_id, ingredient_id, raw_name, position) VALUES (1, 1, 'bread', 0);
        """
    )
    old.close()

    conn = connect(path)
    recipe = get_recipe(conn, 1)
    assert recipe["ingredient_sources"] == []
    assert recipe["yield_label"] is None
    assert recipe["on_screen_text"] is None
    assert [i["name"] for i in recipe["ingredients"]] == ["bread"]
    assert [m.title for m in find_recipes_by_pantry(conn, ["bread"])] == ["Old Toast"]
    conn.close()


def test_renormalize_repoints_changed_names(conn, monkeypatch):
    from db import normalize, repository

    # Simulate a row stored by an older normalizer.
    rid = save_recipe(conn, source_url="https://example.com/pumpkin", title="Pumpkin Balls",
                      ingredients=[ing("pumpkin purée"), ing("glutinous rice flour")])
    conn.execute("UPDATE ingredients SET name = 'pumpkin pur e' WHERE name = 'pumpkin puree'")
    conn.commit()

    assert repository.renormalize_ingredients(conn, dry_run=True) == [
        ("pumpkin purée", "pumpkin pur e", "pumpkin puree")
    ]
    assert conn.execute("SELECT COUNT(*) FROM ingredients WHERE name = 'pumpkin pur e'").fetchone()[0] == 1

    # An alias added later applies to existing rows too.
    monkeypatch.setitem(normalize.ALIASES, "glutinous rice flour", "sweet rice flour")
    changes = repository.renormalize_ingredients(conn)
    assert [c[2] for c in changes] == ["sweet rice flour", "pumpkin puree"]
    names = [i["name"] for i in get_recipe(conn, rid)["ingredients"]]
    assert names == ["pumpkin puree", "sweet rice flour"]
    # old ingredient rows are gone
    assert conn.execute(
        "SELECT COUNT(*) FROM ingredients WHERE name IN ('pumpkin pur e', 'glutinous rice flour')"
    ).fetchone()[0] == 0
    assert repository.renormalize_ingredients(conn) == []


def test_status_ready_or_left_for_backfill(conn):
    from db import backfill_status, count_by_status

    assert {r["status"] for r in list_recipes(conn)} == {"ready"}
    empty = save_recipe(conn, source_url="https://example.com/e", title="Vlog", ingredients=[], description="vlog")
    linked = save_recipe(conn, source_url="https://example.com/l", title="Cake", ingredients=[],
                         status="needs_recipe", status_note="blocked")
    assert get_recipe(conn, empty)["status"] is None
    assert get_recipe(conn, linked)["status_note"] == "blocked"

    seen = []
    assert backfill_status(conn, lambda d: seen.append(d) or "not_recipe") == 1
    assert seen == ["vlog"]
    assert count_by_status(conn) == {"ready": 3, "not_recipe": 1, "needs_recipe": 1}
    assert [r["title"] for r in list_recipes(conn, ["needs_recipe"])] == ["Cake"]

    # Getting ingredients later makes it ready and clears the note.
    save_recipe(conn, source_url="https://example.com/l", title="Cake", ingredients=[ing("flour")],
                status="needs_recipe", status_note="blocked")
    assert (get_recipe(conn, linked)["status"], get_recipe(conn, linked)["status_note"]) == ("ready", None)


def test_backfill_marks_old_rows_with_ingredients_ready(tmp_path):
    path = tmp_path / "old.db"
    conn = connect(path)
    save_recipe(conn, source_url="https://example.com/x", title="X", ingredients=[ing("egg")])
    conn.execute("UPDATE recipes SET status = NULL")
    conn.commit()
    from db import backfill_status

    assert backfill_status(conn, lambda d: "not_recipe") == 1
    assert get_recipe(conn, 1)["status"] == "ready"
    assert backfill_status(conn, lambda d: "not_recipe") == 0

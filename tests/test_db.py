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


def test_pantry_ranks_by_missing_count(conn):
    matches = find_recipes_by_pantry(conn, ["eggs", "Butter", "garlic", "salt"])
    assert [m.title for m in matches] == ["Scrambled Eggs", "Garlic Butter Shrimp", "Beef Stir Fry"]
    eggs, shrimp, beef = matches
    assert (eggs.matched, eggs.total, eggs.missing) == (3, 3, [])
    assert shrimp.missing == ["lemon", "shrimp"]
    assert beef.missing_count == 4


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

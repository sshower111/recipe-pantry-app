import dataclasses
import json

import pytest

import main
from db import PantryMatch, connect, save_recipe
from pipeline import ingest
from pipeline.ingest import IngestResult
from pipeline.parser import Ingredient, ParsedRecipe


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    """Point the CLI at a temporary database with two recipes."""
    path = tmp_path / "recipes.db"
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path))
    conn = connect(path)
    save_recipe(conn, source_url="https://example.com/pasta", title="Garlic Butter Pasta",
                ingredients=[{"name": "pasta"}, {"name": "garlic"}, {"name": "butter"}, {"name": "parmesan"},
                             {"name": "salt"}])
    save_recipe(conn, source_url="https://example.com/shrimp", title="Garlic Shrimp",
                ingredients=[{"name": "shrimp"}, {"name": "garlic"}, {"name": "lemon"}, {"name": "chili flakes"}])
    conn.close()
    return path


def test_parse_ingredient_list_splits_commas():
    assert main.parse_ingredient_list(["garlic, butter,pasta", "soy sauce", " , "]) == [
        "garlic", "butter", "pasta", "soy sauce",
    ]


def test_search_ranks_and_lists_missing(db_path, capsys):
    assert main.main(["search", "--ingredients", "garlic, butter, pasta"]) == 0
    out = capsys.readouterr().out
    assert out.index("Garlic Butter Pasta") < out.index("Garlic Shrimp")
    assert "1. [1] Garlic Butter Pasta  (3/4 ingredients, missing 1)" in out
    assert "     have:    butter, garlic, pasta\n     missing: parmesan\n" in out
    assert "missing: chili flake, lemon, shrimp" in out  # names are normalized
    assert "salt" not in out  # staple


def test_search_json_and_filters(db_path, capsys):
    assert main.main(["search", "-i", "garlic, butter, pasta", "--max-missing", "1", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["title"] for r in rows] == ["Garlic Butter Pasta"]
    assert rows[0]["have"] == ["butter", "garlic", "pasta"]
    assert rows[0]["missing"] == ["parmesan"]


def test_pantry_command_still_works_with_commas(db_path, capsys):
    assert main.main(["pantry", "garlic,", "butter", "pasta", "parmesan"]) == 0
    assert "Garlic Butter Pasta  (4/4 ingredients, can make now)" in capsys.readouterr().out


def test_search_without_matches(db_path, capsys):
    assert main.main(["search", "-i", "chocolate"]) == 0
    assert capsys.readouterr().out.strip() == "No matching recipes."


def test_search_rejects_empty_list(db_path, capsys):
    assert main.main(["search", "-i", " , "]) == 2


def test_format_matches_can_make_now():
    match = PantryMatch(recipe_id=3, title="Toast", source_url="u", total=2, matched=2,
                        have=["bread", "butter"], missing=[])
    assert main.format_matches([match]) == (
        "1. [3] Toast  (2/2 ingredients, can make now)\n"
        "     have:    bread, butter\n"
        "     missing: -\n"
        "     u"
    )


@pytest.fixture
def fake_ingest(monkeypatch):
    """Replace ingest_url: URLs containing 'old' are already stored, 'bad' ones fail."""
    calls = []

    def fake(url, conn, *, skip_existing):
        calls.append((url, skip_existing))
        if "bad" in url:
            raise RuntimeError("Unsupported URL")
        if "old" in url and skip_existing:
            return IngestResult(recipe_id=1, source_url=url, status="skipped")
        parsed = ParsedRecipe(title=f"Recipe {len(calls)}", sources=["description"], yield_label="serves 2",
                              ingredients=[Ingredient(name="egg")])
        status = "updated" if "old" in url else "added"
        return IngestResult(recipe_id=len(calls), source_url=url, status=status, recipe=parsed,
                            transcript_source="whisper", ingredient_sources=["description"])

    monkeypatch.setattr(ingest, "ingest_url", fake)
    return calls


def test_batch_skips_existing_and_in_file_duplicates(db_path, fake_ingest, tmp_path, capsys):
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "# my list\n"
        "https://www.instagram.com/p/old1/\n"
        "\n"
        "Things to try this weekend:\n"
        "Pasta: https://www.instagram.com/p/new1/\n"
        "https://www.instagram.com/reel/new1/?igsh=zz   # same post again\n"
        "https://bad.example/video\n",
        encoding="utf-8",
    )
    assert main.main(["batch", "--file", str(url_file)]) == 1  # one failure

    captured = capsys.readouterr()
    assert "4 URLs from" in captured.out
    assert "(ignored 1 line with no URL)" in captured.out
    assert [url for url, _ in fake_ingest] == [
        "https://www.instagram.com/p/old1/", "https://www.instagram.com/p/new1/", "https://bad.example/video",
    ]
    assert all(skip for _, skip in fake_ingest)
    assert "SKIP   [1] https://www.instagram.com/p/old1/: already stored" in captured.out
    assert "ADDED  [2] Recipe 2 (1 ingredients, makes serves 2;" in captured.out
    assert "duplicate of an earlier URL in this run" in captured.out
    assert "FAILED https://bad.example/video: Unsupported URL" in captured.err
    assert "1 added, 0 updated, 2 skipped, 1 failed" in captured.out


def test_batch_refresh_reparses_existing(db_path, fake_ingest, tmp_path, capsys):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://www.instagram.com/p/old1/\n", encoding="utf-8")
    assert main.main(["batch", "-f", str(url_file), "--refresh"]) == 0
    assert fake_ingest == [("https://www.instagram.com/p/old1/", False)]
    assert "UPDATED [1] Recipe 1" in capsys.readouterr().out


def test_batch_missing_or_empty_file(db_path, tmp_path, capsys):
    assert main.main(["batch", "--file", str(tmp_path / "nope.txt")]) == 1
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing yet\n", encoding="utf-8")
    assert main.main(["batch", "--file", str(empty)]) == 1
    assert "No URLs found" in capsys.readouterr().err


@pytest.fixture
def db_with_empty(db_path):
    conn = connect(db_path)
    save_recipe(conn, source_url="https://example.com/cake", title="Basque Cheesecake", ingredients=[],
                description="Recipe on my website OR Comment SPAIN and I will send it to you")
    save_recipe(conn, source_url="https://example.com/brownie", title="Brownies", ingredients=[],
                description="Full link here: https://scientificallysweet.com/brownies/")
    save_recipe(conn, source_url="https://example.com/ad", title="Coconut Drink", ingredients=[],
                description="#ad with @brand.official")
    save_recipe(conn, source_url="https://example.com/cookies", title="Cookies",
                ingredients=[{"name": "flour"}], description="recipe: https://blog.example.com/cookies")
    conn.close()
    return db_path


def test_list_shows_ready_recipes_and_counts_hidden(db_with_empty, capsys):
    main.main(["list"])
    out = capsys.readouterr().out
    assert "[6] Cookies  (1 ingredients)" in out
    assert "Basque Cheesecake" not in out and "Coconut Drink" not in out
    assert "(hidden: 2 needs a recipe, 1 not a recipe; see `list --todo` or `list --all`)" in out


def test_list_todo_shows_posts_needing_a_recipe(db_with_empty, capsys):
    main.main(["list", "--todo"])
    lines = capsys.readouterr().out.splitlines()
    assert "[4] Brownies" in lines and "[3] Basque Cheesecake" in lines
    assert "      no ingredient list in the post; recipe at https://scientificallysweet.com/brownies/" in lines
    assert not any("Coconut Drink" in line or "Cookies" in line for line in lines)
    assert lines[-1] == "Add a recipe page with: python main.py import-page <id> --url <recipe page>"


def test_list_all_includes_every_status(db_with_empty, capsys):
    main.main(["list", "--all"])
    out = capsys.readouterr().out
    assert "[5] Coconut Drink  (not a recipe)" in out
    assert "[3] Basque Cheesecake  (needs a recipe)" in out
    assert "hidden" not in out


@pytest.mark.parametrize(
    ("recipe_id", "status", "expected"),
    [
        (3, "needs a recipe",
         "No ingredient list in the post; the caption says the recipe is on a blog, in the bio, or by DM"),
        (4, "needs a recipe", "No ingredient list in the post; recipe at https://scientificallysweet.com/brownies/"),
        (5, "not a recipe", "Not a recipe: no ingredient list and nothing pointing to one"),
    ],
)
def test_show_explains_missing_list(db_with_empty, capsys, recipe_id, status, expected):
    main.main(["show", str(recipe_id)])
    lines = capsys.readouterr().out.splitlines()
    assert lines[2:4] == [f"Status: {status}", expected]


def test_show_includes_recorded_failure(db_with_empty, capsys):
    from db import set_status_note

    conn = connect(db_with_empty)
    set_status_note(conn, 4, "scientificallysweet.com blocks automated requests (HTTP 403)")
    conn.close()
    main.main(["show", "4"])
    assert capsys.readouterr().out.splitlines()[3].endswith(
        "[scientificallysweet.com blocks automated requests (HTTP 403)]")


def test_show_prints_full_recipe_link(db_with_empty, capsys):
    main.main(["show", "6"])
    assert "Full recipe: https://blog.example.com/cookies" in capsys.readouterr().out


def test_batch_reports_posts_without_ingredients(db_path, monkeypatch, tmp_path, capsys):
    def fake(url, conn, *, skip_existing):
        parsed = ParsedRecipe(title="Cheesecake", sources=[], yield_label=None, ingredients=[])
        return IngestResult(recipe_id=9, source_url=url, status="added", recipe=parsed,
                            transcript_source="whisper", ingredient_sources=[],
                            description="comment 'CAKE' and I'll send it")

    monkeypatch.setattr(ingest, "ingest_url", fake)
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com/a\nhttps://example.com/b\n", encoding="utf-8")
    main.main(["batch", "-f", str(url_file)])
    out = capsys.readouterr().out
    assert "ADDED  [9] Cheesecake (no ingredient list in the post; the caption says" in out
    assert "2 added, 0 updated, 0 skipped, 0 failed (of the saved: 2 needs a recipe; see `list --todo`)" in out

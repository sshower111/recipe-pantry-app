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

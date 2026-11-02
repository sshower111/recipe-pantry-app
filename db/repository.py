"""Insert and read recipes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from db.normalize import normalize_ingredient_name, normalize_unit


def get_or_create_ingredient(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO ingredients(name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM ingredients WHERE name = ?", (name,)).fetchone()[0]


def save_recipe(
    conn: sqlite3.Connection,
    *,
    source_url: str,
    title: str,
    ingredients: Iterable[Mapping[str, Any]],
    yield_label: str | None = None,
    ingredient_sources: Iterable[str] = (),
    video_id: str | None = None,
    uploader: str | None = None,
    description: str | None = None,
    transcript: str | None = None,
    transcript_source: str | None = None,
    on_screen_text: str | None = None,
    recipe_page_url: str | None = None,
    recipe_page_text: str | None = None,
    raw_llm_json: str | None = None,
    status: str | None = None,
    status_note: str | None = None,
) -> int:
    """Insert or replace a recipe (keyed by source_url) and its ingredient lines.

    Each ingredient mapping needs a ``name``; ``amount`` and ``unit`` are optional.
    Names are normalized onto the shared ``ingredients`` table; the original text is
    kept in ``recipe_ingredients.raw_name``.

    A recipe with ingredient lines is always ``ready``. Without any, ``status`` says why
    (``needs_recipe`` or ``not_recipe``; left NULL if not given, for ``backfill_status``)
    and ``status_note`` can give details.
    """
    sources = ",".join(dict.fromkeys(s for s in ingredient_sources if s)) or None

    with conn:
        recipe_id = conn.execute(
            """
            INSERT INTO recipes (source_url, video_id, title, uploader, description,
                                 transcript, transcript_source, on_screen_text, recipe_page_url,
                                 recipe_page_text, ingredient_sources, yield_label, raw_llm_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                video_id = excluded.video_id,
                title = excluded.title,
                uploader = excluded.uploader,
                description = excluded.description,
                transcript = excluded.transcript,
                transcript_source = excluded.transcript_source,
                on_screen_text = excluded.on_screen_text,
                recipe_page_url = excluded.recipe_page_url,
                recipe_page_text = excluded.recipe_page_text,
                ingredient_sources = excluded.ingredient_sources,
                yield_label = excluded.yield_label,
                raw_llm_json = excluded.raw_llm_json,
                updated_at = datetime('now')
            RETURNING id
            """,
            (source_url, video_id, title, uploader, description,
             transcript, transcript_source, on_screen_text, recipe_page_url, recipe_page_text,
             sources, yield_label, raw_llm_json),
        ).fetchone()[0]

        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))

        position = 0
        for item in ingredients:
            raw_name = str(item.get("name") or "").strip()
            name = normalize_ingredient_name(raw_name)
            if not name:
                continue
            conn.execute(
                """
                INSERT INTO recipe_ingredients
                    (recipe_id, ingredient_id, raw_name, amount, unit, position)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (recipe_id, get_or_create_ingredient(conn, name), raw_name,
                 item.get("amount"), normalize_unit(item.get("unit")), position),
            )
            position += 1

        if position:
            status, status_note = "ready", None
        elif status not in ("needs_recipe", "not_recipe"):
            status = None  # unknown: backfill_status classifies it from the caption
        conn.execute(
            "UPDATE recipes SET status = ?, status_note = ? WHERE id = ?", (status, status_note, recipe_id)
        )

    return recipe_id


def set_status_note(conn: sqlite3.Connection, recipe_id: int, note: str | None) -> None:
    with conn:
        conn.execute("UPDATE recipes SET status_note = ? WHERE id = ?", (note, recipe_id))


def backfill_status(conn: sqlite3.Connection, classify_empty: Callable[[str | None], str]) -> int:
    """Set ``status`` on rows saved before it existed. Rows with ingredients are ``ready``;
    ``classify_empty(description)`` decides the rest. Returns the number of rows updated."""
    rows = conn.execute(
        """
        SELECT r.id, r.description, COUNT(ri.id) AS lines
        FROM recipes r LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
        WHERE r.status IS NULL
        GROUP BY r.id
        """
    ).fetchall()
    with conn:
        conn.executemany(
            "UPDATE recipes SET status = ? WHERE id = ?",
            [("ready" if lines else classify_empty(description), rid) for rid, description, lines in rows],
        )
    return len(rows)


def renormalize_ingredients(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> list[tuple[str, str, str]]:
    """Re-run ``normalize_ingredient_name`` on every stored ``raw_name`` and repoint lines
    whose canonical name changed (after edits to the normalizer or ``ALIASES``).

    Returns ``(raw_name, old_name, new_name)`` for each distinct change. Lines whose raw
    text now normalizes to "" are left alone. Unused ingredient rows are deleted.
    """
    rows = conn.execute(
        """
        SELECT ri.id, ri.raw_name, i.name
        FROM recipe_ingredients ri JOIN ingredients i ON i.id = ri.ingredient_id
        """
    ).fetchall()
    changes: dict[tuple[str, str, str], list[int]] = {}
    for line_id, raw_name, old_name in rows:
        new_name = normalize_ingredient_name(raw_name)
        if new_name and new_name != old_name:
            changes.setdefault((raw_name, old_name, new_name), []).append(line_id)
    if dry_run or not changes:
        return sorted(changes)

    with conn:
        for (_, _, new_name), line_ids in changes.items():
            ingredient_id = get_or_create_ingredient(conn, new_name)
            conn.executemany(
                "UPDATE recipe_ingredients SET ingredient_id = ? WHERE id = ?",
                [(ingredient_id, line_id) for line_id in line_ids],
            )
        conn.execute(
            "DELETE FROM ingredients WHERE id NOT IN (SELECT ingredient_id FROM recipe_ingredients)"
        )
    return sorted(changes)


def find_recipe_id(conn: sqlite3.Connection, source_url: str) -> int | None:
    row = conn.execute("SELECT id FROM recipes WHERE source_url = ?", (source_url,)).fetchone()
    return row[0] if row else None


def get_recipe(conn: sqlite3.Connection, recipe_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        return None
    recipe = dict(row)
    sources = recipe.get("ingredient_sources")
    recipe["ingredient_sources"] = sources.split(",") if sources else []
    recipe["ingredients"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT i.name, ri.raw_name, ri.amount, ri.unit
            FROM recipe_ingredients ri
            JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = ?
            ORDER BY ri.position
            """,
            (recipe_id,),
        )
    ]
    return recipe


def list_recipes(conn: sqlite3.Connection, statuses: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Recipes newest first, optionally only those with one of ``statuses``."""
    wanted = None if statuses is None else json.dumps(list(statuses))
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT r.id, r.title, r.source_url, r.yield_label, r.uploader, r.description,
                   r.status, r.status_note,
                   COUNT(DISTINCT ri.ingredient_id) AS ingredient_count
            FROM recipes r
            LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
            WHERE :wanted IS NULL OR r.status IN (SELECT value FROM json_each(:wanted))
            GROUP BY r.id
            ORDER BY r.created_at DESC, r.id DESC
            """,
            {"wanted": wanted},
        )
    ]


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    return dict(conn.execute("SELECT status, COUNT(*) FROM recipes GROUP BY status").fetchall())

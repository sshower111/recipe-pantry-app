"""Insert and read recipes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
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
    raw_llm_json: str | None = None,
) -> int:
    """Insert or replace a recipe (keyed by source_url) and its ingredient lines.

    Each ingredient mapping needs a ``name``; ``amount`` and ``unit`` are optional.
    Names are normalized onto the shared ``ingredients`` table; the original text is
    kept in ``recipe_ingredients.raw_name``.
    """
    sources = ",".join(dict.fromkeys(s for s in ingredient_sources if s)) or None

    with conn:
        recipe_id = conn.execute(
            """
            INSERT INTO recipes (source_url, video_id, title, uploader, description,
                                 transcript, transcript_source, on_screen_text, ingredient_sources,
                                 yield_label, raw_llm_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url) DO UPDATE SET
                video_id = excluded.video_id,
                title = excluded.title,
                uploader = excluded.uploader,
                description = excluded.description,
                transcript = excluded.transcript,
                transcript_source = excluded.transcript_source,
                on_screen_text = excluded.on_screen_text,
                ingredient_sources = excluded.ingredient_sources,
                yield_label = excluded.yield_label,
                raw_llm_json = excluded.raw_llm_json,
                updated_at = datetime('now')
            RETURNING id
            """,
            (source_url, video_id, title, uploader, description,
             transcript, transcript_source, on_screen_text, sources, yield_label, raw_llm_json),
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

    return recipe_id


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


def list_recipes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT r.id, r.title, r.source_url, r.yield_label,
                   COUNT(DISTINCT ri.ingredient_id) AS ingredient_count
            FROM recipes r
            LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC, r.id DESC
            """
        )
    ]

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
    steps: Iterable[str] = (),
    short_steps: Iterable[str | None] = (),
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

    ``short_steps`` are the island versions of ``steps``, by position (missing ones are NULL).
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
        conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (recipe_id,))
        shorts = list(short_steps)
        pairs = [((t or "").strip(), shorts[n] if n < len(shorts) else None) for n, t in enumerate(steps)]
        conn.executemany(
            "INSERT INTO recipe_steps (recipe_id, position, text, short_text) VALUES (?, ?, ?, ?)",
            [(recipe_id, n, text, short) for n, (text, short) in enumerate(p for p in pairs if p[0])],
        )

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


def set_thumbnail(conn: sqlite3.Connection, recipe_id: int, file_name: str | None) -> None:
    with conn:
        conn.execute("UPDATE recipes SET thumbnail_file = ? WHERE id = ?", (file_name, recipe_id))


def set_marks(
    conn: sqlite3.Connection, recipe_id: int, *, favorite: bool | None = None, tried: bool | None = None
) -> dict[str, bool] | None:
    """Set the user's favorite/tried marks (None leaves a mark as it is). Returns both marks,
    or None if there is no such recipe."""
    with conn:
        conn.execute(
            "UPDATE recipes SET favorite = COALESCE(?, favorite), tried = COALESCE(?, tried) WHERE id = ?",
            (favorite, tried, recipe_id),
        )
    row = conn.execute("SELECT favorite, tried FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    return None if row is None else {"favorite": bool(row[0]), "tried": bool(row[1])}


def set_status(conn: sqlite3.Connection, recipe_id: int, status: str) -> str | None:
    """Relabel a post without an ingredient list: ``needs_recipe`` (keep it, the recipe is
    elsewhere or coming) or ``not_recipe``. Returns the status, None if there is no such
    recipe. Raises ValueError for a recipe that has ingredients (those are always ``ready``)."""
    if status not in ("needs_recipe", "not_recipe"):
        raise ValueError(f"status must be needs_recipe or not_recipe, not {status!r}")
    row = conn.execute(
        "SELECT r.id, COUNT(ri.id) FROM recipes r LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id"
        " WHERE r.id = ? GROUP BY r.id",
        (recipe_id,),
    ).fetchone()
    if row is None:
        return None
    if row[1]:
        raise ValueError("this recipe has an ingredient list, so it stays ready")
    with conn:
        conn.execute("UPDATE recipes SET status = ? WHERE id = ?", (status, recipe_id))
    return status


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
    rows = conn.execute(
        "SELECT text, short_text FROM recipe_steps WHERE recipe_id = ? ORDER BY position", (recipe_id,)
    ).fetchall()
    recipe["steps"] = [r[0] for r in rows]
    recipe["short_steps"] = [r[1] for r in rows]  # None where not shortened yet
    return recipe


def set_short_steps(conn: sqlite3.Connection, recipe_id: int, short_steps: Iterable[str | None]) -> None:
    """Store the island versions of a recipe's steps, by position; nothing else changes."""
    with conn:
        conn.executemany(
            "UPDATE recipe_steps SET short_text = ? WHERE recipe_id = ? AND position = ?",
            [(short, recipe_id, n) for n, short in enumerate(short_steps)],
        )


def list_recipes(conn: sqlite3.Connection, statuses: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Recipes newest first, optionally only those with one of ``statuses``."""
    wanted = None if statuses is None else json.dumps(list(statuses))
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT r.id, r.title, r.source_url, r.yield_label, r.uploader, r.description,
                   r.status, r.status_note, r.video_id, r.thumbnail_file, r.favorite, r.tried,
                   COUNT(DISTINCT ri.ingredient_id) AS ingredient_count,
                   (SELECT COUNT(*) FROM recipe_steps rs WHERE rs.recipe_id = r.id) AS step_count
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

"""Match stored recipes against what's in the pantry."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from db.normalize import normalize_ingredient_name


@dataclass(frozen=True)
class PantryMatch:
    recipe_id: int
    title: str
    source_url: str
    total: int
    matched: int
    have: list[str]
    missing: list[str]

    @property
    def missing_count(self) -> int:
        return self.total - self.matched


_QUERY = """
WITH pantry(name) AS (SELECT DISTINCT value FROM json_each(:pantry)),
     ignored(name) AS (SELECT DISTINCT value FROM json_each(:ignored))
SELECT r.id                                                         AS recipe_id,
       r.title                                                      AS title,
       r.source_url                                                 AS source_url,
       COUNT(DISTINCT ri.ingredient_id)                             AS total,
       COUNT(DISTINCT CASE WHEN p.name IS NOT NULL THEN ri.ingredient_id END) AS matched,
       GROUP_CONCAT(DISTINCT CASE WHEN p.name IS NOT NULL THEN i.name END)    AS have,
       GROUP_CONCAT(DISTINCT CASE WHEN p.name IS NULL THEN i.name END)        AS missing
FROM recipes r
JOIN recipe_ingredients ri ON ri.recipe_id = r.id
JOIN ingredients i         ON i.id = ri.ingredient_id
LEFT JOIN pantry p         ON p.name = i.name
WHERE i.name NOT IN (SELECT name FROM ignored)
GROUP BY r.id
HAVING matched >= :min_matched
   AND (:max_missing IS NULL OR total - matched <= :max_missing)
ORDER BY total - matched ASC,
         CAST(matched AS REAL) / total DESC,
         r.title COLLATE NOCASE
LIMIT :limit
"""


def _split(names: str | None) -> list[str]:
    return sorted(names.split(",")) if names else []


def _normalize_all(names: Iterable[str]) -> list[str]:
    return sorted({n for n in map(normalize_ingredient_name, names) if n})


def find_recipes_by_pantry(
    conn: sqlite3.Connection,
    available_ingredients: list[str],
    *,
    ignore_ingredients: Iterable[str] = (),
    max_missing: int | None = None,
    min_matched: int = 1,
    limit: int | None = None,
) -> list[PantryMatch]:
    """Return recipes ranked by fewest missing ingredients.

    ``ignore_ingredients`` (e.g. salt, water) are left out of both the totals and the
    missing list. Recipes need at least ``min_matched`` pantry hits to be returned.
    """
    rows = conn.execute(
        _QUERY,
        {
            "pantry": json.dumps(_normalize_all(available_ingredients)),
            "ignored": json.dumps(_normalize_all(ignore_ingredients)),
            "min_matched": min_matched,
            "max_missing": max_missing,
            "limit": -1 if limit is None else limit,
        },
    ).fetchall()
    return [
        PantryMatch(
            recipe_id=row["recipe_id"],
            title=row["title"],
            source_url=row["source_url"],
            total=row["total"],
            matched=row["matched"],
            have=_split(row["have"]),
            missing=_split(row["missing"]),
        )
        for row in rows
    ]

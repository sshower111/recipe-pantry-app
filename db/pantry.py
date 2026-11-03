"""Find stored recipes that use the ingredients a user selected (what they have or want to eat)."""

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
    total: int  # the recipe's distinct ingredients, staples excluded
    matched: int  # how many of those were selected
    have: list[str]
    missing: list[str]
    selected: int = 0  # how many distinct ingredients were selected, staples excluded

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
  AND r.hidden = 0
GROUP BY r.id
HAVING matched >= :min_matched
   AND (:max_missing IS NULL OR total - matched <= :max_missing)
ORDER BY matched DESC,           -- uses the most of what was selected
         total - matched ASC,     -- then needs the fewest other ingredients
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
    """Return recipes that use at least ``min_matched`` of the selected ingredients, those
    using the most of them first, ties broken by fewest other ingredients needed.

    ``ignore_ingredients`` (e.g. salt, water) are left out of the counts and lists on both
    sides. ``max_missing`` optionally drops recipes needing more than that many others.
    """
    selected = _normalize_all(available_ingredients)
    ignored = _normalize_all(ignore_ingredients)
    rows = conn.execute(
        _QUERY,
        {
            "pantry": json.dumps(selected),
            "ignored": json.dumps(ignored),
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
            selected=len(set(selected) - set(ignored)),
        )
        for row in rows
    ]

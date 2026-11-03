"""SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id                INTEGER PRIMARY KEY,
    source_url        TEXT NOT NULL UNIQUE,
    video_id          TEXT,
    title             TEXT NOT NULL,
    uploader          TEXT,
    description       TEXT,
    transcript        TEXT,
    transcript_source TEXT CHECK (transcript_source IN ('captions', 'whisper', 'none')),
    -- Distinct text lines OCR'd from video frames (NULL when OCR didn't run).
    on_screen_text    TEXT,
    -- The creator's recipe web page, when ingredients were imported from it.
    recipe_page_url   TEXT,
    recipe_page_text  TEXT,
    -- ready: has ingredients. needs_recipe: the recipe is elsewhere (blog, bio link, DM, or a
    -- site that blocks downloads). not_recipe: not a cooking recipe. Rows are kept either way
    -- so batch runs skip posts already looked at.
    status            TEXT CHECK (status IN ('ready', 'needs_recipe', 'not_recipe')),
    status_note       TEXT,
    -- Comma-separated inputs the ingredients came from: description, speech, captions,
    -- comments, on_screen, title.
    ingredient_sources TEXT,
    -- What the ingredient amounts make, e.g. "serves 4" or "1 standard loaf pan".
    yield_label       TEXT,
    raw_llm_json      TEXT,
    -- Video thumbnail saved under <data dir>/thumbnails/ (file name only).
    thumbnail_file    TEXT,
    -- The user's own marks, set from the app; re-ingesting leaves them alone.
    favorite          INTEGER NOT NULL DEFAULT 0,
    tried             INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Canonical (normalized) ingredient names, shared across recipes.
CREATE TABLE IF NOT EXISTS ingredients (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- One row per ingredient line; the same ingredient may appear twice in a recipe
-- (e.g. salt for the marinade and for the sauce).
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id            INTEGER PRIMARY KEY,
    recipe_id     INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    raw_name      TEXT NOT NULL,
    amount        REAL,
    unit          TEXT,
    position      INTEGER NOT NULL
);

-- The method, one row per step in order.
CREATE TABLE IF NOT EXISTS recipe_steps (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    -- A model-written version of about 40-60 characters for the iOS Dynamic Island and
    -- Lock Screen (NULL until `main.py shorten-steps` or a parse fills it).
    short_text TEXT,
    PRIMARY KEY (recipe_id, position)
);

CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe ON recipe_ingredients(recipe_id);
CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_ingredient ON recipe_ingredients(ingredient_id);
"""

# Columns added after the first release: (table, column, definition). CREATE TABLE IF NOT
# EXISTS leaves older databases alone, so these are added with ALTER TABLE.
_ADDED_COLUMNS = [
    ("recipes", "ingredient_sources", "TEXT"),
    ("recipes", "yield_label", "TEXT"),
    ("recipes", "on_screen_text", "TEXT"),
    ("recipes", "recipe_page_url", "TEXT"),
    ("recipes", "recipe_page_text", "TEXT"),
    ("recipes", "status", "TEXT CHECK (status IN ('ready', 'needs_recipe', 'not_recipe'))"),
    ("recipes", "status_note", "TEXT"),
    ("recipes", "thumbnail_file", "TEXT"),
    ("recipes", "favorite", "INTEGER NOT NULL DEFAULT 0"),
    ("recipes", "tried", "INTEGER NOT NULL DEFAULT 0"),
    ("recipe_steps", "short_text", "TEXT"),
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in _ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def connect(path: str | Path = ":memory:", *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection with foreign keys on and the schema applied.

    ``check_same_thread=False`` is for the API, whose request connections may be opened
    and closed on different worker threads (still used by one request at a time)."""
    on_disk = str(path) != ":memory:"
    if on_disk:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if on_disk:
        conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn)
    return conn

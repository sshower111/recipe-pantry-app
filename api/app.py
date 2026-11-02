"""HTTP API for the web app: a thin JSON layer over the SQLite database.

Run with ``uvicorn api.app:app --port 8000`` (the Next.js app in ``web/`` proxies
``/api/*`` here). ``create_app`` takes explicit paths so tests can use a temporary database.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db import connect, get_recipe, list_recipes, match_step_ingredients, set_marks
from pipeline.urls import embed_url

_STATUSES = {"ready": ["ready"], "todo": ["needs_recipe"], "all": None}


class Marks(BaseModel):
    favorite: bool | None = None
    tried: bool | None = None


def _video(source_url: str) -> dict[str, Any]:
    embed = embed_url(source_url)
    return {"url": source_url, "platform": embed[0] if embed else None, "embed_url": embed[1] if embed else None}


def create_app(db_path: str | Path, thumbnails_dir: Path) -> FastAPI:
    app = FastAPI(title="Recipe Pantry API")

    def db() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def thumbnail_url(recipe: dict[str, Any]) -> str | None:
        name = recipe.get("thumbnail_file")
        return f"/api/recipes/{recipe['id']}/thumbnail" if name and (thumbnails_dir / name).is_file() else None

    @app.get("/api/recipes")
    def recipes(
        status: Literal["ready", "todo", "all"] = "ready", conn: sqlite3.Connection = Depends(db)
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "uploader": r["uploader"],
                "yield_label": r["yield_label"],
                "status": r["status"],
                "ingredient_count": r["ingredient_count"],
                "step_count": r["step_count"],
                "favorite": bool(r["favorite"]),
                "tried": bool(r["tried"]),
                "thumbnail_url": thumbnail_url(r),
                "platform": _video(r["source_url"])["platform"],
            }
            for r in list_recipes(conn, _STATUSES[status])
        ]

    @app.get("/api/recipes/{recipe_id}")
    def recipe(recipe_id: int, conn: sqlite3.Connection = Depends(db)) -> dict[str, Any]:
        r = get_recipe(conn, recipe_id)
        if r is None:
            raise HTTPException(404, "Recipe not found")
        uses = match_step_ingredients(r["steps"], r["ingredients"])
        return {
            "id": r["id"],
            "title": r["title"],
            "uploader": r["uploader"],
            "description": r["description"],
            "yield_label": r["yield_label"],
            "status": r["status"],
            "favorite": bool(r["favorite"]),
            "tried": bool(r["tried"]),
            "thumbnail_url": thumbnail_url(r),
            "recipe_page_url": r["recipe_page_url"],
            "video": _video(r["source_url"]),
            "ingredients": r["ingredients"],
            "steps": [{"text": text, "ingredients": used} for text, used in zip(r["steps"], uses)],
        }

    @app.patch("/api/recipes/{recipe_id}")
    def mark(recipe_id: int, marks: Marks, conn: sqlite3.Connection = Depends(db)) -> dict[str, bool]:
        result = set_marks(conn, recipe_id, favorite=marks.favorite, tried=marks.tried)
        if result is None:
            raise HTTPException(404, "Recipe not found")
        return result

    @app.get("/api/recipes/{recipe_id}/thumbnail")
    def thumbnail(recipe_id: int, conn: sqlite3.Connection = Depends(db)) -> FileResponse:
        row = conn.execute("SELECT thumbnail_file FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        path = thumbnails_dir / row[0] if row and row[0] else None
        if path is None or not path.is_file():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    return app


def _default_app() -> FastAPI:
    from config import settings

    return create_app(settings.db_path, settings.data_dir / "thumbnails")


app = _default_app()

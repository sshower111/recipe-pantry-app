"""HTTP API for the iPhone app: a thin JSON layer over the SQLite database, plus a queue for
posts shared from the phone.

Run with ``uvicorn api.app:app --host 0.0.0.0 --port 8000`` so the phone can reach it over
Wi-Fi. ``create_app`` takes explicit paths so tests can use a temporary database.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.jobs import IngestQueue
from db import (connect, find_recipes_by_pantry, get_recipe, list_recipes, match_step_ingredients, set_marks,
                set_status)
from pipeline.urls import canonical_url, embed_url

_STATUSES = {"ready": ["ready"], "todo": ["needs_recipe"], "all": None}
_LINK = re.compile(r"https?://\S+")


class Marks(BaseModel):
    favorite: bool | None = None
    tried: bool | None = None
    # Removed with a swipe in the app; false brings it back (Undo).
    hidden: bool | None = None
    # Only for posts without an ingredient list: keep it (needs_recipe) or hide it (not_recipe).
    status: Literal["needs_recipe", "not_recipe"] | None = None


class IngestRequest(BaseModel):
    # A link, or shared text containing one ("Check this out! https://vt.tiktok.com/...").
    url: str
    # Re-download and re-read a post already stored ("Check again"); otherwise stored posts
    # finish at once as "skipped".
    refresh: bool = False


def _video(source_url: str) -> dict[str, Any]:
    embed = embed_url(source_url)
    return {"url": source_url, "platform": embed[0] if embed else None, "embed_url": embed[1] if embed else None}


def create_app(
    db_path: str | Path,
    thumbnails_dir: Path,
    staples: tuple[str, ...] = (),
    ingest: Callable[[str], Any] | None = None,
) -> FastAPI:
    """``staples`` (salt, water, ...) are left out of pantry scoring unless a request
    asks for them (``include_staples``). ``ingest(url)`` runs one shared link through the
    pipeline (returning a ``pipeline.ingest.IngestResult``); without it, /api/ingest is off."""
    app = FastAPI(title="Recipe Pantry API")
    jobs = IngestQueue(ingest, key=canonical_url) if ingest else None

    def db() -> Iterator[sqlite3.Connection]:
        # FastAPI may run this dependency's setup and teardown on different threadpool
        # threads; with the default check, close() then fails and the request turns into
        # a 500 (seen when the iOS feed loads many thumbnails at once).
        conn = connect(db_path, check_same_thread=False)
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
            "steps": [
                {"text": text, "short_text": short, "ingredients": used}
                for text, short, used in zip(r["steps"], r["short_steps"], uses)
            ],
        }

    @app.patch("/api/recipes/{recipe_id}")
    def mark(recipe_id: int, marks: Marks, conn: sqlite3.Connection = Depends(db)) -> dict[str, Any]:
        if marks.status is not None:
            try:
                if set_status(conn, recipe_id, marks.status) is None:
                    raise HTTPException(404, "Recipe not found")
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        result = set_marks(conn, recipe_id, favorite=marks.favorite, tried=marks.tried, hidden=marks.hidden)
        if result is None:
            raise HTTPException(404, "Recipe not found")
        status = conn.execute("SELECT status FROM recipes WHERE id = ?", (recipe_id,)).fetchone()[0]
        return {**result, "status": status}

    @app.get("/api/ingredients")
    def ingredients(conn: sqlite3.Connection = Depends(db)) -> list[dict[str, Any]]:
        """Canonical ingredient names used by ready recipes, most used first: what a pantry
        picker can offer."""
        return [
            {"name": name, "recipe_count": count}
            for name, count in conn.execute(
                """
                SELECT i.name, COUNT(DISTINCT ri.recipe_id) AS recipes
                FROM ingredients i
                JOIN recipe_ingredients ri ON ri.ingredient_id = i.id
                JOIN recipes r ON r.id = ri.recipe_id AND r.status = 'ready' AND r.hidden = 0
                GROUP BY i.id
                ORDER BY recipes DESC, i.name
                """
            )
        ]

    @app.get("/api/pantry")
    def pantry(
        have: list[str] = Query(default=[], description="ingredients you have; repeat the parameter"),
        limit: int | None = Query(default=None, ge=1),
        include_staples: bool = False,
        conn: sqlite3.Connection = Depends(db),
    ) -> list[dict[str, Any]]:
        """Recipes using at least one of ``have``, those using the most first, then the ones
        needing the fewest other ingredients (same ranking as ``main.py pantry``)."""
        matches = find_recipes_by_pantry(
            conn, have, ignore_ingredients=() if include_staples else staples, limit=limit
        )
        thumbnails = dict(conn.execute("SELECT id, thumbnail_file FROM recipes"))
        return [
            {
                "recipe_id": m.recipe_id,
                "title": m.title,
                "thumbnail_url": thumbnail_url({"id": m.recipe_id, "thumbnail_file": thumbnails.get(m.recipe_id)}),
                "matched": m.matched,
                "selected": m.selected,
                "total": m.total,
                "missing_count": m.missing_count,
                "have": m.have,
                "missing": m.missing,
            }
            for m in matches
        ]

    @app.get("/api/recipes/{recipe_id}/thumbnail")
    def thumbnail(recipe_id: int, conn: sqlite3.Connection = Depends(db)) -> FileResponse:
        row = conn.execute("SELECT thumbnail_file FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        path = thumbnails_dir / row[0] if row and row[0] else None
        if path is None or not path.is_file():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    # Adding recipes from the phone (share sheet): the job runs here in the background.
    def ingest_jobs() -> IngestQueue:
        if jobs is None:
            raise HTTPException(503, "Adding recipes is not enabled on this server")
        return jobs

    @app.post("/api/ingest", status_code=202)
    def queue_ingest(body: IngestRequest) -> dict[str, Any]:
        link = _LINK.search(body.url)
        if not link:
            raise HTTPException(422, "No link found; share a post's link (https://...)")
        return ingest_jobs().submit(link.group(0).rstrip(".,)"), refresh=body.refresh).to_json()

    @app.get("/api/ingest")
    def ingest_list() -> list[dict[str, Any]]:
        return [job.to_json() for job in ingest_jobs().recent()]

    @app.get("/api/ingest/{job_id}")
    def ingest_job(job_id: str) -> dict[str, Any]:
        job = ingest_jobs().get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job.to_json()

    return app


def _ingest_with_settings(url: str, refresh: bool = False) -> Any:
    """One shared link through the same pipeline as `main.py ingest --skip-existing` (or a
    plain re-ingest with ``refresh``), on its own connection (it runs on the queue's worker
    thread)."""
    from config import settings
    from db import backfill_status, find_recipe_id
    from pipeline.ingest import ingest_url
    from pipeline.urls import canonical_url, classify_missing_recipe

    conn = connect(settings.db_path)
    try:
        before = find_recipe_id(conn, canonical_url(url))
        kept = before is not None and conn.execute(
            "SELECT status FROM recipes WHERE id = ?", (before,)).fetchone()[0] == "needs_recipe"
        result = ingest_url(url, conn, settings, skip_existing=not refresh)
        backfill_status(conn, classify_missing_recipe)  # label posts without a list, as the CLI does
        if kept:
            # Saved for later in the app: "Check again" finding no recipe yet keeps it there.
            conn.execute("UPDATE recipes SET status = 'needs_recipe' WHERE id = ? AND status = 'not_recipe'",
                         (result.recipe_id,))
            conn.commit()
        row = conn.execute("SELECT status, title FROM recipes WHERE id = ?", (result.recipe_id,)).fetchone()
        if row:
            result.recipe_status = result.recipe_status or row[0]
            result.title = result.title or row[1]
        return result
    finally:
        conn.close()


def _default_app() -> FastAPI:
    from config import settings

    return create_app(settings.db_path, settings.data_dir / "thumbnails", settings.pantry_staples,
                      ingest=_ingest_with_settings)


app = _default_app()

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402
from db import connect, save_recipe, set_thumbnail  # noqa: E402


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "recipes.db"
    conn = connect(db_path)
    save_recipe(
        conn,
        source_url="https://www.instagram.com/p/ABC123/",
        title="Garlic Butter Shrimp",
        ingredients=[{"name": "shrimp", "amount": 1, "unit": "lb"}, {"name": "2 cloves garlic, minced"},
                     {"name": "butter", "amount": 3, "unit": "tbsp"}, {"name": "salt"}],
        steps=["Melt the butter.", "Add garlic and shrimp."],
        short_steps=[None, "Add garlic and shrimp"],
        uploader="chef",
    )
    save_recipe(conn, source_url="https://www.instagram.com/p/XYZ/", title="Link in bio", ingredients=[],
                status="needs_recipe")
    thumbs = tmp_path / "thumbnails"
    thumbs.mkdir()
    (thumbs / "1.jpg").write_bytes(b"\xff\xd8jpeg")
    set_thumbnail(conn, 1, "1.jpg")
    conn.close()
    return TestClient(create_app(db_path, thumbs, staples=("salt",)))


def test_list_defaults_to_ready(client):
    recipes = client.get("/api/recipes").json()
    assert [r["title"] for r in recipes] == ["Garlic Butter Shrimp"]
    assert recipes[0]["thumbnail_url"] == "/api/recipes/1/thumbnail"
    assert recipes[0]["platform"] == "instagram"
    assert recipes[0]["favorite"] is False
    assert [r["title"] for r in client.get("/api/recipes?status=todo").json()] == ["Link in bio"]
    assert len(client.get("/api/recipes?status=all").json()) == 2


def test_detail_has_step_ingredients_and_embed(client):
    recipe = client.get("/api/recipes/1").json()
    assert recipe["steps"] == [
        {"text": "Melt the butter.", "short_text": None, "ingredients": [2]},
        {"text": "Add garlic and shrimp.", "short_text": "Add garlic and shrimp", "ingredients": [0, 1]},
    ]
    assert recipe["video"]["embed_url"] == "https://www.instagram.com/p/ABC123/embed/"
    assert client.get("/api/recipes/99").status_code == 404


def test_marks_persist_and_survive_reingest(client, tmp_path):
    assert client.patch("/api/recipes/1", json={"favorite": True}).json() == {"favorite": True, "tried": False, "status": "ready"}
    assert client.patch("/api/recipes/1", json={"tried": True}).json() == {"favorite": True, "tried": True, "status": "ready"}
    conn = connect(tmp_path / "recipes.db")
    save_recipe(conn, source_url="https://www.instagram.com/p/ABC123/", title="Shrimp v2",
                ingredients=[{"name": "shrimp"}])
    conn.close()
    recipe = client.get("/api/recipes/1").json()
    assert (recipe["title"], recipe["favorite"], recipe["tried"]) == ("Shrimp v2", True, True)
    assert client.patch("/api/recipes/99", json={"tried": True}).status_code == 404


def test_thumbnail_served(client):
    response = client.get("/api/recipes/1/thumbnail")
    assert response.status_code == 200 and response.content == b"\xff\xd8jpeg"
    assert client.get("/api/recipes/2/thumbnail").status_code == 404


def test_db_connection_closes_on_another_thread(client):
    # Under uvicorn, FastAPI can run the db dependency's setup and teardown on different
    # threadpool threads; that used to raise sqlite3.ProgrammingError (HTTP 500).
    from concurrent.futures import ThreadPoolExecutor

    route = next(r for r in client.app.routes if getattr(r, "path", "") == "/api/recipes/{recipe_id}/thumbnail")
    db = next(d.call for d in route.dependant.dependencies if d.call.__name__ == "db")
    session = db()
    with ThreadPoolExecutor(1) as opener:
        opener.submit(next, session).result()
    with pytest.raises(StopIteration):
        next(session)


def test_pantry_ranks_and_skips_staples(client, tmp_path):
    conn = connect(tmp_path / "recipes.db")
    save_recipe(conn, source_url="https://x/eggs", title="Garlic Eggs",
                ingredients=[{"name": "eggs"}, {"name": "garlic"}, {"name": "salt"}])
    conn.close()
    matches = client.get("/api/pantry", params={"have": ["Garlic", "2 large eggs", "salt"]}).json()
    assert [(m["title"], m["matched"], m["missing"]) for m in matches] == [
        ("Garlic Eggs", 2, []),
        ("Garlic Butter Shrimp", 1, ["butter", "shrimp"]),
    ]
    assert matches[1]["thumbnail_url"] == "/api/recipes/1/thumbnail" and matches[0]["thumbnail_url"] is None
    assert matches[0]["selected"] == 2  # salt is a staple
    with_staples = client.get("/api/pantry", params={"have": ["salt"], "include_staples": True}).json()
    assert {m["title"] for m in with_staples} == {"Garlic Eggs", "Garlic Butter Shrimp"}
    assert client.get("/api/pantry", params={"have": ["garlic"], "limit": 1}).json()[0]["title"] == "Garlic Eggs"
    assert client.get("/api/pantry").json() == []


def test_ingredients_counts_ready_recipes_only(client):
    names = {i["name"]: i["recipe_count"] for i in client.get("/api/ingredients").json()}
    assert names == {"butter": 1, "garlic": 1, "salt": 1, "shrimp": 1}


def _ingest_client(tmp_path, ingest):
    db_path = tmp_path / "jobs.db"
    connect(db_path).close()
    return TestClient(create_app(db_path, tmp_path, ingest=ingest))


def test_ingest_job_runs_in_background(tmp_path):
    import time
    from types import SimpleNamespace

    seen = []

    def fake_ingest(url, refresh):
        seen.append((url, refresh))
        return SimpleNamespace(recipe_id=7, status="added", title="Garlic Noodles", recipe=None,
                               recipe_status="ready", status_note=None)

    client = _ingest_client(tmp_path, fake_ingest)
    job = client.post("/api/ingest", json={"url": "Look! https://www.instagram.com/reel/ABC/?igsh=x."})
    assert job.status_code == 202 and job.json()["status"] in ("queued", "running", "done")
    # Wait for the worker, then read the finished job back.
    for _ in range(100):
        done = client.get(f"/api/ingest/{job.json()['id']}").json()
        if done["status"] == "done":
            break
        time.sleep(0.02)
    assert seen == [("https://www.instagram.com/reel/ABC/?igsh=x", False)]  # link pulled out of the text
    assert (done["recipe_id"], done["title"], done["result"], done["recipe_status"]) == (7, "Garlic Noodles", "added", "ready")
    assert [j["id"] for j in client.get("/api/ingest").json()] == [done["id"]]
    assert client.get("/api/ingest/nope").status_code == 404


def test_ingest_dedupes_running_jobs_and_reports_failures(tmp_path):
    import threading
    import time

    release = threading.Event()

    def slow_failing_ingest(url, refresh):
        release.wait(2)
        raise RuntimeError("yt-dlp: private video")

    client = _ingest_client(tmp_path, slow_failing_ingest)
    first = client.post("/api/ingest", json={"url": "https://www.instagram.com/reel/XYZ/"}).json()
    again = client.post("/api/ingest", json={"url": "https://www.instagram.com/p/XYZ/?igsh=abc"}).json()
    assert again["id"] == first["id"]  # same post (canonical URL) while still queued/running
    release.set()
    for _ in range(100):
        job = client.get(f"/api/ingest/{first['id']}").json()
        if job["status"] == "failed":
            break
        time.sleep(0.02)
    assert job["status"] == "failed" and "private video" in job["message"]
    assert client.post("/api/ingest", json={"url": "no link here"}).status_code == 422


def test_ingest_off_without_pipeline(client):
    assert client.post("/api/ingest", json={"url": "https://youtu.be/abc"}).status_code == 503


def test_ingest_refresh_reaches_the_pipeline(tmp_path):
    import time
    from types import SimpleNamespace

    seen = []

    def fake_ingest(url, refresh):
        seen.append(refresh)
        return SimpleNamespace(recipe_id=3, status="updated", title="Later", recipe=None,
                               recipe_status="needs_recipe", status_note=None)

    client = _ingest_client(tmp_path, fake_ingest)
    job = client.post("/api/ingest", json={"url": "https://youtu.be/abc", "refresh": True}).json()
    for _ in range(100):
        if client.get(f"/api/ingest/{job['id']}").json()["status"] == "done":
            break
        time.sleep(0.02)
    assert seen == [True] and job["refresh"] is True


def test_patch_status_keeps_or_hides_posts_without_a_list(client):
    # Recipe 2 ("Link in bio") has no ingredients; recipe 1 has a list.
    saved = client.patch("/api/recipes/2", json={"status": "needs_recipe"})
    assert saved.status_code == 200 and saved.json()["status"] == "needs_recipe"
    assert [r["id"] for r in client.get("/api/recipes?status=todo").json()] == [2]
    assert client.patch("/api/recipes/2", json={"status": "not_recipe"}).json()["status"] == "not_recipe"
    assert client.get("/api/recipes?status=todo").json() == []
    assert client.patch("/api/recipes/1", json={"status": "needs_recipe"}).status_code == 409
    assert client.patch("/api/recipes/1", json={"status": "ready"}).status_code == 422
    assert client.patch("/api/recipes/99", json={"status": "not_recipe"}).status_code == 404
    assert client.patch("/api/recipes/1", json={"favorite": True}).json() == {"favorite": True, "tried": False,
                                                                              "status": "ready"}

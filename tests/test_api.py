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
    assert recipe["steps"] == [{"text": "Melt the butter.", "ingredients": [2]},
                               {"text": "Add garlic and shrimp.", "ingredients": [0, 1]}]
    assert recipe["video"]["embed_url"] == "https://www.instagram.com/p/ABC123/embed/"
    assert client.get("/api/recipes/99").status_code == 404


def test_marks_persist_and_survive_reingest(client, tmp_path):
    assert client.patch("/api/recipes/1", json={"favorite": True}).json() == {"favorite": True, "tried": False}
    assert client.patch("/api/recipes/1", json={"tried": True}).json() == {"favorite": True, "tried": True}
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

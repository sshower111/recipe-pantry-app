import requests

from db import connect, get_recipe, save_recipe
from pipeline import thumbnails


class FakeResponse:
    def __init__(self, content_type, content=b"img"):
        self.headers = {"Content-Type": content_type}
        self.content = content

    def raise_for_status(self):
        pass


def test_save_thumbnail_writes_file_and_replaces_old(tmp_path, monkeypatch):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://x/1", title="T", ingredients=[{"name": "egg"}])
    (tmp_path / f"{rid}.png").write_bytes(b"old")
    monkeypatch.setattr(thumbnails.requests, "get", lambda url, timeout: FakeResponse("image/jpeg; q=1"))
    assert thumbnails.save_thumbnail(conn, rid, "https://cdn/x.jpg", tmp_path)
    assert get_recipe(conn, rid)["thumbnail_file"] == f"{rid}.jpg"
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{rid}.jpg"]


def test_save_thumbnail_failures_are_not_raised(tmp_path, monkeypatch):
    conn = connect(":memory:")
    rid = save_recipe(conn, source_url="https://x/1", title="T", ingredients=[{"name": "egg"}])
    monkeypatch.setattr(thumbnails.requests, "get", lambda url, timeout: FakeResponse("text/html"))
    assert not thumbnails.save_thumbnail(conn, rid, "https://cdn/x", tmp_path)

    def boom(url, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(thumbnails.requests, "get", boom)
    assert not thumbnails.save_thumbnail(conn, rid, "https://cdn/x", tmp_path)
    assert not thumbnails.save_thumbnail(conn, rid, None, tmp_path)
    assert get_recipe(conn, rid)["thumbnail_file"] is None

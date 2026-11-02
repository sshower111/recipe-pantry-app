import json
import re

import pytest

from pipeline import webrecipe
from pipeline.webrecipe import RecipePageError, fetch_recipe_page, find_recipe


def page(*blocks):
    scripts = "".join(f'<script type="application/ld+json">{b}</script>' for b in blocks)
    return f"<html><head>{scripts}</head><body>hi</body></html>"


RECIPE = {
    "@type": "Recipe",
    "name": "BEST Homemade Brownies",
    "recipeYield": ["16", "16 brownies"],
    "recipeIngredient": [
        "7 oz (200g) bittersweet chocolate* (minimum 70% cocoa)",
        "<strong>½ cup</strong> (113g) salted butter**",
        "  3 large eggs  ",
        "",
    ],
}


def test_find_recipe_in_graph():
    # WordPress/Yoast shape: everything in one @graph, Recipe somewhere inside.
    doc = {"@context": "https://schema.org", "@graph": [{"@type": "Article"}, {"@type": "WebPage"}, RECIPE]}
    assert find_recipe(page(json.dumps(doc)))["name"] == "BEST Homemade Brownies"


def test_find_recipe_list_type_and_later_block():
    recipe = dict(RECIPE, **{"@type": ["Recipe", "NewsArticle"]})
    html = page("{not json", json.dumps({"@type": "WebSite"}), json.dumps([{"@type": "Person"}, recipe]))
    assert find_recipe(html) is not None


def test_find_recipe_html_escaped_json():
    escaped = json.dumps(RECIPE).replace('"', "&quot;")
    assert find_recipe(page(escaped))["recipeYield"] == ["16", "16 brownies"]


def test_find_recipe_none():
    assert find_recipe(page(json.dumps({"@type": "WebSite"}))) is None
    assert find_recipe("<html>no scripts</html>") is None


class FakeResponse:
    def __init__(self, text, status_code=200, url="https://blog.example.com/brownies/"):
        self.text, self.status_code, self.url = text, status_code, url


def fake_get(response):
    def get(url, headers, timeout):
        assert "Mozilla" in headers["User-Agent"]
        return response
    return get


def test_fetch_recipe_page(monkeypatch):
    monkeypatch.setattr(webrecipe.requests, "get", fake_get(FakeResponse(page(json.dumps(RECIPE)))))
    recipe = fetch_recipe_page("https://blog.example.com/brownies/")
    assert recipe.name == "BEST Homemade Brownies"
    assert recipe.yield_text == "16 brownies"
    assert recipe.ingredients == [
        "7 oz (200g) bittersweet chocolate* (minimum 70% cocoa)",
        "½ cup (113g) salted butter**",
        "3 large eggs",
    ]
    assert recipe.as_text().splitlines()[:3] == ["Recipe: BEST Homemade Brownies", "Yield: 16 brownies", "Ingredients:"]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse("", 403), re.escape("blog.example.com blocks automated requests (HTTP 403)")),
        (FakeResponse("", 404), "returned HTTP 404"),
        (FakeResponse(page('{"@type": "WebSite"}'), url="https://kiley.example.com/"), "is the site's home page"),
        (FakeResponse(page('{"@type": "WebSite"}')), "no recipe data found"),
        (FakeResponse(page(json.dumps(dict(RECIPE, recipeIngredient=[])))), "has no ingredient list"),
    ],
)
def test_fetch_recipe_page_errors(monkeypatch, response, message):
    monkeypatch.setattr(webrecipe.requests, "get", fake_get(response))
    with pytest.raises(RecipePageError, match=message):
        fetch_recipe_page("https://blog.example.com/")


def test_fetch_recipe_page_network_error(monkeypatch):
    def boom(url, headers, timeout):
        raise webrecipe.requests.ConnectionError("dns failure")

    monkeypatch.setattr(webrecipe.requests, "get", boom)
    with pytest.raises(RecipePageError, match="could not fetch"):
        fetch_recipe_page("https://blog.example.com/x")

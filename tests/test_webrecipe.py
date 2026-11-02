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


# --- files the user saved themselves ------------------------------------------------------

from pipeline.webrecipe import read_recipe_file, recipe_from_text  # noqa: E402


def test_read_saved_html_page_uses_canonical_link(tmp_path):
    saved = tmp_path / "Gluten Free Lemon Curd Cookies - The Loopy Whisk.html"
    head = '<link rel="canonical" href="https://theloopywhisk.com/2023/04/07/gluten-free-lemon-curd-cookies/">'
    saved.write_text(page(json.dumps(RECIPE)).replace("<head>", "<head>" + head), encoding="utf-8")
    recipe = read_recipe_file(saved)
    assert recipe.url == "https://theloopywhisk.com/2023/04/07/gluten-free-lemon-curd-cookies/"
    assert recipe.ingredients[0].startswith("7 oz (200g) bittersweet chocolate")
    # An explicit --url wins.
    assert read_recipe_file(saved, url="https://example.com/x").url == "https://example.com/x"


def test_read_saved_html_page_saved_from_marker(tmp_path):
    saved = tmp_path / "page.htm"
    saved.write_text("<!-- saved from url=(0040)https://blog.example.com/brownies/ -->\n" + page(json.dumps(RECIPE)),
                     encoding="utf-8")
    assert read_recipe_file(saved).url == "https://blog.example.com/brownies/"


def test_read_saved_html_without_recipe_data_suggests_text(tmp_path):
    saved = tmp_path / "page.html"
    saved.write_text("<html><body>Lemon cookies! 200g flour</body></html>", encoding="utf-8")
    with pytest.raises(RecipePageError, match="no recipe data found in page.html; copy the ingredient list"):
        read_recipe_file(saved)


def test_read_pasted_ingredient_list(tmp_path):
    txt = tmp_path / "cookies.txt"
    txt.write_text(
        "Ingredients:\n"
        "▢ 120 g unsalted butter, softened\n"
        "- 150 g caster sugar\n"
        "\n"
        "For the filling:\n"
        "• 1 batch lemon curd\n"
        "2. 1 large egg\n"
        "Makes: 12 cookies\n",
        encoding="utf-8",
    )
    recipe = read_recipe_file(txt, url="https://theloopywhisk.com/x/", name="Lemon Curd Cookies")
    assert recipe.ingredients == [
        "120 g unsalted butter, softened", "150 g caster sugar", "1 batch lemon curd", "1 large egg",
    ]
    assert (recipe.yield_text, recipe.url, recipe.name) == ("12 cookies", "https://theloopywhisk.com/x/",
                                                            "Lemon Curd Cookies")


@pytest.mark.parametrize(
    ("line", "expected"),
    [("Serves 8", "serves 8"), ("Servings: 4-6", "serves 4-6"), ("Makes: 12 cookies", "12 cookies"),
     ("Yield: 1 loaf", "1 loaf")],
)
def test_pasted_yield_lines(line, expected):
    assert recipe_from_text(f"2 eggs\n{line}", url=None).yield_text == expected


def test_read_pasted_utf16_notepad_file(tmp_path):
    txt = tmp_path / "list.txt"
    txt.write_bytes("200 g crème fraîche\n2 eggs\n".encode("utf-16"))
    assert read_recipe_file(txt).ingredients == ["200 g crème fraîche", "2 eggs"]


def test_read_recipe_file_errors(tmp_path):
    with pytest.raises(RecipePageError, match="cannot read"):
        read_recipe_file(tmp_path / "missing.txt")
    with pytest.raises(RecipePageError, match="no ingredient lines"):
        recipe_from_text("Ingredients:\n\n", url=None)

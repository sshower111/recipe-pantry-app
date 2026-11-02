"""Read a recipe from a blog page via its schema.org Recipe data (JSON-LD).

Most recipe blogs (WP Recipe Maker, Tasty, Mediavine Create, ...) embed the recipe as
``<script type="application/ld+json">`` for search engines, so the ingredient list can be
read exactly without scraping page layout.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

# Many recipe sites reject the default python-requests user agent.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
_JSON_LD = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")
MAX_BYTES = 5_000_000


class RecipePageError(RuntimeError):
    pass


@dataclass
class WebRecipe:
    url: str
    name: str
    ingredients: list[str]
    yield_text: str | None

    def as_text(self) -> str:
        """The page's recipe as prompt text."""
        lines = [f"Recipe: {self.name}"]
        if self.yield_text:
            lines.append(f"Yield: {self.yield_text}")
        lines += ["Ingredients:", *(f"- {line}" for line in self.ingredients)]
        return "\n".join(lines)


def fetch_recipe_page(url: str, *, timeout: float = 20) -> WebRecipe:
    """Download ``url`` and return its Recipe data, or raise RecipePageError saying why not."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise RecipePageError(f"could not fetch {url}: {exc}") from exc
    if resp.status_code in (401, 403, 429):
        raise RecipePageError(f"{urlsplit(url).hostname} blocks automated requests (HTTP {resp.status_code})")
    if resp.status_code >= 400:
        raise RecipePageError(f"{url} returned HTTP {resp.status_code}")
    recipe = find_recipe(resp.text[:MAX_BYTES])
    if recipe is None:
        if urlsplit(resp.url).path.strip("/") == "":
            raise RecipePageError(f"{url} is the site's home page, not a recipe; pass the recipe's own URL")
        raise RecipePageError(f"no recipe data found on {url}")
    ingredients = [_clean(line) for line in _as_list(recipe.get("recipeIngredient"))]
    ingredients = [line for line in ingredients if line]
    if not ingredients:
        raise RecipePageError(f"the recipe on {url} has no ingredient list")
    return WebRecipe(
        url=resp.url,
        name=_clean(recipe.get("name") or ""),
        ingredients=ingredients,
        yield_text=_yield_text(recipe.get("recipeYield")),
    )


def find_recipe(page: str) -> dict[str, Any] | None:
    """The first schema.org Recipe object in the page's JSON-LD blocks."""
    for block in _JSON_LD.findall(page):
        data = _load_json(block)
        if data is None:
            continue
        for item in _walk(data):
            types = item.get("@type")
            if types == "Recipe" or (isinstance(types, list) and "Recipe" in types):
                return item
    return None


def _load_json(block: str) -> Any:
    for text in (block, html.unescape(block)):
        try:
            return json.loads(text.strip(), strict=False)
        except json.JSONDecodeError:
            continue
    return None


def _walk(data: Any):
    """Yield every dict in a JSON-LD document (top level, lists, and @graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                yield from _walk(data[key])


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _yield_text(value: Any) -> str | None:
    """recipeYield is a string, a number, or a list like ["16", "16 brownies"]; prefer the
    most descriptive entry."""
    options = [str(v).strip() for v in (value if isinstance(value, list) else [value]) if v not in (None, "")]
    return max(options, key=len) if options else None


def _clean(text: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", str(text))).split())

"""Read a recipe from a blog page via its schema.org Recipe data (JSON-LD).

Most recipe blogs (WP Recipe Maker, Tasty, Mediavine Create, ...) embed the recipe as
``<script type="application/ld+json">`` for search engines, so the ingredient list can be
read exactly without scraping page layout.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
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
_CANONICAL = re.compile(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)", re.IGNORECASE)
_OG_URL = re.compile(r"<meta[^>]+property=[\"']og:url[\"'][^>]+content=[\"']([^\"']+)", re.IGNORECASE)
_SAVED_FROM = re.compile(r"<!--\s*saved from url=\(\d+\)(\S+?)\s*-->", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•▢☐□◦·]|\d+[.)])\s+")
_HEADING = re.compile(r"(?i)(?:for the )?[\w ]{0,30}ingredients?:?|[\w ]{1,30}:")
_METHOD_HEADING = re.compile(r"(?i)(?:instructions|method|directions|steps|preparation)\s*:?")
_YIELD = re.compile(r"(?i)^(yield|yields|makes|serves|servings)\s*:?\s*(.+)$")
MAX_BYTES = 5_000_000


class RecipePageError(RuntimeError):
    pass


@dataclass
class WebRecipe:
    url: str | None  # None for pasted text with no known page
    name: str
    ingredients: list[str]
    yield_text: str | None
    instructions: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        """The page's recipe as prompt text."""
        lines = [f"Recipe: {self.name}"]
        if self.yield_text:
            lines.append(f"Yield: {self.yield_text}")
        lines += ["Ingredients:", *(f"- {line}" for line in self.ingredients)]
        if self.instructions:
            lines += ["Instructions:", *(f"{n}. {step}" for n, step in enumerate(self.instructions, 1))]
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
    if find_recipe(resp.text[:MAX_BYTES]) is None and urlsplit(resp.url).path.strip("/") == "":
        raise RecipePageError(f"{url} is the site's home page, not a recipe; pass the recipe's own URL")
    return recipe_from_html(resp.text[:MAX_BYTES], url=resp.url, where=url)


def recipe_from_html(page: str, *, url: str | None, where: str) -> WebRecipe:
    """The Recipe data in an HTML page; ``where`` names the page in error messages."""
    recipe = find_recipe(page)
    if recipe is None:
        raise RecipePageError(f"no recipe data found in {where}")
    ingredients = [_clean(line) for line in _as_list(recipe.get("recipeIngredient"))]
    ingredients = [line for line in ingredients if line]
    if not ingredients:
        raise RecipePageError(f"the recipe in {where} has no ingredient list")
    return WebRecipe(
        url=url,
        name=_clean(recipe.get("name") or ""),
        ingredients=ingredients,
        yield_text=_yield_text(recipe.get("recipeYield")),
        instructions=_instructions(recipe.get("recipeInstructions")),
    )


def _instructions(value: Any) -> list[str]:
    """recipeInstructions: a string, a list of strings, HowToStep objects ({"text": ...}),
    or HowToSection objects whose itemListElement holds the steps."""
    if isinstance(value, str):
        return [line for line in (_clean(part) for part in re.split(r"\n+|<br\s*/?>|</p>", value)) if line]
    steps: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            steps += _instructions(item)
        elif isinstance(item, dict):
            if "itemListElement" in item:
                steps += _instructions(item["itemListElement"])
            elif text := _clean(item.get("text") or item.get("name") or ""):
                steps.append(text)
    return steps


def read_recipe_file(path: Path, *, url: str | None = None, name: str = "") -> WebRecipe:
    """A recipe the user saved themselves, for sites that block automated downloads:

    - a web page saved from the browser (Ctrl+S, .html): read like a fetched page; its address
      comes from ``url``, else the page's own canonical link;
    - a text file with the ingredient list pasted in: one ingredient per line (bullets and
      "Ingredients:" headings are fine; a "Yield: ..." / "Serves ..." line is kept as the yield).
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RecipePageError(f"cannot read {path}: {exc}") from exc
    text = _decode(raw)
    if path.suffix.lower() in (".html", ".htm", ".mhtml") or text.lstrip()[:1] == "<":
        page_url = url or _canonical_url(text)
        try:
            return recipe_from_html(text, url=page_url, where=path.name)
        except RecipePageError as exc:
            raise RecipePageError(
                f"{exc}; copy the ingredient list into a .txt file and pass that instead"
            ) from exc
    return recipe_from_text(text, url=url, name=name)


def recipe_from_text(text: str, *, url: str | None, name: str = "") -> WebRecipe:
    """Lines are ingredients until an "Instructions:" / "Method:" / "Directions:" / "Steps:"
    heading; lines after it are steps."""
    ingredients: list[str] = []
    instructions: list[str] = []
    yield_text = None
    in_method = False
    for line in text.splitlines():
        line = _BULLET.sub("", line).strip()
        if _METHOD_HEADING.fullmatch(line):
            in_method = True
            continue
        if not line or (not in_method and _HEADING.fullmatch(line)):
            continue
        if match := _YIELD.match(line):
            # "Serves 8" keeps its word (a bare "8" is ambiguous); "Makes: 12 cookies" doesn't need it.
            word, value = match.group(1).lower(), match.group(2).strip()
            yield_text = yield_text or (f"serves {value}" if word.startswith("serv") else value)
            continue
        (instructions if in_method else ingredients).append(line)
    if not ingredients:
        raise RecipePageError("the text file has no ingredient lines")
    return WebRecipe(url=url, name=name, ingredients=ingredients, yield_text=yield_text,
                     instructions=instructions)


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):  # Notepad's "Unicode" (UTF-16)
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def _canonical_url(page: str) -> str | None:
    """The page's own address: <link rel="canonical">, og:url, or the
    "<!-- saved from url=(NNNN)https://... -->" marker browsers add when saving."""
    for pattern in (_CANONICAL, _OG_URL, _SAVED_FROM):
        if match := pattern.search(page):
            return html.unescape(match.group(1))
    return None


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

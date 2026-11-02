"""Command-line entry point.

    python main.py ingest <url> [<url> ...] [--skip-existing]
    python main.py batch --file urls.txt [--refresh]
    python main.py search --ingredients "garlic, butter, pasta" --max-missing 3
    python main.py pantry chicken garlic "soy sauce" --max-missing 3
    python main.py list
    python main.py show <recipe_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from config import settings
from db import PantryMatch, connect, find_recipes_by_pantry, get_recipe, list_recipes


def cmd_init_db(args: argparse.Namespace) -> int:
    connect(settings.db_path).close()
    print(f"Database ready at {settings.db_path}")
    return 0


def ingest_many(urls: list[str], *, skip_existing: bool) -> int:
    """Ingest URLs one at a time, keep going past failures, and print a summary."""
    from pipeline.ingest import ingest_url
    from pipeline.urls import canonical_url

    conn = connect(settings.db_path)
    counts = {"added": 0, "updated": 0, "skipped": 0, "failed": 0}
    seen: set[str] = set()
    for url in urls:
        key = canonical_url(url)
        if key in seen:
            print(f"SKIP   {url}: duplicate of an earlier URL in this run")
            counts["skipped"] += 1
            continue
        seen.add(key)
        try:
            result = ingest_url(url, conn, skip_existing=skip_existing)
        except Exception as exc:  # keep going through the rest of the URLs
            logging.getLogger(__name__).debug("ingest failed", exc_info=True)
            print(f"FAILED {url}: {exc}", file=sys.stderr)
            counts["failed"] += 1
            continue
        counts[result.status] += 1
        if result.recipe is None:
            print(f"SKIP   [{result.recipe_id}] {result.source_url}: already stored")
            continue
        recipe = result.recipe
        makes = f", makes {recipe.yield_label}" if recipe.yield_label else ""
        print(
            f"{result.status.upper():<6} [{result.recipe_id}] {recipe.title} "
            f"({len(recipe.ingredients)} ingredients{makes}; "
            f"{describe_sources(result.ingredient_sources or [], result.transcript_source)})"
        )
    if len(urls) > 1:
        print(", ".join(f"{n} {status}" for status, n in counts.items()))
    return 1 if counts["failed"] else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    return ingest_many(args.urls, skip_existing=args.skip_existing)


def cmd_batch(args: argparse.Namespace) -> int:
    from pipeline.urls import read_url_file

    try:
        urls, ignored = read_url_file(Path(args.file).read_text(encoding="utf-8-sig").splitlines())
    except OSError as exc:
        print(f"Cannot read {args.file}: {exc}", file=sys.stderr)
        return 1
    if not urls:
        print(f"No URLs found in {args.file}", file=sys.stderr)
        return 1
    note = f" (ignored {ignored} line{'s' * (ignored != 1)} with no URL)" if ignored else ""
    print(f"{len(urls)} URLs from {args.file}{note}")
    return ingest_many(urls, skip_existing=not args.refresh)


def describe_sources(ingredient_sources: list[str], transcript_source: str | None) -> str:
    sources = ", ".join(ingredient_sources) or "unknown"
    return f"ingredients from {sources}; transcript: {transcript_source or 'none'}"


def parse_ingredient_list(values: list[str]) -> list[str]:
    """Split comma-separated ingredient arguments: ["garlic, butter", "soy sauce"] -> 3 items."""
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def run_pantry_query(ingredients: list[str], args: argparse.Namespace) -> int:
    if not ingredients:
        print("Give at least one ingredient.", file=sys.stderr)
        return 2
    matches = find_recipes_by_pantry(
        connect(settings.db_path),
        ingredients,
        ignore_ingredients=() if args.no_staples else settings.pantry_staples,
        max_missing=args.max_missing,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([asdict(m) for m in matches], indent=2))
        return 0
    print(format_matches(matches))
    return 0


def format_matches(matches: list[PantryMatch]) -> str:
    if not matches:
        return "No matching recipes."
    blocks = []
    for rank, m in enumerate(matches, 1):
        status = "can make now" if not m.missing else f"missing {m.missing_count}"
        blocks.append(
            f"{rank}. [{m.recipe_id}] {m.title}  ({m.matched}/{m.total} ingredients, {status})\n"
            f"     have:    {', '.join(m.have) or '-'}\n"
            f"     missing: {', '.join(m.missing) or '-'}\n"
            f"     {m.source_url}"
        )
    return "\n\n".join(blocks)


def cmd_search(args: argparse.Namespace) -> int:
    """Shared by `search -i "a, b"` and `pantry a b`; both accept commas."""
    return run_pantry_query(parse_ingredient_list(args.ingredients), args)


def cmd_list(args: argparse.Namespace) -> int:
    for r in list_recipes(connect(settings.db_path)):
        makes = f", makes {r['yield_label']}" if r["yield_label"] else ""
        print(f"[{r['id']}] {r['title']}  ({r['ingredient_count']} ingredients{makes})  {r['source_url']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    recipe = get_recipe(connect(settings.db_path), args.recipe_id)
    if recipe is None:
        print(f"No recipe with id {args.recipe_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(recipe, indent=2, default=str))
        return 0
    print(recipe["title"])
    print(recipe["source_url"])
    print(describe_sources(recipe["ingredient_sources"], recipe["transcript_source"]).capitalize())
    print(f"Makes: {recipe['yield_label'] or 'not stated'}\n")
    for ing in recipe["ingredients"]:
        amount = f"{ing['amount']:g} " if ing["amount"] is not None else ""
        unit = f"{ing['unit']} " if ing["unit"] else ""
        print(f"  - {amount}{unit}{ing['raw_name']}")
    return 0


def add_query_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-missing", type=int, default=None, help="hide recipes missing more than this")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-staples", action="store_true", help="count salt/water/etc. as ingredients")
    p.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local recipe extraction and pantry matching")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the SQLite database").set_defaults(func=cmd_init_db)

    p = sub.add_parser("ingest", help="download, transcribe, parse and store recipes")
    p.add_argument("urls", nargs="+")
    p.add_argument("--skip-existing", action="store_true",
                   help="skip URLs already in the database instead of re-parsing them")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("batch", help="ingest every URL listed in a file")
    p.add_argument("--file", "-f", required=True,
                   help="text file with one URL per line; blank lines and # comments are ignored")
    p.add_argument("--refresh", action="store_true",
                   help="re-parse URLs already in the database (default: skip them)")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("search", help="find recipes from a comma-separated ingredient list")
    p.add_argument("--ingredients", "-i", required=True, action="append",
                   help='e.g. "garlic, butter, pasta" (may be repeated)')
    add_query_options(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("pantry", help="find recipes you can make")
    p.add_argument("ingredients", nargs="+", help="ingredients you have")
    add_query_options(p)
    p.set_defaults(func=cmd_search)

    sub.add_parser("list", help="list stored recipes").set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one recipe")
    p.add_argument("recipe_id", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Command-line entry point.

    python main.py ingest <url> [<url> ...] [--skip-existing]
    python main.py batch --file urls.txt [--refresh]
    python main.py search --ingredients "garlic, butter, pasta"
    python main.py pantry chicken garlic "soy sauce"
    python main.py list [--todo | --all]
    python main.py show <recipe_id>
    python main.py import-page <recipe_id> [--url <page>] [--file saved.html|ingredients.txt]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from config import settings
from db import (
    PantryMatch,
    backfill_status,
    connect,
    count_by_status,
    find_recipes_by_pantry,
    get_recipe,
    list_recipes,
    renormalize_ingredients,
)

STATUS_LABELS = {"ready": "ready", "needs_recipe": "needs a recipe", "not_recipe": "not a recipe"}


def open_db():
    """Connect to the database, filling in ``status`` for rows saved before it existed."""
    from pipeline.urls import classify_missing_recipe

    conn = connect(settings.db_path)
    backfill_status(conn, classify_missing_recipe)
    return conn


def cmd_init_db(args: argparse.Namespace) -> int:
    connect(settings.db_path).close()
    print(f"Database ready at {settings.db_path}")
    return 0


def ingest_many(urls: list[str], *, skip_existing: bool) -> int:
    """Ingest URLs one at a time, keep going past failures, and print a summary."""
    from pipeline.ingest import ingest_url
    from pipeline.urls import canonical_url

    conn = open_db()
    counts = {"added": 0, "updated": 0, "skipped": 0, "failed": 0}
    without_list = {"needs_recipe": 0, "not_recipe": 0}
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
        if not recipe.ingredients:
            without_list[result.recipe_status or "needs_recipe"] += 1
            print(f"{result.status.upper():<6} [{result.recipe_id}] {result.title or recipe.title} "
                  f"({describe_missing_list(result.description, result.status_note)})")
            continue
        print(f"{result.status.upper():<6} {describe_result(result)}")
    if len(urls) > 1:
        summary = ", ".join(f"{n} {status}" for status, n in counts.items())
        extra = ", ".join(f"{n} {STATUS_LABELS[k]}" for k, n in without_list.items() if n)
        print(summary + (f" (of the saved: {extra}; see `list --todo`)" if extra else ""))
    return 1 if counts["failed"] else 0


def sentence(text: str) -> str:
    """Uppercase the first letter only (str.capitalize() would turn "DM" into "dm")."""
    return text[:1].upper() + text[1:]


def describe_missing_list(description: str | None, note: str | None = None) -> str:
    """Why a saved post has no ingredients, for `ingest`, `show` and `list --todo` output.
    ``note`` is a recorded failure, e.g. the recipe site blocking downloads."""
    from pipeline.urls import points_elsewhere, recipe_link

    description = description or ""
    link = recipe_link(description)
    if link:
        text = f"no ingredient list in the post; recipe at {link}"
    elif points_elsewhere(description):
        text = "no ingredient list in the post; the caption says the recipe is on a blog, in the bio, or by DM"
    else:
        text = "not a recipe: no ingredient list and nothing pointing to one"
    return f"{text} [{note}]" if note else text


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
        open_db(),
        ingredients,
        ignore_ingredients=() if args.no_staples else settings.pantry_staples,
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
        needs = "nothing else" if not m.missing else f"+{m.missing_count} more"
        blocks.append(
            f"{rank}. [{m.recipe_id}] {m.title}  (uses {m.matched} of {m.selected} selected; {needs})\n"
            f"     uses:       {', '.join(m.have) or '-'}\n"
            f"     also needs: {', '.join(m.missing) or '-'}\n"
            f"     {m.source_url}"
        )
    return "\n\n".join(blocks)


def cmd_search(args: argparse.Namespace) -> int:
    """Shared by `search -i "a, b"` and `pantry a b`; both accept commas."""
    return run_pantry_query(parse_ingredient_list(args.ingredients), args)


def cmd_list(args: argparse.Namespace) -> int:
    """Ready recipes by default; `--todo` lists posts whose recipe still has to be found,
    `--all` everything with its status."""
    conn = open_db()
    if args.todo:
        rows = list_recipes(conn, ["needs_recipe"])
        if not rows:
            print("Nothing to do: no saved posts are waiting for a recipe.")
            return 0
        for r in rows:
            by = f" by {r['uploader']}" if r["uploader"] else ""
            print(f"[{r['id']}] {r['title']}{by}")
            print(f"      {describe_missing_list(r['description'], r['status_note'])}")
            print(f"      {r['source_url']}")
        print("\nAdd a recipe page with: python main.py import-page <id> --url <recipe page>")
        print("If the site blocks downloads, save the page in your browser (Ctrl+S) and use "
              "--file <saved page.html>, or paste the ingredients into a .txt file.")
        return 0

    for r in list_recipes(conn, None if args.all else ["ready"]):
        if r["ingredient_count"]:
            makes = f", makes {r['yield_label']}" if r["yield_label"] else ""
            detail = f"{r['ingredient_count']} ingredients{makes}"
        else:
            detail = STATUS_LABELS.get(r["status"], "no ingredient list")
        print(f"[{r['id']}] {r['title']}  ({detail})  {r['source_url']}")
    if not args.all:
        counts = count_by_status(conn)
        hidden = [f"{counts[k]} {STATUS_LABELS[k]}" for k in ("needs_recipe", "not_recipe") if counts.get(k)]
        if hidden:
            print(f"\n(hidden: {', '.join(hidden)}; see `list --todo` or `list --all`)")
    return 0


def cmd_import_page(args: argparse.Namespace) -> int:
    from pipeline.ingest import import_recipe_page
    from pipeline.webrecipe import RecipePageError

    try:
        result = import_recipe_page(open_db(), args.recipe_id, url=args.url,
                                    file=Path(args.file) if args.file else None)
    except (ValueError, RecipePageError) as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    print(f"UPDATED {describe_result(result)}")
    return 0


def describe_result(result) -> str:
    """'[id] Title (12 ingredients, 6 steps, makes ...; ingredients from ...)'."""
    recipe = result.recipe
    makes = f", makes {recipe.yield_label}" if recipe.yield_label else ""
    steps = f", {len(recipe.steps)} steps" if recipe.steps else ", no steps"
    return (
        f"[{result.recipe_id}] {result.title or recipe.title} "
        f"({len(recipe.ingredients)} ingredients{steps}{makes}; "
        f"{describe_sources(result.ingredient_sources or [], result.transcript_source)})"
    )


def cmd_reparse(args: argparse.Namespace) -> int:
    """Re-run the model on saved recipes (no downloads), e.g. to add steps to recipes saved
    before steps existed. Keeps going past failures."""
    from pipeline.ingest import reparse_recipe
    from pipeline.parser import OllamaError

    conn = open_db()
    ids = list(args.recipe_ids)
    if args.missing_steps:
        ids += [r["id"] for r in list_recipes(conn, ["ready"]) if not r["step_count"]]
    ids = list(dict.fromkeys(ids))
    if not ids:
        print("Nothing to reparse.")
        return 0
    print(f"Reparsing {len(ids)} recipe{'s' * (len(ids) != 1)} (about a minute each)")
    failures = 0
    for n, recipe_id in enumerate(ids, 1):
        try:
            result = reparse_recipe(conn, recipe_id)
        except (ValueError, OllamaError) as exc:
            print(f"FAILED [{recipe_id}] {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"{n}/{len(ids)} UPDATED {describe_result(result)}")
    if len(ids) > 1:
        print(f"{len(ids) - failures} reparsed, {failures} failed")
    return 1 if failures else 0


def cmd_renormalize(args: argparse.Namespace) -> int:
    changes = renormalize_ingredients(open_db(), dry_run=args.dry_run)
    if not changes:
        print("All ingredient names are already up to date.")
        return 0
    for raw_name, old, new in changes:
        print(f"  {raw_name!r}: {old} -> {new}")
    verb = "Would update" if args.dry_run else "Updated"
    print(f"{verb} {len(changes)} ingredient name{'s' * (len(changes) != 1)}.")
    return 0


def cmd_thumbnails(args: argparse.Namespace) -> int:
    """Save thumbnails for recipes stored without one (or all, with --refresh)."""
    from pipeline.downloader import fetch_thumbnail_url
    from pipeline.thumbnails import save_thumbnail

    conn = open_db()
    out_dir = settings.data_dir / "thumbnails"
    rows = [
        (r["id"], r["source_url"])
        for r in list_recipes(conn, ["ready", "needs_recipe"])
        if args.refresh or not (r["thumbnail_file"] and (out_dir / r["thumbnail_file"]).exists())
    ]
    if not rows:
        print("Every recipe already has a thumbnail.")
        return 0
    failures = 0
    for n, (recipe_id, url) in enumerate(rows, 1):
        try:
            image_url = fetch_thumbnail_url(url)
        except Exception as exc:  # yt-dlp raises many types; report and move on
            image_url = None
            print(f"{n}/{len(rows)} FAILED [{recipe_id}] {exc}", file=sys.stderr)
        if image_url and save_thumbnail(conn, recipe_id, image_url, out_dir):
            print(f"{n}/{len(rows)} saved [{recipe_id}]")
        else:
            failures += 1
    print(f"{len(rows) - failures} saved, {failures} failed")
    return 1 if failures else 0


def cmd_show(args: argparse.Namespace) -> int:
    recipe = get_recipe(open_db(), args.recipe_id)
    if recipe is None:
        print(f"No recipe with id {args.recipe_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(recipe, indent=2, default=str))
        return 0
    from pipeline.urls import recipe_link

    print(recipe["title"])
    print(recipe["source_url"])
    link = recipe["recipe_page_url"] or recipe_link(recipe["description"] or "")
    if not recipe["ingredients"]:
        print(f"Status: {STATUS_LABELS.get(recipe['status'], recipe['status'])}")
        print(sentence(describe_missing_list(recipe["description"], recipe["status_note"])))
        return 0
    if link:
        print(f"Full recipe: {link}")
    print(sentence(describe_sources(recipe["ingredient_sources"], recipe["transcript_source"])))
    print(f"Makes: {recipe['yield_label'] or 'not stated'}\n")
    for ing in recipe["ingredients"]:
        amount = f"{ing['amount']:g} " if ing["amount"] is not None else ""
        unit = f"{ing['unit']} " if ing["unit"] else ""
        print(f"  - {amount}{unit}{ing['raw_name']}")
    if recipe["steps"]:
        print("\nSteps:")
        width = len(str(len(recipe["steps"])))
        for n, step in enumerate(recipe["steps"], 1):
            print(f"  {n:>{width}}. {step}")
    else:
        print("\nSteps: not described in the post (try `reparse` if it was saved before steps existed)")
    return 0


def add_query_options(p: argparse.ArgumentParser) -> None:
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

    p = sub.add_parser("list", help="list recipes ready to cook (see --todo, --all)")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--todo", action="store_true",
                       help="posts whose recipe is elsewhere (blog, bio link, DM) and still needs a link")
    which.add_argument("--all", action="store_true", help="everything saved, including non-recipe posts")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("import-page",
                       help="read a stored recipe's ingredients from its recipe web page")
    p.add_argument("recipe_id", type=int)
    p.add_argument("--url", help="the recipe page (default: the page imported before, else the caption's link)")
    p.add_argument("--file", help="a recipe page you saved from your browser (.html), or a .txt file "
                                  "with the ingredient list pasted in; for sites that block downloads")
    p.set_defaults(func=cmd_import_page)

    p = sub.add_parser("reparse", help="run the model again on saved recipes, from their saved text")
    p.add_argument("recipe_ids", type=int, nargs="*", help="recipes to reparse")
    p.add_argument("--missing-steps", action="store_true",
                   help="every ready recipe that has no steps yet (e.g. saved before steps existed)")
    p.set_defaults(func=cmd_reparse)

    p = sub.add_parser("renormalize",
                       help="recompute stored ingredient names after normalizer/alias changes")
    p.add_argument("--dry-run", action="store_true", help="show the changes without saving them")
    p.set_defaults(func=cmd_renormalize)

    p = sub.add_parser("thumbnails", help="save video thumbnails for the app (recipes without one)")
    p.add_argument("--refresh", action="store_true", help="download every thumbnail again")
    p.set_defaults(func=cmd_thumbnails)

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

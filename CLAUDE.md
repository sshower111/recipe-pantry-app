# Recipe Pantry App

A local pipeline that ingests cooking shorts/reels, extracts text/audio ingredients locally,
normalizes them into structured JSON, stores them in SQLite, and lets the user query recipes
based on available pantry items. Everything runs locally: no cloud APIs.

## Technology Stack

- **Ingestion:** yt-dlp (video metadata, captions, audio)
- **Transcription:** faster-whisper (local audio-to-text)
- **OCR (optional, `requirements-ocr.txt`):** EasyOCR on ffmpeg-sampled video frames
- **LLM parsing:** Ollama running `qwen2.5:7b` via the local API (`http://localhost:11434`)
- **Database:** SQLite (`recipes`, `ingredients`, `recipe_ingredients`, `recipe_steps`)
- **Supporting:** requests (Ollama HTTP), pydantic v2 (output validation), python-dotenv, pytest

## Phase Breakdown

1. **Scaffolding** (done): project layout, venv setup instructions (README), `requirements.txt`,
   `requirements-dev.txt`, and `config.py`.
2. **Ingestion & Extraction Pipeline (`pipeline/`)** (done):
   - `downloader.py`: download audio/captions with yt-dlp.
   - `transcriber.py`: run faster-whisper on audio files.
   - `parser.py`: build prompt payloads and call Ollama for structured JSON:
     `{"title": str, "sources": [...], "yield_label": str|null,
       "ingredients": [{"name": str, "amount": float|null, "unit": str|null}], "steps": [str]}`.
     `ParsedRecipe.output_schema()` marks every field required for Ollama even though `steps`
     defaults to `[]` in Python.
   - `ingest.py`: orchestrates URL → media → transcript → recipe → DB.
3. **Database & Query Engine (`db/`)** (done):
   - `schema.py`: SQLite schema (`recipes`, `ingredients`, `recipe_ingredients`) and `connect()`.
   - `repository.py`: insertion with normalized ingredient mapping (`save_recipe`), reads.
   - `pantry.py`: `find_recipes_by_pantry(conn, available_ingredients: list[str], ...)` returns
     recipes using at least one selected ingredient, ranked by how many selected ingredients they
     use (most first), then fewest other ingredients (user's choice: "uses any, best first"; the
     CLI's `--max-missing` was dropped, the function keeps `max_missing` as an optional filter).
4. **Native iOS app** (planned, built on a Mac): SwiftUI app in `ios/` (iOS 17+) reading the
   FastAPI server over Wi-Fi, with a cooking-step Live Activity. Runbook: `docs/ios/README.md`;
   JSON contract: `docs/ios/api.md` (regenerate its samples if API responses change).

## Layout

```
config.py        Settings dataclass from RECIPE_* env vars / .env (see .env.example)
main.py          argparse CLI: init-db | ingest | batch | search | pantry | list | show | import-page |
                 renormalize | thumbnails
api/app.py       FastAPI JSON server for the web and iOS apps (create_app(db_path, thumbnails_dir, staples))
docs/ios/        iOS app runbook and API contract
web/             Next.js (App Router) + Tailwind v4 + Framer Motion frontend; proxies /api to :8000
pipeline/        downloader, transcriber, parser, ingest, urls, ocr, webrecipe, thumbnails
db/              schema, normalize, repository, pantry, step_ingredients
tests/           pytest suite (no network, Ollama, or Whisper model needed)
data/            gitignored: recipes.db and temporary downloads
```

## Commands

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                # run from project root
python main.py ingest <url> [<url> ...] [--skip-existing]
python main.py batch --file urls.txt [--refresh]
python main.py search --ingredients "garlic, butter, pasta" [--limit N] [--json]
python main.py pantry chicken garlic "soy sauce" [--limit N] [--json] [--no-staples]
python main.py list [--todo | --all]   # default: ready recipes only
python main.py show <id> [--json]
python main.py import-page <id> [--url <recipe page>] [--file saved.html|list.txt]   # creator's blog
python main.py reparse <id> [<id> ...] | --missing-steps   # re-run the model on saved text
python main.py shorten-steps [<id> ...] [--refresh]   # island step versions, no reparse
python main.py renormalize [--dry-run]   # after normalizer/ALIASES edits
python main.py thumbnails [--refresh]    # save video thumbnails to data/thumbnails/
uvicorn api.app:app --port 8000          # API for the web app (add --host 0.0.0.0 for the iPhone)
cd web; npm run dev                      # web app on :3000 (also .claude/launch.json "api"/"web")
```

## Design Rules & Conventions

- **Same normalization on both sides.** Recipe ingredients and pantry queries both go through
  `db/normalize.py::normalize_ingredient_name`. Matching relies on consistency, not perfect
  linguistics. Add synonyms to `ALIASES` there; add tests in `tests/test_normalize.py`; then run
  `main.py renormalize` so stored rows pick up the change. Accents on Latin letters are folded
  (`purée` -> `puree`); letters in other scripts are kept, never stripped.
- **Keep the raw text.** `recipe_ingredients.raw_name` stores the original wording; `ingredients.name`
  is the canonical shared name. The same ingredient may appear twice in one recipe.
- **Record where ingredients came from.** `recipes.ingredient_sources` lists the inputs the parser
  read them from (`description`, `speech`, `captions`, `title`; `comments` and `on_screen` are
  reserved for future inputs). `transcript_source` only says which transcript was sent to the model.
- **English output.** The prompt requires title, yield and ingredient names in English whatever
  the video's language (verified on Spanish, Japanese and Cantonese text with qwen3.5:9b);
  the original-language text stays in `description` / `transcript`.
- **One ingredient list per recipe, with its yield.** `recipes.yield_label` records what the amounts
  make ("serves 4", "1 standard loaf pan"). When a post gives several batch sizes, the parser keeps
  only the standard/smallest home-size one, never a mix (user's choice: no multi-version storage).
- **Schema changes to existing tables** go in `_ADDED_COLUMNS` in `db/schema.py`, since
  `CREATE TABLE IF NOT EXISTS` won't touch an existing database.
- **Upsert by canonical `source_url`.** `pipeline/urls.py::canonical_url` maps share-link variants
  (Instagram `/reel/` vs `/p/`, `?igsh=`, `youtu.be`, `/shorts/`) to one URL; always store and
  look up through it. Re-ingesting replaces the recipe and its ingredient lines. `batch` skips
  stored URLs before downloading unless `--refresh`; `ingest` updates unless `--skip-existing`.
- **`db/` is independent of `config.py`.** DB functions take explicit arguments (path, staples);
  the CLI/pipeline pass settings in.
- **Lazy-import faster-whisper** (inside functions) so DB-only commands and tests stay fast.
  `pipeline/__init__.py` stays empty for the same reason.
- **Ollama calls** use `/api/chat` with `format` = `ParsedRecipe.model_json_schema()`,
  `temperature: 0`, `stream: false`, and are validated with pydantic, with one retry on bad output.
- **Thinking models:** send `think: false` by default (`RECIPE_OLLAMA_THINK`). With thinking on,
  `qwen3.5:9b` timed out at 180s; with it off, a parse takes ~30-40s on this machine.
- **OCR fallback** (`RECIPE_OCR`: auto | always | off). In `auto`, OCR runs only when the first
  parse has < 3 ingredients or no amounts (`ingest.looks_incomplete`), or there is no text at all;
  the video is downloaded separately (`download_video`), frames sampled with ffmpeg `mpdecimate`,
  read with EasyOCR, lines grouped (`ocr.group_lines`) and fuzzy-deduped (`ocr.merge_frame_text`),
  then re-parsed. The retry is kept only if it has at least as many ingredients. OCR failures
  are logged and never fail an ingest. Raw text goes in `recipes.on_screen_text`. Lazy-import
  EasyOCR (inside `pipeline/ocr.py::_reader`), like faster-whisper.
- **Recipe pages** (`RECIPE_RECIPE_PAGES`, default on). When a parse looks incomplete and the
  caption links to a non-social page (`urls.recipe_link`), `webrecipe.fetch_recipe_page` reads its
  schema.org Recipe JSON-LD and the model re-parses with a RECIPE PAGE section. This runs before
  OCR (cheaper, exact). Failures (home-page-only link, HTTP 403 bot blocking, no recipe data) are
  logged and skipped; never try to get around a site's bot blocking. Page URL/text are stored in
  `recipe_page_url` / `recipe_page_text`. `import-page` applies it to stored recipes from their
  saved text (no re-download), or with `--url` for "link in bio" posts. For sites that block
  the app, `--file` takes a page the user saved in their browser (Ctrl+S; read the same way,
  address from its canonical link) or a .txt with the ingredient list pasted in
  (`webrecipe.read_recipe_file`). A bad local file never sets the recipe's `status_note`.
- **Instagram comments** were tested and not wired in: signed out, yt-dlp only gets ~12 of
  hundreds of comments, none by the creator on the to-do posts; signing in risks the user's
  account. The `comments` source label stays reserved.
- **Steps.** The same model call returns the method (`steps`), taken only from what the post,
  speech, on-screen text or recipe page says; recipe pages contribute `recipeInstructions`
  (strings, HowToStep, HowToSection), pasted text files a section after an "Instructions:" /
  "Method:" heading. Stored in `recipe_steps`, replaced on every save. Adding steps made a parse
  ~2 min instead of ~1. `reparse` re-runs the model on stored text (no downloads) and never
  replaces existing ingredients with an empty parse; `import-page` without `--url` re-fetches the
  page imported before (pages stored before steps existed lack instructions).
- **Short steps.** `recipe_steps.short_text` is a ~50-character version of each step for the
  iOS Dynamic Island / Lock Screen ("Mix the sauce ingredients"), from a second, small model
  call (`parser.shorten_steps`: steps + ingredient names only). Its schema has one required
  key per step (`step_1`, ...): with a plain list, qwen3.5:9b merged 10 steps into one item. Ingest and `reparse` run it after the parse; failures are logged
  and leave NULLs. `shorten-steps` fills stored recipes from their saved steps (ingredients
  untouched). A version that is empty or not shorter is stored NULL; the app then shortens `text`.
- **Transcript choice:** use platform captions if ≥ 40 chars and `RECIPE_PREFER_CAPTIONS`, else
  Whisper. The video description is always included in the prompt (reels often put the recipe there).
- **Silent reels:** Instagram serves a video-only file when a reel has no audio; faster-whisper
  crashes on it ("tuple index out of range"), so `transcriber.has_audio` is checked first and
  Whisper is skipped. EasyOCR's per-frame PyTorch CPU warnings are filtered in `ocr._quiet_torch`.
- **Posts without an ingredient list** (recipe on a blog, "link in bio", comment-a-keyword DMs,
  or not a recipe) are still saved: the row acts as a cache so `batch` skips them next time
  instead of re-downloading/OCR-ing. `recipes.status` is `ready` (has ingredients),
  `needs_recipe` (caption points elsewhere; `status_note` records failures such as a site's 403),
  or `not_recipe` (user confirmed these are non-recipe videos: food vlogs, ads, restaurant
  visits). `save_recipe` forces `ready` when there are lines and leaves NULL when not told;
  `main.open_db` backfills NULLs via `urls.classify_missing_recipe`. `list` shows only ready,
  `list --todo` the needs_recipe to-do list, `list --all` everything. Empty posts have no
  `ingredient_sources`. `list`/`show`/`ingest` label them; `pipeline/urls.py::recipe_link` and
  `points_elsewhere` find the caption's external recipe link or hint (`show` also prints
  "Full recipe:" for normal recipes). Pantry search never returns them (no ingredient rows).
- **Caption failures** (e.g. YouTube 429) trigger a retry without captions rather than failing.
- **Pantry staples** (`RECIPE_PANTRY_STAPLES`: salt, black pepper, water, oil) are excluded from
  scoring entirely, not counted as matched.
- **Web app.** Thumbnails are downloaded at ingest (`MediaAssets.thumbnail_url`,
  `pipeline/thumbnails.save_thumbnail`) because platform image URLs expire; only the file
  name is stored (`recipes.thumbnail_file`), failures are logged and never fail an ingest.
  `favorite`/`tried` are user marks: `save_recipe`'s upsert must never touch them. Per-step
  ingredients are matched from wording at read time (`db/step_ingredients.py`; uses
  `normalize_ingredient_name(..., aliases=False)` so "white sugar" isn't just "sugar"), not
  stored. Step progress lives in the browser's localStorage. Video plays via the platforms'
  embed players (`urls.embed_url`); Instagram's needs ~326px width, so the mini player
  scales a full-size iframe down. Ingredient cards show amounts, not photos (no image source).
  `components/DynamicIslandStep.tsx` is a black top pill (tap to expand) shown while the step
  card is off screen past the hero, or while a step timer runs; it shares the recipe page's
  progress handlers (`selectStep`, `completeStep`) with `CookingMode`, never its own state.
  Timers come from the step's wording (`lib/stepTimer.ts`: "28-32 minutes" -> 28 min).
- **iOS Live Activity** (`web/native/ios/`, see its README; not compiled yet, no Xcode
  project in the repo). The web side only feeds the active step to the Capacitor plugin
  (`lib/useLiveActivity.ts` -> `LiveActivityManager.setSession`); the native side starts the
  activity on resign-active/background and ends it `.immediate` on foreground/become-active,
  because JS may be suspended. Starting must happen before `didEnterBackground` (iOS refuses
  requests from the background). The "Dynamic Island" switch (`LiveActivityToggle`,
  localStorage `liveActivity:autoStart`) disables auto-start; "End cooking session" ends all
  activities and suppresses the session until the step or timer changes. In a browser every
  bridge call is a no-op (`liveActivitySupported()`).
- Downloaded media is deleted after ingest unless `RECIPE_KEEP_MEDIA=true`.

## Environment Notes (this machine)

Two machines on the home Wi-Fi (user's decision, 2026-11-03: the 16 GB M1 struggled running
everything):

- **Windows PC = backend.** Pipeline (yt-dlp, faster-whisper, Ollama `qwen3.5:9b`), SQLite
  (`data/recipes.db`) and `uvicorn api.app:app --host 0.0.0.0 --port 8000`. Ingest, `reparse`,
  `import-page` and other data commands run there; it has the authoritative database. Changes
  to `api/` or `db/` reach it via git (push here, pull there, restart uvicorn).
- **MacBook Air (Apple M1, 16 GB) = development client only.** Xcode, Claude Code, git,
  pytest. Do **not** run Ollama models, the pipeline, `uvicorn` or iOS Simulators here. Build
  the iOS app for and run it on the physical iPhone (`xcodebuild ... -configuration Release
  -destination 'id=<udid>'`, then `xcrun devicectl device install app`); Debug builds made
  SwiftUI noticeably laggy on the phone. The user checks the screen, since Claude's simulator
  tools don't reach a real device. Keep background processes to a minimum.
- Mac details: macOS 27, default shell bash, Homebrew `python@3.12` (`python3.12`), venv at
  `.venv/` (enough for pytest), Xcode 27. `node@22` is keg-only: `~/.bash_profile` adds
  `/opt/homebrew/opt/node@22/bin` to PATH. Ollama is installed but should stay idle. The
  Mac's `data/` is a stale copy from the brief 2026-11-03 move; don't treat it as current.
- Timings quoted above ("~30-40s", "~2 min" per parse, OCR durations) were measured on the PC.

## Not Yet Verified / Open Items

- End-to-end `ingest` verified on a public Instagram post (Whisper path, qwen3.5:9b). Not yet run
  against a live YouTube URL or the platform-captions path.
- Private/login-gated Instagram reels may need yt-dlp cookies (`cookiefile` / `cookiesfrombrowser`),
  not wired up yet; the public post worked without them.
- `av<19` is pinned in `requirements.txt`: faster-whisper 1.2.1 passes `metadata_errors` to
  `av.open()`, which PyAV 19 rejects. Drop the pin once faster-whisper fixes this.
- OCR verified on a synthetic text-only video (all lines read, parsed correctly) and on the real
  Instagram reel (`RECIPE_OCR=always`: 60 frames, ~4.5 min total vs ~1.5 min without). Not yet
  tested on a real reel whose ingredients appear only on screen.
- Public on GitHub: https://github.com/sshower111/recipe-pantry-app (MIT).

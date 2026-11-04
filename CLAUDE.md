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
4. **Native iOS app** (done on `ios-app`, all runbook build steps 1-8): SwiftUI app in `ios/`
   (iOS 17+) reading the FastAPI server over Wi-Fi: cookbook feed with ingredient search,
   cooking mode, cooking-step Live Activity, Settings, offline copy, share-sheet ingest.
   Runbook: `docs/ios/README.md`; JSON contract: `docs/ios/api.md` (regenerate its samples
   if API responses change).

## Layout

```
config.py        Settings dataclass from RECIPE_* env vars / .env (see .env.example)
main.py          argparse CLI: init-db | ingest | batch | search | pantry | list | show | import-page |
                 renormalize | thumbnails
api/app.py       FastAPI JSON server for the iPhone app (create_app(db_path, thumbnails_dir, staples, ingest))
api/jobs.py      in-memory queue for links shared from the phone (POST /api/ingest)
ios/             Xcode project: Cookbook app, CookingActivity (Live Activity), AddToCookbook (share
                 extension), Shared/ (both app and widget), tools/ + Art/ (cook flipbook font)
docs/ios/        iOS app runbook and API contract
pipeline/        downloader, transcriber, parser, ingest, urls, ocr, frames, webrecipe, thumbnails
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
python main.py video-steps [<id> ...] [--todo] [--dry-run]   # steps from frames of silent recipes
python main.py renormalize [--dry-run]   # after normalizer/ALIASES edits
python main.py thumbnails [--refresh]    # save video thumbnails to data/thumbnails/
uvicorn api.app:app --host 0.0.0.0 --port 8000   # API for the iPhone app (on the PC)
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
  read them from (`description`, `speech`, `captions`, `title`, `on_screen`, `recipe_page`,
  `visual` = the vision model's reading of keyframes; `comments` is reserved). `transcript_source` only says which transcript was sent to the model.
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
- **Visual fallback for silent videos** (`RECIPE_VISUAL`: auto | off). `ingest.is_silent`:
  no real captions and Whisper heard < `RECIPE_VISUAL_MIN_WORDS` (5) words, sound tags like
  "[Music]" not counted. In `auto` it runs last (after recipe page and OCR) when the video is
  silent and the result has no steps or looks incomplete. `pipeline/frames.py` takes ffmpeg
  keyframes (every `RECIPE_VISUAL_INTERVAL` s + scene changes, `showinfo` timestamps),
  `parser.parse_visual_recipe` sends them as Ollama `images` with a frame/time list and gets
  `{"title", "steps": [{"step_number", "timestamp_start", "instruction", "ingredients_used"}]}`
  (times snapped to the frames shown). `ingest.merge_visual`: written text wins; frames only
  fill missing steps (times in `recipe_steps.start_seconds`) and, when there's no ingredient
  list, names without amounts (source label `visual`). One video download is shared with OCR
  (`ingest.VideoFile`). Failures are logged, never fail an ingest. `reparse` keeps steps that
  have start times when the new parse has none. `video-steps` applies it to stored recipes
  (`ingest.steps_from_video`: video download only, stored ingredients kept): by default every
  ready recipe with no steps whose saved transcript is silent; `--todo` adds needs_recipe
  posts (they turn ready if the frames give ingredient names); explicit ids skip the silence
  check. Verified on the PC (2026-11-04, qwen3.5:9b reads images): 5 stored recipes, 6-20
  keyframes each, 3-14 steps; step quality not yet reviewed. The API doesn't expose
  `start_seconds` yet.
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
  The iPhone app relabels them (`PATCH /api/recipes/{id} {"status"}`, `db.set_status`, never
  for rows with ingredients): "Save for later" = `needs_recipe` (its 🔖 list), "Remove" =
  `not_recipe`. "Check again" re-ingests with `refresh`; a `needs_recipe` post that still
  has no list stays `needs_recipe` instead of being re-classified.
- **Caption failures** (e.g. YouTube 429) trigger a retry without captions rather than failing.
- **Pantry staples** (`RECIPE_PANTRY_STAPLES`: salt, black pepper, water, oil) are excluded from
  scoring entirely, not counted as matched.
- **Thumbnails, marks, step ingredients.** Thumbnails are downloaded at ingest
  (`MediaAssets.thumbnail_url`, `pipeline/thumbnails.save_thumbnail`) because platform image
  URLs expire; only the file name is stored (`recipes.thumbnail_file`), failures are logged
  and never fail an ingest. `favorite`/`tried`/`hidden` are user marks: `save_recipe`'s upsert
  must never touch them. Per-step ingredients are matched from wording at read time
  (`db/step_ingredients.py`; uses `normalize_ingredient_name(..., aliases=False)` so "white
  sugar" isn't just "sugar"), not stored. Step timers come from the step's wording
  (`ios/Cookbook/Models/StepTimer.swift`: "28-32 minutes" -> 28 min).
- **The web app** (Next.js in `web/`) was removed on 2026-11-04 at the user's request: this is
  an iPhone app with a Python backend. It's in git history (`4937190`) if ever needed.
- **Native iOS app** (`ios/`; built and run on the iPhone, never a Simulator: see Environment;
  the one exception is the README's demo media, captured in the Simulator with the user's OK).
  - Feed: the search box also takes "what you have" (ingredient chips -> `/api/pantry`
    re-ranks the feed; no separate Pantry tab, the user's choice). Filters All / ❤️ /
    👌🎉 (the API's `tried`, shown as "Cooked" everywhere) / 🔖 (`?status=todo`). Filter
    switches don't animate: animating the feed or a sliding pill stuttered on the phone.
  - Thumbnails (`Views/Thumbnail.swift`) are decoded at their drawn size off the main thread
    and cached in memory; photos come from URLCache once downloaded (offline too).
  - Offline (`Store/OfflineStore.swift`): the feed, 🔖 list and every recipe are saved as JSON
    and shown first; the PC being out of reach keeps them with an "Offline" tag. API calls
    time out after 8 s. Marks, ingredient search and Check again need the PC.
  - Cooking progress (step in focus, done steps, the step timer) lives on the phone
    (`Shared/CookingProgress.swift`, UserDefaults), shared with the Live Activity.
  - Recipe screen: ▶ opens the post only in its app (`UIApplication.open` with
    `universalLinksOnly`; no app installed = an alert offering Safari), never a browser on its
    own: the browser asks people to sign in. Ingredient tiles show black-and-white icons
    (`Models/IngredientIcon.swift`, keyword rules on the canonical name, specific first):
    proteins as their animal (cow, pig, chicken, duck, fish), one mixed-vegetables icon for
    every vegetable, one fruits icon; sources/licenses in `ios/Art/icons` (Health Icons CC0,
    Tabler MIT, Lucide ISC; Tabler/Lucide strokes thinned to 1.25 to match).
  - Cooking mode: the step card (`Views/StepCard.swift`) is a paging horizontal scroll view
    (swipe between steps; a hand-made drag stuttered). The same StepCard, `compact`, pops up
    at the top while scrolling once the card is above the screen (scrolled down past it), and
    tucks away ~2 s after scrolling stops; never while above the card. The step list shows
    every step in full.
  - Live Activity (`CookingActivity/`): follows Apple's Live Activities HIG in the app's look
    (SF Pro, cream/terracotta; Lock Screen cream or warm dark by appearance, 14 pt margins;
    the cook as logo mark; one ‹ | › control plus ✕; compact/minimal fit the 28 pt circle,
    a progress ring or the timer). The expanded island picks 3 or 2 lines with ViewThatFits:
    iOS gives it less height on a long press than when an alert opens it, and a greedy
    (`maxHeight: .infinity`) region squeezed the instruction to one line.
    It starts on ▶ (watch), or on leaving a recipe
    (`.inactive`; iOS refuses requests once in the background) if Settings' switch is on;
    ends whenever the app is active again, on the island's ✕ (`EndCookingIntent`), and when
    the app is closed in the app switcher: iOS keeps activities after their app quits and
    tells a suspended app nothing, so leaving (`.inactive`) starts a ~25 s background task
    and willTerminate ends the activities (run loop kept turning, not a blocked main thread;
    verified on the phone). Closed after that window, the ✕ is the way. iOS collapses the
    expanded island by itself, so a
    silent alert (`Resources/silence.caf`) re-opens it on start and on every ‹ › tap.
    ‹ › run `ChangeStepIntent` (a LiveActivityIntent, so in the app's process: no App Group
    needed). Keep the Lock Screen card and expanded island under ~160 pt, or iOS crops them.
    Island text prefers the server's `short_text`, else `Step.islandText`'s regex shortening.
  - The corner cook: `CookFlip.ttf`'s digits are 10 outline poses; the widget shows one per
    step (`CookFrame`). A 1 frame/s flipbook through `Text(timerInterval:)` in that font was
    tried and doesn't render: iOS draws timer text itself and ignores custom fonts (verified
    in the Simulator: static text in the font shows, the timer is blank). Rebuild with
    `ios/tools/draw_cook_frames.swift` -> `ios/Art/cook-frames/*.svg` ->
    `ios/tools/make_flipbook_font.py`. The cook is an original drawing: don't copy existing
    characters (the user asked for old-school anime style, not Dragon Ball characters).
  - Share sheet (`AddToCookbook/`): posts the link to `POST /api/ingest`; the PC's queue
    (`api/jobs.py`) runs one job at a time with `ingest_url(..., skip_existing=True)`, in
    memory (a uvicorn restart drops queued jobs). The feed polls `GET /api/ingest` and shows
    "Adding..." cards. The extension can't read the app's Settings (no App Group on a free
    Apple ID), so its server address is hard-coded: keep it in sync with
    `APIClient.defaultServerURL` (`http://192.168.2.23:8000`; give the PC that address with a
    DHCP reservation so it doesn't change).
  - Free Apple ID signing: the app must be re-installed every 7 days.
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

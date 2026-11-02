# Recipe Pantry App

A local pipeline that ingests cooking shorts/reels, extracts text/audio ingredients locally,
normalizes them into structured JSON, stores them in SQLite, and lets the user query recipes
based on available pantry items. Everything runs locally: no cloud APIs.

## Technology Stack

- **Ingestion:** yt-dlp (video metadata, captions, audio)
- **Transcription:** faster-whisper (local audio-to-text)
- **OCR (optional, `requirements-ocr.txt`):** EasyOCR on ffmpeg-sampled video frames
- **LLM parsing:** Ollama running `qwen2.5:7b` via the local API (`http://localhost:11434`)
- **Database:** SQLite (`recipes`, `ingredients`, `recipe_ingredients`)
- **Supporting:** requests (Ollama HTTP), pydantic v2 (output validation), python-dotenv, pytest

## Phase Breakdown

1. **Scaffolding** (done): project layout, venv setup instructions (README), `requirements.txt`,
   `requirements-dev.txt`, and `config.py`.
2. **Ingestion & Extraction Pipeline (`pipeline/`)** (done):
   - `downloader.py`: download audio/captions with yt-dlp.
   - `transcriber.py`: run faster-whisper on audio files.
   - `parser.py`: build prompt payloads and call Ollama for structured JSON:
     `{"title": str, "sources": ["title"|"description"|"transcript"], "yield_label": str|null,
       "ingredients": [{"name": str, "amount": float|null, "unit": str|null}]}`.
   - `ingest.py`: orchestrates URL → media → transcript → recipe → DB.
3. **Database & Query Engine (`db/`)** (done):
   - `schema.py`: SQLite schema (`recipes`, `ingredients`, `recipe_ingredients`) and `connect()`.
   - `repository.py`: insertion with normalized ingredient mapping (`save_recipe`), reads.
   - `pantry.py`: `find_recipes_by_pantry(conn, available_ingredients: list[str], ...)` returns
     matching recipes sorted by missing-ingredient count (fewest first).

## Layout

```
config.py        Settings dataclass from RECIPE_* env vars / .env (see .env.example)
main.py          argparse CLI: init-db | ingest | batch | search | pantry | list | show
pipeline/        downloader, transcriber, parser, ingest, urls, ocr
db/              schema, normalize, repository, pantry
tests/           pytest suite (no network, Ollama, or Whisper model needed)
data/            gitignored: recipes.db and temporary downloads
```

## Commands

```powershell
.\.venv\Scripts\Activate.ps1          # Git Bash: source .venv/Scripts/activate
pip install -r requirements-dev.txt
pytest                                # run from project root
python main.py ingest <url> [<url> ...] [--skip-existing]
python main.py batch --file urls.txt [--refresh]
python main.py search --ingredients "garlic, butter, pasta" --max-missing 3 [--json]
python main.py pantry chicken garlic "soy sauce" --max-missing 3 [--json] [--no-staples]
python main.py list
python main.py show <id> [--json]
```

## Design Rules & Conventions

- **Same normalization on both sides.** Recipe ingredients and pantry queries both go through
  `db/normalize.py::normalize_ingredient_name`. Matching relies on consistency, not perfect
  linguistics. Add synonyms to `ALIASES` there; add tests in `tests/test_normalize.py`.
- **Keep the raw text.** `recipe_ingredients.raw_name` stores the original wording; `ingredients.name`
  is the canonical shared name. The same ingredient may appear twice in one recipe.
- **Record where ingredients came from.** `recipes.ingredient_sources` lists the inputs the parser
  read them from (`description`, `speech`, `captions`, `title`; `comments` and `on_screen` are
  reserved for future inputs). `transcript_source` only says which transcript was sent to the model.
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
- **Transcript choice:** use platform captions if ≥ 40 chars and `RECIPE_PREFER_CAPTIONS`, else
  Whisper. The video description is always included in the prompt (reels often put the recipe there).
- **Silent reels:** Instagram serves a video-only file when a reel has no audio; faster-whisper
  crashes on it ("tuple index out of range"), so `transcriber.has_audio` is checked first and
  Whisper is skipped. EasyOCR's per-frame PyTorch CPU warnings are filtered in `ocr._quiet_torch`.
- **Caption failures** (e.g. YouTube 429) trigger a retry without captions rather than failing.
- **Pantry staples** (`RECIPE_PANTRY_STAPLES`: salt, black pepper, water, oil) are excluded from
  scoring entirely, not counted as matched.
- Downloaded media is deleted after ingest unless `RECIPE_KEEP_MEDIA=true`.

## Environment Notes (this machine)

- Windows 11, Python 3.12, venv at `.venv/`. ffmpeg and Ollama are installed and on PATH.
- Installed Ollama models: `qwen3.5:9b` (thinking-capable). `qwen2.5:7b` (the code default) is
  not pulled; the local `.env` sets `RECIPE_OLLAMA_MODEL=qwen3.5:9b` instead.
- Whisper runs on CPU/int8 by default; GPU needs CUDA 12 cuBLAS + cuDNN 9.

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
- The project is not a git repository yet.

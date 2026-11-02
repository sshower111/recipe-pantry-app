# Recipe Pantry

A local pipeline that turns cooking shorts and reels into structured recipes and
tells you what you can cook with what's in your pantry. Everything runs on your machine.

```
URL ──yt-dlp──► metadata + captions + audio
                     │
                     ├─ captions good? ──► transcript
                     └─ else faster-whisper ──► transcript
                                                   │
         title + description + transcript ──► Ollama (qwen2.5:7b, JSON schema)
                                                   │
          too few ingredients / no amounts? ──► video frames ──EasyOCR──► on-screen text
                                                   │                        └─► re-parse
                         normalize names/units ──► SQLite
                                                   │
                     pantry list ──► recipes ranked by fewest missing ingredients
```

## Demo

Real output from my own database of about 90 recipes saved from Instagram reels.

**What can I cook with what's in the fridge?**

```
$ python main.py pantry flour sugar "brown sugar" honey yeast eggs "baking soda" --max-missing 1
1. [84] Classic Japanese Bagel  (4/4 ingredients, can make now)
     have:    flour, honey, sugar, yeast
     missing: -
     instagram.com/p/CzJiZmOLfaW

2. [37] No-Yeast Youtiao  (3/4 ingredients, missing 1)
     have:    baking soda, flour, sugar
     missing: baking powder
     instagram.com/p/C188sW2PfKU

3. [33] Honey Butter Toast  (2/3 ingredients, missing 1)
     have:    brown sugar, honey
     missing: butter
     instagram.com/p/C63hOr1ysaW
```

**A stored recipe, parsed from the reel's caption and speech:**

```
$ python main.py show 55
Salted Maple Banana Bread
instagram.com/p/DZva78zpQuq
Ingredients from description, speech; transcript: whisper
Makes: 1 standard loaf pan

  - 0.75 cup butter
  - 1 cup brown sugar
  - 0.33 cup white sugar
  - 1.33 cup mashed banana
  - 2 egg
  - 1.5 tsp vanilla paste
  - 1 tsp molasses
  - 2 cup all-purpose flour
  - 1 tsp baking soda
  - 1 tsp salt
  - 4 oz buttermilk
  - 0.5 cup maple syrup
  - flaky sea salt
```

Salt, pepper, water and oil count as pantry staples, so they never show up as missing.
Links are shortened here; the CLI prints full URLs.

Recipes by their original creators:
[Classic Japanese Bagel](https://www.instagram.com/p/CzJiZmOLfaW/) ·
[No-Yeast Youtiao](https://www.instagram.com/p/C188sW2PfKU/) ·
[Honey Butter Toast](https://www.instagram.com/p/C63hOr1ysaW/) ·
[Salted Maple Banana Bread](https://www.instagram.com/p/DZva78zpQuq/)

## Layout

```
config.py              settings from RECIPE_* env vars / .env
main.py                CLI
pipeline/
  downloader.py        yt-dlp: metadata, captions (VTT -> text), audio; video for OCR
  ocr.py               ffmpeg frame sampling + EasyOCR -> distinct on-screen text lines
  transcriber.py       faster-whisper (model cached, VAD on)
  parser.py            prompt + Ollama call with JSON-schema output, pydantic validation
  ingest.py            orchestrates the above and saves the result
  urls.py              canonical URLs (share-link variants -> one key), batch file reading
db/
  schema.py            recipes / ingredients / recipe_ingredients + connect()
  normalize.py         canonical ingredient names and units
  repository.py        save_recipe (upsert by URL), get_recipe, list_recipes
  pantry.py            find_recipes_by_pantry
tests/
```

## Setup

Prerequisites: Python 3.10+, [Ollama](https://ollama.com), and ffmpeg on PATH (yt-dlp
uses it for some sites).

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # optional
ollama pull qwen2.5:7b
```

```bash
# macOS / Linux / Git Bash
python -m venv .venv
source .venv/bin/activate        # Git Bash on Windows: source .venv/Scripts/activate
pip install -r requirements-dev.txt
cp .env.example .env
ollama pull qwen2.5:7b
```

The first transcription downloads the Whisper model (`small` is about 500 MB) into the
Hugging Face cache.

**On-screen text (optional):** `pip install -r requirements-ocr.txt` adds EasyOCR (and CPU
PyTorch, a few hundred MB; its models download on first use). With `RECIPE_OCR=auto`
(default), a video whose description and speech give fewer than 3 ingredients, or no
amounts, is downloaded again as video, sampled at `RECIPE_OCR_FPS` (near-identical frames
dropped, at most `RECIPE_OCR_MAX_FRAMES`), OCR'd, and re-parsed with that text. This adds
a few minutes per video on CPU. `RECIPE_OCR=always` does it for every video, `off` never.
Without EasyOCR installed the fallback is skipped with a warning.

**GPU transcription:** set `RECIPE_WHISPER_DEVICE=cuda` and `RECIPE_WHISPER_COMPUTE_TYPE=float16`.
This needs the CUDA 12 cuBLAS and cuDNN 9 libraries; see the faster-whisper README.

## Usage

```bash
python main.py ingest "https://www.youtube.com/shorts/<id>" "https://www.instagram.com/reel/<id>/"
python main.py batch --file urls.txt            # add --refresh to re-parse stored URLs
python main.py list                            # recipes ready to cook
python main.py list --todo                     # posts whose recipe is on a blog / in the bio / by DM
python main.py list --all                      # everything, including non-recipe videos
python main.py show 1
python main.py import-page 34                  # read a post's ingredients from its linked blog recipe
python main.py import-page 63 --url https://...   # ... or from a recipe page you found yourself
python main.py renormalize --dry-run          # re-apply name normalization to stored recipes
python main.py search --ingredients "chicken, garlic, soy sauce, rice, eggs" --max-missing 3
python main.py pantry eggs butter --json        # same query, space-separated
```

**Duplicates.** Recipes are keyed by a canonical URL, so `/reel/<id>/?igsh=...` and
`/p/<id>/` (or `youtu.be/<id>` and `/shorts/<id>`) are the same recipe. `ingest`
re-parses and updates a stored URL (`--skip-existing` skips it); `batch` skips stored
URLs before downloading unless `--refresh` is given, and also skips repeats within the
file. A batch file can mix notes and links (`Banana bread: https://...`): only URLs are
used (`http(s)://...` or bare `instagram.com/...`-style links), and text after a `#` is a
comment, so `# https://...` skips that link. The run reports how many lines had no URL.
Failed URLs are reported and the run continues; the exit code is 1 if any failed.

**Search results** are ranked by fewest missing ingredients, then by the share you have,
and list what you have and what's missing. A recipe needs at least one match to appear.

Pantry matching normalizes both sides the same way: "2 large eggs" and "eggs" both
become `egg`, and "scallions" becomes `green onion`. Staples listed in
`RECIPE_PANTRY_STAPLES` (salt, black pepper, water and oil by default) are left out of
the scoring. Pass `--no-staples` to count them.

From Python:

```python
from db import connect, find_recipes_by_pantry
conn = connect("data/recipes.db")
for m in find_recipes_by_pantry(conn, ["chicken", "garlic", "rice"], max_missing=2):
    print(m.title, m.missing)
```

## Configuration

All settings are optional. See `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `RECIPE_DATA_DIR` | `data` | DB and temporary downloads |
| `RECIPE_OLLAMA_MODEL` | `qwen2.5:7b` | Any Ollama model that handles JSON output |
| `RECIPE_OLLAMA_NUM_CTX` | `8192` | Context window passed to Ollama |
| `RECIPE_OLLAMA_THINK` | `false` | Turns off reasoning on thinking models (much faster). `default` leaves it to the model |
| `RECIPE_WHISPER_MODEL` | `small` | `base` is faster, `medium`/`large-v3` are more accurate |
| `RECIPE_PREFER_CAPTIONS` | `true` | Use platform captions when present, skip Whisper |
| `RECIPE_KEEP_MEDIA` | `false` | Keep downloaded audio/caption files |
| `RECIPE_PANTRY_STAPLES` | `salt,black pepper,water,oil` | Ignored when scoring |

## Tests

```bash
pytest
```

The tests cover normalization, the DB and pantry query, prompt and response
handling (with Ollama mocked), and caption parsing. They don't need network access,
Ollama, or a Whisper model.

## License

MIT. See [LICENSE](LICENSE).

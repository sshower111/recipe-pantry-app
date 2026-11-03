"""Turn a video's text into a structured recipe using a local Ollama model."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, ValidationError, create_model, field_validator

log = logging.getLogger(__name__)


class Ingredient(BaseModel):
    name: str = Field(min_length=1)
    amount: float | None = None
    unit: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Any:
        if isinstance(value, str):
            return parse_quantity(value)
        return value

    @field_validator("unit", mode="before")
    @classmethod
    def _blank_unit(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ParsedRecipe(BaseModel):
    title: str
    # Which prompt sections the ingredient list was read from.
    sources: list[Literal["title", "description", "transcript", "on_screen", "recipe_page"]]
    # What the ingredient amounts make, e.g. "serves 4" or "1 standard loaf pan".
    yield_label: str | None
    ingredients: list[Ingredient]
    # The method, one instruction per item, in order.
    steps: list[str] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def _clean_steps(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [s.strip() for s in value if isinstance(s, str) and s.strip()]
        return value

    @classmethod
    def output_schema(cls) -> dict[str, Any]:
        """JSON schema for Ollama's constrained decoding, with every field required so the
        model always writes them (``steps`` has a default only for code building recipes)."""
        schema = cls.model_json_schema()
        schema["required"] = list(schema["properties"])
        return schema

    @field_validator("yield_label", mode="before")
    @classmethod
    def _blank_yield(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class OllamaError(RuntimeError):
    pass


_UNICODE_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_QUANTITY = re.compile(r"^\s*(\d+(?:\.\d+)?)?\s*(?:(\d+)\s*/\s*(\d+))?\s*$")


def parse_quantity(text: str) -> float | None:
    """Parse "2", "1.5", "1/2", "1 1/2", "1½". Returns None for vague amounts ("to taste")."""
    text = text.strip()
    extra = 0.0
    for char, value in _UNICODE_FRACTIONS.items():
        if char in text:
            extra += value
            text = text.replace(char, " ")
    match = _QUANTITY.match(text)
    if not match:
        return None
    whole, num, den = match.groups()
    total = extra + (float(whole) if whole else 0.0)
    if num and den and int(den) != 0:
        total += int(num) / int(den)
    return total or None


SYSTEM_PROMPT = """\
You extract recipes from cooking video text (title, caption/description, spoken transcript,
and sometimes text read from the video frames or the creator's recipe web page).

Return JSON with:
- "title": a short descriptive recipe name (not clickbait; e.g. "Garlic Butter Shrimp Pasta").
- "sources": which input sections the ingredient list was taken from: any of "title",
  "description", "transcript", "on_screen", "recipe_page". Only list a section if ingredients or
  amounts came from it.
- "yield_label": what the ingredient amounts make, in the text's wording ("serves 4",
  "12 cookies", "1 standard loaf pan"), or null if it is not stated.
- "ingredients": every ingredient used, each as {"name", "amount", "unit"}.
- "steps": the method in order, one short instruction per item ("Cream the butter and both
  sugars.", "Bake at 325°F for 50-60 minutes until deeply golden."). See "Rules for steps".

Language: the video may be in any language (Spanish, Cantonese, Japanese, French, ...) and
the sections may mix languages. ALWAYS write "title", "yield_label" and every ingredient
"name" in standard English, translating as needed ("蒜頭" / "ajo" -> "garlic",
"グラニュー糖" -> "granulated sugar", "15個分" -> "15 rolls"). Use the common English
name a supermarket would use; for ingredients with no English equivalent, use the usual
romanized name ("gochujang", "mirin", "pandan leaf"). Never output non-English text.

If the text gives the same recipe at several batch sizes (e.g. "1x - 1 loaf pan" and
"3x - 2 loaf pans"), use ONLY the standard or smallest home-size batch: take its amounts and
its yield. Never mix or add up amounts from different sizes.

Rules for ingredients:
- "name": the generic ingredient in lowercase singular form without preparation words
  ("2 cloves garlic, minced" -> "garlic"; "3 large eggs" -> "egg"; "chopped fresh cilantro" -> "cilantro").
  Keep words that change what the ingredient is ("brown sugar", "soy sauce", "ground beef").
- "amount": a number (convert fractions: "1/2" -> 0.5) or null if not stated.
- "unit": a short English unit ("tbsp", "tsp", "cup", "g", "ml", "oz", "lb", "clove", "can",
  "pinch"; "大さじ" -> "tbsp", "cucharadita" -> "tsp") or null for countable items ("2 eggs")
  or when unstated.
- List each ingredient once; if quantities are split across steps, add them up when the units match.
- Only include ingredients that are actually mentioned. Do not invent quantities.
- Ignore equipment, sponsorships, and calls to action.
- ON-SCREEN TEXT comes from OCR of the video frames: lines may be out of order, repeated, or
  misspelled ("sov sauce" -> "soy sauce"). Correct obvious OCR errors, and ignore usernames,
  watermarks, and captions that are not ingredients.
- RECIPE PAGE is the full written recipe from the creator's website. When present it is the
  most reliable source: take the ingredient list, amounts and yield from it. Where it gives
  both cups and grams ("½ cup (113g) butter"), use the grams. Ignore footnote marks ("*").
- If the text contains no recipe, return empty "sources", "ingredients" and "steps" lists.

Rules for steps:
- Use only the method the text actually gives (spoken, written, on screen, or the recipe
  page); never invent steps. Prefer the RECIPE PAGE's or the caption's written method when
  present, adding useful detail said in the video.
- Keep oven temperatures, times, pan sizes and doneness cues exactly as given.
- Write each step as one or two plain English sentences in the imperative ("Fold in the
  flour."), without numbering, chit-chat, or sponsor mentions. Merge tiny actions; split
  long paragraphs. At most 20 steps.
- If the method is not described, return an empty "steps" list.
"""


def build_messages(
    *,
    title: str,
    description: str,
    transcript: str,
    on_screen: str = "",
    recipe_page: str = "",
    max_chars: int = 12000,
) -> list[dict[str, str]]:
    """Build the chat messages for Ollama, truncating the transcript to fit context."""
    description = description.strip()[: max_chars // 3]
    on_screen = on_screen.strip()[: max_chars // 3]
    recipe_page = recipe_page.strip()[: max_chars // 3]
    budget = max(max_chars - len(description) - len(on_screen) - len(recipe_page), 0)
    transcript = transcript.strip()
    if len(transcript) > budget:
        transcript = transcript[:budget] + " [...]"
    user = (
        f"VIDEO TITLE:\n{title.strip() or '(none)'}\n\n"
        f"DESCRIPTION / CAPTION:\n{description or '(none)'}\n\n"
        f"TRANSCRIPT (spoken audio):\n{transcript or '(none)'}"
    )
    if on_screen:
        user += f"\n\nON-SCREEN TEXT (OCR of video frames):\n{on_screen}"
    if recipe_page:
        user += f"\n\nRECIPE PAGE (from the creator's website):\n{recipe_page}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def build_payload(
    messages: list[dict[str, str]], *, model: str, num_ctx: int = 8192, think: bool | None = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        # A JSON schema here makes Ollama constrain decoding to valid output.
        "format": ParsedRecipe.output_schema(),
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }
    # Thinking models (qwen3.x, deepseek-r1) reason by default, which is slow and
    # unnecessary for extraction. None leaves the model's default alone.
    if think is not None:
        payload["think"] = think
    return payload


def call_ollama(payload: dict[str, Any], *, base_url: str, timeout: float) -> str:
    try:
        resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
    except requests.ConnectionError as exc:
        raise OllamaError(f"Cannot reach Ollama at {base_url}. Is `ollama serve` running?") from exc
    except requests.Timeout as exc:
        raise OllamaError(
            f"Ollama did not answer within {timeout:g}s. Raise RECIPE_OLLAMA_TIMEOUT or use a smaller model."
        ) from exc
    if resp.status_code == 404:
        raise OllamaError(
            f"Model {payload['model']!r} not found. Run `ollama pull {payload['model']}`."
        )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def parse_recipe(
    *,
    title: str,
    description: str,
    transcript: str,
    on_screen: str = "",
    recipe_page: str = "",
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    timeout: float = 180,
    num_ctx: int = 8192,
    think: bool | None = False,
    max_chars: int = 12000,
    attempts: int = 2,
) -> ParsedRecipe:
    """Ask the model for a structured recipe, retrying if the output fails validation."""
    messages = build_messages(
        title=title, description=description, transcript=transcript, on_screen=on_screen,
        recipe_page=recipe_page, max_chars=max_chars,
    )
    payload = build_payload(messages, model=model, num_ctx=num_ctx, think=think)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        content = call_ollama(payload, base_url=base_url, timeout=timeout)
        try:
            return ParsedRecipe.model_validate_json(content)
        except (ValidationError, json.JSONDecodeError) as exc:
            log.warning("Attempt %d: model output failed validation: %s", attempt, exc)
            last_error = exc
    raise OllamaError(f"Model output never validated: {last_error}")


SHORTEN_PROMPT = """\
You shorten recipe steps for a phone's lock screen, which fits about two short lines.

You get the recipe's ingredient list and its numbered steps. Return JSON with one key per
step, "step_1", "step_2", ...: the short version of that step only.

Rules:
- At most 50 characters each; plain English imperative ("Fold in the flour").
- Keep the action, and any quantities, temperatures, times and pan sizes the step gives
  ("Bake at 170°C for 40-45 minutes until golden." -> "Bake at 170°C for 40-45 min").
- Drop lists of ingredients the ingredient list already shows; name the group instead
  ("In a bowl, mix together hoisin sauce, bean sauce, sugar, ... ginger powder." ->
  "Mix the sauce ingredients"). Keep a single named ingredient ("Add the garlic").
- Drop asides, reasons, tips and doneness descriptions when they don't fit.
- No numbering and no final period. Never add anything the step doesn't say.
"""


def build_shorten_messages(steps: list[str], ingredients: list[str]) -> list[dict[str, str]]:
    listed = "\n".join(f"- {name}" for name in ingredients) or "(none)"
    numbered = "\n".join(f"{n}. {step}" for n, step in enumerate(steps, 1))
    user = f"INGREDIENTS:\n{listed}\n\nSTEPS ({len(steps)}):\n{numbered}"
    return [{"role": "system", "content": SHORTEN_PROMPT}, {"role": "user", "content": user}]


def _clean_short(short: str, step: str) -> str | None:
    """None when the model gave nothing useful (the app then shortens ``step`` itself)."""
    short = short.strip().rstrip(".").strip()
    return short if short and len(short) < len(step) else None


def shorten_steps(
    steps: list[str],
    *,
    ingredients: list[str] = (),
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    timeout: float = 180,
    num_ctx: int = 8192,
    think: bool | None = False,
    attempts: int = 2,
) -> list[str | None]:
    """Ask the model for a ~50-character version of each step, for the iOS Dynamic Island.
    A separate, small call (steps and ingredient names only), so stored recipes can be
    shortened without parsing their text again. A step whose version is empty or not
    shorter comes back None."""
    if not steps:
        return []
    payload = build_payload(build_shorten_messages(list(steps), list(ingredients)),
                            model=model, num_ctx=num_ctx, think=think)
    # One required key per step: a plain list let the model merge all the steps into one item.
    keys = [f"step_{n}" for n in range(1, len(steps) + 1)]
    answer = create_model("ShortSteps", **{key: (str, ...) for key in keys})
    payload["format"] = answer.model_json_schema()

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        content = call_ollama(payload, base_url=base_url, timeout=timeout)
        try:
            shorts = answer.model_validate_json(content)
        except ValidationError as exc:
            log.warning("Attempt %d: short steps failed validation: %s", attempt, exc)
            last_error = exc
            continue
        return [_clean_short(getattr(shorts, key), step) for key, step in zip(keys, steps)]
    raise OllamaError(f"Short steps never validated: {last_error}")

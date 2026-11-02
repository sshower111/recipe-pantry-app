"""Turn a video's text into a structured recipe using a local Ollama model."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

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
    sources: list[Literal["title", "description", "transcript", "on_screen"]]
    # What the ingredient amounts make, e.g. "serves 4" or "1 standard loaf pan".
    yield_label: str | None
    ingredients: list[Ingredient]

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
and sometimes text read from the video frames).

Return JSON with:
- "title": a short descriptive recipe name (not clickbait; e.g. "Garlic Butter Shrimp Pasta").
- "sources": which input sections the ingredient list was taken from: any of "title",
  "description", "transcript", "on_screen". Only list a section if ingredients or amounts came
  from it.
- "yield_label": what the ingredient amounts make, in the text's wording ("serves 4",
  "12 cookies", "1 standard loaf pan"), or null if it is not stated.
- "ingredients": every ingredient used, each as {"name", "amount", "unit"}.

If the text gives the same recipe at several batch sizes (e.g. "1x - 1 loaf pan" and
"3x - 2 loaf pans"), use ONLY the standard or smallest home-size batch: take its amounts and
its yield. Never mix or add up amounts from different sizes.

Rules for ingredients:
- "name": the generic ingredient in lowercase singular form without preparation words
  ("2 cloves garlic, minced" -> "garlic"; "3 large eggs" -> "egg"; "chopped fresh cilantro" -> "cilantro").
  Keep words that change what the ingredient is ("brown sugar", "soy sauce", "ground beef").
- "amount": a number (convert fractions: "1/2" -> 0.5) or null if not stated.
- "unit": a short unit ("tbsp", "tsp", "cup", "g", "ml", "oz", "lb", "clove", "can", "pinch")
  or null for countable items ("2 eggs") or when unstated.
- List each ingredient once; if quantities are split across steps, add them up when the units match.
- Only include ingredients that are actually mentioned. Do not invent quantities.
- Ignore equipment, sponsorships, and calls to action.
- ON-SCREEN TEXT comes from OCR of the video frames: lines may be out of order, repeated, or
  misspelled ("sov sauce" -> "soy sauce"). Correct obvious OCR errors, and ignore usernames,
  watermarks, and captions that are not ingredients.
- If the text contains no recipe, return empty "sources" and "ingredients" lists.
"""


def build_messages(
    *, title: str, description: str, transcript: str, on_screen: str = "", max_chars: int = 12000
) -> list[dict[str, str]]:
    """Build the chat messages for Ollama, truncating the transcript to fit context."""
    description = description.strip()[: max_chars // 3]
    on_screen = on_screen.strip()[: max_chars // 3]
    budget = max(max_chars - len(description) - len(on_screen), 0)
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
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def build_payload(
    messages: list[dict[str, str]], *, model: str, num_ctx: int = 8192, think: bool | None = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        # A JSON schema here makes Ollama constrain decoding to valid output.
        "format": ParsedRecipe.model_json_schema(),
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
        max_chars=max_chars,
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

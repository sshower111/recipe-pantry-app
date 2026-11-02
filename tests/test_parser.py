import json

import pytest
from pydantic import ValidationError

from pipeline import parser
from pipeline.parser import (
    Ingredient,
    OllamaError,
    ParsedRecipe,
    build_messages,
    parse_quantity,
    parse_recipe,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2", 2), ("1.5", 1.5), ("1/2", 0.5), ("1 1/2", 1.5), ("1½", 1.5), ("¼", 0.25), ("to taste", None)],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


def test_ingredient_coerces_string_amount():
    assert Ingredient(name="sugar", amount="1/2", unit="").model_dump() == {
        "name": "sugar", "amount": 0.5, "unit": None,
    }


def test_parsed_recipe_blank_yield_is_none():
    recipe = ParsedRecipe(title="Toast", sources=["transcript"], yield_label=" ", ingredients=[])
    assert recipe.yield_label is None


def test_parsed_recipe_rejects_unknown_source():
    with pytest.raises(ValidationError):
        ParsedRecipe(title="x", sources=["comments"], yield_label=None, ingredients=[])


def test_build_messages_on_screen_section_only_when_present():
    without = build_messages(title="T", description="d", transcript="t")[1]["content"]
    assert "ON-SCREEN TEXT" not in without
    with_text = build_messages(title="T", description="d", transcript="t", on_screen="2 tbsp honey")[1]["content"]
    assert with_text.endswith("ON-SCREEN TEXT (OCR of video frames):\n2 tbsp honey")


def test_build_messages_truncates_transcript():
    messages = build_messages(title="T", description="d" * 10, transcript="x" * 500, max_chars=100)
    user = messages[1]["content"]
    assert user.count("x") == 90
    assert user.endswith("[...]")


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_parse_recipe_retries_until_valid(monkeypatch):
    good = json.dumps({
        "title": "Toast",
        "sources": ["transcript"],
        "yield_label": "serves 1",
        "ingredients": [{"name": "bread", "amount": 2, "unit": None}],
    })
    responses = iter([FakeResponse("{not json"), FakeResponse(good)])
    sent = []

    def fake_post(url, json, timeout):
        sent.append(json)
        return next(responses)

    monkeypatch.setattr(parser.requests, "post", fake_post)
    recipe = parse_recipe(title="t", description="", transcript="toast two slices of bread")
    assert recipe.title == "Toast"
    assert recipe.ingredients[0].amount == 2
    assert recipe.yield_label == "serves 1"
    assert len(sent) == 2
    assert set(sent[0]["format"]["required"]) == {"title", "sources", "yield_label", "ingredients", "steps"}
    assert sent[0]["stream"] is False
    assert sent[0]["think"] is False


def test_parse_recipe_missing_model(monkeypatch):
    monkeypatch.setattr(parser.requests, "post", lambda *a, **k: FakeResponse("", status_code=404))
    with pytest.raises(OllamaError, match="ollama pull"):
        parse_recipe(title="t", description="", transcript="x")


def test_system_prompt_requires_english_output():
    prompt = parser.SYSTEM_PROMPT
    assert "ALWAYS write \"title\", \"yield_label\" and every ingredient\n\"name\" in standard English" in prompt
    assert '"ajo" -> "garlic"' in prompt


def test_build_messages_recipe_page_section():
    user = build_messages(title="T", description="d", transcript="t", recipe_page="- 2 eggs")[1]["content"]
    assert user.endswith("RECIPE PAGE (from the creator's website):\n- 2 eggs")
    assert "RECIPE PAGE" not in build_messages(title="T", description="d", transcript="t")[1]["content"]

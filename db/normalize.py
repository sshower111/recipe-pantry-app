"""Canonicalize ingredient names and units.

Both stored recipe ingredients and pantry queries pass through the same functions,
so matching only needs to be consistent, not linguistically perfect.
"""

from __future__ import annotations

import re

# Words that describe preparation/size rather than identity ("2 large eggs, beaten" -> "egg").
_DESCRIPTORS = {
    "fresh", "freshly", "chopped", "finely", "roughly", "coarsely", "minced", "diced",
    "sliced", "thinly", "grated", "shredded", "crushed", "peeled", "large", "small",
    "medium", "organic", "optional", "softened", "melted", "cold", "warm", "hot",
    "boneless", "skinless", "packed", "heaping", "heaped", "lightly", "beaten",
    "cubed", "halved", "quartered", "julienned", "trimmed", "rinsed", "drained",
    "mashed", "pureed", "ripe", "overripe", "flaky",
    "about", "approx", "approximately", "some", "a", "an", "the", "of",
}

# Applied after descriptor removal and singularization.
ALIASES = {
    "scallion": "green onion",
    "spring onion": "green onion",
    "garbanzo bean": "chickpea",
    "courgette": "zucchini",
    "aubergine": "eggplant",
    "capsicum": "bell pepper",
    "all purpose flour": "flour",
    "plain flour": "flour",
    "ap flour": "flour",
    "granulated sugar": "sugar",
    "white sugar": "sugar",
    "caster sugar": "sugar",
    "kosher salt": "salt",
    "sea salt": "salt",
    "table salt": "salt",
    "extra virgin olive oil": "olive oil",
    "pepper": "black pepper",  # "salt and pepper"
    "ground black pepper": "black pepper",
    "unsalted butter": "butter",
    "salted butter": "butter",
    "neutral oil": "oil",
    "vegetable oil": "oil",
    "cooking oil": "oil",
}

_IRREGULAR_PLURALS = {
    "leaves": "leaf",
    "loaves": "loaf",
    "halves": "half",
    "knives": "knife",
}

# Words where stripping a trailing "s" would mangle them.
_NO_SINGULAR = {"asparagus", "hummus", "couscous", "molasses", "swiss", "grits", "series"}

_UNITS = {
    "tbsp": "tbsp", "tbs": "tbsp", "tbsps": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "cup": "cup", "cups": "cup", "c": "cup",
    "g": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "mg": "mg",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "fl oz": "fl oz", "fluid ounce": "fl oz", "fluid ounces": "fl oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash",
}

# Count/container words the model sometimes leaves in the name ("2 cloves garlic").
_LEADING_UNITS = set(_UNITS) | {
    "clove", "cloves", "can", "cans", "slice", "slices", "piece", "pieces", "sprig", "sprigs",
    "bunch", "bunches", "handful", "stick", "sticks", "head", "heads", "package", "packet",
    "jar", "bottle",
}

_LEADING_QUANTITY = re.compile(r"^[\d\s/.,½¼¾⅓⅔⅛-]+")
_PARENS = re.compile(r"\([^)]*\)")
_NON_WORD = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")


def _singularize(word: str) -> str:
    if word in _NO_SINGULAR or len(word) <= 3:
        return word
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_ingredient_name(raw: str) -> str:
    """Return a canonical lowercase singular name, or "" if nothing meaningful remains."""
    name = raw.lower().strip()
    name = _PARENS.sub(" ", name)
    name = name.split(",", 1)[0]  # "garlic, minced" -> "garlic"
    name = name.replace("-", " ")
    name = _NON_WORD.sub(" ", name)
    name = _LEADING_QUANTITY.sub("", name)
    words = [w for w in _SPACES.split(name) if w and w not in _DESCRIPTORS]
    if len(words) > 1 and words[0] in _LEADING_UNITS:
        words = words[1:]
    if not words:
        return ""
    words[-1] = _singularize(words[-1])
    name = " ".join(words)
    return ALIASES.get(name, name)




def normalize_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    unit = _SPACES.sub(" ", raw.lower().replace(".", "")).strip()
    if not unit:
        return None
    return _UNITS.get(unit) or _singularize(unit)

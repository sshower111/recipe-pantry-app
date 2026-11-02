"""Work out which ingredient lines each step uses, from the step's wording.

Steps are free text ("Cream the butter and both sugars"), so this is a best-effort text
match, good enough to show the ingredients beside a step while cooking. Each line is known
by its own name (the raw wording, cleaned but not aliased: "white sugar") and by its
canonical name ("sugar") when no other line shares that canonical name.

1. A plural word shared by several lines' names names all of them ("both sugars" ->
   brown sugar and white sugar).
2. A line's full name found in the step claims that text. Longer names go first, so
   "flaky sea salt" takes its words before "salt" can.
3. Text left over can still match the end of a name ("cocoa powder" -> unsweetened
   dutch-process cocoa powder), down to its last word ("the syrup" -> maple syrup) when no
   line sharing that word matched already.

Plurals are accepted on the last word ("eggs" matches egg).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from db.normalize import _fold_text, normalize_ingredient_name

_PARENS = re.compile(r"\([^)]*\)")
_NON_WORD = re.compile(r"[^\w\s]|_")
_SPACES = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = _PARENS.sub(" ", _fold_text(text).lower()).replace("-", " ")
    return _SPACES.sub(" ", _NON_WORD.sub(" ", text)).strip()


def _pattern(phrase: str, *, plural_only: bool = False) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?:e?s){'' if plural_only else '?'}(?!\w)")


def _claim(text: str, pattern: re.Pattern[str]) -> tuple[str, bool]:
    """Blank out every match of ``pattern`` so shorter names can't reuse those words."""
    blanked, count = pattern.subn(lambda m: " " * len(m.group(0)), text)
    return blanked, count > 0


def match_step_ingredients(
    steps: Sequence[str], ingredients: Sequence[Mapping[str, Any]]
) -> list[list[int]]:
    """For each step, the indexes (into ``ingredients``) of the lines it mentions, in list
    order. Each ingredient needs ``name`` (canonical) and may have ``raw_name``."""
    canonical = [_clean(item.get("name") or "") for item in ingredients]
    shared = Counter(canonical)
    names: list[tuple[int, str]] = []
    endings: list[tuple[int, str]] = []
    heads: dict[str, list[int]] = {}
    for index, item in enumerate(ingredients):
        own = _clean(normalize_ingredient_name(item.get("raw_name") or "", aliases=False)) or canonical[index]
        phrases = {own} | ({canonical[index]} if shared[canonical[index]] == 1 else set())
        names += [(index, phrase) for phrase in phrases - {""}]
        if own:
            words = own.split(" ")
            endings += [(index, " ".join(words[n:])) for n in range(1, len(words) - 1)]
            heads.setdefault(words[-1], []).append(index)
    names.sort(key=lambda pair: len(pair[1]), reverse=True)
    endings.sort(key=lambda pair: len(pair[1]), reverse=True)
    groups = {head: indexes for head, indexes in heads.items() if len(indexes) > 1}

    matches: list[list[int]] = []
    for step in steps:
        text = f" {_clean(step)} "
        found: set[int] = set()
        for head, indexes in groups.items():
            text, hit = _claim(text, _pattern(head, plural_only=True))
            if hit:
                found.update(indexes)
        for index, phrase in names:
            text, hit = _claim(text, _pattern(phrase))
            if hit:
                found.add(index)
        for index, ending in endings:
            if index not in found:
                text, hit = _claim(text, _pattern(ending))
                if hit:
                    found.add(index)
        for head, indexes in heads.items():
            if any(i in found for i in indexes):
                continue
            text, hit = _claim(text, _pattern(head))
            if hit:
                found.update(indexes)
        matches.append(sorted(found))
    return matches

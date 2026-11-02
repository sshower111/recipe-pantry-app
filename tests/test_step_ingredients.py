from db import match_step_ingredients, normalize_ingredient_name


def ing(raw_name):
    return {"name": normalize_ingredient_name(raw_name), "raw_name": raw_name}


BANANA_BREAD = [ing(n) for n in ("butter", "brown sugar", "white sugar", "banana", "egg", "all-purpose flour",
                                 "salt", "buttermilk", "flaky sea salt", "maple syrup")]


def test_full_names_plurals_and_hyphens():
    steps = ["Add the eggs and mashed banana.", "Whisk the all-purpose flour and salt."]
    assert match_step_ingredients(steps, BANANA_BREAD) == [[3, 4], [5, 6]]


def test_plural_shared_word_names_every_line():
    # "white sugar" is stored as plain "sugar"; "sugars" still means both.
    assert BANANA_BREAD[2]["name"] == "sugar"
    assert match_step_ingredients(["Cream the butter and both sugars."], BANANA_BREAD) == [[0, 1, 2]]


def test_aliased_name_shared_by_two_lines_is_not_used():
    # Both salts may be stored as "salt"; plain "salt" in a step is the plain salt line.
    assert match_step_ingredients(["Top with flaky sea salt.", "Add the salt."], BANANA_BREAD) == [[8], [6]]


def test_end_of_name_fallback():
    assert match_step_ingredients(["Brush the syrup over the top."], BANANA_BREAD) == [[9]]
    lines = [ing("baking powder"), ing("unsweetened dutch-process cocoa powder"), ing("instant espresso powder")]
    assert match_step_ingredients(["Whisk cocoa powder and espresso powder."], lines) == [[1, 2]]


def test_word_boundaries():
    # "buttermilk" is not butter; nothing in "Bake until golden" is an ingredient.
    assert match_step_ingredients(["Add the buttermilk.", "Bake until golden."], BANANA_BREAD) == [[7], []]


def test_raw_wording_and_accents():
    lines = [ing("2 cloves garlic, minced"), ing("Tomato purée")]
    assert match_step_ingredients(["Stir in the purée and the garlic."], lines) == [[0, 1]]

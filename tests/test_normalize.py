import pytest

from db.normalize import normalize_ingredient_name, normalize_unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2 cloves garlic, minced", "garlic"),
        ("Large Eggs", "egg"),
        ("chopped fresh cilantro", "cilantro"),
        ("cherry tomatoes", "cherry tomato"),
        ("Tomatoes", "tomato"),
        ("berries", "berry"),
        ("peaches", "peach"),
        ("bay leaves", "bay leaf"),
        ("Scallions", "green onion"),
        ("all-purpose flour", "flour"),
        ("extra-virgin olive oil", "olive oil"),
        ("soy sauce", "soy sauce"),
        ("ground beef", "ground beef"),
        ("pepper", "black pepper"),
        ("red bell peppers", "red bell pepper"),
        ("asparagus", "asparagus"),
        ("onion (about 1 cup)", "onion"),
        ("boneless skinless chicken thighs", "chicken thigh"),
        ("1/2 tsp", "tsp"),
        ("Mashed banana", "banana"),
        ("3 overripe bananas", "banana"),
        ("Ap flour", "flour"),
        ("Flaky sea salt", "salt"),
        ("pumpkin purée", "pumpkin puree"),
        ("Crème fraîche", "creme fraiche"),
        ("jalapeños", "jalapeno"),
        ("２ cloves garlic", "garlic"),  # full-width digit
        ("蒜頭", "蒜頭"),  # untranslated names stay visible
        ("グラニュー糖", "グラニュー糖"),  # kana voicing marks kept
        ("soy_sauce!", "soy sauce"),
        ("fresh", ""),
    ],
)
def test_normalize_ingredient_name(raw, expected):
    assert normalize_ingredient_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tablespoons", "tbsp"),
        ("tbsp.", "tbsp"),
        ("teaspoon", "tsp"),
        ("cups", "cup"),
        ("grams", "g"),
        ("lbs", "lb"),
        ("cloves", "clove"),
        ("cans", "can"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected

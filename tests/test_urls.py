import pytest

from pipeline.urls import canonical_url, points_elsewhere, read_url_file, recipe_link


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.instagram.com/p/DZlOp2nJL4I/", "https://www.instagram.com/p/DZlOp2nJL4I/"),
        ("https://www.instagram.com/reel/DZlOp2nJL4I/?igsh=abc123", "https://www.instagram.com/p/DZlOp2nJL4I/"),
        ("instagram.com/reels/DZlOp2nJL4I", "https://www.instagram.com/p/DZlOp2nJL4I/"),
        ("https://www.instagram.com/some.chef/reel/DZlOp2nJL4I/", "https://www.instagram.com/p/DZlOp2nJL4I/"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=xyz", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("https://www.tiktok.com/@chef.k/video/7300000000000000000?lang=en",
         "https://www.tiktok.com/@chef.k/video/7300000000000000000"),
        ("  https://example.com/recipe?id=3#comments ", "https://example.com/recipe?id=3"),
    ],
)
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected


def test_read_url_file_skips_blanks_and_comments():
    lines = [
        "# weeknight dinners",
        "https://youtu.be/aaaaaaaaaaa",
        "",
        "   ",
        "https://www.instagram.com/p/X1/   # banana bread",
        "https://example.com/a#frag https://example.com/b",
        "# https://www.instagram.com/p/OFF/  (commented out)",
    ]
    assert read_url_file(lines) == ([
        "https://youtu.be/aaaaaaaaaaa",
        "https://www.instagram.com/p/X1/",
        "https://example.com/a#frag",
        "https://example.com/b",
    ], 0)


def test_read_url_file_ignores_other_text():
    lines = [
        "Banana bread: https://www.instagram.com/p/X1/",
        "salmon (https://youtu.be/aaaaaaaaaaa), make on Sunday!",
        "see https://www.tiktok.com/@chef/video/123.",
        "also instagram.com/reel/X2/?igsh=zz and www.youtube.com/shorts/bbbbbbbbbbb",
        "try this later, e.g. 1.5 cups of rice and/or noodles",
        "htps://typo.example/x",
        "email me at chef@mail.com/x",
    ]
    assert read_url_file(lines) == ([
        "https://www.instagram.com/p/X1/",
        "https://youtu.be/aaaaaaaaaaa",
        "https://www.tiktok.com/@chef/video/123",
        "https://instagram.com/reel/X2/?igsh=zz",
        "https://www.youtube.com/shorts/bbbbbbbbbbb",
    ], 3)


@pytest.mark.parametrize(
    ("caption", "link", "elsewhere"),
    [
        # Shapes of real captions from saved reels.
        ("The recipe is at the link in my bio. Full link here: https://scientificallysweet.com/best-brownies/ "
         "Brownie Tips: 1. Never use raising agents", "https://scientificallysweet.com/best-brownies/", True),
        ("the full recipe is up on my blog at wellmadebykiley.com OR you can comment 'BANANA' to get it",
         "https://wellmadebykiley.com", True),
        ("Recipe on my website OR Comment SPAIN and I will send it to you", None, True),
        ("recipe on okonomikitchen blog or comment 'recipe' & I'll send you the link!", None, True),
        ("Full recipe is on my blog, link in my bio!! #lemoncookies", None, True),
        ("coconut matcha cloud with @hellotoa.official Simple + Addition Coconut Water #ad", None, False),
        ("ep.9 what the focc series, 1.5 cups flour", None, False),
        ("follow me on instagram.com/chef and youtube.com/@chef", None, False),
    ],
)
def test_recipe_link_and_points_elsewhere(caption, link, elsewhere):
    assert recipe_link(caption) == link
    assert points_elsewhere(caption) is elsewhere


def test_classify_missing_recipe():
    from pipeline.urls import classify_missing_recipe

    assert classify_missing_recipe("Full recipe is on my blog, link in my bio!!") == "needs_recipe"
    assert classify_missing_recipe("📍Patois 794 Dundas St W, Toronto #torontofood") == "not_recipe"
    assert classify_missing_recipe(None) == "not_recipe"

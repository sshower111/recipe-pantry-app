import pytest

from pipeline.urls import canonical_url, read_url_file


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

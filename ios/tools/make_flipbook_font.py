"""Turn the cook animation's frames into the flipbook font the Live Activity uses.

Live Activities can't run animations, but iOS keeps `Text(timerInterval:)` ticking on its
own. Shown in this font and cropped to its last character, that clock's seconds digit
(0-9, a new one every second) becomes a 10-frame flipbook. See
`ios/CookingActivity/CookingActivityLiveActivity.swift::CookFlipbook`.

Frames are SVGs on a 100x100 viewBox whose `<path d="...">` shapes are filled outlines
(strokes already turned into shapes: Inkscape "Stroke to Path", or
`ios/tools/draw_cook_frames.swift`, which writes them). They become ordinary vector glyphs,
so the widget colors them (`foregroundStyle`), e.g. yellow.

Usage (from the project root, any Python with fonttools):

    python ios/tools/make_flipbook_font.py ios/Art/cook-frames

1-10 frames, sorted by file name; fewer than 10 repeat in order.
Output: `ios/CookingActivity/Fonts/CookFlip.ttf`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path

FAMILY = "CookFlip"
UPEM = 1000
VIEWBOX = 100
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
# The clock's other characters get empty glyphs; the widget crops them away anyway.
BLANKS = {"space": 0x20, "colon": 0x3A, "period": 0x2E, "hyphen": 0x2D}


def frame_glyph(svg: Path):
    paths = re.findall(r'\sd="([^"]+)"', svg.read_text())
    if not paths:
        sys.exit(f"{svg}: no <path d=...> found")
    pen = TTGlyphPen(None)
    # SVG is y-down on a 100 box; glyphs are y-up on a 1000 em.
    scale = UPEM / VIEWBOX
    flipped = TransformPen(Cu2QuPen(pen, max_err=1.0, reverse_direction=True), (scale, 0, 0, -scale, 0, UPEM))
    for d in paths:
        parse_path(d, flipped)
    return pen.glyph()


def build(frames_dir: Path, out: Path) -> None:
    frames = sorted(frames_dir.glob("*.svg"))
    if not frames:
        sys.exit(f"No SVG frames in {frames_dir}")
    glyphs = [frame_glyph(path) for path in frames]

    glyph_order = [".notdef", *DIGITS, *BLANKS]
    builder = FontBuilder(UPEM, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    cmap = {0x30 + i: name for i, name in enumerate(DIGITS)}
    cmap.update({code: name for name, code in BLANKS.items()})
    builder.setupCharacterMap(cmap)
    empty = TTGlyphPen(None).glyph()
    outlines = {name: empty for name in glyph_order}
    outlines.update({name: glyphs[i % len(glyphs)] for i, name in enumerate(DIGITS)})
    builder.setupGlyf(outlines)
    # Every glyph is one square em wide, so the last character is exactly one em.
    builder.setupHorizontalMetrics({name: (UPEM, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=UPEM, descent=0)
    builder.setupOS2(sTypoAscender=UPEM, sTypoDescender=0, sTypoLineGap=0,
                     usWinAscent=UPEM, usWinDescent=0)
    builder.setupNameTable({"familyName": FAMILY, "styleName": "Regular",
                            "psName": f"{FAMILY}-Regular", "fullName": FAMILY})
    builder.setupPost()

    out.parent.mkdir(parents=True, exist_ok=True)
    builder.save(out)
    print(f"{out}: {len(glyphs)} frame(s) -> digits 0-9")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("frames", type=Path, help="folder of SVG frames")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "CookingActivity/Fonts/CookFlip.ttf")
    args = parser.parse_args()
    build(args.frames, args.out)

"""Turn the LPC cat sheet (CC-BY 3.0, bluecarrot16) into a Siamese variant.

The source sheet is 16x8 frames of 32x32, four colour variants of four columns
each. The white variant (columns 0..3) is the base: its body colour becomes
cream, and the extremities get the classic Siamese points (dark face mask, ears,
paws, tail tip).

Points are painted by position, per pose row, because the sprite has no notion
of "extremity" - the rules below are deliberately simple and visible in
assets/preview_siamese.png for inspection.

Attribution: "[LPC] Cats and Dogs" by bluecarrot16, CC-BY 3.0,
https://opengameart.org/content/lpc-cats-and-dogs - this file is a derivative.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "src" / "lpc-cat.png"
OUT = ROOT / "assets" / "siamese.png"
PREVIEW = ROOT / "assets" / "preview_siamese.png"

F = 32                      # frame size
BODY_IN = (239, 233, 231)   # the white variant's body colour
BODY_OUT = (242, 229, 200)  # cream
POINT = (92, 62, 44)        # seal-brown points

# (row, col) -> list of point rectangles in frame-local 32x32 coordinates.
# Rows: 0 side-right walk (3 frames) + sleep, 1 back, 2 front, 3 side-left walk
# (3 frames) + sleep, 4 head-down (eat/groom).
POINTS: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}


def _side(right: bool, sleeping: bool) -> list[tuple[int, int, int, int]]:
    """Side view: head/ears on one side, paws along the bottom, tail tip opposite."""
    if sleeping:                      # curled up: only the head and the front paw
        return [(18, 4, 29, 16), (10, 22, 24, 29)]
    head_x = (17, 30) if right else (2, 15)
    tail_x = (0, 7) if right else (25, 31)
    return [head_x + (0, 14),          # ear + face mask
            (0, 25, 32, 31),           # paws
            tail_x + (6, 20)]          # tail tip


def _back() -> list:
    return [(4, 22, 28, 31), (10, 6, 22, 14)]      # paws + tail tip (up the middle)


def _front() -> list:
    return [(10, 8, 22, 18), (8, 26, 24, 31)]      # face + paws


def _head_down() -> list:
    return [(11, 10, 21, 18), (6, 25, 26, 31)]     # muzzle + paws


for c in (0, 1, 2):
    POINTS[(0, c)] = _side(right=True, sleeping=False)     # walk right
    POINTS[(3, c)] = _side(right=False, sleeping=False)    # walk left
POINTS[(0, 3)] = _side(right=True, sleeping=True)
POINTS[(3, 3)] = _side(right=False, sleeping=True)
for c in (0, 1, 2):
    POINTS[(1, c)] = _back()
    POINTS[(2, c)] = _front()
for c in range(4):
    POINTS[(4, c)] = _head_down()


def recolour(img: Image.Image) -> None:
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if (r, g, b) == BODY_IN:
                px[x, y] = (*BODY_OUT, a)


def paint_points(cell: Image.Image, key: tuple[int, int]) -> None:
    """Paint this pose's extremities. Coordinates are cell-local (32x32)."""
    px = cell.load()
    for (x0, y0, x1, y1) in POINTS.get(key, []):
        for y in range(y0, min(y1, F)):
            for x in range(x0, min(x1, F)):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                # only body/mark pixels become points; the outline stays dark
                if (r, g, b) in (BODY_OUT, BODY_IN):
                    px[x, y] = (*POINT, a)


def build() -> Image.Image:
    src = Image.open(SRC).convert("RGBA")
    out = Image.new("RGBA", (4 * F, 5 * F), (0, 0, 0, 0))
    for row in range(5):
        for col in range(4):
            cell = src.crop((col * F, row * F, col * F + F, row * F + F))
            recolour(cell)
            paint_points(cell, (row, col))
            out.paste(cell, (col * F, row * F))
    return out


def preview(img: Image.Image, scale: int = 5) -> Image.Image:
    rows = 5
    canvas = Image.new("RGBA", (img.size[0] * scale, rows * F * scale + rows * 4), (24, 24, 32, 255))
    big = img.resize((img.size[0] * scale, img.size[1] * scale), Image.NEAREST)
    canvas.alpha_composite(big)
    return canvas


def main() -> int:
    siamese = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    siamese.save(OUT)
    preview(siamese).save(PREVIEW)
    print(f"SIAMESE ok frames={4 * 5} -> {OUT.relative_to(ROOT)}  preview -> {PREVIEW.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

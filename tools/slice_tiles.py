"""Slice the CC-BY furniture sheets into individual sprites and draw a numbered
contact sheet, so a human can pick by number instead of guessing coordinates.

    uv run python tools/slice_tiles.py
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "tiles"
OUT = SRC / "pieces"
MIN_AREA = 120          # ignore stray pixels


def components(alpha: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of the 8-connected opaque blobs, largest first."""
    h, w = alpha.shape
    seen = np.zeros((h, w), dtype=bool)
    boxes = []
    for y in range(h):
        for x in range(w):
            if not alpha[y, x] or seen[y, x]:
                continue
            q = deque([(x, y)])
            seen[y, x] = True
            x0 = x1 = x
            y0 = y1 = y
            area = 0
            while q:
                cx, cy = q.popleft()
                area += 1
                x0, x1 = min(x0, cx), max(x1, cx)
                y0, y1 = min(y0, cy), max(y1, cy)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and alpha[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((nx, ny))
            if area >= MIN_AREA:
                boxes.append((x0, y0, x1 + 1, y1 + 1))
    boxes.sort(key=lambda b: (b[1] // 20, b[0]))
    return boxes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC)
    a = ap.parse_args(argv)
    a_out = a.src / "pieces"
    a_out.mkdir(parents=True, exist_ok=True)
    pieces = []
    for png in sorted(a.src.glob("*.png")):
        img = Image.open(png).convert("RGBA")
        alpha = np.asarray(img)[:, :, 3] > 8
        for i, (x0, y0, x1, y1) in enumerate(components(alpha)):
            piece = img.crop((x0, y0, x1, y1))
            if piece.size[0] < 4 or piece.size[1] < 4:
                continue
            name = f"{png.stem[:18]}_{i:02d}.png"
            piece.save(a_out / name)
            pieces.append((name, piece))
    pieces.sort(key=lambda kv: kv[0])
    print(f"{len(pieces)} pieces -> {a_out.relative_to(ROOT)}")

    # numbered contact sheet, 8 per row, cells sized to the biggest piece
    cell = max(max(p.size) for _, p in pieces) + 26
    per_row = 8
    rows = (len(pieces) + per_row - 1) // per_row
    sheet = Image.new("RGBA", (cell * per_row, cell * rows), (28, 28, 36, 255))
    d = ImageDraw.Draw(sheet)
    for idx, (name, piece) in enumerate(pieces):
        cx, cy = (idx % per_row) * cell, (idx // per_row) * cell
        sheet.alpha_composite(piece, (cx + (cell - piece.size[0]) // 2, cy + 20))
        d.text((cx + 3, cy + 3), str(idx), fill=(120, 255, 120, 255))
    scale = max(1, min(2, 1500 // sheet.size[0]))
    sheet.resize((sheet.size[0] * scale, sheet.size[1] * scale), Image.NEAREST).save(ROOT / "build" / "pieces_sheet.png")
    for idx, (name, piece) in enumerate(pieces):
        print(f"{idx:3d} {name:34s} {piece.size[0]}x{piece.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

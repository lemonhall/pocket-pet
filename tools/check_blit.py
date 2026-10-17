"""Reproduce display_cat.c's blit in Python against the exported .bin files.

If the cat shows up here, the data is fine and the bug is in the C control flow.
If it does not, the exporter is wrong. Either way this removes the guesswork.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "firmware" / "main"
PANEL_W, PANEL_H = 720, 1280
ROOM_X, ROOM_Y = 40, 56
F = 64
COLS = 4
KEY = 0x0000


def load(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def main() -> int:
    room = load(MAIN / "room.bin")
    sheet = load(MAIN / "sprites.bin")
    room_w, room_h = 640, 360
    fb = [0x0000] * (PANEL_W * PANEL_H)

    def put(x, y, v):
        if 0 <= x < PANEL_W and 0 <= y < PANEL_H:
            fb[y * PANEL_W + x] = v

    # 1. the room, opaque
    for j in range(room_h):
        for i in range(room_w):
            put(ROOM_X + i, ROOM_Y + j, room[j * room_w + i])
    # 2. the cat, keyed on black - same math as display_cat.c
    for (row, col, cx, cy, label) in [(0, 0, 160, 130, "walk-right-0"),
                                      (1, 0, 80, 90, "back"),
                                      (4, 1, 240, 150, "head-down")]:
        frame = sheet[(row * F) * (COLS * F) + col * F:]
        dx = ROOM_X + int(cx * 2.0) - F // 2
        dy = ROOM_Y + int(cy * 2.0) - F // 2
        painted = 0
        for j in range(F):
            for i in range(F):
                v = frame[j * (COLS * F) + i]
                if v == KEY:
                    continue
                put(dx + i, dy + j, v)
                painted += 1
        print(f"{label}: frame origin row{row} col{col} -> ({dx},{dy}), painted {painted} px")
    out = Image.new("RGB", (PANEL_W, PANEL_H))
    px = out.load()
    for y in range(PANEL_H):
        for x in range(PANEL_W):
            v = fb[y * PANEL_W + x]
            px[x, y] = (((v >> 11) & 0x1F) * 255 // 31, ((v >> 5) & 0x3F) * 255 // 63, (v & 0x1F) * 255 // 31)
    out = out.rotate(-90, expand=True)
    out.save(ROOT / "build" / "offline_cat_blit.png")
    print(f"wrote build/offline_cat_blit.png ({out.size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

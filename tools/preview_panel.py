"""Draw the status panel exactly as display_cat.c does, from the same labels.bin.

If the glyphs are garbled here too, the problem is the strip data or the blit maths;
if they look fine here, the problem is the on-device layout.

    uv run python tools/preview_panel.py
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "firmware" / "main"
W, H = 1280, 720
X0, Y0, PW, PH = 300, 60, 680, 600


def load(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def main() -> int:
    labels = load(MAIN / "labels.bin")
    room = load(MAIN / "room.bin")
    img = Image.new("RGB", (W, H), (0, 0, 0))
    px = img.load()
    # the room backdrop, 2x upscale as on the device
    for y in range(H):
        row = (y // 2) * 640
        for x in range(W):
            v = room[row + x // 2]
            px[x, y] = (((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
    # the panel
    for y in range(Y0, Y0 + PH):
        for x in range(X0, X0 + PW):
            px[x, y] = (24, 28, 34)

    # label geometry as the exporter wrote it
    import re
    hdr = (MAIN / "assets.h").read_text(encoding="utf-8")
    LABEL_H = int(re.search(r"#define CAT_LABEL_H (\d+)", hdr).group(1))
    offs = [int(v) for v in re.search(r"cat_label_off\[CAT_LABEL_COUNT\] = \{(.*?)\};", hdr, re.S).group(1).replace("\n", " ").split(",") if v.strip()]
    wid = [int(v) for v in re.search(r"cat_label_w\[CAT_LABEL_COUNT\] = \{(.*?)\};", hdr, re.S).group(1).replace("\n", " ").split(",") if v.strip()]
    print("CAT_LABEL_H", LABEL_H, "labels", len(offs), len(wid), "widths", wid[:4], "...", wid[9:13])

    def blit(idx: int, x: int, y: int, keyed: bool = True) -> None:
        o, w = offs[idx], wid[idx]
        for j in range(LABEL_H):
            for i in range(w):
                v = labels[o + j * w + i]
                if keyed and v == 0:
                    continue
                if 0 <= x + i < W and 0 <= y + j < H:
                    px[x + i, y + j] = (((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)

    blit(0, X0 + 28, Y0 + 18)                 # the goal
    for i in range(9):
        y = Y0 + 78 + i * 54
        blit(9 + i, X0 + 28, y)
        bx = X0 + 260
        for j in range(26):
            for k in range(360):
                px[bx + k, y + 8 + j] = (41, 42, 53) if k > 200 else (63, 255, 128)
    img.resize((W // 2, H // 2), Image.NEAREST).save(ROOT / "build" / "panel_preview.png")
    print("wrote build/panel_preview.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

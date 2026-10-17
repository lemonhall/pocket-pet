"""Render every pixel the cat firmware needs into three raw RGB565 blobs.

The device has no font code and no image decoder: Python does the drawing once and
the firmware just blits. That is why this script exists.

Outputs (little-endian RGB565, row-major, no padding):
    firmware/main/room.bin     640x360  the static room background (2x of 320x180)
    firmware/main/sprites.bin  20 frames of 32x32 (4 cols x 5 rows), already 2x = 64x64
    firmware/main/labels.bin   the goal names and drive names, one strip per label
    firmware/main/assets.h     geometry + the label offsets the firmware indexes

    uv run python tools/export_cat_assets.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from pocket_pet import render, world

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "firmware" / "main"
SPRITE_SCALE = 4                    # 32 -> 128 px: the room fills 1280x720, so 4x
ROOM_W, ROOM_H = world.W * 2, world.H * 2      # 640x360, upscaled 2x again on the device
LABEL_H = 44                        # big enough to read on the tablet at arm's length
LABEL_FONT_PX = 34
CJK_FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")


LEGEND = ("食盆喂食", "水碗加水", "玩具陪玩", "猫砂盆清洁", "点猫撸猫")
LEGEND_H = 26
CJK_FONT = Path(r"C:\Windows\Fonts\msyh.ttc")


def legend_strips() -> tuple[bytes, list[int], list[int]]:
    """The on-screen legend: what each tap area does. Rendered with a CJK font,
    because the device has no font of its own (that is the whole reason this
    script exists)."""
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(str(CJK_FONT), 22)
    except OSError:
        font = ImageFont.load_default()
    blob = bytearray()
    offs, widths = [], []
    for text in LEGEND:
        probe = Image.new("RGB", (8, 8))
        w = ImageDraw.Draw(probe).textlength(text, font=font) + 10
        strip = Image.new("RGB", (int(w), LEGEND_H), (0, 0, 0))
        ImageDraw.Draw(strip).text((5, 2), text, fill=(255, 255, 255), font=font)
        offs.append(len(blob) // 2)
        widths.append(int(w))
        blob += rgb565(strip)
    return bytes(blob), offs, widths


def heart_sprite(size: int = 28) -> Image.Image:
    """The purr bubble's heart."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 4
    d.ellipse([2, 2, 2 + 2 * r, 2 + 2 * r], fill=(240, 90, 120, 255))
    d.ellipse([size - 2 - 2 * r, 2, size - 2, 2 + 2 * r], fill=(240, 90, 120, 255))
    d.polygon([(2, 2 + r), (size - 2, 2 + r), (size // 2, size - 2)], fill=(240, 90, 120, 255))
    return img


def rgb565(img: Image.Image) -> bytes:
    """PIL RGB -> little-endian RGB565."""
    out = bytearray()
    px = img.convert("RGB").load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            r, g, b = px[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out += bytes((v & 0xFF, v >> 8))
    return bytes(out)


def room_background() -> Image.Image:
    img = Image.new("RGB", (world.W, world.H), (0, 0, 0))
    render.draw_room(ImageDraw.Draw(img))
    return img.resize((ROOM_W, ROOM_H), Image.NEAREST)


def sprite_sheet() -> Image.Image:
    """The 4x5 sheet, upscaled to 64x64 frames."""
    sheet = render.load_sheet()
    return sheet.resize((sheet.size[0] * SPRITE_SCALE, sheet.size[1] * SPRITE_SCALE), Image.NEAREST)


def label_strips(texts: list[str]) -> tuple[bytes, list[int], list[int]]:
    """Pre-rendered text: one strip per label, white on black.

    Returns (blob, offsets, widths). The WIDTHS must be the real ones: the header
    used to emit a hand-written `8*len+4` guess while the strips were cut to the
    measured text length, so every row was read with the wrong stride and the panel
    showed vertical noise (found with tools/preview_panel.py)."""
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(str(CJK_FONT_PATH), LABEL_FONT_PX)
    except OSError:
        font = ImageFont.load_default()
    blob = bytearray()
    offsets, widths = [], []
    for t in texts:
        probe = Image.new("RGB", (8, 8))
        w = int(ImageDraw.Draw(probe).textlength(t, font=font)) + 8
        strip = Image.new("RGB", (w, LABEL_H), (0, 0, 0))
        ImageDraw.Draw(strip).text((4, 2), t, fill=(255, 255, 255), font=font)
        offsets.append(len(blob) // 2)             # in pixels (16-bit units)
        widths.append(w)
        blob += rgb565(strip)
    return bytes(blob), offsets, widths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)

    room = room_background()
    (a.out / "room.bin").write_bytes(rgb565(room))

    sheet = sprite_sheet()
    (a.out / "sprites.bin").write_bytes(rgb565(sheet))

    labels = list(render.GOAL_LABELS) + list(render.DRIVE_LABELS)
    # The panel shows these. The C side indexes by position, so the order must not
    # change - only the words rendered into each strip are translated.
    ZH = {
        "seek_food": "找吃的", "sleep": "睡觉", "play": "玩耍", "groom": "理毛",
        "follow_owner": "找主人", "scratch": "磨爪", "explore": "溜达", "hide": "躲起来",
        "drink": "喝水",
        "hunger": "饿", "energy": "精力", "bored": "无聊", "clingy": "粘人",
        "litter": "猫砂", "curiosity": "好奇", "bold": "胆量", "lazy": "懒", "scruff": "毛乱",
    }
    blob, offs, widths = label_strips([ZH.get(t, t) for t in labels])
    (a.out / "labels.bin").write_bytes(blob)

    # the legend (what each tap does) and the purr heart, on their own
    legend, l_offs, l_widths = legend_strips()
    heart = heart_sprite()
    (a.out / "legend.bin").write_bytes(legend + rgb565(heart))
    heart_off = len(legend) // 2

    header = [
        "/* generated by tools/export_cat_assets.py - do not edit */",
        "#pragma once",
        f"#define CAT_ROOM_W {ROOM_W}",
        f"#define CAT_ROOM_H {ROOM_H}",
        f"#define CAT_FRAME {32 * SPRITE_SCALE}",
        f"#define CAT_SHEET_COLS {sheet.size[0] // (32 * SPRITE_SCALE)}",
        f"#define CAT_LABEL_H {LABEL_H}",
        f"#define CAT_LABEL_COUNT {len(labels)}",
        f"#define CAT_LEGEND_COUNT {len(LEGEND)}",
        f"#define CAT_LEGEND_H {LEGEND_H}",
        f"#define CAT_HEART {heart.size[0]}",
        f"#define CAT_HEART_OFF {heart_off}",
        "static const int cat_legend_off[CAT_LEGEND_COUNT] = {",
        "    " + ", ".join(str(o) for o in l_offs),
        "};",
        "static const int cat_legend_w[CAT_LEGEND_COUNT] = {",
        "    " + ", ".join(str(w) for w in l_widths),
        "};",
        "#define CAT_LABEL_DRINK 8      /* the reflex layer's goal, see ECN-0003 */",
        "static const int cat_label_off[CAT_LABEL_COUNT] = {",
        "    " + ", ".join(str(o) for o in offs),
        "};",
        "static const int cat_label_w[CAT_LABEL_COUNT] = {",
        "    " + ", ".join(str(w) for w in widths),
        "};",
    ]
    (a.out / "assets.h").write_text("\n".join(header) + "\n", encoding="utf-8")
    print(f"ASSETS room {room.size} {len(rgb565(room))} B | sprites {sheet.size} "
          f"{len(rgb565(sheet))} B | labels {len(labels)} {len(blob)} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render the sim to a GIF and a contact sheet (the morning's visible result).

    uv run python tools/make_gif.py --minutes 3 --fps 8 --out assets/siamese_room.gif
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from pocket_pet import render, sim

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fps", type=int, default=8, help="GIF frames per second (sim runs at 10)")
    ap.add_argument("--max-frames", type=int, default=140, help="keep the GIF small")
    ap.add_argument("--no-advisor", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "siamese_room.gif")
    a = ap.parse_args(argv)

    sheet = render.load_sheet()
    frames: list[Image.Image] = []
    keep = max(1, sim.FPS // a.fps)

    def on_frame(cat, t, stats):
        if t % keep == 0 and len(frames) < a.max_frames:
            frames.append(render.render(cat, t, sheet))

    cat, stats = sim.run(a.minutes, a.seed, use_advisor=not a.no_advisor, on_frame=on_frame)
    if not frames:
        print("no frames rendered")
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    small = [f.resize((f.size[0] // 2, f.size[1] // 2), Image.NEAREST) for f in frames]
    small[0].save(a.out, save_all=True, append_images=small[1:], duration=int(1000 / a.fps),
                  loop=0, optimize=True, disposal=2)

    picks = [frames[i * len(frames) // 4] for i in range(4)]
    w, h = picks[0].size
    sheet_img = Image.new("RGBA", (w * 2, h * 2), (20, 20, 26, 255))
    for i, f in enumerate(picks):
        sheet_img.alpha_composite(f, ((i % 2) * w, (i // 2) * h))
    sheet_path = a.out.with_name(a.out.stem + "_sheet.png")
    sheet_img.save(sheet_path)

    d = stats.as_dict()
    print(f"GIF {a.out.relative_to(ROOT)} frames={len(small)} size={small[0].size} "
          f"states_seen={d['states_seen']} goals={len(d['goals'])}")
    print(f"SHEET {sheet_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

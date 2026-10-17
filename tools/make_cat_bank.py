"""Turn pocket-tank's sound-bank packer into the cat's, then build the bank.

The packer (tools/make_sounds.py upstream) already does the hard part: normalise,
trim, loop-crossfade, then emit sounds.bin plus a sounds.h/c pair whose enum order
is the contract with the firmware. Only three things change for the cat: the cue
list, where the WAVs come from, and where the generated files go.

    uv run python tools/make_cat_bank.py
"""
from __future__ import annotations

import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(r"E:\development\pocket-tank\tools\make_sounds.py")
DST = ROOT / "tools" / "_cat_bank"
DST.mkdir(parents=True, exist_ok=True)

CUES = '''CUES = [
    ("meow_short", 0), ("meow_long", 0), ("chirp", 0), ("hiss", 0),
    ("purr", 1),
]
'''

src = UPSTREAM.read_text(encoding="utf-8")
# The tank's audio.c already carries the cue table (SND_TAP, SND_FEED, ...), so we
# keep its CUES list verbatim and only supply cat WAVs under those names. Changing
# the list here would mean editing audio.c as well, for no benefit.
# paths: where the WAVs live and where the generated files land.
# (lambdas on purpose: a Windows path in the replacement would be read as an
# escape sequence, which is exactly how "bad escape \d" bit me here)
src = re.sub(r"^ROOT = .*$", lambda m: f'ROOT = r"{ROOT}"', src, flags=re.M)
src = re.sub(r"^DST = .*$", lambda m: f'DST = r"{ROOT / "assets" / "sounds"}"', src, flags=re.M)
src = re.sub(r"^OUT_H = .*$", lambda m: f'OUT_H = r"{ROOT / "firmware" / "main" / "sounds.h"}"', src, flags=re.M)
src = re.sub(r"^OUT_C = .*$", lambda m: f'OUT_C = r"{ROOT / "firmware" / "main" / "sounds.c"}"', src, flags=re.M)
src = re.sub(r"^DEFERRED = .*$", lambda m: "DEFERRED = set()", src, flags=re.M)

patched = DST / "make_sounds_cat.py"
patched.write_text(src, encoding="utf-8")
print(f"patched packer -> {patched.relative_to(ROOT)}")

import sys
sys.argv = [str(patched), "build"]
runpy.run_path(str(patched), run_name="__main__")

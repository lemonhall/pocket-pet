"""Synthesise the cat's voice as 16 kHz mono WAVs, then hand them to a copy of
pocket-tank's make_sounds.py (which packs them into sounds.bin + sounds.h).

Why synthesise instead of hunting for recordings: the shipped bank has to be
small, licence-clean, and parameterisable, and a cat's voice is mostly a pitch
contour over a harmonic stack - which is exactly what is cheap to write here.

    uv run python tools/make_cat_sounds.py

Writes assets/sounds/cat-<cue>.wav:
    meow_short  asking for food (up-then-down, bright)
    meow_long   wanting attention (slower, lower, softer)
    purr        being stroked (looping, low pulse train)
    chirp       curious / playing (fast rising blip)
    hiss        startled / hiding (band-limited noise, sharp attack)
"""
from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np

RATE = 16000
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "sounds"


def env(n: int, attack: float, release: float) -> np.ndarray:
    a = max(1, int(attack * RATE))
    r = max(1, int(release * RATE))
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a) ** 0.6
    e[-r:] = np.linspace(1, 0, r) ** 1.4
    return e


def hz(contour: np.ndarray, vibrato_hz: float = 5.5, depth: float = 0.012) -> np.ndarray:
    """Phase accumulator for a time-varying frequency (plus a little vibrato)."""
    n = len(contour)
    t = np.arange(n) / RATE
    f = contour * (1.0 + depth * np.sin(2 * np.pi * vibrato_hz * t))
    return 2 * np.pi * np.cumsum(f) / RATE


def meow(dur: float, f0: float, f1: float, f2: float, bright: float) -> np.ndarray:
    n = int(dur * RATE)
    contour = np.concatenate([
        np.linspace(f0, f1, int(n * 0.35)),
        np.linspace(f1, f2, n - int(n * 0.35)),
    ])
    ph = hz(contour)
    x = np.zeros(n)
    for k, amp in enumerate((1.0, 0.55 * bright, 0.3 * bright ** 2, 0.16 * bright ** 3), start=1):
        x += amp * np.sin(k * ph)
    # a nasal formant: a gentle boost around 1.1 kHz by adding a detuned partial
    x += 0.25 * np.sin(ph * 4.2) * np.exp(-((np.arange(n) / n) - 0.45) ** 2 / 0.02)
    x *= env(n, 0.035, dur * 0.45)
    return x


def purr(dur: float) -> np.ndarray:
    """A purr that a tablet speaker can actually reproduce.

    The first version sat at 72/144 Hz - physically correct for a cat, but a tiny
    speaker rolls off hard below ~300 Hz, so it was inaudible on the device (the
    user heard nothing when stroking the cat). The throat flutter stays at 26 Hz
    (that is amplitude modulation, not pitch), while the carrier moved to 340/680
    Hz with a breath of filtered noise on top."""
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    pulse = 0.45 + 0.55 * np.sin(2 * np.pi * 26 * t)          # the throat flutter
    tone = np.sin(2 * np.pi * 340 * t) + 0.55 * np.sin(2 * np.pi * 680 * t) \
           + 0.25 * np.sin(2 * np.pi * 1020 * t)
    noise = np.random.default_rng(3).normal(0, 1, n)
    noise = np.convolve(noise, np.ones(24) / 24, mode="same") * 0.6
    x = (tone * 0.5 + noise) * pulse
    edge = int(0.06 * RATE)
    x[:edge] *= np.linspace(0, 1, edge)
    x[-edge:] *= np.linspace(1, 0, edge)
    return x


def chirp(dur: float) -> np.ndarray:
    n = int(dur * RATE)
    ph = hz(np.linspace(700, 1500, n))
    x = np.sin(ph) + 0.4 * np.sin(2 * ph)
    return x * env(n, 0.008, dur * 0.55)


def hiss(dur: float) -> np.ndarray:
    n = int(dur * RATE)
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, n)
    # crude band limit: two moving averages as a difference
    a = np.convolve(x, np.ones(5) / 5, mode="same")
    b = np.convolve(x, np.ones(40) / 40, mode="same")
    x = a - b
    return x * env(n, 0.01, dur * 0.7)


def write(path: Path, x: np.ndarray) -> None:
    x = np.asarray(x, dtype=np.float64)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.72
    pcm = (x * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    clips = {
        "cat-meow_short": meow(0.42, 520, 820, 430, 1.0),
        "cat-meow_short_v2": meow(0.36, 560, 760, 470, 0.85),
        "cat-meow_long": meow(0.85, 430, 640, 380, 0.7),
        "cat-purr": purr(1.6),
        "cat-chirp": chirp(0.16),
        "cat-chirp_v2": chirp(0.22),
        "cat-hiss": hiss(0.5),
    }
    for name, data in clips.items():
        write(a.out / f"{name}.wav", data)
        print(f"{name}.wav  {len(data) / RATE:.2f}s")
    print(f"wrote {len(clips)} clips to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

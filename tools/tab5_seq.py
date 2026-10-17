"""Send several console commands through ONE serial session and capture the replies.

Opening COM9 resets the P4 (DTR/RTS), so a sequence of `tab5_console.py` calls
loses commands to the reboot in between. This opens the port once, waits for the
cat's boot line, then writes each command and reads for a while - which is what
an interaction-evidence run needs.

    python tools/tab5_seq.py COM9 "status" "food" "play" "pet" "clean" "status" --settle 2
"""
from __future__ import annotations

import argparse
import sys
import time

import serial


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("commands", nargs="+")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--wait-for", default="cat is on screen")
    ap.add_argument("--boot-wait", type=float, default=25.0)
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--read-first", type=float, default=6.0)
    a = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ser = serial.Serial(a.port, a.baud, timeout=0.2)
    ser.dtr = False
    ser.rts = False

    deadline = time.time() + a.boot_wait
    seen = False
    boot = []
    while time.time() < deadline:
        line = ser.readline()
        if not line:
            continue
        text = line.decode("utf-8", "replace").rstrip()
        boot.append(text)
        if a.wait_for in text:
            seen = True
            break
    if not seen:
        print(f"warn: never saw {a.wait_for!r}; sending anyway", file=sys.stderr)

    for cmd in a.commands:
        ser.write((cmd + "\r\n").encode())
        ser.flush()
        t0 = time.time()
        out = []
        while time.time() - t0 < a.settle:
            line = ser.readline()
            if line:
                out.append(line.decode("utf-8", "replace").rstrip())
        print(f"===== {cmd} =====")
        for l in out:
            if l.strip():
                print(l)
    ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The room the cat lives in (REQ-0001-009).

A small top-down room. Everything is drawn from primitives - no tile assets are
needed - so the world is described in code and can be unit-tested. Positions are
in room pixels; the cat is a 32x32 sprite.

Zones are named after what they afford, because that is also how the state line
talks about the world (`food near 3`, `litter_box mid 9`, ...).
"""
from __future__ import annotations

from dataclasses import dataclass, field

W, H = 320, 180                 # room size in pixels and the render size
WALL_H = 40                     # the top band is the back wall
FLOOR = (206, 178, 140)
FLOOR_ALT = (196, 168, 130)
WALL = (120, 104, 128)
WALL_DARK = (96, 82, 104)
WINDOW = (150, 196, 224)
WINDOW_FRAME = (238, 236, 228)
BOWL = (206, 92, 84)
LITTER = (168, 158, 140)
TREE = (140, 108, 74)
TOY = (232, 196, 96)

# Where things are, and the clock direction the state line reports for them.
ANCHORS = {
    "food": (54, 128),
    "water": (104, 152),        # the second bowl; the firmware's thirst reflex uses it
    "litter_box": (286, 146),
    "toy": (196, 62),
    "window": (160, 26),
    "owner": (60, 74),          # the couch the human sits on
    "tree": (250, 60),          # a target, not a state field
    "bed": (86, 44),            # a target, not a state field
}
# A cat at (x, y) "sees" an anchor as near/mid/far by straight-line distance.
NEAR_PX, MID_PX = 70.0, 150.0


def bucket(x: float, y: float, ax: float, ay: float) -> str:
    d = ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    return "near" if d <= NEAR_PX else "mid" if d <= MID_PX else "far"


def clock_dir(x: float, y: float, ax: float, ay: float) -> int:
    """1..12, 12 = straight up (screen coordinates, y grows downward)."""
    import math

    ang = math.degrees(math.atan2(ax - x, -(ay - y)))     # 0 = up, clockwise
    return int((ang + 360.0) % 360.0 // 30) + 1


@dataclass
class Cat:
    x: float = 160.0
    y: float = 130.0
    heading: float = 0.0            # degrees, 0 = facing up
    moving: bool = False
    asleep: bool = False
    frame: int = 0
    drives: dict = field(default_factory=lambda: {
        "hunger": 5, "energy": 7, "bored": 4, "clingy": 6, "litter": 2,
        "curiosity": 6, "bold": 5, "lazy": 4, "scruff": 2,
    })
    stage: str = "adult"
    last: str = "explore"
    goal: str = "explore"

    def facing(self) -> str:
        """Which sprite row to use: side-right, side-left, front or back."""
        h = self.heading % 360
        if 45 <= h < 135:
            return "right"
        if 135 <= h < 225:
            return "down"
        if 225 <= h < 315:
            return "left"
        return "up"

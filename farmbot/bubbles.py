"""The pale speech bubbles over home-village buildings, and what's in them.

Full collectors (gold, elixir, dark elixir) and the ice cube show their
loot in the same pale cream bubble; so do things that aren't loot: the boat
(to the Builder Base) and the capital airship's crossed swords (raids left).
The bubble is found by its frame's colour and shape, the same for every
player, and is only called loot when the icon inside is one of the known
loot colours. Anything else is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# The frame: a pale, slightly yellow cream (H ~30, S 30-60, V ~200-215 on MuMu and LDPlayer).
FRAME_LOW, FRAME_HIGH = (18, 15, 165), (42, 80, 240)
# The lit top of the frame (its arch: the bottom is in shade), in px at the
# village's usual zoom: about 30 x 27.
SIZE = (22, 50)
FRAME_SHARE = (0.15, 0.6)  # of the arch's box that is frame colour (the icon fills the rest)


@dataclass(frozen=True)
class Bubble:
    x: int  # the middle of the bubble (tapping it collects)
    y: int
    w: int
    h: int
    kind: str | None  # "gold", "elixir", "dark", "ice", or None (not loot)


def _icon_kind(hsv: np.ndarray) -> str | None:
    """What the icon inside a bubble (its middle, as HSV) is."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    shares = {
        "gold": ((h >= 15) & (h <= 35) & (s > 150) & (v > 170)).mean(),
        "elixir": ((h >= 140) & (h <= 170) & (s > 110) & (v > 120)).mean(),
        "dark": ((v < 110) & (s > 40) & ((h >= 110) & (h <= 170))).mean(),
        "ice": ((h >= 80) & (h <= 100) & (s > 50) & (s < 170) & (v > 190)).mean(),
    }
    (kind, share), (_, second) = sorted(shares.items(), key=lambda kv: -kv[1])[:2]
    # A loot icon is all one colour: a purple hexagon in a gold ring (not loot) is two.
    return kind if share >= ICON_SHARE and second < OTHER_SHARE else None


ICON_SHARE = 0.4  # of the bubble's middle that is the loot's colour (0.45 the palest elixir seen)
OTHER_SHARE = 0.1  # of it, at most, in another loot's colour


def find(screen: np.ndarray) -> list[Bubble]:
    """Every pale bubble on ``screen``, with what it holds (``kind`` None:
    not loot), top to bottom."""
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    frame = cv2.inRange(hsv, FRAME_LOW, FRAME_HIGH)
    # Close the frame's ring so each bubble is one blob, icon and all.
    blobs = cv2.morphologyEx(frame, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(blobs)
    found = []
    for i in range(1, count):
        x, y, w, h, _ = stats[i]
        if not (SIZE[0] <= w <= SIZE[1] and SIZE[0] <= h <= SIZE[1] and 0.8 <= w / h <= 1.6):
            continue
        share = float((frame[y:y + h, x:x + w] > 0).mean())
        if not FRAME_SHARE[0] <= share <= FRAME_SHARE[1]:
            continue
        middle = hsv[y + h // 3:y + h, x + w // 4:x + 3 * w // 4]  # the icon: under the arch's top
        found.append(Bubble(int(x + w // 2), int(y + 2 * h // 3), int(w), int(h), _icon_kind(middle)))
    return sorted(found, key=lambda b: (b.y, b.x))

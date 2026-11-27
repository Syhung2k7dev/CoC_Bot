"""Enemy buildings on a battle's base, from pictures the user taught.

Buildings change with every level and skin: each is a folder of pictures
(``buildings/air_defense/<level>.png``), cut in the Pictures tool from a
base kept in ``screens/bases`` (every war and ranked battle keeps its base
there). The Air Defense's ship with the bot (10, each finding some the
others miss on 267 kept bases); a user adds more, or others, the same way.
With no picture of a building, it's simply never found, and the attack
plays as it would without it.
"""

from __future__ import annotations

import logging

import numpy as np

from farmbot.geometry import Point

log = logging.getLogger(__name__)

LIKENESS = 0.8  # a building's picture against the base: lower, and other buildings pass for it
# An Air Defense's launcher turns, so no picture fits it closely: 10 pictures
# at different turns, at 0.65, find more of them than 40 did at 0.7, with no
# other building passing (250 kept bases); at 0.6 wall corners pass.
AIR_DEFENSE_LIKENESS = 0.65
APART = 0.6  # matches nearer than this share of the picture's size are the same building


def find(vision, screen: np.ndarray, name: str, threshold: float = LIKENESS) -> list[Point]:
    """Where the building ``name`` (a picture folder) stands on ``screen``,
    one point per building, best match first. [] if none, or no picture."""
    if screen is None or not vision.library.has(name):
        return []
    found: list[tuple[float, Point, int]] = []
    for match in sorted(vision.find_all(screen, name, threshold), key=lambda m: -m.score):
        reach = APART * max(match.w, match.h)
        if all(abs(match.x - x) > reach or abs(match.y - y) > reach for _, (x, y), _ in found):
            found.append((match.score, (match.x, match.y), max(match.w, match.h)))
    if found:
        log.info("Found %d %s: %s", len(found), name.split("/")[-1].replace("_", " "),
                 ", ".join(f"{p}" for _, p, _ in found))
    return [p for _, p, _ in found]

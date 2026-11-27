"""The home village's Star Bonus: the day's five stars, shown in a strip
above the Battle button.

Each star won in a home battle lights one; with all five the game opens
"Star Bonus received!" over the village (its Claim pressed by
``clear_popups``, then its chest opened like an event's) and its loot goes
to the Clan Castle's treasury (emptied by ``village.collect_treasury``).
Once it's received, the Battle button shows a green check until the next
day's bonus starts (the strip, grey again, then counts nothing); on older
game versions the strip went instead.

The strip is found from the Battle button (it sits right above it, whatever
the scenery), its stars by their shape: a star picture of each look the game
has had, earned or not, so a new background or a restyled strip still
matches one. Whether a star is earned is told by its colour, not by which
picture matched: an earned star is white, the rest grey, brown or olive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from farmbot.game import Game, T
from farmbot.geometry import Rect

log = logging.getLogger(__name__)

# Where the stars may be, from the Battle button's centre (bot px): left,
# top, width, height. They sit about 130 px above it, about 50 px to each side.
AREA = (-100, -185, 200, 100)
BUTTON = (-70, -110, 140, 110)  # the Battle button's picture, above its word (the done check is on it)
ROW = 10  # px: stars this close in height are on the strip's one row
SAME_STAR = 10  # px: matches this close are the same star
EARNED_LIGHT = 200  # an earned star's middle: this bright (HSV value)...
EARNED_BRIGHTER = 1.6  # ...or this many times the darkest star's (the screen dimmed by a window opening)...
EARNED_GREY = 40  # ...and this colourless (HSV saturation, 0-255)
MIDDLE = 3  # px around a star's centre read for its colour
STARS = 5  # the strip's stars: fewer seen is a strip half covered (by a window, say): not read


@dataclass(frozen=True)
class Stars:
    earned: int
    total: int

    @property
    def done(self) -> bool:
        return self.earned >= self.total


def _middle(screen: np.ndarray, x: int, y: int) -> tuple[float, float]:
    """A star's middle: its saturation and brightness (HSV, 0-255)."""
    patch = screen[max(y - MIDDLE, 0):y + MIDDLE + 1, max(x - MIDDLE, 0):x + MIDDLE + 1]
    if patch.size == 0:
        return 255.0, 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0)
    return float(hsv[1]), float(hsv[2])


def read(game: Game) -> Stars | None:
    """The Star Bonus strip's stars on the home village, or None when no
    strip shows (the day's bonus already received, or the Battle button
    not in sight)."""
    if not game.has(T.STAR_BONUS):
        return None
    battle = game.find(T.BATTLE)
    if battle is None:
        return None
    w, h = game.size
    if game.has(T.STAR_BONUS_DONE):
        left, top = max(battle.x + BUTTON[0], 0), max(battle.y + BUTTON[1], 0)
        if game.find(T.STAR_BONUS_DONE, region=Rect(left, top, BUTTON[2], BUTTON[3])) is not None:
            return Stars(STARS, STARS)  # the day's bonus received
    left, top = max(battle.x + AREA[0], 0), max(battle.y + AREA[1], 0)
    area = Rect(left, top, min(AREA[2], w - left), min(AREA[3], h - top))
    found = sorted(game.find_all(T.STAR_BONUS, region=area), key=lambda m: -m.score)
    stars = []
    for m in found:
        if all(abs(m.x - s.x) > SAME_STAR or abs(m.y - s.y) > SAME_STAR for s in stars):
            stars.append(m)
    if not stars:
        return None
    # The strip is one row: the row most stars are on (anything else is scenery).
    row = max((s.y for s in stars), key=lambda y: sum(abs(s.y - y) <= ROW for s in stars))
    stars = [s for s in stars if abs(s.y - row) <= ROW]
    if len(stars) != STARS:
        return None
    screen = game._current()
    middles = [_middle(screen, s.x, s.y) for s in stars]
    darkest = min(v for _, v in middles)
    earned = sum(1 for sat, v in middles if sat <= EARNED_GREY and (v >= EARNED_LIGHT or v >= EARNED_BRIGHTER * darkest))
    return Stars(earned, len(stars))


def wanted(game: Game) -> Stars | None:
    """The strip's stars when the day's bonus still has some to earn, else None."""
    stars = read(game)
    return stars if stars is not None and not stars.done else None

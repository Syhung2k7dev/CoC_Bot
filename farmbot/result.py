"""A battle's stars and Total damage, off its result screen.

The three stars sit over the "Victory"/"Defeat" ribbon: an earned one is
bright silver, one not earned a dark see-through shape. The middle star
carries "Total damage:" and the percentage in green. Both count up as the
screen opens, so a reading is taken once two in a row agree.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from farmbot import text
from farmbot.geometry import STANDARD_WIDTH, Rect

# On a screen STANDARD_WIDTH (860) wide: a spot on each star's body (left,
# the middle one's top point clear of its text, right).
STARS = ((325, 140), (430, 64), (535, 140))
STAR_HALF = 5
EARNED, UNEARNED = 200, 120  # a star's brightness: earned above, not earned below; between: no stars shown
DAMAGE = (390, 110, 475, 140)  # x0, y0, x1, y1 of the green "88%"
GREEN = ((35, 80, 120), (85, 255, 255))


@dataclass(frozen=True)
class Result:
    stars: int
    damage: int | None  # % (None: not read)


def stars(screen: np.ndarray) -> int | None:
    """Stars earned, or None if the three stars aren't plainly there."""
    s = screen.shape[1] / STANDARD_WIDTH
    value = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)[..., 2]
    count = 0
    for x, y in STARS:
        x, y, h = round(x * s), round(y * s), max(2, round(STAR_HALF * s))
        level = float(value[y - h:y + h, x - h:x + h].mean())
        if level >= EARNED:
            count += 1
        elif level > UNEARNED:
            return None
    return count


def split(mask: np.ndarray) -> list[np.ndarray]:
    """``mask`` as one digit, or as two where it is wider than tall: two
    digits touching ("71"), cut at the thinnest column of its middle half."""
    height, width = mask.shape
    if width <= height:
        return [mask]
    columns = (mask > 0).sum(axis=0)
    cut = width // 4 + int(np.argmin(columns[width // 4:width - width // 4]))
    halves = []
    for half in (mask[:, :cut], mask[:, cut:]):
        filled = np.flatnonzero((half > 0).any(axis=0))
        if filled.size:
            halves.append(half[:, filled[0]:filled[-1] + 1])
    return halves


def damage(screen: np.ndarray, font: text.Font) -> int | None:
    """The Total damage %, or None if it can't be read."""
    s = screen.shape[1] / STANDARD_WIDTH
    x0, y0, x1, y1 = (round(v * s) for v in DAMAGE)
    hsv = cv2.cvtColor(screen[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, *GREEN)
    white = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    white[green > 0] = 255  # the font knows white digits
    found = sorted(text.pieces(white, Rect(0, 0, x1 - x0, y1 - y0)), key=lambda p: p[0])
    if len(found) < 2:
        return None
    digits = ""
    masks = [half for _, mask in found[:-1] for half in split(mask)]  # the last is the % sign (it passes for an 8)
    for mask in masks:
        char, score = font.classify(mask)
        if not char.isdigit() or score < 0.4:
            return None
        digits += char
    return int(digits) if digits and int(digits) <= 100 else None


def read(screen: np.ndarray, font: text.Font | None) -> Result | None:
    """The stars and damage on a result ``screen``, or None (no stars there)."""
    earned = stars(screen)
    if earned is None:
        return None
    return Result(earned, damage(screen, font) if font is not None else None)


# During a battle, bottom right over the troop bar: "Overall Damage" and,
# under it, the stars so far and the damage ("25%"): white digits with a dark
# outline, right-aligned. On a screen STANDARD_WIDTH (860) wide, 672 high:
# the box this looks in, from the right and from the bottom (a taller screen
# keeps the bar and the box at its bottom).
OVERALL_BOX = (110, 146, 108, 34)  # x from the right, y from the bottom, width, height (under the label)
OVERALL_HEIGHT = (11, 24)  # px a digit is tall (at 860 wide): shorter or taller is something else
OVERALL_SURE = 0.6  # each digit's least match
# The words "Overall Damage" over it: small white letters, many in a row (the
# scouting screen's Next button has its cost there instead, "50", which read
# as 5%). x from the right, y from the bottom, width, height; letters at least.
OVERALL_LABEL = (110, 166, 108, 22)
OVERALL_LETTERS = 7


def overall_damage(screen: np.ndarray, font: text.Font) -> int | None:
    """The Overall Damage % during a battle, or None if it can't be read.
    The number is the last run of digits left of the "%" sign, the right
    end of the box."""
    s = screen.shape[1] / STANDARD_WIDTH
    h, w = screen.shape[:2]
    dx, dy, bw, bh = OVERALL_BOX
    region = Rect(w - round(dx * s), h - round(dy * s), round(bw * s), round(bh * s))
    lx, ly, lw, lh = OVERALL_LABEL
    label = Rect(w - round(lx * s), h - round(ly * s), round(lw * s), round(lh * s))
    if len(text.pieces(screen, label)) < OVERALL_LETTERS:
        return None  # no "Overall Damage" over it: not a battle's damage
    low, high = OVERALL_HEIGHT[0] * s, OVERALL_HEIGHT[1] * s
    found = [(x, m) for x, m in text.pieces(screen, region) if low <= m.shape[0] <= high and m.shape[1] >= 3 * s]
    if len(found) < 2:
        return None
    found.sort(key=lambda p: p[0])
    masks = [half for _, mask in found[:-1] for half in split(mask)]  # the last is the % sign
    digits = ""
    for mask in masks[-3:]:
        char, score = font.classify(mask)
        if not char.isdigit() or score < OVERALL_SURE:
            return None
        digits += char
    value = int(digits) if digits else None
    return value if value is not None and value <= 100 else None

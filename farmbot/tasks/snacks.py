"""Snacks and potions waiting in the box left of Build (November 2026).

A red number on the box counts what's waiting. A tap on the box opens a
strip over the village: first what's already working (blue: "2x Loot 1/2",
"Battles Left: 17/18", "Active"), then what's waiting, each with a ribbon
over it: green "Use" (it can be used now) or grey "Full!" (it can't, say a
potion while what it fills is full). A tap on a green one opens its window
("Mighty Morsel": heroes at max for 3 battles), with a big green Use; after
it the strip goes back to its start. A second tap on the box closes the
strip. A snack not used works by itself when it expires.

Only the green "Use" ribbons are tapped (``buttons/snack_use``), and only the
window's own Use button (``buttons/snack_use_window``) is pressed: the blue
and grey ones, and anything else that opens, are left alone. Looked for in
the strip's band right above the box, wherever the box is.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from farmbot.game import Game, T
from farmbot.geometry import Rect

log = logging.getLogger(__name__)

# The strip, in box heights from the box's middle: from 5.3 above (over its
# ribbons) to 1.6 above (under its cards).
BAND_TOP, BAND_BOTTOM = 5.3, 1.6
CARD_BELOW_RIBBON = 2.3  # the item under its ribbon, in ribbon heights (a tap there opens its window)
SWIPES = 6  # along the strip at most, looking for a green ribbon
# Swipes start on a coloured card (blue, working, or green), never a grey
# "Full!" one: a press there looks like a tap on it. Told by the cards'
# middle saturation, in box heights above the box's middle.
CARDS_TOP, CARDS_BOTTOM = 4.6, 2.1
COLOURED = 100  # median saturation of a blue or green card; a grey one about 0-40
SWIPE_RUN = 0.9  # box widths of colour, side by side, to start on
SWIPE_LENGTH = 7.0  # box widths, to the left
SETTLE = 4  # looks at most for the strip to stop sliding after a swipe
SAME_STRIP = 3.0  # mean grey difference under which a swipe moved nothing: the strip's end
MOST_USES = 10  # in one round, at most
WINDOW_WAIT = 3.0  # s for an item's window to open
# The badge: red, on the box's top right corner.
BADGE_RED = 120  # pixels of strong red at least
SAME_DIGITS = 0.75  # overlap of two badges' white digits, at least, for the same number
STRIP_BRIGHT = 0.2  # share of the band bright with the strip open


def _box(game: Game):
    if not game.has(T.SNACK_BOX):
        return None
    return game.find(T.SNACK_BOX, region=_lower_right(game))


def _lower_right(game: Game) -> Rect:
    w, h = game.size
    return Rect(w // 2, h * 3 // 4, w - w // 2, h - h * 3 // 4)


def _band(game: Game, box) -> Rect:
    top = max(round(box.y - BAND_TOP * box.h), 0)
    return Rect(0, top, min(box.x + box.w, game.size[0]), round(box.y - BAND_BOTTOM * box.h) - top)


def badge(game: Game, box) -> np.ndarray | None:
    """The red number on the box, or None without one: the badge alone,
    red and the white digits on it (the village behind it moves, and
    isn't part of it), to tell a new count from the last."""
    x0, y0 = box.x, max(round(box.y - 1.3 * box.h), 0)
    area = game.screen[y0:box.y, x0:box.x + box.w]
    if area.size == 0:
        return None
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    red = ((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 172)) & (hsv[:, :, 1] >= 150) & (hsv[:, :, 2] >= 150)
    if int(red.sum()) < BADGE_RED:
        return None
    ys, xs = np.nonzero(red)
    inside = hsv[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    white = (inside[:, :, 1] <= 70) & (inside[:, :, 2] >= 200)
    return np.where(white, 255, np.where(red[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 128, 0)).astype(np.uint8)


def same_badge(a: np.ndarray | None, b: np.ndarray | None) -> bool:
    """Whether two badges show the same number."""
    if a is None or b is None:
        return a is None and b is None
    if abs(a.shape[0] - b.shape[0]) > 3 or abs(a.shape[1] - b.shape[1]) > 3:
        return False  # (more digits: a wider badge)
    b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
    wa, wb = a == 255, b == 255
    both = int((wa | wb).sum())
    return both == 0 or int((wa & wb).sum()) / both >= SAME_DIGITS


def green_ribbons(game: Game, band: Rect) -> list:
    """The green "Use" ribbons showing in the strip, left to right."""
    return sorted(game.find_all(T.SNACK_USE, region=band), key=lambda m: m.x)


def _strip(game: Game, band: Rect) -> np.ndarray:
    return cv2.cvtColor(game.screen[band.y:band.y + band.h, band.x:band.x + band.w], cv2.COLOR_BGR2GRAY)


def _find_green(game: Game, box, band: Rect):
    """Swipe along the strip until a green ribbon shows; None at its end."""
    for swipe in range(SWIPES + 1):
        found = green_ribbons(game, band)
        if found:
            return found[0]
        if swipe == SWIPES:
            break
        before = _strip(game, band)
        start = _swipe_start(game, box)
        if start is None:
            log.info("Snacks: no coloured card to swipe the strip from; leaving it")
            break
        x, y = start
        game.swipe(x, y, max(x - round(SWIPE_LENGTH * box.w), 0), y, 500)
        game.wait(1.0)
        game.refresh()
        if _moved(game, band, before) < SAME_STRIP:
            break  # the strip's end
        _settle(game, band)
    return None


def _swipe_start(game: Game, box) -> tuple[int, int] | None:
    """The middle of the rightmost coloured card showing (not a grey one)."""
    top = max(round(box.y - CARDS_TOP * box.h), 0)
    bottom = round(box.y - CARDS_BOTTOM * box.h)
    right = min(round(box.x + 0.4 * box.w), game.size[0])  # short of the strip's arrow
    if bottom <= top or right <= 0:
        return None
    sat = cv2.cvtColor(game.screen[top:bottom, :right], cv2.COLOR_BGR2HSV)[:, :, 1]
    coloured = np.median(sat, axis=0) >= COLOURED
    need = max(round(SWIPE_RUN * box.w), 1)
    end = right
    while end > 0:
        while end > 0 and not coloured[end - 1]:
            end -= 1
        start = end
        while start > 0 and coloured[start - 1]:
            start -= 1
        if end - start >= need:
            return (start + end) // 2, (top + bottom) // 2
        end = start
    return None


def _moved(game: Game, band: Rect, before: np.ndarray) -> float:
    return float(np.abs(_strip(game, band).astype(np.int16) - before.astype(np.int16)).mean())


def _settle(game: Game, band: Rect) -> None:
    """Wait for the strip to stop sliding, so a ribbon found is where it stays."""
    for _ in range(SETTLE):
        before = _strip(game, band)
        game.wait(0.4)
        game.refresh()
        if _moved(game, band, before) < SAME_STRIP:
            return


def use_snacks(game: Game) -> int:
    """Open the box when it shows a number and use every green ("Use")
    item, then close it. Returns how many were used; -1 when the box shows
    no number (nothing to look at)."""
    game.refresh()
    box = _box(game)
    if box is None or badge(game, box) is None:
        return -1
    used = 0
    game.tap(box.x, box.y)  # the strip opens
    game.wait(1.5)
    game.refresh()
    band = _band(game, box)
    try:
        while used < MOST_USES:
            ribbon = _find_green(game, box, band)
            if ribbon is None:
                break
            game.tap(ribbon.x, round(ribbon.y + CARD_BELOW_RIBBON * ribbon.h))
            if not game.click_when_visible(T.SNACK_USE_WINDOW, timeout=WINDOW_WAIT):
                log.info("Snacks: tapped a green one but its Use window didn't show; leaving them")
                game.refresh()
                if game.has(T.CLOSE):
                    game.click(T.CLOSE)
                    game.wait(0.8)
                return used
            used += 1
            game.wait(1.5)  # the strip goes back to its start
            game.refresh()
    finally:
        game.refresh()
        again = _box(game)
        if again is not None and _strip_open(game, again):  # a second tap on the box closes it
            game.tap(again.x, again.y)
            game.wait(1.0)
    if used:
        log.info("Snacks: used %d", used)
    return used


def _strip_open(game: Game, box) -> bool:
    """Whether the strip shows over the village: its band is framed by a
    dark border light inside (the items' cards), unlike the village."""
    band = _band(game, box)
    area = game.screen[band.y:band.y + band.h, band.x:band.x + band.w]
    if area.size == 0:
        return False
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    # The cards are bright: about a third of the band (0.29-0.40), the village under it an eighth.
    return float((hsv[:, :, 2] >= 200).mean()) > STRIP_BRIGHT

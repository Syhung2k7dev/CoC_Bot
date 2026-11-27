"""Hero equipment upgrades: the Build list's Hero Equipment tab.

Equipment is upgraded at the Blacksmith with ores (Shiny, Glowy and
Starry), not with gold or elixir, and takes no builder: an upgrade is
done at once. So it's an upgrader of its own, beside the laboratory and
the builders, taking its turn in the upgrade order ("equipment").

The tab lists the equipment, those equipped first, each row with its
name and the ores its next level costs. A row's name is read (Windows'
OCR, as the buildings picked are: see row_names.py), the row tapped, and
its window ("Upgrade <name> to Level N?") paid with its green Confirm,
unless:

- a price on the Confirm is red: not enough of that ore (the row is
  passed over for a while),
- the window shows a gem (never paid),
- there's no green Confirm (the equipment is at its highest level for
  now: the Blacksmith's level caps it).

That it went through is checked by the window's title: its level goes up
(or the window closes). The tab won't open before the Blacksmith (Town
Hall 8); the village data says so first (``townhall.locked``).
"""

from __future__ import annotations

import logging
import re

import cv2
import numpy as np

from farmbot.game import Game, T
from farmbot.tasks.build_list import (HOME, LIST_PAGE, LIST_SWIPE_FROM_BOTTOM, LIST_SWIPE_X, SLOW_SWIPE_MS,
                                      BuildList, asks_for_gems, close_windows, green_confirm, list_ends_here,
                                      list_still, open_tab, tab_open, to_top)

log = logging.getLogger(__name__)

MAX_PER_ROUND = 3  # equipment upgraded in one round at most (each is a tap or two, but loot comes first)
MAX_PAGES = 6  # the tab's pages looked through at most (about 40 pieces of equipment)
PASS_OVER_FOR = 3600.0  # s a piece that couldn't be paid for (or wouldn't go) is left alone
NOTHING_FOR = 1800.0  # s the tab isn't opened again after a round that found nothing to upgrade
WINDOW_TIMEOUT = 3.0
# A Confirm's price, red where an ore is short: red pixels under its label.
SHORT_AREA = (-170, 15, 170, 60)  # x from, y from, x to, y to: from the Confirm label's middle
SHORT_RED = 40  # red pixels at least
RED_HUE = ((0, 8), (170, 179))
RED_MIN = (150, 150)  # saturation, value
LEVEL = re.compile(r"level\s*(\d+)", re.IGNORECASE)
TITLE_NAME = re.compile(r"upgrade\s*(.*?)\s*to\s*leve", re.IGNORECASE)  # "Upgrade <name> to Level N?"
TITLE_ABOVE, TITLE_BELOW = 30, 30  # the window's title: this far above and below its X's middle
TITLE_LEFT = 150  # from this x to its X


def _plain(text: str) -> str:
    from farmbot.tasks.row_names import _plain as plain

    return plain(text)


def due(game: Game) -> bool:
    """Whether the tab is worth opening this round (not right after one
    that found nothing to upgrade)."""
    return game.clock() >= getattr(game, "equipment_next", 0.0)


def short_of_ore(screen: np.ndarray, label_x: int, label_y: int) -> bool:
    """Whether the Confirm whose label is at (``label_x``, ``label_y``)
    shows a price in red: an ore the upgrade needs more of."""
    x0, y0, x1, y1 = SHORT_AREA
    h, w = screen.shape[:2]
    area = screen[max(label_y + y0, 0):min(label_y + y1, h), max(label_x + x0, 0):min(label_x + x1, w)]
    if area.size == 0:
        return False
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    red = np.zeros(hsv.shape[:2], bool)
    for lo, hi in RED_HUE:
        red |= (hsv[..., 0] >= lo) & (hsv[..., 0] <= hi)
    red &= (hsv[..., 1] >= RED_MIN[0]) & (hsv[..., 2] >= RED_MIN[1])
    return int(red.sum()) >= SHORT_RED


def level_in(title: str | None) -> int | None:
    """The level an upgrade window's title offers ("Upgrade Rage Vial to Level 10?" -> 10)."""
    m = LEVEL.search(title or "")
    return int(m.group(1)) if m else None


def asks_to_upgrade(title: str) -> bool:
    """Whether a window's title is the upgrade question ("Upgrade Rage Vial to
    Level 10?"), not the piece's own window ("Rage Vial Level 10")."""
    return TITLE_NAME.search(title) is not None


def titled(name: str, title: str | None) -> bool:
    """Whether an upgrade window's title is ``name``'s (read as the list's
    names are: the OCR's slips allowed for)."""
    from farmbot.tasks import row_names

    if not title:
        return True  # (not read: the tapped row's taken on trust)
    m = TITLE_NAME.search(title)
    said = m.group(1) if m else title
    return row_names.building(said, "equipment") == name or _plain(name) in _plain(title)


def order(names: list[str], picks: tuple[str, ...] | None) -> list[str]:
    """The pieces to try, first to last: the picks in their order (those
    on show), or, with none picked, every one on show in the list's order
    (equipped first)."""
    if not picks:
        return list(dict.fromkeys(names))
    shown = set(names)
    return [p for p in picks if p in shown]


def upgrade_equipment(game: Game, picks: tuple[str, ...] | None = None, lst: BuildList = HOME,
                      most: int = MAX_PER_ROUND) -> int:
    """With the Build list open: upgrade equipment in the Hero Equipment
    tab, ``picks`` first to last (None: any, in the list's order), at most
    ``most``. Returns how many were upgraded."""
    if not due(game):
        return 0
    open_tab(game, "equipment", lst)
    if tab_open(game, "equipment", lst) is False:
        log.info("Upgrades: the Hero Equipment tab didn't open (no Blacksmith yet?)")
        game.equipment_next = game.clock() + NOTHING_FOR
        return 0
    if picks:
        log.info("Upgrades: only this equipment, first to last: %s", ", ".join(picks))
    passed: dict[str, float] = getattr(game, "equipment_passed", {})
    game.equipment_passed = passed
    done = 0
    to_top(game)
    if picks:
        done = _picks_in_order(game, picks, lst, passed, most)
        if done is None:
            return 0  # (the OCR isn't working: said in the log)
    else:
        tried: set[str] = set()
        for _ in range(MAX_PAGES):
            lines = _names(game, lst)
            if lines is None:
                return done  # (the OCR isn't working: said in the log)
            here = {name: y for y, name in lines if name}
            for name in order(list(here), None):
                if done >= most:
                    break
                if name in tried or passed.get(name, 0.0) > game.clock():
                    continue
                tried.add(name)
                done += _try(game, name, here[name], lst, passed)
            if done >= most or list_ends_here(game) or not _scroll(game):
                break
    if not done:
        log.info("Upgrades: no equipment to upgrade with the ore there is%s",
                 " (of the pieces picked)" if picks else "")
        game.equipment_next = game.clock() + NOTHING_FOR
    return done


def pages_of(pages: list[list[str]], picks: tuple[str, ...]) -> list[tuple[str, int]]:
    """The picks on show, first to last, each with the page (0: the top)
    it was first seen on."""
    first: dict[str, int] = {}
    for i, names in enumerate(pages):
        for name in names:
            first.setdefault(name, i)
    return [(p, first[p]) for p in picks if p in first]


def _picks_in_order(game: Game, picks: tuple[str, ...], lst: BuildList, passed: dict[str, float],
                    most: int) -> int | None:
    """Picked equipment, strictly in the order picked across the whole
    list: every page is read first, then each pick is gone back to.
    ``None``: the names couldn't be read."""
    pages: list[list[str]] = []
    for _ in range(MAX_PAGES):
        lines = _names(game, lst)
        if lines is None:
            return None
        pages.append([name for _, name in lines if name])
        if all(any(p in names for names in pages) for p in picks) or list_ends_here(game) or not _scroll(game):
            break
    done, at = 0, len(pages) - 1
    for name, page in pages_of(pages, picks):
        if done >= most:
            break
        if passed.get(name, 0.0) > game.clock():
            continue
        if page != at:
            to_top(game)
            for _ in range(page):
                _scroll(game)
            at = page
        here = {n: y for y, n in (_names(game, lst) or []) if n}
        if name not in here:
            log.info("Upgrades: %s wasn't where it was seen in the list; leaving it this round", name)
            continue
        done += _try(game, name, here[name], lst, passed)
    return done


def _try(game: Game, name: str, y: int, lst: BuildList, passed: dict[str, float]) -> int:
    """Upgrade ``name`` (1 if it went); one that didn't is passed over a while."""
    if _upgrade(game, name, y, lst) == "upgraded":
        log.info("Upgraded equipment: %s", name)
        return 1
    passed[name] = game.clock() + PASS_OVER_FOR
    return 0


def _names(game: Game, lst: BuildList) -> list[tuple[int, str | None]] | None:
    from farmbot.tasks import row_names

    return row_names.read(game, lst, "equipment")


def _scroll(game: Game) -> bool:
    """One page down the list; False if it didn't move (the end)."""
    w, h = game.size
    x, y = w - LIST_SWIPE_X, h - LIST_SWIPE_FROM_BOTTOM
    before = game.refresh().copy()
    game.swipe(x, y, x, y - LIST_PAGE, duration_ms=SLOW_SWIPE_MS)
    game.wait(0.8)
    return not list_still(before, game.refresh())


def window_title(game: Game, list_y: int) -> str | None:
    """The text of an upgrade window's title (left of its X), or None if
    no window is open over the list."""
    from farmbot.redact import read_text

    xs = [m for m in game.find_all(T.CLOSE) if m.y > list_y + 40]
    if not xs:
        return None
    x = min(xs, key=lambda m: m.y)
    area = game.screen[max(x.y - TITLE_ABOVE, 0):x.y + TITLE_BELOW, TITLE_LEFT:max(x.x - x.w, TITLE_LEFT + 1)]
    lines = read_text(area, 1.5) if area.size else None
    return " ".join(t for _, t in lines) if lines else ""


def _upgrade(game: Game, name: str, y: int, lst: BuildList) -> str:
    """Tap the row named ``name`` (its name at height ``y``) and pay its
    window's green Confirm. "upgraded", or why not: "short" (not enough
    ore), "max" (no Confirm: as high as it goes for now), "gems", "failed"."""
    game.refresh()
    list_close = game.find(T.CLOSE)
    list_y = list_close.y if list_close else 0
    w, _ = game.size
    confirm, title = None, None
    for _ in range(2):  # a tap just after the tab opens can be missed: once more if nothing opened
        game.tap(w - 280, y)
        deadline = game.clock() + WINDOW_TIMEOUT
        while game.clock() < deadline:
            game.wait(0.5)
            game.refresh()
            confirm = green_confirm(game)
            if confirm is not None:
                break
        opened = any(m.y > list_y + 40 for m in game.find_all(T.CLOSE))
        if confirm is not None or opened:
            break
    if confirm is None:
        opened = any(m.y > list_y + 40 for m in game.find_all(T.CLOSE))
        log.info("Upgrades: %s: %s", name, "no Confirm (at its highest level for now)" if opened
                 else "its window didn't open")
        close_windows(game, list_y)
        return "max" if opened else "failed"
    title = window_title(game, list_y)
    if not titled(name, title):
        log.info("Upgrades: tapped %s but the window says %r: leaving it", name, title)
        close_windows(game, list_y)
        return "failed"
    if short_of_ore(game.screen, confirm.x, confirm.y):
        log.info("Upgrades: not enough ore for %s (%s)", name, title or "")
        close_windows(game, list_y)
        return "short"
    if asks_for_gems(game, confirm.y):
        log.warning("Upgrades: %s's upgrade asks for gems; leaving it alone", name)
        close_windows(game, list_y)
        return "gems"
    before = level_in(title)
    game.tap_match(confirm)
    game.wait(1.5)
    game.refresh()
    after_title = window_title(game, list_y)
    after = level_in(after_title)
    # gone (None), or the piece's own window now ("Invisibility Vial Level 13",
    # the upgrade's banner over it): its level as the OCR reads it ("Level B")
    # can't be relied on, the question being gone can
    went = (after_title is None or not asks_to_upgrade(after_title)
            or (before is not None and after is not None and after > before))
    if not went and before is not None and after == before and green_confirm(game) is None:
        went = True  # (now at its highest: the same title, without a Confirm)
    if not went:
        log.info("Upgrades: %s's upgrade didn't go through (%r)", name, after_title)
    close_windows(game, list_y)
    return "upgraded" if went else "failed"

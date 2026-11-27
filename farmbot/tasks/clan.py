"""Clan Castle requests and troop donations.

These screens differ between game versions, so every step goes through a
template you crop from your own screenshots (see templates/README.md).
Missing templates switch the feature off with a log message instead of
guessing where to tap.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from farmbot.config import ClanConfig
from farmbot.game import Game, T
from farmbot.vision import Rect

log = logging.getLogger(__name__)


def _missing(game: Game, names: tuple[str, ...]) -> list[str]:
    return [n for n in names if not game.has(n)]


def in_clan(game: Game, close: bool = True) -> bool | None:
    """Open the chat and look: the "Join A Clan" panel means not in a clan.
    ``None`` if the chat couldn't be opened. The chat is closed again unless
    ``close`` is False (the next clan step then uses it as it is)."""
    if _missing(game, (T.OPEN_CHAT, T.CLOSE_CHAT, T.NO_CLAN)):
        return None
    if not _open_chat(game):
        return None
    member = game.find(T.NO_CLAN) is None
    if close or not member:
        _close_chat(game)
    return member


# Where the Request button sits in the open chat, and its cooldown text
# ("10m") under the castle once a request is out (bot coordinates).
REQUEST_AREA = [380, 850, 120, 60]  # [x, y, w, h]
COOLDOWN_TEXT = [428, 880, 52, 26]
TIMER_FONT = "fonts/timer"  # the timer's digits, learned from the game (fonts/loot misreads 3 as 5)
WAIT_OUT = 75  # s: a cooldown this short is waited out in the chat, then the request sent
WAIT_LOOK = 5.0  # s between looks at the button while waiting it out


def _open_chat(game: Game) -> bool:
    game.refresh()
    if game.find(T.CLOSE_CHAT):
        return True  # already open
    if not game.click(T.OPEN_CHAT) or not game.wait_for(T.CLOSE_CHAT, timeout=4):
        return False
    game.wait(0.8)  # the panel slides in
    game.refresh()
    return True


def close_chat(game: Game) -> None:
    """Close the clan chat if it's open (after steps run with close=False)."""
    _close_chat(game)


def _close_chat(game: Game) -> None:
    game.refresh()
    if game.click(T.CLOSE_CHAT):
        game.wait(0.8)


def read_timer(game: Game) -> tuple[int, str] | None:
    """The timer on the Request button: its number and unit ("10m" is
    (10, "m"), "45s" is (45, "s")); ``None`` if there's none or it can't
    be read. The unit is told by its shape: lower case, so shorter than the
    digits; an "m" is wider than tall, an "s" isn't."""
    from farmbot import text

    try:
        font = game.vision.font(TIMER_FONT)
    except (FileNotFoundError, ValueError):
        font = game.vision.font(T.LOOT_FONT)
    found = text.pieces(game._current(), game.region(COOLDOWN_TEXT))
    if not found:
        return None
    masks = [mask for _, mask in found]
    if len(masks) < 2:
        return None
    *numbers, letter = masks  # the unit ends it
    h, w = letter.shape[:2]
    if h >= max(m.shape[0] for m in numbers):
        return None  # no unit after the number: not the timer
    digits = ""
    for mask in numbers:
        char, score = font.classify(mask)
        if score < 0.45 or not char.isdigit():
            return None
        digits += char
    if not int(digits):
        return None
    return int(digits), "m" if w > h else "s"


def request_cooldown(game: Game) -> float | None:
    """Seconds until the Request button is free again at most, read from
    the timer on it ("10m": 9 to 10 minutes; "45s"); ``None`` if it can't
    be read."""
    timer = read_timer(game)
    if timer is None:
        return None
    value, unit = timer
    return float(value) * 60 if unit == "m" else float(value)


def soonest(wait: float) -> float:
    """The least a cooldown read as ``wait`` s can be: the game rounds
    minutes up ("10m" right after a request, "1m" with a few seconds left)."""
    return max(wait - 60, 0.0) if wait >= 60 and wait % 60 == 0 else wait


def request_troops(game: Game, cfg: ClanConfig, close: bool = True) -> tuple[bool, float | None]:
    """Clan chat → Request (next to Challenge) → Send. Returns whether a
    request went out, and how many seconds until the next one can (from the
    button's cooldown timer; ``None`` if unknown). A Request button with a
    gem price is on cooldown and is never pressed. (With the Clan Castle
    emptied first, the request goes from the army window instead:
    ``request_from_army``.)"""
    missing = _missing(game, (T.OPEN_CHAT, T.CLOSE_CHAT, T.REQUEST, T.REQUEST_SEND))
    if missing:
        log.warning("Cannot request troops; missing pictures: %s", ", ".join(missing))
        return False, None
    if not _open_chat(game):
        log.info("Couldn't open the clan chat")
        return False, None
    if game.has(T.NO_CLAN) and game.find(T.NO_CLAN):
        log.info("Not in a clan: can't request troops")
        _close_chat(game)
        return False, None
    sent = _send_request(game)
    wait = None if sent else request_cooldown(game)
    if not sent and wait is not None and wait <= WAIT_OUT:
        # About to be free: wait for it here rather than a whole round more.
        log.info("The request is free in %d s at most: waiting for it", wait)
        deadline = game.clock() + wait + WAIT_LOOK
        while not sent and game.clock() < deadline:
            game.wait(WAIT_LOOK, exact=True)
            game.refresh()
            sent = _send_request(game)
        wait = None if sent else request_cooldown(game)
    if sent:
        # The new timer, once it reads the same twice (as it shows, the
        # "request sent" banner can make the first look wrong).
        last = None
        for _ in range(6):
            game.wait(0.6, exact=True)
            game.refresh()
            wait = request_cooldown(game)
            if wait is not None and wait == last:
                break
            last = wait
        log.info("The next request in %s", f"{wait / 60:.0f} min at most" if wait else "an unknown time")
    elif _request_free(game):
        log.info("The request didn't go out, though its button is free")
    else:
        log.info("Request is on cooldown%s", f" for {wait / 60:.0f} more min" if wait else "")
    if close:
        _close_chat(game)
    return sent, wait


def _request_free(game: Game) -> bool:
    game.refresh()
    return game.find(T.REQUEST, region=game.region(REQUEST_AREA)) is not None


# Emptying the Clan Castle: Battle → Edit Army → the bin on the castle's row
# → "Remove troops?" Okay. The bin is taken only on the castle's own row
# (another row's bin would remove the army or its spells). The same window
# has a request button of its own, by Add: emptying and requesting are one
# trip there, with no clan chat.
CASTLE_EMPTY_PICTURES = (T.BATTLE, T.EDIT_ARMY, T.CASTLE_ROW, T.CASTLE_TRASH, T.REMOVE_TROOPS, T.OKAY, T.CLOSE)
ROW_SLACK = 15  # px: the bin's middle this close to the castle row's, vertically
ARMY_WAIT = 5.0  # s for the army window to open
MENU_WAIT = 4.0  # s for the battle menu's Edit Army to show


def _open_army(game: Game) -> Rect | None:
    """Battle → Edit Army, from the village: the band of the army window's
    Clan Castle row once it shows (``None`` if it doesn't, everything closed
    again)."""
    from farmbot import screens

    # Edit Army shows as the menu opens, before its cards have slid in: tapped at once.
    game.refresh()
    if not (game.find(T.EDIT_ARMY) or game.click(T.BATTLE)) or not game.click_when_visible(T.EDIT_ARMY, MENU_WAIT):
        log.info("Clan Castle: the battle menu's Edit Army didn't show")
        screens.settle(game)
        return None
    row = game.wait_for(T.CASTLE_ROW, timeout=ARMY_WAIT)
    if row is None:
        log.info("Clan Castle: the army window didn't open")
        _close_army(game)
        return None
    game.wait(0.4)  # the window's cards settle
    game.refresh()
    row = game.find(T.CASTLE_ROW) or row
    return Rect(row.x, row.y - ROW_SLACK - row.h, game.size[0] - row.x, 2 * (ROW_SLACK + row.h))


def _bins(game: Game, band: Rect) -> list:
    middle = band.y + band.h // 2
    return [m for m in game.find_all(T.CASTLE_TRASH, region=band) if abs(m.y - middle) <= ROW_SLACK]


def _remove(game: Game, band: Rect) -> bool | None:
    """In the open army window: the castle row's bin, then "Remove troops?"
    Okay. True once removed, False if it held nothing, ``None`` if it
    couldn't be done."""
    bins = _bins(game, band)
    if not bins:
        log.info("Clan Castle: already empty")
        return False
    game.tap_match(max(bins, key=lambda m: m.x))
    if game.wait_for(T.REMOVE_TROOPS, timeout=3) is None:
        log.info("Clan Castle: the bin didn't ask to remove the troops")
        return None
    if not game.click_when_visible(T.OKAY, timeout=2):
        log.info("Clan Castle: no Okay under \"Remove troops?\"")
        return None
    game.wait(0.8)
    game.refresh()
    gone = game.find(T.REMOVE_TROOPS) is None and not _bins(game, band)
    log.info("Emptied the Clan Castle" if gone else "Clan Castle: its troops still show after Okay")
    return gone or None


def empty_castle(game: Game) -> bool | None:
    """Remove what the Clan Castle holds (troops, spells, siege machine),
    from the army window, and close it again. True once removed, False if
    it held nothing (its bin isn't there), ``None`` if it couldn't be done."""
    missing = _missing(game, CASTLE_EMPTY_PICTURES)
    if missing:
        log.warning("Cannot empty the Clan Castle; missing pictures: %s", ", ".join(missing))
        return None
    band = _open_army(game)
    if band is None:
        return None
    try:
        return _remove(game, band)
    finally:
        _close_army(game)


def request_from_army(game: Game, cfg: ClanConfig) -> bool | None:
    """Request from the army window (Battle, Edit Army), the Clan Castle
    emptied first with ``cfg.empty_castle``: one trip, no clan chat. Only
    while its request button is free (on cooldown it shows a gem price
    and isn't the button's picture): nothing is removed then, the troops
    would be lost with no request after. True once a request went out,
    False while it's on cooldown (its timer isn't read: too small there),
    ``None`` if it couldn't be done."""
    missing = _missing(game, (*CASTLE_EMPTY_PICTURES, T.CASTLE_REQUEST, T.REQUEST_SEND))
    if missing:
        log.warning("Cannot request troops from the army window; missing pictures: %s", ", ".join(missing))
        return None
    _close_chat(game)  # (left open by the clan check)
    band = _open_army(game)
    if band is None:
        return None
    try:
        if game.find(T.CASTLE_REQUEST) is None:
            log.info("Request is on cooldown (the army window's request button isn't free)")
            return False
        if cfg.empty_castle:
            _remove(game, band)
            game.refresh()
        if not game.click(T.CASTLE_REQUEST):
            log.info("The army window's request button went")
            return None
        if not game.click_when_visible(T.REQUEST_SEND, timeout=4):
            log.info("The request window didn't show its Send button")
            return None
        log.info("Requested Clan Castle troops (from the army window)")
        game.wait_for(T.CASTLE_ROW, timeout=3, interval=0.3)  # (the request window closing)
        return True
    finally:
        _close_army(game)


def _close_army(game: Game) -> None:
    """The army window's X, then the battle menu under it (Back closes it,
    as ``screens.settle`` does): each as soon as it shows, not after a set
    wait. Anything else left open goes to ``screens.settle``."""
    from farmbot import screens

    game.refresh()
    if game.find(T.REMOVE_TROOPS) is None and game.find(T.CASTLE_ROW) is not None and game.click(T.CLOSE):
        game.wait_for(T.FIND_MATCH, timeout=2, interval=0.3)
    back = getattr(game.device, "back", None)
    if back and game.find(T.FIND_MATCH) is not None:
        back()
        game.screen = None
        if game.wait_for(T.BATTLE, timeout=3, interval=0.3) is not None:
            return
    screens.settle(game)


def _send_request(game: Game) -> bool:
    """Request (when free: on cooldown it shows a gem price and isn't the
    button's picture) → Send."""
    if not game.click(T.REQUEST, region=game.region(REQUEST_AREA)):
        return False
    if game.click_when_visible(T.REQUEST_SEND, timeout=4):
        log.info("Requested Clan Castle troops")
        return True
    log.info("The request window didn't show its Send button")
    game.refresh()
    game.click(T.CLOSE)
    return False


CHAT_CLOSE_SPOT = (250, 150)  # a tap here, on the chat, closes the donate window
MAX_OPENS = 12  # donate windows opened in one visit at most
# A request's bubble, from its Donate button: who asks, what for, and its
# room ("35/45"...). It tells requests apart wherever the chat has moved
# them (a request filling up, or a new message, moves the others).
BUBBLE = (-370, -150, 330, 166)  # x, y, w, h from the button's centre
SAME_BUBBLE = 0.0005  # share of a bubble's pixels changed (by SAME_GREY) below which it's the same request (another name alone changes more)
SAME_GREY = 40
SAME_PLACE = 12  # px: a Donate button this close to where it was is the same one (a message moves it further)


def bubble(screen: np.ndarray, point: tuple[int, int]) -> np.ndarray:
    x, y, w, h = BUBBLE
    x0, y0 = max(0, point[0] + x), max(0, point[1] + y)
    return cv2.cvtColor(screen[y0:point[1] + y + h, x0:point[0] + x + w], cv2.COLOR_BGR2GRAY)


def same_bubble(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape or not a.size:
        return False
    return float((np.abs(a.astype(np.int16) - b.astype(np.int16)) >= SAME_GREY).mean()) < SAME_BUBBLE


def _close_window(game: Game) -> None:
    """Close the donate window (a tap on the chat), looking until it's gone."""
    game.tap(*CHAT_CLOSE_SPOT)
    for _ in range(8):
        game.wait(0.15, exact=True)
        game.refresh()
        if game.find(T.DONATE_WINDOW) is None:
            return


def donate(game: Game, cfg: ClanConfig, close: bool = True) -> int:
    """Fill every open request in clan chat, the ones that come in
    meanwhile too: the main units first, then the biggest that fit (see
    farmbot/tasks/donate.py). Returns units given."""
    from farmbot.tasks.donate import donate_open_window

    missing = _missing(game, (T.OPEN_CHAT, T.CLOSE_CHAT, T.DONATE, T.DONATE_WINDOW))
    if missing:
        log.warning("Cannot donate; missing pictures: %s", ", ".join(missing))
        return 0
    if (not cfg.donate_main and not cfg.donate_siege and not cfg.donate_spells and not cfg.donate_fill
            and not any(cfg.donate_presets.values())):
        return 0
    if not _open_chat(game):
        return 0
    donated = done = 0
    handled: list[np.ndarray] = []  # the bubbles of requests done with, as they look now
    for _ in range(MAX_OPENS):
        chat = game.refresh()  # the requests' bubbles, before a window covers them
        requests = [m for m in sorted(game.find_all(T.DONATE), key=lambda m: m.y)
                    if not any(same_bubble(bubble(chat, m.point), b) for b in handled)]
        if not requests:
            break
        request = requests[0]
        handled.append(bubble(chat, request.point))
        game.tap_match(request)
        game.screen = None
        if not game.wait_for(T.DONATE_WINDOW, timeout=3, interval=0.2):
            continue
        given = donate_open_window(game, cfg, chat, request.point)
        donated += given
        done += given > 0
        if game.find(T.DONATE_WINDOW):
            _close_window(game)
        # As it looks now (fuller), if it's still where it was (the chat
        # didn't move): not opened again unless it changes. (One that moved
        # is opened again, gives nothing more, and is known by then.)
        after = game.refresh()
        still = [m for m in game.find_all(T.DONATE) if abs(m.y - request.y) <= SAME_PLACE]
        if still:
            handled.append(bubble(after, still[0].point))
    if close:
        _close_chat(game)
    if donated:
        log.info("Donated %d unit(s) to %d request(s)", donated, done)
    return donated

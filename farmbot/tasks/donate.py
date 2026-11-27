"""Donating to Clan Castle requests from the donate window.

The window (Donation Resource) shows two rows of troop cards, with the
siege machines at their end, and a row of spells; both scroll sideways.
The bot pages along a row while a unit it wants hasn't shown yet (not when
the request names its units, nor when nothing on show is in colour: all
further along is grey then), flicks the troop rows to their end for the
siege machines, and back to their start to fill with what it paged past.
A main unit that gets nothing is logged with why.
A card in colour can be donated, a grey one can't (it doesn't fit, it's
not unlocked, or there's no resource for it; when a request names units,
those come first in the window and are the only ones in colour). Each tap
gives one unit and costs the elixir or dark elixir on the card.

The bot gives the player's main troops first, in their order, while they're
in colour; then (if asked) fills what's left with the biggest troop that
still fits; then the siege machine and spells picked. With no main troops
picked, it gives the preset army of the requester's Clan Castle level,
read from the room the request's bubble shows (see farmbot/castle.py). It never
donates while the window is set to pay with gems. Every tap is checked to
have given a unit (the window's counters change); one that didn't means
the request filled up from others' donations, and it's left at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from farmbot.castle import Castle, castle_for, preset
from farmbot.config import ClanConfig
from farmbot.game import Game, T
from farmbot.geometry import Rect
from farmbot.text import TextStyle, pieces
from farmbot.units import BY_NAME, BY_SLUG

log = logging.getLogger(__name__)

# The donate window, in bot coordinates when its title is at TITLE_Y.
TITLE_Y = 185
TROOP_ROWS = ((268, 382), (386, 500))
SPELL_ROWS = ((553, 667),)
PANEL_X = (455, 1125)
GAP_BGR = np.array([205, 210, 210])  # the light grey between cards
GAP_RUN = 3  # px: a gap is at least this wide (about 5); a thinner run is a card's own light grey (a greyed-out one has plenty)
CARD_W = (78, 92)
ART = (0.05, 0.5, 0.06, 0.94)  # the card's picture: top, bottom, left, right shares (no level, no price)
SAME_UNIT = 0.7  # picture likeness to name a card
IN_COLOUR = 45  # mean saturation of a card's picture: in colour (donatable), below: greyed out
MAX_TAPS = 60  # taps on one request at most, whatever happens

# The request's bubble in chat, left of its Donate button: "0/55" troops,
# "0/3" spells, "1/2" siege machines, grey on dark grey. Their room is the
# requester's Clan Castle. (The window's own "Donate Troops: 0/25" is how
# much one player may give, not the castle.)
ROOM_X = {"troops": (-321, -241), "spells": (-206, -146), "siege": (-126, -71)}  # from the button's centre
ROOM_Y = (-14, 12)
ROOM_TEXT = TextStyle(max_saturation=50, min_value=100, min_area=4)
# Then brighter only: on LDPlayer the text is sharper and brighter, and at
# 100 its edges join the "0" and "/" of "0/50".
ROOM_TEXT_BRIGHT = TextStyle(max_saturation=50, min_value=170, min_area=4)
ROOM_HEIGHT = 14  # px: taller pieces are the icons, not text
ROOM_GAP = 4  # px: a wider gap ends a word; the number is the last one
ROOM_SCORE = 0.72  # a digit not learned yet scores about 0.65 against the nearest one
ROOM_FONT = "fonts/request"  # its "/" is slash.png
ROOM_SCREENS = Path("screens/donate_room")  # bubbles that couldn't be read, to learn their digits from


@dataclass(frozen=True)
class DonateCard:
    name: str | None  # None: a unit without a picture yet
    x: int
    y: int
    w: int
    h: int
    available: bool

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def housing(self) -> int:
        unit = BY_NAME.get(self.name or "")
        return unit.housing if unit else 0


def _art(card: np.ndarray) -> np.ndarray:
    h, w = card.shape[:2]
    top, bottom, left, right = ART
    return card[int(h * top):int(h * bottom), int(w * left):int(w * right)]


@lru_cache(maxsize=4)
def _pictures(folder: str) -> tuple[tuple[str, np.ndarray], ...]:
    """Every unit picture under ``folder``, grey (a greyed-out card must
    still be recognised)."""
    out = []
    for path in sorted(Path(folder).glob("*.png")):
        unit = BY_SLUG.get(path.stem.split("@")[0])  # super_miner@2.png: another picture of it
        image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
        if unit and image is not None:
            out.append((unit.name, image))
    return tuple(out)


def name_card(card: np.ndarray, pictures) -> str | None:
    art = cv2.cvtColor(_art(card), cv2.COLOR_BGR2GRAY)
    best, best_score = None, SAME_UNIT
    for name, picture in pictures:
        sized = cv2.resize(art, (picture.shape[1], picture.shape[0]))
        score = float(cv2.matchTemplate(sized, picture, cv2.TM_CCOEFF_NORMED)[0, 0])
        if score > best_score:
            best, best_score = name, score
    return best


def _columns(screen: np.ndarray, y0: int, y1: int) -> list[tuple[int, int]]:
    """Left and right edge of each whole card in a row, from the gaps between them."""
    x0, x1 = PANEL_X
    band = screen[y0 + 7:y1 - 7, x0:x1].astype(np.int16)
    gap = list((np.abs(band - GAP_BGR).max(axis=2) < 14).mean(axis=0) > 0.5)
    # A greyed-out card's picture can have a stripe as light as the gap:
    # not a gap unless it's as wide as one (or the card is split and lost).
    i = 0
    while i < len(gap):
        if gap[i]:
            end = i
            while end < len(gap) and gap[end]:
                end += 1
            if end - i < GAP_RUN and 0 < i and end < len(gap):
                gap[i:end] = [False] * (end - i)
            i = end
        else:
            i += 1
    out, start = [], None
    for i, is_gap in enumerate(gap + [True]):
        if not is_gap and start is None:
            start = i
        elif is_gap and start is not None:
            if CARD_W[0] <= i - start <= CARD_W[1]:
                out.append((x0 + start, x0 + i))
            start = None
    return out


def read_cards(screen: np.ndarray, rows, pictures, dy: int = 0) -> list[DonateCard]:
    cards = []
    for y0, y1 in rows:
        y0, y1 = y0 + dy, y1 + dy
        for left, right in _columns(screen, y0, y1):
            card = screen[y0:y1, left:right]
            saturation = float(cv2.cvtColor(_art(card), cv2.COLOR_BGR2HSV)[:, :, 1].mean())
            cards.append(DonateCard(name_card(card, pictures), left, y0, right - left, y1 - y0,
                                    saturation >= IN_COLOUR))
    return cards


def pays_with_gems(screen: np.ndarray, cards: list[DonateCard]) -> bool:
    """True if the cards' prices are in gems (the green gem icon) rather
    than elixir or dark elixir."""
    for c in cards:
        icon = screen[c.y + int(c.h * 0.82):c.y + int(c.h * 0.96), c.x + int(c.w * 0.78):c.x + c.w - 3]
        hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
        green = (hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 120)
        if icon.size and green.mean() > 0.25:
            return True
    return False


def choose(cards: list[DonateCard], main: list[str], fill: bool) -> DonateCard | None:
    """The next card to tap: the first main unit in colour, else (with
    ``fill``) the biggest troop in colour (units without a known housing
    last; siege machines only when picked), else none."""
    available = [c for c in cards if c.available]
    for name in main:
        for c in available:
            if c.name == name:
                return c
    troops = [c for c in available if not _siege(c)]
    if fill and troops:
        return max(troops, key=lambda c: c.housing)
    return None


def names_units(*groups: list[DonateCard]) -> bool:
    """True if the open request names the units it wants: those lead the
    troops' and spells' cards in colour (column by column), the rest grey.
    A request that doesn't has every card you can give in colour."""
    shown = [[c.available for c in sorted(cards, key=lambda c: (c.x, c.y))] for cards in groups]
    return (any(any(s) for s in shown) and not all(all(s) for s in shown)
            and all(s == sorted(s, reverse=True) for s in shown))


def _siege(card: DonateCard) -> bool:
    return card.name in BY_NAME and BY_NAME[card.name].kind == "siege"


def _title_dy(game: Game) -> int | None:
    match = game.find(T.DONATE_WINDOW)
    return None if match is None else match.y - TITLE_Y


def read_room(screen: np.ndarray, font, button: tuple[int, int], kind: str) -> int | None:
    """The room for one kind ("troops", "spells", "siege") in the bubble of
    the request whose Donate button is at ``button``, or ``None`` if it
    can't be read."""
    (x0, x1), (y0, y1) = ROOM_X[kind], ROOM_Y
    region = Rect(button[0] + x0, button[1] + y0, x1 - x0, y1 - y0)
    for style in (ROOM_TEXT, ROOM_TEXT_BRIGHT):
        room = _room(screen, font, region, style)
        if room is not None:
            return room
    return None


def _room(screen: np.ndarray, font, region: Rect, style: TextStyle) -> int | None:
    word: list[np.ndarray] = []
    end = None
    for x, mask in pieces(screen, region, style):
        if mask.shape[0] > ROOM_HEIGHT:
            continue
        if end is not None and x - end > ROOM_GAP:
            word = []
        word.append(mask)
        end = x + mask.shape[1]
    # Only the room, after the "/", has to be read (what's given so far can
    # have any digit; the room is one of a few numbers).
    read = [font.classify(mask) for mask in word]
    slashes = [i for i, (char, score) in enumerate(read) if char == "slash" and score >= ROOM_SCORE]
    if not slashes or any(score < ROOM_SCORE for _, score in read[slashes[-1] + 1:]):
        return None
    room = "".join(char for char, _ in read[slashes[-1] + 1:])
    return int(room) if room.isdigit() else None


def read_castle(game: Game, screen: np.ndarray, button: tuple[int, int]) -> Castle | None:
    """The requester's Clan Castle, from the room its request's bubble shows."""
    try:
        font = game.vision.font(ROOM_FONT)
    except (FileNotFoundError, ValueError):
        return None
    troops, spells, siege = (read_room(screen, font, button, kind) for kind in ("troops", "spells", "siege"))
    castle = castle_for(troops, spells, siege) if troops is not None else None
    if castle is None:
        log.info("Couldn't read the Clan Castle's room (the screen is kept to learn its digits from)")
        from farmbot.tasks.village import _keep_screen

        _keep_screen(ROOM_SCREENS, screen)
        return None
    log.info("Clan Castle level %d: room for %d troops, %d spells, %d siege; units come at level %d at most",
             castle.level, castle.troops, castle.spells, castle.siege, castle.lab_cap)
    return castle


# What changes in the window when a tap gives a unit: the "Donate Troops:
# n/N" and "Donate Spells: n/N" counters (under their labels) and the strip
# of what's been given, at the bottom. A tap that changes none of them was
# turned down (the request filled up from others' donations meanwhile).
COUNTERS = ((455, 238, 320, 26), (455, 518, 320, 26), (455, 712, 670, 100))  # x, y, w, h with the title at TITLE_Y
CHANGED = 40  # a pixel this much brighter or darker in any channel has changed...
CHANGED_PIXELS = 4  # ...and this many of them is a donation that went through (a still window changes none: one thin digit is enough)
TAP_LOOKS = (0.12, 0.15, 0.2, 0.3)  # s between looks for a tap's donation to show (0.77 s in all)
# The first of them is the pause before the next tap too: a person's, so it
# follows "Waits run a touch longer" and tiredness (the others are polls).
OPEN_LOOKS = 6  # looks (0.15 s apart) for the window's cards to show once it opens

# Scrolling a row of cards sideways. A drag that slows to a stop before it
# lifts moves the row by its own length (no fling), so a page overlaps the
# one before by a couple of cards (a card cut by the panel's edge isn't
# read). To the end (the siege machines), quick flicks.
PAGE_DRAG = 400  # px; the row moves about 270 of it (the touch slop takes the rest): three cards
PAGE_MS = 650
FLICK = 560
FLICK_MS = 160
SCROLL_SETTLE = 0.25  # s before the first look at a row let go of...
STILL_LOOKS = 8  # ...then looks (0.1 s apart) until it's at rest: two the same
ROW_RESTING = 1.0  # mean change of the row's pixels between two looks below which it's at rest
MAX_PAGES = 16  # drags along one row at most (flicks to its end or start too)
ROW_STILL = 3.0  # mean change of the row's pixels below which a drag moved nothing: its end


class Refused(Exception):
    """A tap that gave nothing: the request is full (others filled it), or
    the game turned the donation down."""

    def __init__(self, given: int):
        super().__init__(f"donation refused after {given} unit(s)")
        self.given = given


def _counters(screen: np.ndarray, dy: int) -> list[np.ndarray]:
    h, w = screen.shape[:2]
    out = []
    for x, y, cw, ch in COUNTERS:
        y0, y1 = max(0, y + dy), min(h, y + dy + ch)
        out.append(screen[y0:y1, x:min(w, x + cw)].astype(np.int16))
    return out


def went_through(before: np.ndarray, after: np.ndarray, dy: int) -> bool:
    """True if a donation shows between two looks at the window: a counter
    or the strip of given units changed."""
    changed = 0
    for a, b in zip(_counters(before, dy), _counters(after, dy)):
        if a.shape == b.shape and a.size:
            changed += int((np.abs(a - b).max(axis=2) >= CHANGED).sum())
    return changed >= CHANGED_PIXELS


def _title_on(game: Game, screen: np.ndarray | None) -> int | None:
    """The window's offset on this very screenshot (``None``: closed)."""
    if screen is None:
        return None
    match = game.vision.find(screen, T.DONATE_WINDOW)
    return None if match is None else match.y - TITLE_Y


def _row_band(rows, dy: int) -> tuple[int, int]:
    return rows[0][0] + dy + 7, rows[-1][1] + dy - 7


def _drag_row(game: Game, rows, dy: int, distance: int, ms: int, slow_end: bool) -> None:
    """Drag a row of cards ``distance`` px to the left (negative: to the
    right, back to its start), along the gap between the two troop rows (or
    a spell card's top edge): long enough never to read as a tap on a card."""
    y = ((rows[0][1] + rows[1][0]) // 2 if len(rows) > 1 else rows[0][0] + 10) + dy
    x1 = PANEL_X[1] - 50 if distance > 0 else PANEL_X[0] + 50
    x2 = x1 - distance
    drag = getattr(game.device, "drag", None)
    if slow_end and drag is not None:
        # Along the row, slowing down, then held still a moment before
        # lifting: the row stops where the finger does.
        game.check_in_front()
        steps = 14
        points = [(round((x1 + (x2 - x1) * (1 - (1 - i / steps) ** 2)) * game.scale), round(y * game.scale))
                  for i in range(steps + 1)]
        points += [points[-1]] * 4
        if drag(points, ms):
            game.screen = None
            return
    game.swipe(x1, y, x2, y, ms)


def _at_rest(game: Game, rows, dy: int) -> np.ndarray:
    """The screen once a row let go of has stopped (a flick coasts, and
    may bounce at the row's end): two looks in a row the same."""
    y0, y1 = _row_band(rows, dy)
    x0, x1 = PANEL_X
    game.wait(SCROLL_SETTLE, exact=True)
    last = game.refresh()
    for _ in range(STILL_LOOKS):
        game.wait(0.1, exact=True)
        now = game.refresh()
        if _title_on(game, now) != dy:
            return now
        band = (slice(y0, y1), slice(x0, x1))
        if float(np.abs(now[band].astype(np.int16) - last[band].astype(np.int16)).mean()) < ROW_RESTING:
            return now
        last = now
    return last


def scroll_row(game: Game, rows, dy: int, to_end: bool = False, back: bool = False) -> np.ndarray | None:
    """Move a row of cards on (a page, or a flick towards its end; ``back``:
    a flick towards its start); the screen after, or ``None`` if it didn't
    move (it was at that end) or the window closed."""
    before = game.screen if game.screen is not None else game.refresh()
    y0, y1 = _row_band(rows, dy)
    x0, x1 = PANEL_X
    if back:
        _drag_row(game, rows, dy, -FLICK, FLICK_MS, slow_end=False)
    elif to_end:
        _drag_row(game, rows, dy, FLICK, FLICK_MS, slow_end=False)
    else:
        _drag_row(game, rows, dy, PAGE_DRAG, PAGE_MS, slow_end=True)
    after = _at_rest(game, rows, dy)
    if _title_on(game, after) != dy:
        return None
    moved = float(np.abs(after[y0:y1, x0:x1].astype(np.int16) - before[y0:y1, x0:x1].astype(np.int16)).mean())
    return after if moved >= ROW_STILL else None


def _flick_along(game: Game, rows, dy: int, back: bool = False) -> np.ndarray:
    """Flick a row to its end (``back``: its start) until it stops moving;
    the screen after."""
    for _ in range(MAX_PAGES):
        if scroll_row(game, rows, dy, to_end=not back, back=back) is None:
            break
    return game.screen if game.screen is not None else game.refresh()


def _give(game: Game, rows, main: list[str], fill: bool, pictures, limit: int,
          counts: dict[str, int | None] | None = None, to_end: bool = False, asked: bool = False) -> int:
    """Donate from one set of rows (troops or spells) until nothing more
    should or can be given; with ``counts``, at most that many of each main
    unit (``None``: as many as fit). The row is paged through while a main
    unit wanted hasn't shown yet; ``to_end`` goes to the row's end first
    (the siege machines). ``asked``: the request names its units (they lead
    the row, in colour), so the row isn't paged: what's further is grey.
    Each tap is checked to have given a unit: one that didn't raises
    :class:`Refused`. Returns how many units were given; a main unit that
    got none is logged with why."""
    left = {name: count for name, count in (counts or {}).items() if count is not None}

    def wanted() -> list[str]:
        return [n for n in main if left.get(n, 1) > 0]

    given = pages = 0
    seen: set[str | None] = set()  # every unit on show so far (paging stops once the wanted ones have)
    coloured: set[str | None] = set()  # ...and the ones of them in colour
    gave: dict[str | None, int] = {}
    went_back = False

    def fill_behind() -> bool:
        # Filling would give something seen in colour on a page left behind.
        return fill and pages > 0 and not went_back and any(
            n not in main and not (n in BY_NAME and BY_NAME[n].kind == "siege") for n in coloured)

    screen = game.refresh()
    dy = _title_on(game, screen)
    if dy is not None and to_end:
        # Straight to the row's end, unless what's wanted is in colour
        # where the window opens (a request that names it may put it first).
        here = read_cards(screen, rows, pictures, dy)
        if not any(c.available and c.name in main for c in here):
            screen = _flick_along(game, rows, dy)
    elif dy is not None and not any(c.available for c in read_cards(screen, rows, pictures, dy)):
        # Nothing in colour where the window opens, the cheapest units
        # included: this kind's room is full (or there's no elixir).
        # Paging on would find only grey cards.
        if main or fill:
            kind = "spell" if rows == SPELL_ROWS else "troop"
            log.info("No %s can be given: every card is greyed out (%s)", kind,
                     f"the request asks for no {kind}s" if asked
                     else "the request has no room left for them, or there isn't the elixir")
        return 0
    while given < limit:
        dy = _title_on(game, screen)
        if dy is None:
            break  # the window closed: the request is full
        cards = read_cards(screen, rows, pictures, dy)
        seen.update(c.name for c in cards)
        coloured.update(c.name for c in cards if c.available)
        card = choose(cards, wanted(), fill)
        unseen = [] if asked else [n for n in wanted() if n not in seen]
        if card is None and not unseen and fill_behind():
            # Paged on to a main unit that's grey there, and what can be
            # given was further back: back to the row's start to fill.
            went_back = True
            seen.update(wanted())
            screen = _flick_along(game, rows, dy, back=True)
            continue
        if card is None or (card.name not in main and unseen):
            # A main unit wanted may be further along the row: page on to
            # it (filling waits until every one has shown, or the row ends).
            if not unseen:
                break
            moved = scroll_row(game, rows, dy) if pages < MAX_PAGES else None
            pages += 1
            if moved is not None:
                screen = moved
                continue
            if card is None and not fill_behind():
                break
            seen.update(wanted())  # the row's end: fill from here (or from its start, above)
            continue
        name = card.name
        log.info("Donating %s", name or "an unknown unit")
        # Give it while it stays in colour (and stays the best choice).
        retried = False
        while given < limit:
            game.tap(*card.center)
            game.screen = None
            after = screen
            for i, pause in enumerate(TAP_LOOKS):
                game.wait(pause, exact=i > 0)
                after = game.refresh()
                if _title_on(game, after) != dy or went_through(screen, after, dy):
                    break
            if _title_on(game, after) != dy:
                # It closed: the request filled (this tap may have been the last).
                return given + 1 if went_through(screen, after, dy) else given
            if not went_through(screen, after, dy):
                # Once more if it's still there in colour (a tap the game
                # missed); a second that gives nothing: the request is full.
                here = read_cards(after, rows, pictures, dy)
                again = next((c for c in here if c.name == name and c.available and abs(c.x - card.x) < 20), None)
                if retried or again is None:
                    raise Refused(given)
                retried, card, screen = True, again, after
                continue
            given += 1
            gave[name] = gave.get(name, 0) + 1
            if name in left:
                left[name] -= 1
            screen = after
            here = read_cards(screen, rows, pictures, dy)
            card = next((c for c in here if c.name == name and c.available and abs(c.x - card.x) < 20), None)
            if card is None or choose(here, wanted(), fill) != card:
                break  # greyed out, given enough, or something better is on show now
    if given < limit and _title_on(game, game.screen if game.screen is not None else game.refresh()) is not None:
        for name in main:
            if not gave.get(name):
                log.info("Not donating %s: %s", name, why_not(name, seen, coloured, asked, fill))
    return given


def why_not(name: str, seen: set, coloured: set, asked: bool, fill: bool) -> str:
    """Why a main unit got nothing, as far as the window tells: no card for
    it, or a grey one (which looks the same whatever the reason)."""
    if name in coloured:
        return "the request had no room left for it"
    if name not in seen and not asked:
        return "no card for it in the window (not unlocked yet, or its picture wasn't recognised)"
    if asked:  # (grey, or further along the row, which isn't paged through then)
        return ("greyed out: the request asks for other units" +
                ("" if fill else " (\"Fill the rest\" is off, so those aren't given either)"))
    return "greyed out: no room left for it in the request, not unlocked, or not enough elixir / dark elixir"


def wait_for_cards(game: Game) -> int | None:
    """Once the window's title shows, a few quick looks until its cards do
    (they slide in with it). Its offset, or ``None`` if it closed."""
    for _ in range(OPEN_LOOKS):
        screen = game.refresh()
        dy = _title_on(game, screen)
        if dy is None:
            return None
        if _columns(screen, TROOP_ROWS[0][0] + dy, TROOP_ROWS[0][1] + dy):
            return dy
        game.wait(0.15, exact=True)
    return _title_on(game, game.screen)


def donate_open_window(game: Game, cfg: ClanConfig, request: np.ndarray | None = None,
                       button: tuple[int, int] | None = None) -> int:
    """Fill the request whose donate window is open. ``request`` is the
    chat before it opened and ``button`` its Donate button there (to read
    the castle's room from the bubble). Returns units given; a request that
    turns a donation down (full meanwhile) is left at once."""
    dy = wait_for_cards(game)
    if dy is None:
        return 0
    pictures = _pictures(str(Path(game.vision.library.root) / T.DONATE_ITEM_DIR))
    screen = game.screen
    troops, spell_cards = read_cards(screen, TROOP_ROWS, pictures, dy), read_cards(screen, SPELL_ROWS, pictures, dy)
    if pays_with_gems(screen, troops + spell_cards):
        log.warning("The donate window is set to pay with gems: not donating (switch it back to elixir)")
        return 0
    limit = MAX_TAPS
    # No main troops picked: the preset army of the requester's castle
    # level. A request that names its units shows only those in colour, so
    # the preset's others are passed over and the filling gives those.
    castle = None if cfg.donate_main or request is None or button is None else read_castle(game, request, button)
    plan = preset(cfg.donate_presets.get(str(castle.level), [])) if castle else {}

    def of(kind: str, picked: list[str]) -> list[str]:
        return [n for n in picked or list(plan) if BY_NAME.get(n) and BY_NAME[n].kind == kind]

    siege = of("siege", cfg.donate_siege)
    spells = of("spell", cfg.donate_spells)
    # A request that names its units has them first in colour, the rest
    # grey: the rows aren't paged through then (nothing further can be given).
    asked = names_units(troops, spell_cards)
    if asked:
        log.info("The request names the units it wants: %s", ", ".join(sorted(
            {c.name or "an unknown unit" for c in troops + spell_cards if c.available})))
    # Spells: the ones picked; filling them too only when the request names
    # its units (then what's in colour is what it asked for).
    fill_spells = cfg.donate_fill and asked
    steps = [(TROOP_ROWS, of("troop", cfg.donate_main), cfg.donate_fill, plan, False)]
    if siege:
        # Siege machines sit at the end of the troop rows: only the ones picked.
        steps.append((TROOP_ROWS, siege, False, None if cfg.donate_siege else plan, True))
    if spells or fill_spells:
        steps.append((SPELL_ROWS, spells, fill_spells, None if cfg.donate_spells else plan, False))
    given = 0
    try:
        for rows, main, fill, counts, to_end in steps:
            if given >= limit:
                break
            given += _give(game, rows, main, fill, pictures, limit - given, counts, to_end, asked)
            if _title_on(game, game.screen if game.screen is not None else game.refresh()) is None:
                break  # it closed: full
    except Refused as refused:
        given += refused.given
        log.info("The request is full (the game turned a donation down): on to the next one")
    return given

"""Find a base worth attacking."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Callable

import cv2

from farmbot import human
from farmbot.config import RegionsConfig, SearchConfig
from farmbot.game import Game, T
from farmbot.geometry import Rect
from farmbot.text import SNOW, YELLOW, TextStyle

log = logging.getLogger(__name__)


class SearchError(RuntimeError):
    pass


class SearchBlocked(SearchError):
    """"Unable to attack Village! Try again later.": a battle left without
    surrendering still runs on the server. Only closing the game for a few
    minutes clears it."""


class NextNotFound(SearchError):
    """No base showed: its Next button never came (or went away)."""


class GameRefreshed(SearchError):
    """The game's "New Content" window showed instead of a base: Refresh was
    pressed and the game reloaded to the village. Searching again is all it takes."""


class LootUnreadable(SearchError):
    """The bases showed, but their loot couldn't be read."""


class NextDidNothing(SearchError):
    """Next was tapped (twice) and the same base is still showing."""


@dataclass(frozen=True)
class Loot:
    gold: int
    elixir: int
    dark: int


# Called for every scouted base with its loot and whether it was accepted.
BaseCallback = Callable[[Loot, bool], None]


DARK_WORTH = 100  # one dark elixir counts as this much gold or elixir


def loot_value(loot: Loot, criteria: SearchConfig | None = None) -> int:
    """Gold + elixir + dark elixir, dark counted ``DARK_WORTH`` times."""
    return loot.gold + loot.elixir + loot.dark * DARK_WORTH


def is_worth_attacking(loot: Loot, criteria: SearchConfig) -> bool:
    checks = [
        loot.gold >= criteria.min_gold,
        loot.elixir >= criteria.min_elixir,
        loot.dark >= criteria.min_dark,
    ]
    enough = any(checks) if criteria.match_any else all(checks)
    return enough


def near_miss(rng, loot: Loot, criteria: SearchConfig, accepted: bool) -> bool | None:
    """"Imperfect choices": True to attack a base up to NEAR under the
    minimums after all, False to pass over one up to NEAR over them, None
    to leave the choice as it is (nearly always)."""
    def scaled(by: float) -> SearchConfig:
        return replace(criteria, min_gold=int(criteria.min_gold * by), min_elixir=int(criteria.min_elixir * by),
                       min_dark=int(criteria.min_dark * by))

    if not (criteria.min_gold or criteria.min_elixir or criteria.min_dark):
        return None  # no minimums: every base is taken
    if accepted:
        just = not is_worth_attacking(loot, scaled(1 + human.NEAR))
        return False if just and rng.random() < human.SKIP_OVER else None
    just = is_worth_attacking(loot, scaled(1 - human.NEAR))
    return True if just and rng.random() < human.TAKE_UNDER else None


def closeness(loot: Loot, criteria: SearchConfig) -> float:
    """How near ``loot`` comes to the minimums (1: it meets them): what a
    person weighs when deciding how long to look at a base."""
    shares = [have / least for have, least in ((loot.gold, criteria.min_gold), (loot.elixir, criteria.min_elixir),
                                                (loot.dark, criteria.min_dark)) if least > 0]
    if not shares:
        return 1.0
    return max(shares) if criteria.match_any else min(shares)


def look_at_base(game: Game, loot: Loot, criteria: SearchConfig, picked: bool, on: bool) -> None:
    """"Look at each base": a quick look at a poor one, longer at one close
    to the minimums, a moment at the one picked."""
    centre = human.look_centre(closeness(loot, criteria), picked)
    seconds = human.look(game.rng, centre) if on else 0.0
    game.note("look_at_bases", human.look_extra(centre), seconds)
    if seconds:
        game.wait(seconds, exact=True)


def _loot_number(game: Game, regions: RegionsConfig, name: str) -> int | None:
    region = game.region(regions.rect(name))
    found = game.read_number(region, T.LOOT_FONT)
    if found is None:
        # Snow behind the digits passes for their white and joins them: again without its blue.
        found = game.read_number(region, T.LOOT_FONT, SNOW)
    # With "Loot Available 2x" the digits are yellow (white reads bits of the
    # cupcake beside them, "15"): the longer of the two readings is the number.
    yellow = game.read_number(region, T.LOOT_FONT, YELLOW)
    if yellow is not None and (found is None or len(str(yellow)) > len(str(found))):
        return yellow
    return found


def read_loot(game: Game, regions: RegionsConfig) -> Loot | None:
    gold = _loot_number(game, regions, "loot_gold")
    elixir = _loot_number(game, regions, "loot_elixir")
    if gold is None or elixir is None:
        return None
    # Dark elixir is absent on low town halls; treat unreadable as zero.
    dark = _loot_number(game, regions, "loot_dark") or 0
    return Loot(gold, elixir, dark)


# A loot boost (a food item, 16 Nov 2026) shows "Loot Available 2x:" over a
# base's loot, the numbers in yellow and already multiplied: a base is judged
# on what it holds, the shown loot divided by the boost.
BOOST_LABEL = 50  # px above the gold row the label sits in, at most
BOOST_WORDS = ("loot", "ailable", "avail")  # (OCR reads the label loosely: "Loot·ailable 2k:")
BOOST_NUMBER = re.compile(r"(\d+)\s*[x×k]")
BOOST_USUAL = 2  # the boost when its label shows but its number can't be read


def loot_boost(game: Game, regions: RegionsConfig) -> int:
    """How many times the shown loot is multiplied: 1 without a boost, else
    the label's number. The elixir row tells: white (pinkish) without one,
    yellow with one (gold's digits are a little yellow either way)."""
    elixir = game.region(regions.rect("loot_elixir"))
    if game.read_number(elixir, T.LOOT_FONT, YELLOW) is None:
        return 1
    gold = game.region(regions.rect("loot_gold"))
    from farmbot import wordbuttons

    top = max(gold.y - BOOST_LABEL, 0)
    try:
        lines = wordbuttons.read(game.screen[top:gold.y + gold.h // 2, 0:gold.x + gold.w + 150])
    except Exception as exc:  # (no OCR on this Windows: the usual boost)
        log.debug("Couldn't read the loot boost's label: %s", exc)
        lines = []
    for _, text in lines:
        low = text.lower()
        if any(w in low for w in BOOST_WORDS):
            found = BOOST_NUMBER.search(low.split("ailable")[-1])
            if found and 1 < int(found.group(1)) <= 10:
                return int(found.group(1))
            return BOOST_USUAL
    return BOOST_USUAL  # yellow loot digits are the boost's


def unboosted(loot: Loot, boost: int) -> Loot:
    """What a base holds, from the loot shown under a ``boost``."""
    if boost <= 1:
        return loot
    return Loot(loot.gold // boost, loot.elixir // boost, loot.dark // boost)


SETTLE_READS = 4  # tries at a steady reading of a base's loot


def read_settled_loot(game: Game, regions: RegionsConfig, interval: float = 0.3) -> Loot | None:
    """The base's loot once two readings in a row agree: the counters
    count up when a base loads, and a reading mid-way is wrong. ``None``
    if it never reads the same twice."""
    last = None
    for attempt in range(SETTLE_READS):
        if attempt:
            game.wait(interval)
            game.refresh()
        loot = read_loot(game, regions)
        if loot is not None and loot == last:
            return loot
        last = loot
    return None


def _own(game: Game, regions: RegionsConfig, name: str, shift: int = 0) -> int | None:
    r = game.region(regions.rect(name))
    return game.read_number(Rect(r.x - shift, r.y, r.w, r.h), T.LOOT_FONT)


def own_gold(game: Game, regions: RegionsConfig, shift: int = 0) -> int | None:
    """Your gold, read from the home village's resource bar (``shift``
    pixels further left: a window open on the right pushes the bar over)."""
    return _own(game, regions, "own_gold", shift)


def own_resources(game: Game, regions: RegionsConfig, shift: int = 0) -> Loot | None:
    """Your gold, elixir and dark elixir from the home village's resource bar."""
    gold = own_gold(game, regions, shift)
    elixir = _own(game, regions, "own_elixir", shift)
    if gold is None or elixir is None:
        return None
    dark = (_own(game, regions, "own_dark", shift) or 0) if has_dark(game, regions, shift) else 0
    return Loot(gold, elixir, dark)


# Tapping a resource bar opens a box under it, "Max: 21 000 000" first; tapping
# it again closes it (in the builder base too). The "Max:" label is
# smaller than the number, so pieces shorter than the digits are left out.
MAX_STYLE = TextStyle(min_height_ratio=0.85)
# The box's look and place change with the game's updates (November 2026:
# light, wider, with "Production per hour" and "In treasury" rows under
# "Max:"), so "Max:" is looked for anywhere in a wide area under the bar
# (any look of it in icons/storage_max/) and its number read on its row.
MAX_AREA = (10, 100)  # top and height of where "Max:" may be, below the bar's middle
MAX_SPAN = (430, 40)  # the area reaches this far left of the bar's number and right of it
MAX_ROW_HEIGHT = 30  # the "Max:" row's number, centred on the label
LEAST_STORAGE = 1000  # no storage holds less (a town hall 1's gold storage holds 1 500)
ROUND_SIZE = 500  # what storages hold comes in steps of this at least
OVER_FULL = 3  # a storage holding more than its size holds at most this many times it


def _max_region(game: Game, regions: RegionsConfig, kind: str) -> Rect:
    """Where the box's "Max:" label can be, under the ``kind`` bar."""
    r = game.region(regions.rect(f"own_{kind}"))
    middle = r.y + r.h // 2
    left = max(r.x + r.w - MAX_SPAN[0], 0)
    return Rect(left, middle + MAX_AREA[0], r.x + r.w + MAX_SPAN[1] - left, MAX_AREA[1])


def _max_number_region(label, area: Rect) -> Rect:
    """The "Max:" row's number: right of its label, to the area's right edge."""
    x = label.x + label.w // 2 + 2
    return Rect(x, label.y - MAX_ROW_HEIGHT // 2, area.x + area.w - x, MAX_ROW_HEIGHT)


def has_dark(game: Game, regions: RegionsConfig, shift: int = 0) -> bool:
    """Whether the home village's third bar is dark elixir. Below town hall
    7 there's none, and the gems' bar is there (with a gem by its number):
    read as dark elixir it'd be the gems, and a tap on it opens the Shop."""
    if not game.has(T.GEM):
        return True
    r = game.region(regions.rect("own_dark"))
    # The bar's icon, right of its number (a window open on the right pushes it ``shift`` over),
    # and no taller than its bar: the next bar down (the gems', from town hall 7) isn't it.
    x = r.x - shift
    icons = game.find_all(T.GEM, region=Rect(x, max(r.y - r.h, 0), game.size[0] - x, 3 * r.h))
    return not any(r.y - r.h // 4 <= m.y <= r.y + r.h + r.h // 4 for m in icons)  # (its middle in the bar)


def storage_max(game: Game, regions: RegionsConfig, kind: str) -> int | None:
    """How much the ``kind`` storages hold, from the box tapping its bar
    opens (closed again after). ``None`` without the "Max:" picture."""
    if not game.has(T.STORAGE_MAX):
        return None
    r = game.region(regions.rect(f"own_{kind}"))
    bar = (r.x + r.w // 2, r.y + r.h // 2)
    where = _max_region(game, regions, kind)

    def label():
        # The topmost "Max:" (the box's first row).
        found = game.find_all(T.STORAGE_MAX, region=where)
        return min(found, key=lambda m: m.y) if found else None

    def is_open() -> bool:
        game.refresh()
        return label() is not None

    most = None
    for _ in range(2):  # a second tap if the game missed the first
        game.tap(*bar)
        if _soon(game, is_open, MAX_OPENS):
            m = label()
            if m is not None:
                most = game.vision.read_number(game._current(), _max_number_region(m, where), T.LOOT_FONT,
                                               MAX_STYLE)
            break
    # Close it. The home village's light box (November 2026) stays open on a
    # second tap on the bar: a tap on the box itself closes it (it takes the
    # tap), so it gets that tap first, not a wasted one on the bar (seen as a
    # double tap on each bar). The dark, see-through box (the builder base's)
    # closes from the bar: never tapped first, a tap on it reaches what's
    # under it (the builder base's boat: home).
    game.refresh()
    m = label()
    order = ("box", "bar") if m is not None and _light_box(game, m) else ("bar", "box", "bar")
    for close in order:
        game.refresh()
        m = label()
        if m is None:
            break
        game.tap(*((m.x, m.y) if close == "box" else bar))
        if _soon(game, lambda: not is_open(), MAX_CLOSES):
            break
    return most


LIGHT_BOX = 0.5  # share of bright pixels around "Max:" in the light box (about 0.76); the see-through one far less


def _light_box(game: Game, label) -> bool:
    """Whether the storage's box is the light one, which a tap closes."""
    area = game.screen[max(label.y - label.h, 0):label.y + label.h, max(label.x - 2 * label.w, 0):label.x + 2 * label.w]
    if area.size == 0:
        return False
    return float((cv2.cvtColor(area, cv2.COLOR_BGR2HSV)[:, :, 2] >= 200).mean()) >= LIGHT_BOX


MAX_OPENS = 1.2  # seconds the storage's box takes to open at most (it's looked for as it does)
MAX_CLOSES = 0.9


def _soon(game: Game, done, timeout: float, first: float = 0.25, interval: float = 0.2) -> bool:
    """``done()`` comes true within ``timeout`` seconds, looked at every
    ``interval`` (a screenshot takes ~0.2 s itself)."""
    deadline = game.clock() + timeout
    game.wait(first)
    while not done():
        if game.clock() >= deadline:
            return False
        game.wait(interval)
    return True


def storage_maxes(game: Game, regions: RegionsConfig, kinds: tuple[str, ...] = ("gold", "elixir", "dark")
                  ) -> dict[str, int]:
    """What each storage holds (no dark elixir on low town halls). The
    builder base has only ``("gold", "elixir")``: its third bar is gems."""
    game.refresh()
    maxes = {}
    if "dark" in kinds and not has_dark(game, regions):
        log.info("No dark elixir in this village yet (town hall 7): not reading its storages")
        kinds = tuple(k for k in kinds if k != "dark")
    for kind in kinds:
        held = _own(game, regions, f"own_{kind}")
        if held is None:
            continue  # no such bar
        most = storage_max(game, regions, kind)
        # A misread size (say, numbers read at the wrong place before the
        # UI's scale is known) would make that storage look full, or keep
        # nothing of it: only a size that can hold what's in it is kept.
        # A storage can hold more than its size, though (rewards go in over
        # it: 7 071 000 gold seen in 6 500 000, 12 724 973 elixir too): a
        # round size, as storages' are, not far under what's in it is then
        # believed all the same.
        over = most and most % ROUND_SIZE == 0 and held <= most * OVER_FULL
        if most and most >= LEAST_STORAGE and (most >= held or over):
            maxes[kind] = most
        elif most:
            log.info("Storage size read as %s for %s holding %s: not believed", f"{most:,}", kind, f"{held:,}")
    return maxes


FULL_AMOUNT = 0.99  # of what a storage holds: a little short of it is full enough


def full_by_amount(loot: Loot, maxes: dict[str, int]) -> set[str]:
    """Which storages are full, from what's in them and what they hold."""
    return {k for k, most in maxes.items() if getattr(loot, k) >= most * FULL_AMOUNT}


def start_search(game: Game, super_troops: bool = False, dark: int | None = None) -> int:
    """Home village → Battle → Find a Match → Attack! (army screen).
    ``super_troops``: on the army screen, boost the super troops showing
    Activate first, with ``dark``, the dark elixir you have. Returns how
    many were boosted."""
    game.refresh()
    # The battle menu may already be open (e.g. after a failed round).
    if not game.find(T.FIND_MATCH) and not game.click(T.BATTLE):
        raise SearchError("battle button not visible; is the home village showing?")
    if not _find_a_match(game, timeout=5):
        # A tap on Battle can go unanswered (the village just back from an
        # attack, say), or open a window first (the game's news, "League
        # Overview" after an update): closed, and Battle tapped once more.
        from farmbot.tasks.village import clear_popups

        if clear_popups(game, rounds=2):
            log.info("A window opened instead of the battle menu: closed it")
        if not (game.find(T.FIND_MATCH) or game.click(T.BATTLE)) or not _find_a_match(game, timeout=5):
            raise SearchError("find-a-match button did not appear")
    # Newer versions confirm the army first; older ones go straight to scouting.
    boosted = 0
    if super_troops and game.has(T.ARMY_ATTACK) and game.wait_for(T.ARMY_ATTACK, timeout=4):
        from farmbot.tasks.super_troops import activate_super_troops

        boosted = activate_super_troops(game, dark)
    if game.has(T.ARMY_ATTACK) and game.click_when_visible(T.ARMY_ATTACK, timeout=4):
        log.debug("Confirmed army")
    if game.has(T.LAYOUT_OBSTRUCTED):
        from farmbot.tasks.village import attack_despite_obstructed_layout

        game.wait(1.0)
        game.refresh()
        attack_despite_obstructed_layout(game)
    return boosted


# The battle menu has two "Find a Match" buttons: the regular Battle card's
# (x about 227 on the bot's screen) and Ranked Battle's (about 586), which
# spends one of the day's ranked attacks. Only one left of this is tapped:
# while a battle left midway still runs, the regular card shows a countdown
# instead, and as the menu opens Ranked Battle's can be drawn first, so
# "the leftmost one" alone would be Ranked Battle's.
REGULAR_MATCH_RIGHT = 407


def _find_a_match(game: Game, timeout: float) -> bool:
    """Tap the regular Battle's Find a Match, never Ranked Battle's. Raises
    :class:`SearchBlocked` if its card shows "Attack available in" (the
    lockout, shown in the menu). True if it was tapped."""
    deadline = game.clock() + timeout
    while True:
        game.refresh()
        if game.has(T.ATTACK_COOLDOWN) and game.find(T.ATTACK_COOLDOWN):
            log.warning("Attack countdown in the battle menu: %s", _screen_state(game))
            raise SearchBlocked("lockout screen detected (attack countdown): the Battle card says \"Attack "
                                "available in\" (a battle left without surrendering still runs)")
        if game.click(T.FIND_MATCH, region=Rect(0, 0, REGULAR_MATCH_RIGHT, game.size[1]), leftmost=True):
            return True
        if game.clock() >= deadline:
            return False
        game.wait(0.5, exact=True)


NEXT_TIMEOUT = 40  # s for a base to show (slow emulators and networks take a while on the clouds)
ARMY_RETAP = 3  # s the army window may stay up after Attack! before it's tapped again
RECALIBRATE_AFTER = 10  # s without Next before the UI scale is measured again on this screen
# "Unable to attack Village!" is drawn a little differently on some emulators:
# looked for less strictly than other pictures (it's only looked for here).
UNABLE_THRESHOLD = 0.72
# ...and the screen it's on is nearly all white: what's left when the picture misses.
WHITE_PIXEL = (40, 215)  # saturation at most, value at least
LOCKOUT_WHITE = 0.6  # share of the screen that white


def white_share(screen) -> float:
    """Share of ``screen`` that is plain white (the "Unable to attack" screen)."""
    import cv2

    small = cv2.resize(screen, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    white = (hsv[..., 1] <= WHITE_PIXEL[0]) & (hsv[..., 2] >= WHITE_PIXEL[1])
    return float(white.mean())


def _unable_to_attack(game: Game) -> bool:
    return game.has(T.UNABLE_TO_ATTACK) and game.find(T.UNABLE_TO_ATTACK, threshold=UNABLE_THRESHOLD) is not None


def _screen_state(game: Game) -> str:
    """What the screen looks like, for the log: each picture's score, the UI
    scale and how much of it is white."""
    return (f"{game.scores(T.NEXT, T.UNABLE_TO_ATTACK, T.RETURN_HOME)}; UI scale {game.ui_scale or 1.0:.2f}; "
            f"white {white_share(game.screen):.0%}")


def _blocked(game: Game, why: str) -> SearchBlocked:
    """The lockout: Return Home first if it's there, then the error that
    closes the game for a few minutes."""
    log.warning("Lockout screen (%s): %s", why, _screen_state(game))
    for button in (T.LOCKOUT_RETURN_HOME, T.RETURN_HOME):
        if game.has(button) and game.click(button):
            log.info("Pressed Return Home on the lockout screen")
            game.wait(1.0)
            break
    return SearchBlocked(f"lockout screen detected ({why}): Clash of Clans says \"Unable to attack Village! "
                         "Try again later.\" (a battle left without surrendering still runs)")


def _wait_for_base(game: Game, timeout: float = NEXT_TIMEOUT) -> bool:
    """Until a base shows (its Next button). Raises :class:`SearchBlocked`
    if the game says it can't attack. Halfway through a long wait the UI
    scale is measured again, in case Next is there at another size."""
    start = game.clock()
    deadline = start + timeout
    recalibrated = False
    tapped = start
    while True:
        game.refresh()
        if game.find(T.NEXT):
            return True
        if _unable_to_attack(game):
            raise _blocked(game, "its words")
        if game.clock() - tapped >= ARMY_RETAP and game.has(T.ARMY_ATTACK) and game.click(T.ARMY_ATTACK):
            # the army window still up: its Attack! tap went unanswered (18 Nov 2026)
            tapped = game.clock()
            log.info("The army window's Attack! didn't answer: tapped it again")
            continue
        if refresh_for_new_content(game):
            raise GameRefreshed("the game's \"New Content\" window showed instead of a base: refreshed")
        if game.has(T.RETURN_HOME) and game.find(T.RETURN_HOME):
            # A result screen instead of a base: the lockout's own Return
            # Home (its words drawn too differently to match), or a battle
            # left on its result.
            if white_share(game.screen) >= LOCKOUT_WHITE:
                raise _blocked(game, "a white screen with Return Home")
            log.warning("A battle result showed instead of a base: going home (%s)", _screen_state(game))
            game.click(T.RETURN_HOME)
            game.wait(1.0)
            raise NextNotFound("next button never appeared: a battle result showed instead of a base")
        if not recalibrated and game.clock() - start >= RECALIBRATE_AFTER:
            recalibrated = True
            if game.recalibrate(T.NEXT) and game.find(T.NEXT):
                return True
        if game.clock() >= deadline:
            if white_share(game.screen) >= LOCKOUT_WHITE:
                raise _blocked(game, "a white screen where a base should be")
            log.warning("Next not detected after %ds: %s", timeout, _screen_state(game))
            return False
        game.wait(0.5, exact=True)


NEW_CONTENT_RELOAD = 120  # s the game takes at most to reload to the village after Refresh


def refresh_for_new_content(game: Game) -> bool:
    """The game's "New Content" window ("Builder needs a moment to add new
    game data to the village... Choose Refresh to reload"): Refresh pressed,
    and the village waited for. Cancel would only bring it back. True if the
    window showed."""
    if not (game.has(T.NEW_CONTENT) and game.find(T.NEW_CONTENT)):
        return False
    log.info("The game has new content to load: pressing Refresh")
    if not game.click(T.NEW_CONTENT_REFRESH):
        return False
    if not game.wait_for(T.BATTLE, timeout=NEW_CONTENT_RELOAD):
        log.warning("The village didn't show within %ds of Refresh", NEW_CONTENT_RELOAD)
    return True


def _press_next(game: Game, delay: float) -> None:
    """Tap Next (looked for once more if it's gone a moment), then wait."""
    if not game.click(T.NEXT):
        game.wait(1.0, exact=True)
        game.refresh()
        if not game.click(T.NEXT):
            log.warning("Next not detected to tap: %s", _screen_state(game))
            raise NextNotFound("next button disappeared")
    game.wait(delay)


SAME_VIEW = 8.0  # mean grey difference (of 255) below which two looks at a base are the same base


def _view(screen):
    """A small grey picture of the screen: enough to tell two bases apart."""
    import cv2

    small = cv2.resize(screen, None, fx=0.125, fy=0.125, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype("int16")


def same_base(before, after) -> bool:
    """Whether two small views (see :func:`_view`) show the same base: the
    loot alone can be the same on two bases."""
    if before is None or after is None or before.shape != after.shape:
        return False
    return float(abs(after - before).mean()) < SAME_VIEW


MAX_UNREADABLE = 3  # bases in a row whose loot can't be read before giving up


def search(game: Game, criteria: SearchConfig, regions: RegionsConfig, on_base: BaseCallback | None = None,
           zoom_out: bool = False, look: bool = False, near: bool = False) -> Loot:
    """Press Next until a base meets ``criteria``; returns its loot.
    ``zoom_out``: the village was left zoomed in (on an upgrade), and the
    battle opens at its zoom: zoom out on the first base. ``look``: look at
    each base a while first, as a person would ("Look at each base").
    ``near``: "Imperfect choices": a base just under the minimums is
    sometimes attacked, one just over them sometimes passed over.

    Must be called after :func:`start_search`. Raises :class:`SearchError`
    if the search gets stuck or exceeds ``criteria.max_searches``.
    """
    last: Loot | None = None
    last_view = None
    repeats = unreadable = 0
    zoomed = zoom_out
    boost: int | None = None  # the loot boost, read on the first base whose loot reads
    for count in range(1, criteria.max_searches + 1):
        if not _wait_for_base(game):
            raise NextNotFound(f"next button never appeared in {NEXT_TIMEOUT}s; search screen not loaded")
        game.wait(0.5)  # let the loot counters finish animating
        if count == 1 and zoom_out:
            game.zoom_out()
        game.refresh()
        loot = read_settled_loot(game, regions)
        if loot is None and not zoomed:
            # The battle opens at the village's zoom: left zoomed in on an
            # upgrade, the base's health bars can sit over the numbers.
            zoomed = True
            game.zoom_out()
            loot = read_settled_loot(game, regions)
        if loot is None:
            unreadable += 1
            if unreadable >= MAX_UNREADABLE:
                raise LootUnreadable(f"could not read available loot on {unreadable} bases in a row (UI scale "
                                     f"{game.ui_scale or 1.0:.2f}); check regions and the loot font")
            log.warning("Base %d: loot OCR failed; skipping it", count)
            _press_next(game, criteria.next_delay)
            continue
        unreadable = 0
        if boost is None:
            boost = loot_boost(game, regions)
            if boost > 1:
                log.info("Loot boost %dx on: each base is judged on its loot shown divided by %d", boost, boost)
        held = unboosted(loot, boost)
        accepted = is_worth_attacking(held, criteria)
        slip = near_miss(game.rng, held, criteria, accepted) if near else None
        if slip is not None:
            accepted = slip
        log.info("Base %d: gold %s, elixir %s, dark %s%s%s%s", count, f"{held.gold:,}", f"{held.elixir:,}",
                 f"{held.dark:,}", f" ({boost}x shown)" if boost > 1 else "", "  → attack" if accepted else "",
                 "" if slip is None else " (a little under the minimums: taken anyway)" if slip else
                 " (meets the minimums, only just: passed over)")
        if on_base:
            on_base(held, accepted)
        look_at_base(game, held, criteria, accepted, look)
        if accepted:
            return loot
        view = _view(game.screen)
        if loot == last and same_base(last_view, view):
            repeats += 1
            if repeats >= 2:
                raise NextDidNothing("next tap did not change the base (tapped again, still the same); "
                                     "search is stuck")
            log.info("Base %d is the one before: the Next tap didn't take; tapping it again", count)
        else:
            repeats = 0
        last, last_view = loot, view
        _press_next(game, criteria.next_delay)
    raise SearchError(f"no base matched after {criteria.max_searches} searches")

"""Clan Games (beta): take a challenge the farm can do, and pick the rewards.

The games run once a month, from the 22nd 08:00 UTC for six days; the
rewards are picked in the week after. The board opens from the event
buttons at the bottom of the home village (the bearded builder with a log;
the "<" at their end folds them away, and ">" brings them back), or from
the caravan at the top of the village, which says "Choose" while no
challenge is going. It holds eight challenges, each with its points under
it. Tapping one shows its name, what it asks ("Collect a total of 3x Stars
from Multiplayer Battles."), its points and its time, and Start. Only one
runs at a time: it moves to the first place, with a gold frame and its
progress ("0/3"), and the others grey out. A started challenge can be
trashed (only a started one: the board shows no other way to get rid of
one); no other can be started for 10 minutes after.

Which challenges the farm can do:

* stars, loot and destroying buildings in multiplayer battles: they go on
  by themselves while it farms;
* Builder Base challenges (told by their card's dark teal frame with
  stars; a home one's is light blue): the bot sails over and fights
  Builder Base battles for them, in any mode, once the builder base is
  unlocked;
* "Earn a Star ... using at least one <unit>": while the army has that
  unit. The unit is told from the challenge's picture (the same as the
  donate window's, in ``templates/donate``), and looked for in the army
  window (Battle, Edit Army).

A challenge is told by its name, read with Windows' OCR (the names read
well; the sentences under them don't), and failing that by words of its
sentence. One it can't tell is left alone. With none it can do, one it
can't is started and trashed for a new one (``trade_in``): it costs
nothing but the 10 minutes.

The rewards: one from each tier the clan unlocked, from the board's Rewards
tab, once the games are over. A magic item first (a reward with an "i" on
it), then gems, then the first one. These screens only show in that week:
each step is saved to ``logs/`` to check on.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from farmbot.game import Game, T
from farmbot.geometry import Rect

log = logging.getLogger(__name__)

# The games: the 22nd from 08:00 UTC for six days; then a week for the rewards.
START_DAY = 22
START_HOUR = 8
GAMES = timedelta(days=6)
REWARDS = timedelta(days=7)

# Clearing out costs 10 minutes with no challenge: only while the board runs low on ones the farm can do.
CLEAR_OUT_BELOW = 3  # others doable on the board (besides the one started)
TRASH_WAIT = 10 * 60 + 30  # s: no challenge can start for 10 minutes after one is trashed
LOOK_EVERY = 60 * 60  # s between looks at the board while a challenge goes (the caravan's "Choose" says sooner)
LOOK_AGAIN = 30 * 60  # s: the board couldn't be read, or nothing on it could be done
OPEN_WAIT = 5.0  # s for the board to open
POPUP_WAIT = 3.0  # s for a challenge's window (Start or Trash) to show
SCROLL_FROM_MEDAL = (-55, -60)  # where the scroll starts off the lowest row's medal: on its tile's picture
SCROLL_BY = 380  # px up: past the board's end (it stops there), about two rows
SCROLL_BACK_INSIDE = 80  # px: the way back starts this far below where the way down ended
SCROLL_WAIT = 1.2  # s for the board to stop scrolling
CLOSE_SETTLE = 0.6  # s after a challenge's window closes before the board takes taps again

# A tile, from the medal after its points: where its picture is (to tap it,
# and to tell a unit's challenge from it) and where its points are.
TILE_FROM_MEDAL = (-55, -97)
# A Builder Base challenge's card has a dark teal frame (with stars), a home one a light blue one: the frame's
# sides, this far from the card's middle (px), told by their colour (HSV saturation and brightness).
FRAME_SIDE = (67, 74)
FRAME_TALL = 40  # px above and below the middle
BUILDER_FRAME = (190, 170)  # a builder card's frame: saturation at least this, brightness under this
ART_HALF = 72  # px: half the picture's box
POINTS_FROM_MEDAL = (-100, -17, 86, 34)  # x, y, w, h off the medal's middle
GREEN = 80  # least mean saturation of a Start that can be pressed (a greyed one is near 0)

# The challenge's window, from its Start (or Trash): its name, and what it asks.
NAME_BOX = (-300, -238, 430, 38)  # x, y, w, h off the button's middle
TEXT_BOX = (-275, -168, 385, 56)
OCR_ZOOM = 2.5
MEDALS_WAIT = 3.0  # s for a done challenge's medals to fly to the score
TRASH_LOWER = 21  # px a Trash sits below where the Start is
GOING_TO_TILE = (45, 47)  # off the stopwatch: the going challenge's picture
# "Your Score: 0/10000", under the left picture, from the "Clan Games" sign.
SCORE_BOX = (-150, 560, 280, 90)
PROGRESS_FROM_GOING = (-25, 125, 140, 36)  # x, y, w, h off the stopwatch: the going challenge's "2/6"

# Unit pictures: the donate window's, about 1.5 times bigger on a challenge
# and 0.9 times in the army window.
UNIT_SIZES = (1.3, 1.4, 1.5, 1.6, 1.7)
UNIT_SURE = 0.8  # the right unit ~0.9, the next best under 0.75
UNIT_AHEAD = 0.1  # ...and this far ahead of any other
ARMY_SIZES = (0.85, 0.9, 0.95)
ARMY_LEFT = 25  # px left of the Clan Castle row's label where the army's cards begin (the heroes end before)
ARMY_SURE = 0.72  # in the army: units there 0.77-0.86, others under 0.66

# What each kind of challenge counts for when picking: points times this.
# Stars and loot come with every battle; buildings of one kind may not all
# fall in time.
FIGHT_FOR = ("stars", "destroy", "unit")  # challenges a battle fought to its end helps
WORTH = {"stars": 1.0, "loot": 1.0, "unit": 0.9, "builder": 0.9, "destroy": 0.8}

# Challenge names, in lower case, and their kinds.
NAMES = {
    "star collector": "stars",
    "gold grab": "loot",
    "elixir embezzlement": "loot",
    "heavy lifting": "loot",
    "dark elixir challenge": "loot",
    "dark elixir heist": "loot",
    "building boom boom": "builder",
    "builder hall blow up": "builder",
    "healing hut havoc": "builder",
    "destroy tesla towers": "destroy",
    "destroy air defenses": "destroy",
    "destroy x bows": "destroy",
    "dark spell factory sabotage": "destroy",
    "spell factory sabotage": "destroy",
    "anger management": "unit",
    "getting over it": "unit",
    "lava is love": "unit",
    "rocking along": "unit",
    "icy onslaught": "unit",
    "battle blimp boogie": "unit",
    "reigning champion": "unit",  # (a star using the Royal Champion: a hero's isn't told apart)  # (with a Battle Blimp: taken only if the army has the unit it shows)
}
# What each loot challenge fills; its storage (near) full, it's skipped: it
# can hardly go on (a full storage takes nothing in).
LOOT_OF = {
    "gold grab": ("gold",),
    "elixir embezzlement": ("elixir",),
    "heavy lifting": ("dark",),
    "dark elixir challenge": ("dark",),
    "dark elixir heist": ("dark",),
}
CLOSE_TO_FULL = 0.9  # of what a storage holds: from here it counts as full for loot challenges
NAME_ALIKE = 0.75  # how alike a read name and a known one must be (OCR reads "Stan Collect0R")
WORD_ALIKE = 0.8  # the same for single words of the sentence
# Words of a challenge the farm can't do: it's never taken, whatever else it says.
# Buildings a "Destroy ..." challenge names (its "Destroy" doesn't always read).
BUILDINGS = ("factory", "defense", "defenses", "tower", "towers", "mortar", "mortars", "cannon", "cannons",
             "inferno", "eagle", "artillery", "scattershot", "xbow", "bow", "bows", "barracks", "laboratory",
             "storage", "storages", "collector", "collectors", "drill", "drills", "mine", "mines", "monolith",
             "sweeper", "trap", "traps", "buildings", "walls", "hall")
NEVER = ("donate", "donations", "war", "capital", "raid", "obstacles", "gems", "ability", "train", "boost")


@dataclass
class Tile:
    """One challenge on the board."""

    point: tuple[int, int]  # its picture's middle (tapped to open it)
    points: int | None
    art: np.ndarray  # its picture
    unit: str | None = None  # the donate picture it shows ("lava_hound"), for a unit's challenge
    name: str = ""
    text: str = ""
    kind: str | None = None
    page: int = 0  # 0: the board as it opens, 1: scrolled to its end (13 challenges don't fit at once)
    builder: bool = False  # a Builder Base challenge (its card's frame is dark teal)


@dataclass
class Visit:
    """What a look at the board came to, and when to look again (s)."""

    started: str = ""  # the challenge started
    traded: bool = False  # one was started and trashed for a new one
    going: bool = False  # a challenge was going already
    capped: bool = False  # the player's score is full
    wait: float = LOOK_AGAIN
    kind: str | None = None  # what the challenge going (or started) is: "stars", "destroy"...
    name: str = ""


@dataclass
class Memory:
    """What the bot keeps between looks: challenges told before (by their
    picture and points: tapping each one costs a look with OCR), and what
    the army had."""

    known: list[tuple[np.ndarray, int | None, str, str, str | None]] = field(default_factory=list)
    army: dict[str, bool] = field(default_factory=dict)
    army_read: float | None = None  # game clock when the army was looked at
    going: tuple[str, str | None] | None = None  # the challenge going: its name and kind
    going_points: int | None = None  # what it's worth
    sure: bool = False  # ``going`` was seen this run (one kept from before is looked at once: it may be stale)
    score: int | None = None  # your score as last read, plus challenges done since (it doesn't always read)
    progress: int | None = None  # how far the challenge going was, as last seen (its note, or the board)
    idle: int = 0  # its battles since it last went on (no note after them)

    def new_going(self, what: tuple[str, str | None] | None, points: int | None = None) -> None:
        """Another challenge is going (or none): its progress starts over."""
        self.going, self.going_points, self.progress, self.idle = what, points, None, 0

    def recall(self, tile: Tile) -> bool:
        sig = _signature(tile.art)
        for known, points, name, text, kind in self.known:
            if points == tile.points and float(np.abs(known - sig).mean()) < 6:
                tile.name, tile.text = name, text
                tile.kind = classify(name, text, tile.unit, tile.builder)  # (as now: the rules may have changed since)
                return True
        return False

    def keep(self, tile: Tile) -> None:
        self.known.append((_signature(tile.art), tile.points, tile.name, tile.text, tile.kind))
        del self.known[:-40]

    def save(self, path: Path | None, ends: datetime | None) -> None:
        """Kept beside the profile, for these games (``ends``): a restart
        doesn't open every challenge again."""
        if path is None:
            return
        data = {"ends": ends.isoformat() if ends else None, "going": list(self.going) if self.going else None,
                "going_points": self.going_points, "score": self.score, "progress": self.progress,
                "idle": self.idle,
                "known": [{"picture": sig.astype(int).ravel().tolist(), "points": points, "name": name,
                           "text": text, "kind": kind} for sig, points, name, text, kind in self.known]}
        try:
            Path(path).write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            log.debug("Clan Games: couldn't keep what's known: %s", e)

    @classmethod
    def load(cls, path: Path | None, ends: datetime | None) -> "Memory":
        """What was kept for these games (``ends``), or nothing."""
        memory = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else None
        except (OSError, ValueError):
            data = None
        if not data or data.get("ends") != (ends.isoformat() if ends else None):
            return memory  # other games' challenges
        try:
            for k in data.get("known") or []:
                sig = np.array(k["picture"], np.float32).reshape(16, 16)
                memory.known.append((sig, k.get("points"), k.get("name", ""), k.get("text", ""), k.get("kind")))
            going = data.get("going")
            memory.going = (going[0], going[1]) if going else None
            memory.going_points, memory.score = data.get("going_points"), data.get("score")
            memory.progress, memory.idle = data.get("progress"), int(data.get("idle") or 0)
        except (KeyError, TypeError, ValueError):
            return cls()
        return memory


def memory_path(village_path) -> Path | None:
    """Beside the village export: ``x.village.json`` -> ``x.clan_games.json``."""
    if village_path is None:
        return None
    p = Path(village_path)
    return p.with_name(p.name.replace("village", "clan_games") if "village" in p.name else p.stem + ".clan_games.json")


def _signature(art: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY) if art.ndim == 3 else art
    return cv2.resize(grey, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)


# -- when ------------------------------------------------------------------
def _start_of(year: int, month: int) -> datetime:
    return datetime(year, month, START_DAY, START_HOUR, tzinfo=timezone.utc)


def phase(now: datetime) -> tuple[str | None, datetime | None]:
    """("games", their end), ("rewards", the end of the week to pick them)
    or (None, None), at ``now`` (UTC if it has no zone)."""
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    last = (now.year, now.month) if now.day >= START_DAY else (
        (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1))
    for year, month in ((now.year, now.month), last):
        start = _start_of(year, month)
        if start <= now < start + GAMES:
            return "games", start + GAMES
        if start + GAMES <= now < start + GAMES + REWARDS:
            return "rewards", start + GAMES + REWARDS
    return None, None


# -- telling challenges ----------------------------------------------------
def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", text.lower().replace("0", "o"))).strip()


def _has(words: list[str], word: str, shortest: int = 4) -> bool:
    """``word`` is among ``words``, or one alike as read (words this short
    or longer: a short one is too like others)."""
    return any(w == word or (len(word) >= shortest and difflib.SequenceMatcher(None, w, word).ratio() >= WORD_ALIKE)
               for w in words)


def known_name(name: str) -> str | None:
    """The known challenge name ``name`` (as read) is, if it's one."""
    plain = _plain(name)
    if not plain:
        return None
    best = max(NAMES, key=lambda known: difflib.SequenceMatcher(None, plain, known).ratio())
    return best if difflib.SequenceMatcher(None, plain, best).ratio() >= NAME_ALIKE else None


def classify(name: str, text: str, unit: str | None = None, builder_card: bool = False) -> str | None:
    """The kind of a challenge from its name and sentence as read (and the
    unit its picture shows, and whether its card is a Builder Base one):
    "stars", "loot", "destroy", "builder", "unit", or ``None`` for one the
    farm can't do or that isn't understood."""
    words = _plain(f"{name} {text}").split()
    if any(_has(words, w, 6) for w in NEVER):  # ("gems" reads alike "golems")
        return None
    if builder_card:  # (whatever it asks, Builder Base battles play it)
        return "builder"
    known = known_name(name)
    if known is not None:
        return NAMES[known]
    if unit is not None:
        return "unit"
    if _has(words, "using"):  # ("... using the Royal Champion", "... using a Battle Blimp"): only with that one
        return "unit"
    builder = _has(words, "builder")
    if _has(words, "destroy"):
        return "builder" if builder else "destroy"
    if builder:
        return "builder" if _has(words, "battles") or _has(words, "stars") else None
    if _has(words, "stars") or _has(words, "star"):
        return "stars"
    if any(_has(words, w) for w in ("loot", "gold", "elixir")):
        return "loot"
    if any(_has(words, w, 6) for w in BUILDINGS):
        return "destroy"
    return None


def stuck_after(cfg) -> int:
    """Battles with no progress after which the challenge going is traded
    in (0: never)."""
    try:
        return max(0, int(getattr(cfg, "stuck_after", 0) or 0))
    except (TypeError, ValueError):
        return 0


def goal_of(cfg) -> int:
    """The score to play up to ("Play up to"): 10,000 unless set lower."""
    try:
        return int(getattr(cfg, "goal", "10000") or 10000)
    except (TypeError, ValueError):
        return 10000


# What a battle brings, on average, toward a challenge (loot: as this session's battles brought, when known):
# its points over the battles it takes pick it (the score climbs fastest).
PER_BATTLE = {"stars": 1.5, "destroy": 2.0, "unit": 1.0, "builder": 2.0,
              "gold": 600_000, "elixir": 600_000, "dark": 4_000}
GUESS_BATTLES = 5.0  # a challenge whose number didn't read


def need_of(text: str) -> int | None:
    """The number a challenge's sentence asks for ("Loot 500,000 Gold": 500000)."""
    found = [int(re.sub(r"\D", "", n)) for n in re.findall(r"\d[\d,.]*", text or "")]
    # ("10x" read "IOX", "1x" "lx", "60x" "GOX": a count before its x)
    for count in re.findall(r"(?<![A-Za-z])([0-9IlOoSG]{1,3})\s?[xX](?![A-Za-z])", text or ""):
        digits = count.translate(str.maketrans("IlOoSG", "110056"))
        if digits.isdigit():
            found.append(int(digits))
    found = [n for n in found if n > 0]
    return max(found) if found else None


def battles_for(tile: "Tile", per_battle: dict | None = None) -> float:
    """About how many battles the challenge takes (1 at least)."""
    rates = {**PER_BATTLE, **(per_battle or {})}
    need = need_of(tile.text)
    if need is None or not tile.kind:
        return GUESS_BATTLES
    if tile.kind == "loot":
        rate = max(rates.get(k, 0) for k in loot_for(tile.name, tile.text))
    else:
        rate = rates.get(tile.kind, 1.0)
    return max(1.0, need / rate) if rate > 0 else GUESS_BATTLES


def loot_for(name: str, text: str = "") -> tuple[str, ...]:
    """The storages a loot challenge fills (any one of them helps): by
    its name, else by the words of its sentence, else any of the three."""
    known = known_name(name)
    if known in LOOT_OF:
        return LOOT_OF[known]
    words = _plain(f"{name} {text}").split()
    if _has(words, "dark"):
        return ("dark",)
    if _has(words, "elixir"):
        return ("elixir",)
    if _has(words, "gold"):
        return ("gold",)
    return ("gold", "elixir", "dark")


def nearly_full(loot, maxes: dict[str, int]) -> set[str]:
    """The storages full or close to it (``CLOSE_TO_FULL``): ``loot``
    (what's in them) against ``maxes`` (what they hold)."""
    return {k for k, most in maxes.items() if most and getattr(loot, k, 0) >= most * CLOSE_TO_FULL}


def _filled(name: str, text: str, full) -> bool:
    """A loot challenge every storage of which is (near) full."""
    return bool(full) and all(r in full for r in loot_for(name, text))


def unit_on(art: np.ndarray, pictures: dict[str, np.ndarray]) -> str | None:
    """The unit a challenge's picture shows (a ``templates/donate`` name),
    if it clearly shows one."""
    scores = []
    for name, picture in pictures.items():
        best = 0.0
        for size in UNIT_SIZES:
            sized = cv2.resize(picture, None, fx=size, fy=size, interpolation=cv2.INTER_LINEAR)
            if sized.shape[0] > art.shape[0] or sized.shape[1] > art.shape[1]:
                break
            best = max(best, float(cv2.minMaxLoc(cv2.matchTemplate(art, sized, cv2.TM_CCOEFF_NORMED))[1]))
        scores.append((best, name))
    if not scores:
        return None
    scores.sort(reverse=True)
    first, name = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    return name if first >= UNIT_SURE and first - second >= UNIT_AHEAD else None


def in_army(screen: np.ndarray, area: Rect, picture: np.ndarray) -> bool:
    """Whether the army window's ``area`` (the army's rows, not the Clan
    Castle's) shows the unit ``picture``."""
    part = screen[max(0, area.y):area.y + area.h, max(0, area.x):area.x + area.w]
    for size in ARMY_SIZES:
        sized = cv2.resize(picture, None, fx=size, fy=size, interpolation=cv2.INTER_AREA)
        if sized.shape[0] > part.shape[0] or sized.shape[1] > part.shape[1]:
            continue
        if cv2.minMaxLoc(cv2.matchTemplate(part, sized, cv2.TM_CCOEFF_NORMED))[1] >= ARMY_SURE:
            return True
    return False


def _unit_pictures(game: Game) -> dict[str, np.ndarray]:
    root = game.vision.library.root / T.DONATE_ITEM_DIR
    return {p.stem: game.vision.library._load(p) for p in sorted(root.glob("*.png")) if "@" not in p.stem}


# -- the board -------------------------------------------------------------
def ready(game: Game) -> bool:
    return all(game.has(n) for n in (T.CG_TITLE, T.CG_MEDAL, T.CG_START, T.CG_TRASH, T.CG_CLOSE))


def open_board(game: Game) -> bool:
    """Open the Clan Games board from the village: the event button (the
    event buttons unfolded first if they're folded), or the caravan's
    "Choose". True once it shows."""
    game.refresh()
    if game.find(T.CG_TITLE) is not None:
        return True
    button = game.find(T.CG_ICON) if game.has(T.CG_ICON) else None
    if button is None and game.has(T.CG_UNFOLD) and game.click(T.CG_UNFOLD):
        game.wait(0.8)
        game.refresh()
        button = game.find(T.CG_ICON)
    if button is None and game.has(T.CG_CHOOSE):
        button = game.find(T.CG_CHOOSE)
    if button is None:
        return False
    game.tap_match(button)
    game.screen = None
    if game.wait_for(T.CG_TITLE, timeout=OPEN_WAIT, interval=0.4) is None:
        return False
    _scroll["page"] = 0  # it opens at its top
    game.wait(0.6)  # the tiles pop in
    game.refresh()
    return True


def close_board(game: Game) -> None:
    from farmbot import screens

    for _ in range(3):
        game.refresh()
        if game.find(T.CG_TITLE) is None and game.find(T.CG_TRASH_TITLE) is None:
            return
        if not game.click(T.CG_CLOSE):
            break
        game.wait(0.8)
    screens.settle(game)


def _title(game: Game):
    return game.find(T.CG_TITLE)


def going(game: Game) -> bool:
    """A challenge is going (its tile shows a stopwatch, in a gold frame)."""
    return _clock(game) is not None


# The stopwatch's hand turns, and the going challenge's picture can reach over
# it (Gold Grab's sack): it scores 0.72 and up, a board without one 0.56 at most.
GOING_SURE = 0.68


def _clock(game: Game):
    """The stopwatch on the going challenge's tile, if one is going."""
    return game.find(T.CG_GOING, threshold=GOING_SURE) if game.has(T.CG_GOING) else None


# Where the board is scrolled to, and the swipe that scrolled it (from the
# medals: they're only found on a board that opened at its top).
_scroll: dict = {"page": 0, "swipe": None}


def _show_page(game: Game, page: int) -> None:
    """Scroll the board to ``page`` (0 its top, 1 its end)."""
    swipe = _scroll["swipe"]
    if page == _scroll["page"] or swipe is None:
        return
    x, y1, y2 = swipe
    if page:
        game.swipe(x, y1, x, y2, 500)
    else:  # down, from inside the tiles (y2 is above them)
        game.swipe(x, y2 + SCROLL_BACK_INSIDE, x, y1 + SCROLL_BACK_INSIDE, 500)
    game.wait(SCROLL_WAIT, exact=True)
    game.screen = None
    game.refresh()
    _scroll["page"] = page


def read_board(game: Game) -> list[Tile]:
    """All the challenges that can be started: those in view as the board
    opens, then those at its end (scrolled to, and left there)."""
    tiles = read_tiles(game)
    if not tiles:
        return tiles
    lowest = max(tiles, key=lambda t: t.point[1])
    x, y = lowest.point[0], lowest.point[1] - TILE_FROM_MEDAL[1] + SCROLL_FROM_MEDAL[1]
    _scroll["swipe"] = (x, y, y - SCROLL_BY)
    _show_page(game, 1)
    more = [t for t in read_tiles(game, page=1)
            if not any(t.points == o.points and float(np.abs(_signature(t.art) - _signature(o.art)).mean()) < 6
                       for o in tiles)]  # rows seen in both views (or a board that didn't scroll)
    if more:
        log.info("Clan Games: %d more challenge(s) further down the board", len(more))
    return tiles + more  # (left at its end: the challenges there are told first, then those at the top)


def read_tiles(game: Game, page: int = 0) -> list[Tile]:
    """The challenges in view that can be started (in colour: with one
    going, or just after one was trashed, they're grey), with their points."""
    screen = game.screen if game.screen is not None else game.refresh()
    font = game.vision.font(T.LOOT_FONT)
    tiles = []
    for medal in sorted(game.find_all(T.CG_MEDAL), key=lambda m: (round(m.y / 40), m.x)):
        x, y = medal.point
        bx, by, bw, bh = POINTS_FROM_MEDAL
        points = font.read_number(screen, Rect(x + bx, y + by, bw, bh))
        cx, cy = x + TILE_FROM_MEDAL[0], y + TILE_FROM_MEDAL[1]
        art = screen[max(0, cy - ART_HALF):cy + ART_HALF, max(0, cx - ART_HALF):cx + ART_HALF].copy()
        tiles.append(Tile((cx, cy), points, art, page=page, builder=is_builder_card(screen, (cx, cy))))
    return tiles


def is_builder_card(screen: np.ndarray, middle: tuple[int, int]) -> bool:
    """The card around ``middle`` is a Builder Base challenge's: its frame's
    sides are dark teal (a home card's are light blue; a grey card, on a
    board with one going, is neither)."""
    cx, cy = middle
    near, far = FRAME_SIDE
    top, bottom = max(0, cy - FRAME_TALL), cy + FRAME_TALL
    sides = [screen[top:bottom, max(0, cx - far):max(0, cx - near)], screen[top:bottom, cx + near:cx + far]]
    sides = [side for side in sides if side.size]
    if not sides:
        return False
    hsv = cv2.cvtColor(np.vstack([side.reshape(-1, 1, 3) for side in sides]), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    saturation, brightness = float(hsv[:, 1].mean()), float(hsv[:, 2].mean())
    return saturation >= BUILDER_FRAME[0] and brightness < BUILDER_FRAME[1]


def _ocr(image: np.ndarray, zoom: float) -> list[str]:
    from farmbot import redact

    return [text for _, text in (redact.read_text(image, zoom) or [])]


def read_popup(screen: np.ndarray, button: tuple[int, int], trash: bool = False) -> tuple[str, str]:
    """A challenge window's name and sentence, read from above its Start
    (or its Trash, which sits lower): both in one look (each look at the
    OCR takes ~1.5 s)."""
    x, y = button
    y -= TRASH_LOWER if trash else 0

    def box(spec):
        bx, by, bw, bh = spec
        return screen[max(0, y + by):y + by + bh, max(0, x + bx):x + bx + bw]

    name, text = box(NAME_BOX), cv2.cvtColor(cv2.cvtColor(box(TEXT_BOX), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    if not name.size or not text.size:
        return "", ""
    width = max(name.shape[1], text.shape[1])
    pad = lambda im: cv2.copyMakeBorder(im, 0, 12, 0, width - im.shape[1], cv2.BORDER_CONSTANT, value=(235, 235, 235))
    lines = _ocr(np.vstack([pad(name), pad(text)]), OCR_ZOOM)
    if not lines:
        return "", ""
    return lines[0], " ".join(lines[1:])


def _fraction(lines: list[str]) -> tuple[int, int] | None:
    for line in lines:
        found = re.search(r"(\d[\d,. ]*)\s*/\s*(\d[\d,. ]*)", line)
        if found:
            a, b = (int(re.sub(r"\D", "", g)) for g in found.groups())
            if 0 < b <= 100000 and a <= b:
                return a, b
    return None


def read_progress(game: Game) -> tuple[int, int] | None:
    """How far the going challenge is ("2/6" under its picture), if it reads."""
    clock = _clock(game)
    if clock is None:
        return None
    bx, by, bw, bh = PROGRESS_FROM_GOING
    x, y = clock.point
    return _read_fraction(game.screen[max(0, y + by):y + by + bh, max(0, x + bx):x + bx + bw])


def _read_fraction(part: np.ndarray) -> tuple[int, int] | None:
    """A white "8/10" on a bar: the white alone first (the bar's yellow
    behind it confuses the OCR), then as it is."""
    if not part.size:
        return None
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 1] < 60) & (hsv[..., 2] > 200)).astype(np.uint8) * 255
    plain = cv2.copyMakeBorder(cv2.cvtColor(255 - white, cv2.COLOR_GRAY2BGR), 10, 10, 10, 10,
                               cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return _fraction(_ocr(plain, 2.0)) or _fraction(_ocr(part, 2.0))


# The note the home village shows for a few seconds after a battle that
# helped the challenge going (bottom right): "Challenge Progress" over its
# bar, "Completed!" on it once it's done (with "New Challenge" under it).
NOTE_WAIT = 2.0  # s after Return Home: the note slides in within ~1 s (and stays ~3 s)
NOTE_SETTLE = 0.4  # s: it slides in
NOTE_BAR = (-130, 6, 242, 30)  # its bar, from the title's middle: x, y, w, h


def _completed(lines: list[str]) -> bool:
    """ "Completed!" as read ("C0Mp1ete!")."""
    for line in lines:
        plain = re.sub(r"[^a-z]", "", line.lower().replace("0", "o").replace("1", "l"))
        if "complet" in plain or "mplete" in plain or (
                plain and difflib.SequenceMatcher(None, plain, "completed").ratio() >= 0.7):
            return True
    return False


def catch_note(game: Game, wait: float = NOTE_WAIT) -> np.ndarray | None:
    """Right after Return Home: the challenge's note, if one comes (it
    shows only a few seconds, when a challenge is completed): its bar,
    cut out to be read later (:func:`note_says`); ``None`` if none came."""
    if not game.has(T.CG_NOTE):
        return None
    deadline = game.clock() + wait
    while True:
        game.refresh()
        if game.find(T.CG_NOTE) is not None:
            break
        if game.clock() >= deadline:
            return None
        game.wait(0.3, exact=True)
    game.wait(NOTE_SETTLE, exact=True)
    game.refresh()
    title = game.find(T.CG_NOTE)
    if title is None:
        return np.zeros((0, 0, 3), np.uint8)
    x, y, w, h = NOTE_BAR
    return game.screen[max(0, title.y + y):title.y + y + h, max(0, title.x + x):title.x + x + w].copy()


def note_says(part: np.ndarray):
    """What a note's bar says: "done" ("Completed!"), the progress (3, 10),
    or "" if it doesn't read."""
    if part is None or not part.size:
        return ""
    lines = _ocr(part, 2.0)
    if _completed(lines):
        return "done"
    return _fraction(lines) or _read_fraction(part) or ""


def read_note(game: Game, wait: float = NOTE_WAIT):
    """The challenge's note: "done", its progress, "" for one seen but not
    read, or ``None`` with no note."""
    part = catch_note(game, wait)
    return None if part is None else note_says(part)


def read_score(game: Game) -> tuple[int, int] | None:
    """"Your Score": (points, most), if it reads."""
    title = _title(game)
    if title is None:
        return None
    bx, by, bw, bh = SCORE_BOX
    x, y = title.point
    screen = game.screen
    return _read_fraction(screen[max(0, y + by):y + by + bh, max(0, x + bx):x + bx + bw])


def _popup_button(game: Game):
    for name in (T.CG_START, T.CG_TRASH):
        found = game.find(name)
        if found is not None:
            return found
    return None


def _close_popup(game: Game) -> None:
    """Tap the Challenges tab (already open): the challenge's window closes."""
    game.refresh()
    if _popup_button(game) is None:
        return
    if game.has(T.CG_CHALLENGES_TAB) and game.click(T.CG_CHALLENGES_TAB):
        for _ in range(6):
            game.wait(0.3, exact=True)
            game.refresh()
            if _popup_button(game) is None:
                game.wait(CLOSE_SETTLE, exact=True)  # a tap while it fades is lost
                return


def _open_tile(game: Game, tile: Tile):
    """Tap the tile: its window's Start (or Trash), once it shows."""
    _close_popup(game)
    _show_page(game, tile.page)
    for _ in range(2):  # once more if the tap was lost (the last window still fading)
        game.tap(*tile.point)
        game.screen = None
        deadline = game.clock() + POPUP_WAIT / 2
        while game.clock() < deadline:
            game.wait(0.3, exact=True)
            game.refresh()
            button = _popup_button(game)
            if button is not None:
                return button
    return None


def tell(game: Game, tile: Tile, memory: Memory | None) -> None:
    """Fill in what the challenge is: from memory, or its window."""
    if memory is not None and memory.recall(tile):
        return
    button = _open_tile(game, tile)
    if button is None:
        log.info("Clan Games: a challenge's window didn't open")
        return
    tile.name, tile.text = read_popup(game.screen, button.point, button.name.startswith(T.CG_TRASH))
    tile.kind = classify(tile.name, tile.text, tile.unit, tile.builder)
    log.info("Clan Games: %r (%s points): %s", tile.name or "?", tile.points, tile.kind or "not one to take")
    if memory is not None and tile.name:
        memory.keep(tile)


def read_going(game: Game) -> tuple[str, str | None] | None:
    """The challenge going: its name and kind, from its window."""
    clock = _clock(game)
    if clock is None:
        return None
    cx, cy = clock.x + GOING_TO_TILE[0], clock.y + GOING_TO_TILE[1]
    art = game.screen[max(0, cy - ART_HALF):cy + ART_HALF, max(0, cx - ART_HALF):cx + ART_HALF].copy()
    tile = Tile((cx, cy), None, art, unit=unit_on(art, _unit_pictures(game)),
                builder=is_builder_card(game.screen, (cx, cy)))
    tell(game, tile, None)
    _close_popup(game)
    return (tile.name, tile.kind) if tile.name else None


def _green(screen: np.ndarray, match) -> bool:
    part = screen[max(0, match.y - match.h // 2):match.y + match.h // 2, max(0, match.x - match.w // 2):match.x + match.w // 2]
    return part.size > 0 and float(cv2.cvtColor(part, cv2.COLOR_BGR2HSV)[..., 1].mean()) >= GREEN


def start(game: Game, tile: Tile) -> bool:
    """Start the challenge: its Start, then its Trash shows instead."""
    button = _open_tile(game, tile)
    if button is None:
        return False
    if not button.name.startswith(T.CG_START):
        return True  # its Trash: it's the one going already
    if not _green(game.screen, button):
        log.info("Clan Games: Start is greyed out (a challenge is going, or one was just trashed)")
        return False
    game.tap_match(button)
    game.screen = None
    return game.wait_for(T.CG_TRASH, timeout=POPUP_WAIT, interval=0.3) is not None


def trash(game: Game) -> bool:
    """Trash the challenge whose window is open: Trash, then Okay."""
    if not game.click(T.CG_TRASH):
        return False
    if game.wait_for(T.CG_TRASH_TITLE, timeout=POPUP_WAIT, interval=0.3) is None:
        return False
    if not game.click_when_visible(T.OKAY, timeout=2):
        return False
    game.wait(0.8)
    game.refresh()
    return game.find(T.CG_TRASH_TITLE) is None


def trash_going(game: Game) -> bool:
    """Trash the challenge going (its window opened from its tile)."""
    clock = _clock(game)
    if clock is None:
        return False
    cx, cy = clock.x + GOING_TO_TILE[0], clock.y + GOING_TO_TILE[1]
    button = _open_tile(game, Tile((cx, cy), None, np.zeros((1, 1, 3), np.uint8)))
    if button is None or not button.name.startswith(T.CG_TRASH):
        _close_popup(game)
        return False
    return trash(game)


def army_units(game: Game, wanted: list[str], pictures: dict[str, np.ndarray]) -> dict[str, bool] | None:
    """Which of ``wanted`` (donate picture names) the army has, from the
    army window (Battle, Edit Army: its rows above the Clan Castle's);
    ``None`` if it couldn't be opened. The board is closed first."""
    from farmbot.tasks import clan

    close_board(game)
    band = clan._open_army(game)
    if band is None:
        return None
    try:
        game.refresh()
        left = band.x - ARMY_LEFT
        area = Rect(left, 0, game.size[0] - left, band.y)
        return {name: in_army(game.screen, area, pictures[name]) for name in wanted if name in pictures}
    finally:
        clan._close_army(game)


ARMY_FRESH = 2 * 60 * 60  # s an army reading is kept


def play(game: Game, cfg, builder: bool, memory: Memory | None = None, full=(),
         per_battle: dict | None = None) -> Visit:
    """Look at the board (the home village showing) and start the best
    challenge the farm can do; with none, trade one in (``cfg.trade_in``).
    ``builder``: Builder Base battles count (the builder base is farmed).
    ``full``: the storages full or close to it: loot challenges for them
    are skipped (and one going is traded in, ``cfg.trade_in``)."""
    visit = Visit()
    _scroll.update(page=0, swipe=None)
    if not ready(game):
        log.warning("Clan Games: pictures missing; see Pictures")
        return Visit(wait=6 * 60 * 60)
    if not open_board(game):
        log.info("Clan Games: the board didn't open (no event button or caravan in view)")
        return visit
    finished = False  # a challenge was just done: one the farm can't do may be cleared out first
    try:
        score = read_score(game)
        if memory is not None:
            if score is not None:
                memory.score = score[0]
            elif memory.score is not None:
                score = (memory.score, 10000)  # (as counted: it didn't read)
        if score is not None and score[0] >= min(goal_of(cfg), score[1]):
            log.info("Clan Games: your score reached its goal (%d/%d, goal %d)", *score, goal_of(cfg))
            return Visit(capped=True, wait=24 * 60 * 60)
        done = read_progress(game) if going(game) else None
        if going(game) and ((done is not None and done[0] >= done[1]) or game.find_all(T.CG_MEDAL)):
            # (Others in colour while it's going: it's done, whatever the OCR read.)
            # Done: opening the board just sent its points to the score. The board is
            # opened again for the next challenge, once they're in.
            log.info("Clan Games: %r is done: its points go to your score",
                     ((memory.going if memory is not None else None) or ("the challenge",))[0])
            if memory is not None:
                if memory.score is not None and memory.going_points:
                    memory.score += memory.going_points  # (counted, in case the score doesn't read)
                memory.new_going(None)
            finished = True
            game.wait(MEDALS_WAIT)
            close_board(game)
            if not open_board(game):
                return visit
            done = read_progress(game) if going(game) else None
        if going(game):
            kept = memory.going if memory is not None and memory.sure else None
            what = kept or read_going(game)
            if memory is not None:
                if what and what != memory.going:
                    memory.new_going(what)  # (another than was kept: its points aren't known)
                memory.going, memory.sure = what, True
            name, kind = what or ("", None)
            if memory is not None and done is not None:
                if memory.progress is not None and done[0] > memory.progress:
                    memory.idle = 0  # (it went on: its note was missed)
                memory.progress = done[0]
            stuck = stuck_after(cfg)
            if stuck and memory is not None and memory.idle >= stuck and cfg.trade_in:
                if trash_going(game):
                    log.info("Clan Games: traded in %r: no progress in %d of its battles", name or "the challenge",
                             memory.idle)
                    memory.new_going(None)
                    return Visit(traded=True, wait=TRASH_WAIT)
                log.info("Clan Games: couldn't trade in %r (no progress in %d battles)", name or "?", memory.idle)
            if kind == "loot" and name and _filled(name, "", full):
                if not cfg.trade_in:
                    log.info("Clan Games: %r is going, but its storage is (nearly) full", name)
                    return Visit(going=True, wait=LOOK_EVERY, kind=kind, name=name)
                if trash_going(game):
                    log.info("Clan Games: traded in %r: its storage is (nearly) full", name)
                    if memory is not None:
                        memory.new_going(None)
                    return Visit(traded=True, wait=TRASH_WAIT)
                log.info("Clan Games: couldn't trade in %r (its storage is nearly full)", name)
            log.info("Clan Games: %s is going%s%s", repr(name) if name else "a challenge",
                     f", {done[0]}/{done[1]} done" if done else "", f" (score {score[0]}/{score[1]})" if score else "")
            return Visit(going=True, wait=LOOK_EVERY, kind=kind, name=name)
        if memory is not None and memory.going is not None:
            memory.new_going(None)  # it's over: its points may still be flying to the score
            finished = True
            game.wait(MEDALS_WAIT)
            game.screen = None
            game.refresh()
        tiles = read_board(game)
        if not tiles:
            log.info("Clan Games: no challenge can be started now (one was trashed lately?)")
            return Visit(wait=TRASH_WAIT)
        pictures = _unit_pictures(game)
        for tile in tiles:
            tile.unit = unit_on(tile.art, pictures)
        chosen = _choose(game, tiles, builder, memory, pictures, full, per_battle)
        cant = [t for t in tiles if t.name and cant_do(t, builder, memory)]
        others = [t for t in tiles if t is not chosen and t.name and not cant_do(t, builder, memory)]
        if (chosen is not None and finished and cant and cfg.trade_in and getattr(cfg, "clear_out", False)
                and len(others) < CLEAR_OUT_BELOW):
            # One the farm can't do takes a place on the board for good: traded in, a new one comes in
            # (none can start for 10 minutes then; the best one is started after).
            swap = max(cant, key=lambda t: t.points or 0)
            if open_board(game) and start(game, swap) and trash(game):
                log.info("Clan Games: traded in %r (one the farm can't do) for a new challenge; %r next",
                         swap.name, chosen.name)
                return Visit(traded=True, wait=TRASH_WAIT)
            log.info("Clan Games: couldn't trade in %r", swap.name)
        if chosen is not None:
            if not open_board(game):  # (closed for the army window)
                return visit
            if start(game, chosen):
                log.info("Clan Games: started %r for %s points", chosen.name or chosen.unit, chosen.points)
                if memory is not None:
                    memory.new_going((chosen.name, chosen.kind), chosen.points)
                    memory.sure = True
                return Visit(started=chosen.name or chosen.unit or "?", wait=LOOK_EVERY, kind=chosen.kind,
                             name=chosen.name)
            log.info("Clan Games: %r didn't start", chosen.name)
            return visit
        if not cfg.trade_in:
            log.info("Clan Games: none of the challenges is one the farm can do; looking again later")
            return visit
        if not all(t.name for t in tiles):  # one wasn't read: it may be doable, so nothing is thrown away
            log.info("Clan Games: not every challenge could be read; looking again later")
            return visit
        if not open_board(game):
            return visit
        swap = min(tiles, key=lambda t: t.points or 0)
        if start(game, swap) and trash(game):
            log.info("Clan Games: traded in %r (none could be done) for a new challenge", swap.name or "?")
            return Visit(traded=True, wait=TRASH_WAIT)
        log.info("Clan Games: couldn't trade a challenge in")
        return visit
    finally:
        close_board(game)


def cant_do(tile: Tile, builder: bool, memory: Memory | None) -> bool:
    """A challenge the farm can't do: not one to take, Builder Base battles
    while the builder base isn't farmed, or a unit the army hasn't (as
    last looked at)."""
    if not tile.kind or (tile.kind == "builder" and not builder):
        return True
    if tile.kind == "unit":
        return memory is None or not memory.army.get(tile.unit or "", False)
    return False


def _choose(game: Game, tiles: list[Tile], builder: bool, memory: Memory | None,
            pictures: dict[str, np.ndarray], full=(), per_battle: dict | None = None) -> Tile | None:
    """The challenge to start, of those the farm can do: the most points
    (by ``WORTH``) for the battles it takes (:func:`battles_for`). Each is
    opened (or recalled) only as needed, best first."""
    def worth(tile: Tile, kind: str | None) -> float:
        return (tile.points or 0) * WORTH.get(kind or "", 0.8)

    # Those in view first (the board is left where it was read last), so it scrolls once at most.
    here = _scroll["page"]
    def guess(tile: Tile) -> str | None:  # (its kind before it's opened)
        return "unit" if tile.unit else "builder" if tile.builder else None

    for tile in sorted(tiles, key=lambda t: (t.page != here, -worth(t, guess(t)))):
        tell(game, tile, memory)
    _close_popup(game)
    doable = [t for t in tiles if t.kind and (t.kind != "builder" or builder)]
    filled = [t for t in doable if t.kind == "loot" and _filled(t.name, t.text, full)]
    if filled:
        log.info("Clan Games: skipping %s: %s storage is (nearly) full", ", ".join(repr(t.name) for t in filled),
                 "/".join(sorted(full)))
        doable = [t for t in doable if t not in filled]
    doable.sort(key=lambda t: -worth(t, t.kind) / battles_for(t, per_battle))
    units = [t.unit for t in doable if t.kind == "unit" and t.unit]
    has: dict[str, bool] = {}
    if units:
        fresh = memory is not None and memory.army_read is not None and game.clock() - memory.army_read < ARMY_FRESH
        if fresh and all(u in memory.army for u in units):
            has = memory.army
        else:
            read = army_units(game, units, pictures)
            if read is not None:
                has = read
                if memory is not None:
                    memory.army.update(read)
                    memory.army_read = game.clock()
            log.info("Clan Games: the army has %s", ", ".join(u for u, there in has.items() if there) or "none of "
                     + ", ".join(units))
    for tile in doable:
        if tile.kind == "unit" and not has.get(tile.unit or "", False):
            continue
        return tile
    return None


# -- rewards ---------------------------------------------------------------
LOGS = Path("logs")
REWARD_SURE = 0.75  # an "i" on a reward: greyed ones (locked tiers) score less
COLOURFUL = 60  # mean saturation of a reward that can be picked (locked tiers are grey)
REWARD_COLUMN = 60  # px: rewards this near across are one tier
CONFIRM_WORDS = ("claim", "collect", "select", "choose", "confirm", "okay", "ok")


def _save(game: Game, step: str) -> None:
    from farmbot import imagefile

    try:
        LOGS.mkdir(exist_ok=True)
        imagefile.write(str(LOGS / f"clan_games_{datetime.now():%Y%m%d-%H%M%S}_{step}.png"), game.refresh())
    except Exception:  # noqa: BLE001 - only a record
        pass


def _colourful(screen: np.ndarray, x: int, y: int, half: int = 30) -> float:
    part = screen[max(0, y - half):y + half, max(0, x - half):x + half]
    return float(cv2.cvtColor(part, cv2.COLOR_BGR2HSV)[..., 1].mean()) if part.size else 0.0


def reward_picks(screen: np.ndarray, infos: list, tiers: list[list[tuple[int, int]]]) -> list[tuple[int, int]]:
    """For each tier (its rewards' middles, top down), the one to pick:
    the first with an "i" on it (a magic item, potion or book), then gems
    (green), then the first."""
    picks = []
    for rewards in tiers:
        def has_info(p):
            return any(abs(m.x - (p[0] + 35)) < 25 and abs(m.y - (p[1] - 35)) < 25 for m in infos)

        def gem(p):
            part = screen[p[1] - 25:p[1] + 15, p[0] - 25:p[0] + 25]
            if not part.size:
                return False
            hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
            green = (hsv[..., 0] > 40) & (hsv[..., 0] < 80) & (hsv[..., 1] > 120)
            return float(green.mean()) > 0.15

        best = next((p for p in rewards if has_info(p)), None) or next((p for p in rewards if gem(p)), None) or rewards[0]
        picks.append(best)
    return picks


def collect_rewards(game: Game) -> bool | None:
    """Pick a reward from each tier the clan unlocked (the Rewards tab,
    once the games are over). True once picked, False if there was none
    to pick, ``None`` if it couldn't be done (each step is saved to logs/)."""
    from farmbot import wordbuttons

    if not (game.has(T.CG_TITLE) and game.has(T.CG_REWARDS_TAB)):
        return None
    if not open_board(game):
        log.info("Clan Games rewards: the board didn't open")
        return None
    try:
        game.click(T.CG_REWARDS_TAB)
        game.wait(1.0)
        _save(game, "rewards")
        screen = game.refresh()
        infos = game.find_all(T.CG_INFO, threshold=REWARD_SURE) if game.has(T.CG_INFO) else []
        # The rewards: tiles in colour in the tiers' columns, found from their
        # "i"s and from colour along the same rows.
        rows = sorted({round(m.y / 20) * 20 for m in infos})
        columns = sorted({round(m.x / 20) * 20 for m in infos})
        tiers: list[list[tuple[int, int]]] = []
        for cx in columns:
            rewards = [(cx - 35, ry + 35) for ry in rows if _colourful(screen, cx - 35, ry + 35) >= COLOURFUL]
            if rewards:
                tiers.append(rewards)
        if not tiers:
            log.info("Clan Games rewards: none to pick (or not told apart: see logs/)")
            return False
        picked = 0
        for x, y in reward_picks(screen, infos, tiers):
            game.tap(x, y)
            game.wait(1.0)
            found = wordbuttons.read(game.refresh())
            for rect, text in found:
                if wordbuttons._plain(text) in CONFIRM_WORDS:
                    game.tap(rect.x + rect.w // 2, rect.y + rect.h // 2)
                    game.wait(1.0)
                    break
            picked += 1
        _save(game, "rewards_after")
        log.info("Clan Games rewards: picked %d (check them in the game: these screens are new to the bot)", picked)
        return True
    finally:
        close_board(game)

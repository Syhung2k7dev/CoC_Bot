"""Hero walks: the Archer Queen (her Healers behind her) or the Royal
Champion goes in first, on her own, and walks round the outside of the base
taking its buildings one by one. Once she's hurt, Invisibility Spells keep
her hidden, one after another, for as long as they last; the rest of the army follows her in, from the same side, once she
falls (or the walk has had its longest time). (A Royal Champion with the Spirit Fox turns invisible by
herself: the pet needs nothing from the bot.)

The bot reads her health on her card, and finds her on the field by the
health bar over her head (it shows once she's hurt, in her card's colour);
each Invisibility Spell goes ahead of her along the way she's walking, only
where she's just been seen (or, by her heading, where she's walked on to
since): never on an old sighting, nor again where one missed her."""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from farmbot import armybar, plan
from farmbot.armybar import Card
from farmbot.config import WALK_FOXES, Config
from farmbot.game import Game, T
from farmbot.geometry import Point

log = logging.getLogger(__name__)

PICTURES = {"queen": T.QUEEN_CARD, "champion": T.CHAMPION_CARD}
NAMES = {"queen": "Archer Queen", "champion": "Royal Champion"}

FRAME_WIDTH = 1177  # px wide the sizes below are for (the bot's frames on MuMu)
FIELD_BOTTOM = 0.8  # share of the screen's height above the troop bar
FIELD_SAT, FIELD_VALUE = 110, 120  # her bar's colour this strong and bright at least (18 Nov: a dim,
# teal-tinted base, her bar at saturation 120-160, brightness 130-190, went unseen)
FIELD_SAT_STRONG = 200  # ...and its strongest colour (her bar's fill is ~245)
FIELD_SAT_PALE, BADGE_SAT_PALE = 55, 20  # her bar and badge while she's invisible (paler), looked for...
PALE_CONFIRM, PALE_SAME = 1.2, 15  # s and px within which a next look confirms a pale sighting off from her
PALE_MOST = 90  # ...and never further (18 Nov: unseen 5.5 s, a pale bar 220 px off was taken for her; she
# walks 15-20 px a second)
PALE_REACH = 30  # ...this many px from where she was at most, and FIELD_WALK more a second since (
# 18 Nov: 57 px off in 0.4 s, another bar)
PALE_HUE = 7  # OpenCV hue her bar's fill is off her card's bar's (towards the ground's) at least, seen pale...
PALE_HUE_HEALTH = 0.62  # (her health this much at least: lower, her card's bar turns yellow first)
PALE_SHARE = 0.68  # ...or its saturation this share of the strongest she's shown, at most
FIELD_GREEN_FROM, GREEN_TILL = 45, 0.4  # her bar's green from this hue; it can be green down to this health
FIELD_GREEN = 66  # OpenCV hue: a hero's bar is greener than this; an account's glowing scenery is ~77
BAR_TO_HERO = (20, 25)  # px from the left end of the bar over her head to her
BADGE_HUE = (125, 165)  # her bar has her level on a purple badge just left of it (18 Nov:
BADGE_SHARE = 0.2  # ...grass flecks of the bar's green were taken for it); this share of the patch purple...
BADGE_SAT = 45  # ...this strong at least (18 Nov: on a dim teal base, 40-120)
FIELD_BAR = 26  # px her bar over her head is when full; the coloured part is her health's share of it
BAR_SLACK = 0.3  # ...and this share longer at most...
BAR_SHORT = 0.35  # ...this share of it at least (a spell's sparkle can hide much of it: 18 Nov, 8 px at 72%)
HUE_SLACK = 7  # OpenCV hue her field bar is off her card's bar at most (lights by her bar: hue 15-25, seen)
CARD_HUE_SLACK = 12  # ...from her card's bar, yellow to red (18 Nov: 31 over her head by 19 on her card at 53%)
STRIP_EDGE, STRIP_CLEAR = 3, 0.2  # rows just over her bar (and from the 2nd under it) with this share of its colour at most...
STRIP_FULL, STRIP_ROWS = 0.75, (2, 4)  # ...and this many rows of it this full (the zoom varies by base;
# a dark speck of her over it leaves a row 84% full: 18 Nov)
STRIP_SAT = 0.7  # its colour is this share of its middle's saturation at least (lime grass of its hue
# just over and under it is paler: 18 Nov, S 100-130 by her bar's 190-245)
FIELD_REACH = 450  # px she's looked for from where she was last seen (or went down) at most...
FIELD_STEP = 80  # ...just after (a look is under a second apart)...
FIELD_WALK = 40  # px a second the reach from where she was last seen grows while she isn't seen
INVISIBLE_FOR = 4.0  # s an Invisibility Spell hides her: the next one goes as it wears off
MISS_AFTER = 2.4  # s a spell takes to hold her, and the shots already at her to land: her health then is what it holds...
# (18 Nov: at 1.5 s, before it landed, 91% -> 72% as it did said "missed"; it held her at 64-72% after)
COVER_FROM = 1.0  # s after a spell goes that it may hide her (it lands in 1.8 s or so)
MISS_DROP = 0.1  # ...and dropping by this much from it says it missed her: another one at once
# (18 Nov: 36% -> 9% "hidden"; but measured from the cast, the hit before it held looked like a miss)
WALK_ABILITY_HEALTH = 0.5  # no Invisibility left: her ability (heal, shield) at this health, not lost with her
ABILITY_LEAD = 1.0  # s before her last Invisibility wears off that it goes (18 Nov: she fell as it did)
WALK_LAST_STAND = 0.25  # ...and at this health whatever's left: an Invisibility Spell may have missed her
FOX_COOLDOWN = 6.0  # s the Spirit Fox waits between its turns hiding her (the wiki; 5 before March 2024)
SPELL_WORTH = 1.0  # s of her showing a spell must hide, at least, before the fox's next turn
SPELL_LAND = 1.8  # s from the look that sends a spell till it holds her (it falls first; shots already on their
# way still land: 18 Nov, the circle showed 1.7 s on and she was hit a second more)
STILL = 15  # ...so with her standing (fighting: two sightings this many px apart at most), it goes that
# early, before the fox lets her go, on where she stands (seen this many s before its turn, at most)
STILL_SEEN = 1.5
STILL_SPAN = 0.7  # s apart at least, the two sightings that say she's standing
STANDING = 5.0  # px a second at most her heading shows, standing (her sightings jitter a few px; walking,
# 15-20): only then does a spell go on where she was seen a while ago (issue #30)
SPELL_RADIUS = (60, 45)  # px across and up an Invisibility Spell's circle reaches (18 Nov); she's
# hidden only inside it (18 Nov: walked 50 px on from a spell's spot, hit before the next was due)
LEAD_SHARE = 0.5  # share of where she'd walk to by the time a spell lands that it goes ahead of her
# (she often stops at the next building: the whole way overshoots)...
LEAD_MOST = 0.6  # ...the circle's middle this share of its reach ahead of where she is, at most: walking on, she
# crosses the most of it; stopping (at a building), she's still well inside it (issue #30: put half a reach
# ahead of where she was, she walked out of it in a second or two and was hit while thought hidden)
PREDICT_FOR = 2.0  # s since she was seen, at most, that her heading still says where she's walked to (longer,
# she may have turned or stopped: no spell till she's seen again; issue #30: spells went on sightings
# 130-340 px behind her). A judgement, not the game's: she walks 15-20 px a second (FIELD_WALK's note)
HIT_FLIGHT = 0.6  # s shots fired before the fox's turn keep landing in it
HIT_SPAN, HIT_DROP = 1.2, 0.04  # her health down this much within this many s: she's being hit
FRESH = 0.8  # s since she was seen that a spell goes on that sighting; older, by her heading (PREDICT_FOR)...
SIGHT_WAIT = 0.6  # ...after waiting this long at most to see her again (18 Nov: spells landed where she'd been)...
SIGHT_LOW = 0.4  # ...but not at all once she's this low (18 Nov: at 26% she fell while it waited). With no
# heading to go by, it waits till she's seen, low or not: a spell on an old spot misses (issue #30)
HEALERS_UNREAD = 5  # Healers to send when the card's count isn't read
FOX_LOOKS = 1.5  # s of looks the fox's clock is set by
FOX_SLACK = 0.8  # s into its turn (or gap) and before its end, at least, that a look against its clock sets it
PET_SEEN, PET_DOWN = 0.2, 0.3  # her pet's picture this colourful at first; this share of it, it's down
SPEAR_LOOKS = 4.0  # s after she goes in that her equipment's looked for over her card
SPEAR_HURT = 1.0  # her health at most for her ability, the Rocket Spear on her: at once, at the edge, far from
# the defences (it throws at them from further than they reach her; the user, 19 Nov: use it early, then a spell
# once she's first hurt, then spells cycled with the fox's turns)...
SPEAR_EARLY_LEVEL = 9  # ...from this level of the spear on (by the village export): its reach is the same at
# every level, but how many throws it boosts and by how much grow with it (Supercell's announcement of the
# piece: supercell.com/en/games/clashofclans/blog/news/super-wall-breaker-spotlight-new-hero-equipment);
# lower, fewer and weaker, so her ability's kept for when she's hurt, as without it. The level is a
# judgement, not the game's (a third of an Epic piece's 27): an unknown level goes early, as before
LOOK_EVERY = 0.1  # s between looks at her health (a screenshot is most of a look: 18 Nov, looks
# 0.8-2 s apart sent spells 2-3 s after she'd been hit)


@dataclass
class Walk:
    hero: Card
    side: str
    start: Point
    began: float
    before: np.ndarray | None = None  # the field just before she went in (its lights aren't her bar)
    seen: Point | None = None  # where she was last seen on the field
    found: bool = False  # ...by her bar (else where she went down)
    seen_at: float = 0.0  # ...when
    healers: list[Card] = field(default_factory=list)
    invisibility: list[Card] = field(default_factory=list)
    fired: bool = False  # her ability went during the walk
    cast: int = 0  # Invisibility Spells cast on her
    cast_at: float = 0.0  # ...the last one when
    held: float | None = None  # ...her health once it held
    missed: bool = False  # ...it missed her
    still: bool = False  # she stood where she was seen STILL_SPAN s or more before
    track: list = field(default_factory=list)  # ...her sightings of late (time, spot)
    cast_on: Point | None = None  # where the last Invisibility Spell went
    fox_at: float = 0.0  # when a turn of her Spirit Fox's began (by its clock; at first, as she went down)
    fox_down: bool = False  # ...the fox is down (its picture on her card greyed out)
    pet: float | None = None  # ...its picture's colour at first...
    pet_grey: int = 0  # ...and looks running it's been greyed out
    looks: list = field(default_factory=list)  # (time, hidden) of late, her bar seen
    strongest: float | None = None  # her bar's strongest saturation seen (not hidden), green
    shown: int = 0  # looks running she's been seen not hidden
    spear: bool = False  # the Rocket Spear's on her: her ability as she goes in (at SPEAR_EARLY_LEVEL or more)
    spear_level: int | None = None  # ...its level, by the village export (None: not known)
    casts: list = field(default_factory=list)  # when each Invisibility Spell went
    maybe: tuple | None = None  # a pale sighting off from where she was, till a next look confirms it (time, spot)
    missed_on: list = field(default_factory=list)  # where spells that missed her went
    missed_at: float | None = None  # ...the last one found out when

    def __post_init__(self):
        self.fox_at = self.fox_at or self.began


def _pictures(game: Game, name: str) -> list:
    library = game.vision.library
    return [p for _, p in library.get(name)] if library.has(name) else []


def _like(game: Game, cards: list[Card], name: str) -> list[Card]:
    pictures = _pictures(game, name)
    if not pictures or not cards:
        return []
    screen = game.refresh()
    return [c for c in cards if any(armybar.card_is(screen, c, p) for p in pictures)]


def walker(game: Game, cfg: Config, singles: list[Card]) -> Card | None:
    """The card of the hero who walks (``attack.hero_walk``), among ``singles``."""
    how = cfg.attack.hero_walk
    if how not in PICTURES:
        return None
    found = _like(game, singles, PICTURES[how])
    return found[0] if found else None


def ready(game: Game, cfg: Config) -> bool:
    """A walk opens this battle: chosen, and the hero's card is on show (by its picture)."""
    how = cfg.attack.hero_walk
    if how not in PICTURES:
        return False
    if not _pictures(game, PICTURES[how]):
        log.warning("%s walk: no %s card picture (%s.png): the army goes in as usual",
                    NAMES[how], NAMES[how], PICTURES[how])
        return False
    from farmbot.tasks.attack import _bar_cards

    if walker(game, cfg, [c for c in _bar_cards(game, cfg) if c.kind == "single"]) is None:
        log.info("%s walk: her card isn't on the bar (not brought, or down): the army goes in as usual",
                 NAMES[how])
        return False
    return True


def _bars(screen: np.ndarray, health: float, sats: tuple[int, ...] = ()) -> list[tuple[int, int, int]]:
    """Health bars on the field (x, y, width) of the colour a hero at
    ``health`` shows: green, orange about half way, red when low (of these
    saturations at least: by default, a bar as it shows while she's seen)."""
    scale = screen.shape[1] / FRAME_WIDTH
    hsv = cv2.cvtColor(screen[:int(screen.shape[0] * FIELD_BOTTOM)], cv2.COLOR_BGR2HSV)
    hue = hsv[..., 0].astype(int)
    green = (hue >= FIELD_GREEN_FROM) & (hue <= FIELD_GREEN)  # (the scenery's glow is a bluer green)
    warm = (hue <= armybar.BAR_HUE_WARM) | (hue >= 180 - armybar.BAR_HUE_RED)  # yellow, orange, red
    colour = green if health > 0.6 else warm if health < 0.4 else green | warm
    # (Low, the bar's short: 18 Nov, 6 px at 31%, wiped out by a 7 px opening and an 8 px least.)
    shortest = min(8.0, max(5.0, 0.6 * FIELD_BAR * health))
    found: list[tuple[int, int, int]] = []
    # (Also of the strongest colour only: 18 Nov, lime grass of her bar's hue just over it, less
    # strong, ran into it, and the two made one blotch too tall for a bar.)
    for sat in sats or (FIELD_SAT, FIELD_SAT_STRONG):
        bright = (hsv[..., 1] > sat) & (hsv[..., 2] > FIELD_VALUE)
        mask = cv2.morphologyEx((bright & colour).astype(np.uint8), cv2.MORPH_OPEN,
                                np.ones((2, max(3, round(min(7.0, shortest) * scale))), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        found += [(int(x), int(y), int(w)) for x, y, w, h, _ in stats[1:n]
                  if w >= shortest * scale and 2 <= h <= 8 * scale
                  and not any(abs(x - a) <= 2 * scale and abs(y - b) <= 2 * scale for a, b, _ in found)]
    return found


@dataclass
class Sighting:
    spot: Point  # where she is
    pale: bool  # her bar's only to be seen pale (she's invisible)
    sat: float = 0.0  # ...its fill's saturation and hue (seen pale against the ground behind it, the hue
    hue: int = -1  # drifts towards the ground's and the saturation drops)


def sight(screen: np.ndarray | None, before: np.ndarray | None, near: Point, health: float,
          reach: float = FIELD_REACH, hue: int | None = None, since: float = 0.5) -> Sighting | None:
    """Where she is on the field, her bar as ``find`` has it, or else, close
    to where she was, pale (she's invisible: the Spirit Fox's turn or a
    spell; 18 Nov, saturation 75-95 by 170-245 seen). Only near her: a
    pale bar is too like grass (``since`` s since she was seen there). With
    its fill's colour, to tell (``hidden``)."""
    spot = find(screen, before, near, health, reach, hue)
    if screen is None:
        return Sighting(spot, False) if spot is not None else None
    scale = screen.shape[1] / FRAME_WIDTH
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    pale = False
    if spot is None:
        bars = [(x, y, w) for x, y, w in _bars(screen, health, (FIELD_SAT_PALE,))
                if _badge(hsv, x, y, scale, BADGE_SAT_PALE)
                and _like_hers(hsv, x, y, w, health, hue, scale, FIELD_SAT_PALE)]
        # (Of its own paleness: 18 Nov, under a spell on grass, her bar unseen 9 s, spells where she'd been.)
        spots = [(round(x + BAR_TO_HERO[0] * scale), round(y + BAR_TO_HERO[1] * scale)) for x, y, _ in bars]
        spots = [p for p in spots if math.dist(p, near) <= min(reach, PALE_REACH + FIELD_WALK * since, PALE_MOST) * scale]
        if not spots:
            return None
        spot, pale = min(spots, key=lambda p: math.dist(p, near)), True
    x, y = round(spot[0] - BAR_TO_HERO[0] * scale), round(spot[1] - BAR_TO_HERO[1] * scale)
    w = max(3, round(FIELD_BAR * health * scale * BAR_SHORT))  # (its first stretch: a sparkle can hide the rest)
    fill = hsv[max(y, 0):y + max(1, round(2 * scale)), max(x + 1, 0):x + w]
    if not fill.size:
        return Sighting(spot, pale)
    return Sighting(spot, pale, float(np.median(fill[..., 1])), _fill(hsv, x, y, w, scale))


def hidden(seen: Sighting, health: float, card_hue: int | None, strongest: float | None) -> bool:
    """Whether a sighting is of her invisible: her bar pale, by its fill
    against her card's bar (always solid) and the strongest she's shown this
    walk. (18 Nov, no spells: on a teal base, under the Spirit Fox, hue
    64-66 by her card's 50, saturation 130-166 by 185-237 seen; on lime grass,
    the hue kept, saturation 75-95 by 170-245.)"""
    if seen.pale:
        return True
    if seen.hue < 0:
        return False
    # (Lower, from green to yellow, the bar over her head turns later than her card's: 18 Nov,
    # hue 61 over her head by 45 on her card at 56%.)
    green = card_hue is not None and FIELD_GREEN_FROM <= card_hue <= FIELD_GREEN and health >= PALE_HUE_HEALTH
    if green and FIELD_GREEN_FROM <= seen.hue <= FIELD_GREEN + 14 and seen.hue - card_hue >= PALE_HUE:
        return True
    return bool(strongest and _family(seen.hue) == "green" and seen.sat < PALE_SHARE * strongest)


def _family(hue: int) -> str:
    return "green" if FIELD_GREEN_FROM - 10 <= hue <= FIELD_GREEN + 14 else "warm"


def find(screen: np.ndarray | None, before: np.ndarray | None, near: Point, health: float,
         reach: float = FIELD_REACH, hue: int | None = None) -> Point | None:
    """Where she is on the field, by the health bar over her head (it shows
    once she's hurt, and not while she's invisible): a bar that wasn't there
    before she went in, with her level badge, as long as her health says and
    (``hue``) the colour of her card's bar; the nearest to where she was last
    seen. (18 Nov: orange lights by purple roofs were taken for her.)"""
    if screen is None:
        return None
    scale = screen.shape[1] / FRAME_WIDTH
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    there = _there(before, health) if before is not None and before.shape == screen.shape else []
    # (Not what was there before she went in, of its colour: 18 Nov, her green bar over an
    # orange building's lights was left out.)
    new = [(x, y, w) for x, y, w in _bars(screen, health)
           if not any(abs(x - a) <= 4 * scale and abs(y - b) <= 4 * scale and _near_hue(_fill(hsv, x, y, w, scale), f)
                      for a, b, f in there)
           and _badge(hsv, x, y, scale) and _like_hers(hsv, x, y, w, health, hue, scale)]
    spots = [(round(x + BAR_TO_HERO[0] * scale), round(y + BAR_TO_HERO[1] * scale)) for x, y, _ in new]
    spots = [p for p in spots if math.dist(p, near) <= reach * scale]
    return min(spots, key=lambda p: math.dist(p, near)) if spots else None


_THERE: dict = {}


def _there(before: np.ndarray, health: float) -> list[tuple[int, int, int]]:
    """The bars on ``before`` (x, y, fill hue) a hero at ``health`` would
    match, worked out once a walk (a look is a screenshot and this, seen)."""
    key = (id(before), int(before[::97, ::89].sum()), round(health, 2))  # (an id can be had again)
    if key not in _THERE:
        if len(_THERE) > 64 or any(k[0] != key[0] for k in _THERE):
            _THERE.clear()
        scale = before.shape[1] / FRAME_WIDTH
        was = cv2.cvtColor(before, cv2.COLOR_BGR2HSV)
        _THERE[key] = [(x, y, _fill(was, x, y, w, scale)) for x, y, w in _bars(before, health)]
    return _THERE[key]


def _like_hers(hsv: np.ndarray, x: int, y: int, w: int, health: float, hue: int | None, scale: float,
               floor: int = FIELD_SAT) -> bool:
    """A bar as long as her health makes it and (if known) of her card's colour
    (``floor``: as strong at least, paler while she's invisible)."""
    length = FIELD_BAR * health * scale
    if w > length + max(3 * scale, BAR_SLACK * length) or w < BAR_SHORT * length:
        return False
    fill = _fill(hsv, x, y, w, scale)
    if not _strip(hsv, x, y, w, fill, scale, floor):
        return False
    if hue is None or hue < 0 or (FIELD_GREEN_FROM <= fill <= FIELD_GREEN and health >= GREEN_TILL):
        return True  # (from green to yellow, the bar over her head turns later than her card's:
        # 18 Nov, hue 61 over her head and 45 on her card at 56%; the lamps it's against are orange)
    return _near_hue(fill, hue, CARD_HUE_SLACK)


def _fill(hsv: np.ndarray, x: int, y: int, w: int, scale: float) -> int:
    """The OpenCV hue of a bar's fill at (x, y)."""
    fill = hsv[y:y + max(1, round(2 * scale)), x:x + w, 0].astype(int).ravel()
    return int(np.median(np.where(fill >= 90, fill - 180, fill))) % 180  # (red runs round)


def _near_hue(a: int, b: int, slack: int = HUE_SLACK) -> bool:
    off = abs(a - b)
    return min(off, 180 - off) <= slack


def _strip(hsv: np.ndarray, x: int, y: int, w: int, fill: int, scale: float, floor: int = FIELD_SAT) -> bool:
    """Her bar is a thin strip of its colour with none of it just above or
    below (a lamp or a lit roof edge is a blotch: 18 Nov)."""
    hue = hsv[..., 0].astype(int)
    rows = slice(max(y - round(7 * scale), 0), y + round(9 * scale))  # (its top row can be just over y)
    cols = slice(x + 1, x + max(2, w - 1))
    off = np.abs(hue[rows, cols] - fill)
    middle = hsv[y:y + max(1, round(2 * scale)), cols, 1]
    sat = max(floor, STRIP_SAT * float(np.median(middle))) if middle.size else floor
    near = (np.minimum(off, 180 - off) <= HUE_SLACK) & (hsv[rows, cols, 1] > sat) & (hsv[rows, cols, 2] > FIELD_VALUE)
    share = near.mean(axis=1)
    edge = round(STRIP_EDGE * scale)
    full = np.flatnonzero(share >= STRIP_FULL)
    if full.size < STRIP_ROWS[0] * scale or full.size > STRIP_ROWS[1] * scale or full[-1] - full[0] >= full.size:
        return False  # (solid rows, one block of them)
    # (It ends sharply, past a soft row at either end: a red flier's edge thins out over rows;
    # 18 Nov, her bar's soft top row was 67% of its colour.)
    over, under = full[0] - 1, full[-1] + 2
    return bool(share[max(over - edge, 0):over].max(initial=0) <= STRIP_CLEAR
                and share[under:under + edge].max(initial=0) <= STRIP_CLEAR)


def _badge(hsv: np.ndarray, x: int, y: int, scale: float, sat: int = BADGE_SAT) -> bool:
    """The purple level badge just left of a bar at (x, y)."""
    patch = hsv[max(y - round(5 * scale), 0):y + round(8 * scale), max(x - round(14 * scale), 0):max(x - 1, 0)]
    if not patch.size:
        return False
    purple = ((patch[..., 0] >= BADGE_HUE[0]) & (patch[..., 0] <= BADGE_HUE[1])
              & (patch[..., 1] >= sat) & (patch[..., 2] >= 70))
    return bool(purple.mean() >= BADGE_SHARE)


def start_point(edges: dict[str, list[Point]], side: str) -> Point:
    """Where she goes down: the middle of the side's points (the army's stretch)."""
    return plan.nearest_point(edges, side, plan.middle(edges[side]))


def spear_level(village) -> int | None:
    """The Rocket Spear's level by the village export already kept (never
    read for this), None without one. (The export lists an Epic piece at
    level 1 whether it's had or not: it's only gone by once the spear's seen
    on her.)"""
    from farmbot import upgradable

    return upgradable.item_levels(village, "equipment", ("Rocket Spear",)).get("Rocket Spear")


def spear_early(level: int | None) -> bool:
    """Whether her ability goes at once for the Rocket Spear at ``level``
    (unknown: yes, as before levels were looked at)."""
    return level is None or level >= SPEAR_EARLY_LEVEL


def walk(game: Game, cfg: Config, singles: list[Card], troops: list[Card], spells: list[Card],
         counts: dict[Card, int | None], edges: dict[str, list[Point]], sides: list[str],
         fallback=None, spear: int | None = None) -> Walk | None:
    """The walk: the hero down (her Healers on her heels), then her health
    watched till she falls (``walk_time`` seconds at most). Once it drops to
    ``walk_invisibility_health`` an Invisibility Spell goes on her, and
    another each time one wears off, keeping her hidden while they last
    (the Spirit Fox's own invisibility first, if she has it). Returns what went out,
    for the rest of the battle to leave alone; None if she didn't go.
    ``spear``: the Rocket Spear's level, if known (:func:`spear_level`)."""
    from farmbot.tasks import attack as atk

    acfg = cfg.attack
    hero = walker(game, cfg, singles)
    side = next((s for s in sides if edges.get(s)), None)
    name = NAMES.get(acfg.hero_walk, acfg.hero_walk)
    if hero is None or side is None:
        log.warning("%s walk: %s; the army goes in as usual", name,
                    "her card isn't on the bar" if hero is None else "no side to send her in from")
        return None
    start = start_point(edges, side)
    invisibility = _like(game, spells, T.INVISIBILITY_SPELL_CARD)  # (looked for now: not while she walks)
    before = game.refresh()
    tapped: dict[int, float] = {}
    went = atk.place_singles(game, [hero], itertools.chain([start], itertools.cycle(edges[side])), cfg, fallback,
                             tapped=tapped)
    if not went:
        log.warning("%s walk: she wasn't placed; the army goes in as usual", name)
        return None
    # Her Spirit Fox's turns count from the tap that put her down (18 Nov: counted from before
    # placing, 3 s early, a spell went into the fox's own turn and was lost; from after its checks, late).
    done = Walk(hero, side, start, tapped.get(id(hero), game.clock()), before=before, seen=start, spear_level=spear)
    log.info("%s walk: she goes in at %s on the %s side; the army follows once she falls (%.0f s at most)",
             name, start, side, acfg.walk_time)
    if acfg.hero_walk == "queen":
        done.healers = _like(game, troops, T.HEALER_CARD)
        for card in done.healers:
            taps = counts.get(card) or HEALERS_UNREAD
            log.info("%s walk: %d Healer(s) behind her", name, taps)
            atk.deploy_taps(game, card, itertools.repeat(start), taps, cfg)
        if not done.healers and _pictures(game, T.HEALER_CARD):
            log.info("%s walk: no Healers on the bar", name)
    done.invisibility = invisibility
    left = {id(c): counts.get(c) for c in done.invisibility}
    _watch(game, cfg, done, left, name)
    return done


def _scale(screen) -> float:
    return screen.shape[1] / FRAME_WIDTH if screen is not None else 1.0


def _outside(spot: Point, centre: Point, screen) -> bool:
    """Whether ``spot`` is out of an Invisibility Spell's circle round ``centre``."""
    rx, ry = SPELL_RADIUS[0] * _scale(screen), SPELL_RADIUS[1] * _scale(screen)
    return ((spot[0] - centre[0]) / rx) ** 2 + ((spot[1] - centre[1]) / ry) ** 2 > 1.0


def _heading(done: Walk) -> tuple[float, float] | None:
    """Her walk in px a second, by her last sighting and the oldest still
    kept, STILL_SPAN s or more before it (looks a tenth of a second apart see
    her move a few px, and a sighting's off by a few: over longer, that's
    less of her heading); None without two such. Next to nothing (STANDING),
    she's standing: none."""
    if not done.found or not done.track:
        return None
    t1, p1 = done.track[-1]
    older = [(t, p) for t, p in done.track if t1 - t >= STILL_SPAN]
    if not older:
        return None
    t0, p0 = older[0]
    v = (p1[0] - p0[0]) / (t1 - t0), (p1[1] - p0[1]) / (t1 - t0)
    return v if math.hypot(*v) > STANDING else (0.0, 0.0)


def _standing(done: Walk) -> bool:
    """She stood when last seen: still, and her heading next to nothing."""
    v = _heading(done)
    return done.found and done.still and v is not None and math.hypot(*v) <= STANDING


def _now_at(done: Walk, now: float) -> Point | None:
    """Where she is now: where she was just seen, or, seen a while ago
    (PREDICT_FOR s at most), as far on as her heading has taken her since;
    None if that's not known (never found, seen too long ago, or not since a
    spell missed her: what it was aimed by was wrong)."""
    if not done.found:
        return None
    age = now - done.seen_at
    if age <= FRESH:
        v = _heading(done) or (0.0, 0.0)
        return round(done.seen[0] + v[0] * age), round(done.seen[1] + v[1] * age)
    v = _heading(done)
    if v is None or age > PREDICT_FOR or (done.missed_at is not None and done.seen_at < done.missed_at):
        return None
    return round(done.seen[0] + v[0] * age), round(done.seen[1] + v[1] * age)


def _ahead(done: Walk, now: float, screen) -> Point | None:
    """Where a spell goes: ahead of where she is now (:func:`_now_at`) the
    way she's walking, for her to cross the most of its circle while it
    lasts: by LEAD_SHARE of her walk till it's half over, LEAD_MOST of its
    reach at most (she may stop at a building: still inside). None if where
    she is isn't known: no spell on an old spot (issue #30), nor, by a guess,
    in the circle of one that missed her."""
    here = _now_at(done, now)
    if here is None:
        return None
    v = _heading(done)
    if v is None:
        return here
    k = LEAD_SHARE * (SPELL_LAND + INVISIBLE_FOR / 2)
    # (Measured from where she was last seen, by her heading since and the lead together: had she
    # stopped there, she's still inside.)
    dx, dy = here[0] - done.seen[0] + v[0] * k, here[1] - done.seen[1] + v[1] * k
    rx, ry = SPELL_RADIUS[0] * _scale(screen), SPELL_RADIUS[1] * _scale(screen)
    far = math.hypot(dx / rx, dy / ry)
    if far > LEAD_MOST:
        dx, dy = dx * LEAD_MOST / far, dy * LEAD_MOST / far
    there = round(done.seen[0] + dx), round(done.seen[1] + dy)
    if now - done.seen_at > FRESH and any(not _outside(there, m, screen) for m in done.missed_on):
        return None
    return there


def _leaves(spot: Point, v: tuple[float, float] | None, centre: Point, screen) -> float | None:
    """In how many s, walking on at ``v`` px a second from ``spot``, she's
    out of the spell's circle round ``centre`` (0: out already); None if she
    isn't walking."""
    rx, ry = SPELL_RADIUS[0] * _scale(screen), SPELL_RADIUS[1] * _scale(screen)
    x, y = (spot[0] - centre[0]) / rx, (spot[1] - centre[1]) / ry
    if x * x + y * y > 1.0:
        return 0.0
    if v is None:
        return None
    vx, vy = v[0] / rx, v[1] / ry
    a = vx * vx + vy * vy
    if a < 1e-9:
        return None
    b, c = 2 * (x * vx + y * vy), x * x + y * y - 1.0
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def _down(screen, hero: Card, cfg: Config, fired: bool = False) -> bool:
    """Her card has greyed out: she's down. Once her ability's gone, it's
    grey with her health bar still on it (18 Nov: grey at 100%, green,
    she walked on; the walk took her for fallen and the army went in): then
    only with the bar gone."""
    if screen is None or not armybar.is_spent(screen, hero, cfg.bar):
        return False
    return not fired or armybar.hero_bar(screen, hero) is None


def fox_gap(fox: float, since: float) -> tuple[bool, float]:
    """With a Spirit Fox that hides her ``fox`` s when she goes down and
    again each FOX_COOLDOWN s after, ``since`` s on: whether she's showing
    (the fox between turns), and for how long yet."""
    phase = since % (fox + FOX_COOLDOWN)
    return (phase >= fox, fox + FOX_COOLDOWN - phase if phase >= fox else 0.0)


def _spell_time(fox: float, since: float, done: Walk, now: float | None = None) -> bool:
    """A spell now is worth it, as far as her Spirit Fox goes: she's
    showing (the fox between turns), long enough yet. The first goes as
    the gap opens (18 Nov: waiting a second into it, defences took
    her the moment the fox let go), the next as that one wears off; or
    early, to land as the fox lets her go: where she was just seen (pale,
    the fox on her), or where she stood as it took her."""
    if not fox:
        return True
    showing, left = fox_gap(fox, since)
    if not showing:
        phase = since % (fox + FOX_COOLDOWN)
        if fox - phase > SPELL_LAND or not done.found:
            return False
        # (On where she stood as the fox took her: 18 Nov, a sighting 9 s old, from before a
        # spell, sent one where she no longer was.)
        fresh = now is not None and now - done.seen_at <= FRESH
        return fresh or (done.still and since - (done.seen_at - done.fox_at) <= phase + STILL_SEEN)
    return left >= SPELL_WORTH


def _fox_seen(done: Walk, fox: float, now: float, hid: bool, covered: bool, name: str) -> None:
    """Sets the Spirit Fox's clock by what's seen of her: hidden twice
    running with no spell on her, its turn has begun; seen twice running
    in what the clock has for its turn, that's over. (18 Nov, no
    spells: its turns 0-4.4, 10.2-14.6, 20.3-24.9 s from the tap.)"""
    done.looks = [(t, h) for t, h in done.looks if now - t <= FOX_LOOKS] + [(now, hid)]
    if not fox or done.fox_down or covered or len(done.looks) < 2 or done.looks[-2][1] != hid:
        return
    other = [i for i, (_, h) in enumerate(done.looks) if h != hid]
    # (It changed between the last look the other way and the next.)
    turned = ((done.looks[other[-1]][0] + done.looks[other[-1] + 1][0]) / 2 if other
              else done.looks[-2][0])
    since = now - done.fox_at
    phase = since % (fox + FOX_COOLDOWN)
    showing = phase >= fox
    if hid and showing and phase - fox >= FOX_SLACK and fox + FOX_COOLDOWN - phase >= FOX_SLACK:
        log.info("%s walk: hidden with no spell on her: the Spirit Fox's turn (its clock set by it)", name)
        done.fox_at = turned
    elif not hid and not showing and phase >= FOX_SLACK and fox - phase >= FOX_SLACK:
        log.info("%s walk: seen in what the clock had for the Spirit Fox's turn: its turn is over", name)
        done.fox_at = turned - fox


def _confirmed(done: Walk, sighting: Sighting | None, now: float, scale: float) -> Sighting | None:
    """A pale sighting away from where she was last seen, only once a next
    look has it there too (18 Nov: a wall's lit edge 76 px off, taken for
    her while she stood still: a spell went on it)."""
    if sighting is None or not sighting.pale or not done.found or math.dist(sighting.spot, done.seen) <= PALE_REACH * scale:
        done.maybe = None
        return sighting
    was, done.maybe = done.maybe, (now, sighting.spot)
    if was and now - was[0] <= PALE_CONFIRM and math.dist(was[1], sighting.spot) <= PALE_SAME * scale:
        return sighting
    return None


def _covered(done: Walk, now: float) -> bool:
    """Whether an Invisibility Spell may be on her: from soon after any went
    till it wears off, another after it or not."""
    return any(t + COVER_FROM <= now < t + SPELL_LAND + INVISIBLE_FOR for t in done.casts)


def _pet(screen, done: Walk, name: str) -> None:
    """Watches her pet's picture on her card: greyed out, the Spirit Fox is down
    (and its turns with it: 18 Nov, she went 70% -> 15% as it fell)."""
    if screen is None or done.fox_down or not hasattr(done.hero, "left"):
        return  # (her ability greys her card, not the fox's picture: 18 Nov, 0.56 on it till it fell)
    colour = armybar.pet_colour(screen, done.hero)
    if done.pet is None:
        done.pet = colour if colour >= PET_SEEN else None
        return
    done.pet_grey = done.pet_grey + 1 if colour < PET_DOWN * done.pet else 0
    if done.pet_grey >= 2:
        done.fox_down = True
        log.info("%s walk: her Spirit Fox is down: no more turns hiding her, spells back to back", name)


def _watch(game: Game, cfg: Config, done: Walk, left: dict[int, int | None], name: str) -> None:
    from farmbot.tasks.attack import pick_reward

    acfg = cfg.attack
    level = WALK_FOXES.get(acfg.walk_fox, 0.0)
    spears = [p for p in _pictures(game, T.ROCKET_SPEAR) if p is not None] if acfg.hero_walk == "champion" else []
    seen = False
    hidden_until = 0.0
    wanted = None  # since when a spell has waited to see her
    healths: list[tuple[float, float]] = []  # her health of late (time, share)
    while game.clock() - done.began < acfg.walk_time:
        screen = game.refresh()
        if pick_reward(game):
            continue
        health = armybar.hero_health(screen, done.hero)
        bar = armybar.hero_bar(screen, done.hero) if screen is not None and health is not None else None
        now = game.clock()
        if seen and _down(screen, done.hero, cfg, done.fired):
            # Her card greys out once she's down (its bar still shows, red): the army goes in.
            log.info("%s walk: she fell after %.0f s", name, now - done.began)
            return
        if level:
            _pet(screen, done, name)
        if spears and not done.spear and now - done.began <= SPEAR_LOOKS and screen is not None:
            # (Her equipment shows over her card once she's down.)
            done.spear = hasattr(done.hero, "top") and any(armybar.shows_equipment(screen, done.hero, p)
                                                          for p in spears)
            if done.spear:
                lvl = done.spear_level
                log.info("%s walk: the Rocket Spear on her (%s)%s", name,
                         f"level {lvl}" if lvl is not None else "its level not known: as if strong",
                         "" if spear_early(lvl) or not acfg.walk_spear_early
                         else f": under level {SPEAR_EARLY_LEVEL}, her ability's kept for when she's hurt")
        fox = 0.0 if done.fox_down else level
        if (done.spear and acfg.hero_abilities and acfg.walk_spear_early and spear_early(done.spear_level)
                and not done.fired and health is not None and health <= SPEAR_HURT):
            # (Her spears at the defence that reached her, and those near it, standing off.)
            log.info("%s walk: health %.0f%%, far from the defences: her ability, for the Rocket Spear",
                     name, health * 100)
            game.tap(*done.hero.center)
            done.fired = True
        if health is None:
            # No bar on her card that isn't grey: she's invisible (her card hides it meanwhile;
            # 18 Nov: the Spirit Fox). Nothing to do till she shows again: a spell then.
            pass
        else:
            seen = True
            # Unseen a while, she may be further off: the reach grows as she walks, from when she was
            # last seen or else went down (18 Nov: first hurt 270 px in, past a fixed reach, she
            # was never found and every spell went on where she went down).
            since = now - (done.seen_at if done.found else done.began)
            reach = min(FIELD_REACH, FIELD_STEP + FIELD_WALK * max(0.0, since))
            card_hue = bar[1] if bar else None
            sighting = sight(screen, done.before, done.seen, health, reach, card_hue, max(0.0, since))
            sighting = _confirmed(done, sighting, now, _scale(screen))
            spot = sighting.spot if sighting else None
            hid = sighting is not None and hidden(sighting, health, card_hue, done.strongest)
            if spot is not None:
                # (Over a second or so, not look to look: looks a tenth of a second apart see her
                # walk a few px.)
                done.track = [(t, p) for t, p in done.track if now - t <= STILL_SPAN + STILL_SEEN]
                older = [p for t, p in done.track if now - t >= STILL_SPAN]
                done.still = bool(older) and math.dist(spot, older[-1]) <= STILL * _scale(screen)
                done.track.append((now, spot))
                done.seen, done.found, done.seen_at = spot, True, now
                if not hid and sighting.hue >= 0 and _family(sighting.hue) == "green":
                    done.strongest = max(done.strongest or 0.0, sighting.sat)
                done.shown = 0 if hid else done.shown + 1
            # A spell on her: from when it lands till it wears off.
            # A spell may be on her: from soon after any went till it wears off, whether or not another
            # followed (18 Nov: hidden by the last but one after a recast, the fox's clock was set by it).
            covered = _covered(done, now)
            if spot is not None and sighting.hue >= 0 and now - done.began >= fox + FOX_SLACK:
                # (Its first turn's from the tap, sure; her bar's first sightings, pale, are less so.)
                _fox_seen(done, fox, now, hid, covered, name)
            fox_turn = bool(fox) and not fox_gap(fox, now - done.fox_at)[0]
            if (spot is not None and now < hidden_until and done.cast_on is not None
                    and now - done.cast_at >= SPELL_LAND and _outside(spot, done.cast_on, screen)):
                # Walked out of its circle: another on her, at once if she shows; under the fox's
                # turn, to land as it ends (the fox's invisibility goes with her; the spell's doesn't).
                log.info("%s walk: she walked out of the Invisibility Spell's circle (%s from %s)%s",
                         name, spot, done.cast_on, ": the fox hides her for now" if fox_turn else "")
                hidden_until, done.cast_on = now, None
            elif (spot is not None and now < hidden_until and done.cast_on is not None
                  and now - done.cast_at >= COVER_FROM
                  and (out := _leaves(spot, _heading(done), done.cast_on, screen)) is not None
                  and out < SPELL_LAND + LOOK_EVERY and hidden_until + SPELL_LAND - now > out):
                # Walking out of its circle before it wears off (it holds SPELL_LAND s past
                # hidden_until, which is when the next is cast): the next goes now, ahead of her, to
                # take hold as she leaves it (issue #30: cast once she was out, she was hit meanwhile).
                log.info("%s walk: she'll walk out of the Invisibility Spell's circle in %.1f s (%s from %s): "
                         "another ahead of her", name, out, spot, done.cast_on)
                hidden_until = now
            elif (spot is not None and not hid and sighting.hue >= 0 and _family(sighting.hue) == "green"
                  and done.shown >= 2 and now < hidden_until
                  and done.cast_on is not None and now - done.cast_at >= SPELL_LAND + LOOK_EVERY):
                # Seen, not hidden, where the spell should hide her: it isn't (missed her, or wore off).
                # Only a green bar's told apart, hidden or not: a red one's left to her health (19 Nov:
                # at 33-38% and holding, red sightings sent three spells back to back; she fell for want).
                log.info("%s walk: seen though her Invisibility Spell should hide her: another", name)
                done.missed_on.append(done.cast_on)
                hidden_until, done.cast_on, done.missed, done.missed_at = now, None, True, now
            if now < hidden_until and now - done.cast_at >= MISS_AFTER and done.held is None:
                done.held = health
            elif now < hidden_until and done.held is not None and health <= done.held - MISS_DROP:
                log.info("%s walk: health %.0f%% and dropping: the Invisibility Spell missed her",
                         name, health * 100)
                if done.cast_on is not None:
                    done.missed_on.append(done.cast_on)
                hidden_until, done.missed, done.missed_at = now, True, now
            spell = next((c for c in done.invisibility if left[id(c)] is None or left[id(c)] > 0), None)
            # Losing health, she's not hidden, whatever the fox's clock says (18 Nov: hit from 92% to
            # 76% in what its clock had for its turn, the spell waited for it to end).
            healths = [(t, h) for t, h in healths if now - t <= HIT_SPAN] + [(now, health)]
            # In the fox's turn, shots already flying as it began still land: only a drop after counts
            # (18 Nov: 82% -> 76% as its turn began, a spell went into the turn).
            turn_from = now - (now - done.fox_at) % (fox + FOX_COOLDOWN) + HIT_FLIGHT if fox_turn else -1e9
            hit = max([h for t, h in healths if t >= turn_from] or [health]) - health >= HIT_DROP
            early = fox_turn  # (cast as the fox's turn ends, to land as it lets her go)
            # (Not as the fox's next turn's about to hide her: it would land in it. 18 Nov, hit 0.2 s
            # before its turn, a spell went into it.)
            hit = hit and not (fox and not fox_turn and fox_gap(fox, now - done.fox_at)[1] < SPELL_LAND)
            due = (spell is not None and now >= hidden_until
                   and (done.cast or health <= acfg.walk_invisibility_health)
                   and (hit or _spell_time(fox, now - done.fox_at, done, now))
                   # Hidden now, with no spell on her and her health holding: the fox's turn the clock
                   # hasn't caught up with (it will in a look or two); not as it ends, though.
                   and not (hid and not hit and not early and not covered))
            # Where it would go: never an old sighting (issue #30: two spells on where she went
            # down, 130 px behind her; two on a sighting 340 px behind her).
            there = _ahead(done, now, screen) if due else None
            if due and early and there is None and _standing(done) and done.seen not in done.missed_on:
                # (In the fox's turn, on where she stood fighting as it took her: she's still there.
                # Only standing by her heading, too: STILL lets a slow walk by.)
                there = done.seen
            if due and there is None:
                # Where she is isn't known (never found, seen too long ago, or not since a spell
                # missed her): none till she's seen, low or not; her ability's for her last stand.
                if wanted is None:
                    log.info("%s walk: health %.0f%%: an Invisibility Spell's due, but she %s: looking for "
                             "her first", name, health * 100,
                             "hasn't been seen yet" if not done.found else f"was last seen at {done.seen} "
                             f"{now - done.seen_at:.1f} s ago")
                wanted = now if wanted is None else wanted
                due = False
            elif due and not early and spot is None and now - done.seen_at > FRESH:
                # Not seen of late, but her heading says where she's got to: a look or two more for
                # her first. Low, at once (18 Nov: at 26% she fell meanwhile). Nor as the fox's gap
                # closes: by the next look it's too late for one (18 Nov: at 51%, 1.2 s before the
                # fox's turn, it waited and none went; she fell).
                wanted = now if wanted is None else wanted
                closing = fox and fox_gap(fox, now - done.fox_at)[1] < SPELL_WORTH + SIGHT_WAIT
                due = health <= SIGHT_LOW or closing or now - wanted >= SIGHT_WAIT
            if due:
                wanted = None
                if left[id(spell)] is None and armybar.is_spent(screen, spell, cfg.bar):
                    left[id(spell)] = 0
                else:
                    log.info("%s walk: health %.0f%%: Invisibility Spell on %s (%s %s)%s", name, health * 100,
                             there, "seen at" if spot is not None else "last seen at" if now - done.seen_at <= FRESH
                             else f"by her heading, {now - done.seen_at:.1f} s since she was seen at", done.seen,
                             ": to land as the fox's turn ends" if early else "")
                    game.tap(*spell.center)
                    game.wait(0.1)
                    game.tap(*there, jitter=3)
                    done.cast += 1
                    done.casts.append(now)
                    done.cast_at, done.held, done.missed, done.still = now, None, False, False
                    done.cast_on = there
                    hidden_until = now + INVISIBLE_FOR
                    if left[id(spell)] is not None:
                        left[id(spell)] -= 1
            elif (spell is None and acfg.hero_abilities and not done.fired
                  and health <= WALK_ABILITY_HEALTH and now >= hidden_until - ABILITY_LEAD):
                log.info("%s walk: health %.0f%%, no Invisibility left: her ability", name, health * 100)
                game.tap(*done.hero.center)
                done.fired = True
            elif acfg.hero_abilities and not done.fired and health <= WALK_LAST_STAND:
                # Nearly down though hidden (or a spell missed her): her ability, before it's lost
                # with her. (18 Nov: 59% -> cast -> 34% -> cast -> gone, ability unused.)
                log.info("%s walk: health %.0f%% even so: her ability", name, health * 100)
                game.tap(*done.hero.center)
                done.fired = True
        game.wait(LOOK_EVERY)

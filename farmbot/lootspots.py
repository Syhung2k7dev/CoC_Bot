"""Where the loot sits on an enemy base, for the "Toward the loot" placement.

Loot buildings change look with every level, so they aren't told apart by
pictures (there would be one per level and per resource). What every level
shares is the colour of the loot itself, and elixir's is plain to see: a
pink-magenta liquid, in a big glass globe on an Elixir Storage and a small
glass tank on an Elixir Collector. The fuller one is, the more pink shows,
and little else on a base is that colour. So the spots are the pink
patches inside the base, each weighed by its size.

Gold isn't found by colour: the brightest gold patches on a base are the
Builder's Hut's canvas and the Town Hall's roof, while a Gold Storage's
coins are paler than both (measured on bases from TH3 to TH16). Dark Elixir
is as dark as the stone and the shadows. Pictures taught in the Pictures
tool (``buildings/loot``: any storage, collector, mine or drill, a picture
per kind and level) are found too, so a user can add those; the base's
Available Loot (when read) weighs what pictures find against the elixir.

Tapping a building to read its name would tell it for sure, but a tap
inside the red line drops a troop (and on MuMu, a stray tap can hang the
game), so it is never done.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np

from farmbot.geometry import STANDARD_WIDTH, Point, Rect, scaled

log = logging.getLogger(__name__)

# Hue (OpenCV's 0-180), least saturation, least brightness.
ELIXIR = ((136, 172), 80, 190)
# Least size (px on a screen 860 wide, squared) of a patch that counts.
ELIXIR_MIN_AREA = 6.0  # an Elixir Collector's small tank
# A patch filling less than this share of its box is a line (a wall run, a trim), not a store.
MIN_FILL = 0.35
MAX_ASPECT = 3.0  # nor is one much longer than it is wide
MAX_AREA = 700.0  # nor one bigger than the biggest store: a patch of scenery (a rainbow, say)
TAUGHT_AREA = 60.0  # weight of a building found by its picture (as a fair-sized patch)
HEART_REACH = 90.0  # px on a screen 860 wide: stores this near each other count as one heap
INSET = 0.92  # spots only this far out from the base's middle to its outline: its edge is grass and decorations


@dataclass(frozen=True)
class Spot:
    kind: str  # "elixir" (by colour) or "taught" (by picture)
    point: Point
    weight: float


def _blank(mask: np.ndarray, rects: list[list[int]]) -> None:
    h, w = mask.shape[:2]
    for values in rects:
        r = Rect.from_list(values).resolve(w, h)
        mask[max(r.y, 0):r.y + r.h, max(r.x, 0):r.x + r.w] = 0


def base_mask(shape: tuple, outline: list[Point]) -> np.ndarray:
    """The base's inside: the hull of its deploy points, drawn in a little."""
    h, w = shape[:2]
    mask = np.zeros((h, w), np.uint8)
    if len(outline) < 3:
        return mask
    hull = cv2.convexHull(np.array(outline, np.int32).reshape(-1, 1, 2)).reshape(-1, 2).astype(np.float32)
    middle = hull.mean(axis=0)
    hull = middle + (hull - middle) * INSET
    cv2.fillPoly(mask, [hull.round().astype(np.int32)], 255)
    return mask


def _patches(hsv: np.ndarray, inside: np.ndarray, colour, min_area: float, width: int, kind: str) -> list[Spot]:
    (h_lo, h_hi), s_min, v_min = colour
    mask = cv2.inRange(hsv, (h_lo, s_min, v_min), (h_hi, 255, 255)) & inside
    k = max(2, round(scaled(2, width)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    unit = (width / STANDARD_WIDTH) ** 2  # px² on this screen per px² on a standard one
    spots = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not min_area * unit <= area <= MAX_AREA * unit:
            continue
        if area < MIN_FILL * w * h or max(w, h) > MAX_ASPECT * min(w, h):
            continue
        cx, cy = centres[i]
        spots.append(Spot(kind, (int(round(cx)), int(round(cy))), area / unit))
    return spots


def find(screen: np.ndarray, outline: list[Point], exclude: list[list[int]] = (),
         taught: list[Point] = ()) -> list[Spot]:
    """The loot patches inside the base whose deploy points are ``outline``
    (the UI's ``exclude`` rects left out), plus buildings ``taught`` by
    picture, each weighed by its size."""
    inside = base_mask(screen.shape, outline)
    _blank(inside, list(exclude))
    width = screen.shape[1]
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    spots = _patches(hsv, inside, ELIXIR, ELIXIR_MIN_AREA, width, "elixir")
    spots += [Spot("taught", p, TAUGHT_AREA) for p in taught if inside[p[1], p[0]]]
    return spots


def shares(loot) -> dict[str, float]:
    """How much each kind of spot counts: elixir patches by the base's
    elixir against its gold, buildings taught by picture as they are
    (``loot``: its Available Loot, or None: even)."""
    gold, elixir = (getattr(loot, "gold", 0) or 0, getattr(loot, "elixir", 0) or 0) if loot else (0, 0)
    total = gold + elixir
    return {"elixir": 2 * elixir / total if total > 0 else 1.0, "taught": 1.0}


def heart(spots: list[Spot], width: int, loot=None) -> tuple[Point, float] | None:
    """Where most loot sits together: the spot with the most weight within
    HEART_REACH of it (each kind weighed by ``shares``), and that weight.
    None when there is no spot."""
    if not spots:
        return None
    share = shares(loot)
    reach = scaled(HEART_REACH, width)
    best = None
    for spot in spots:
        near = sum(s.weight * share[s.kind] for s in spots if math.dist(s.point, spot.point) <= reach)
        if best is None or near > best[1]:
            best = (spot.point, near)
    return best


HEAP_SHARE = 0.35  # a heap of loot this share of the biggest one's weight gets troops of its own
MOST_HEAPS = 4  # troops split between at most this many heaps
# Least weight of the biggest heap for the loot to count as seen: a storage
# seen plainly. Less (empty storages, a few pink specks) is a guess, and
# troops sent after it can miss the loot altogether: they spread instead.
MIN_HEAP = 100.0


def heaps(spots: list[Spot], width: int, loot=None) -> list[tuple[Point, float]]:
    """Where the loot sits, heap by heap, biggest first: the heart, then
    the heart of the spots more than HEART_REACH from it, and so on. Kept:
    those with at least HEAP_SHARE of the biggest one's weight, at most
    MOST_HEAPS (storages spread round a base each get troops). None when
    even the biggest weighs under MIN_HEAP."""
    reach = scaled(HEART_REACH, width)
    left, found = list(spots), []
    while left and len(found) < MOST_HEAPS:
        at, weight = heart(left, width, loot)
        if not found and weight < MIN_HEAP:
            return []  # not seen plainly enough to go by
        if found and weight < HEAP_SHARE * found[0][1]:
            break
        found.append((at, weight))
        left = [s for s in left if math.dist(s.point, at) > reach]
    return found


FRONT_REACH = 80.0  # px on a screen 860 wide: the stretch of a side either way of its point nearest the loot


def front(points: list[Point], at: Point, width: int) -> list[Point]:
    """The stretch of a side's deploy ``points`` (in their order) nearest
    ``at``: its nearest point and those within FRONT_REACH of that one."""
    nearest = min(points, key=lambda p: math.dist(p, at))
    reach = scaled(FRONT_REACH, width)
    return [p for p in points if math.dist(p, nearest) <= reach]


def draw(screen: np.ndarray, spots: list[Spot], at: Point | None = None) -> np.ndarray:
    """``screen`` with the spots ringed (pink elixir, white taught) and the heart crossed."""
    out = screen.copy()
    colours = {"elixir": (255, 0, 255), "taught": (255, 255, 255)}
    for s in spots:
        cv2.circle(out, s.point, max(4, int(math.sqrt(s.weight))), colours[s.kind], 2)
    if at is not None:
        cv2.drawMarker(out, at, (0, 0, 255), cv2.MARKER_TILTED_CROSS, 30, 3)
    return out

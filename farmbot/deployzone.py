"""Where troops can go when no red line is shown.

The base's building area is drawn as bright checkerboard grass; the
darker strip around it is never built on. We find the bright grass,
wrap it in its convex hull, push that outline outward by about a tile,
and keep the points that land on open ground away from the screen's UI.
Any point the game still rejects just costs a tap: the deploy loop checks
whether the troop count went down.

At low Town Halls the bright grass covers nearly the whole map, so its
outline is the map's edge. There the ring goes round the cluster of
buildings instead (see :func:`building_cluster`). On sceneries with no
grass (a city's paving, a stone floor, snow) the buildings are told from
the ground by their edges instead of by colour (see :func:`texture`).
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from farmbot.config import ZoneConfig
from farmbot.geometry import Point, Rect, scaled
from farmbot.redline import SIDE_ANGLES, RedLine

log = logging.getLogger(__name__)


def building_area(screen: np.ndarray, cfg: ZoneConfig) -> np.ndarray | None:
    """Convex hull of the bright building-area grass, or ``None``.

    The grass is a little darker on some screens (the scouting view is
    dimmed slightly on some emulators), so a darker threshold is tried when
    the configured one finds nothing.
    """
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    for darker in (0, 10, 20):
        hull = _grass_hull(hsv, cfg, cfg.grass_min_value - darker)
        if hull is not None:
            return hull
    return None


def _grass_hull(hsv: np.ndarray, cfg: ZoneConfig, v_min: int) -> np.ndarray | None:
    (h_lo, h_hi), s_min = cfg.grass_hue, cfg.grass_min_saturation
    mask = cv2.inRange(hsv, (h_lo, s_min, v_min), (h_hi, 255, 255))
    _blank(mask, cfg.exclude)
    # At half size (every second pixel): the patches are big, and it takes
    # a quarter of the time.
    mask, step = mask[::CLUSTER_STEP, ::CLUSTER_STEP], CLUSTER_STEP
    opening, closing = max(1, round(cfg.open_px / step)), 2 * round(cfg.close_px / step / 2) + 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((opening, opening), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (closing, closing)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] * step * step >= cfg.min_patch]
    if len(keep) < cfg.min_patches:
        return None
    points = cv2.findNonZero(np.isin(labels, keep).astype(np.uint8))
    return cv2.convexHull(points) * step


def _blank(mask: np.ndarray, rects: list[list[int]]) -> None:
    h, w = mask.shape[:2]
    for values in rects:
        r = Rect.from_list(values).resolve(w, h)
        mask[max(r.y, 0):r.y + r.h, max(r.x, 0):r.x + r.w] = 0


def ground(screen: np.ndarray) -> np.ndarray:
    """Grass or dirt, per pixel."""
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    grass = (h >= 22) & (h <= 58) & (s >= 90) & (v >= 90)
    dirt = (h >= 10) & (h < 22) & (s >= 80) & (v >= 80)
    return grass | dirt


def open_ground(screen: np.ndarray, cfg: ZoneConfig) -> np.ndarray:
    """Share of non-ground pixels around each pixel (0 = all grass/dirt)."""
    blocked = 1.0 - ground(screen).astype(np.float32)
    k = cfg.ground_window
    return cv2.blur(blocked, (k, k))


# share of the screen not grass or dirt above which its colour can't tell ground (city, stone, snow)
GROUND_UNKNOWN = 0.8
EDGE_STEP = 120  # a brightness step (Sobel) this sharp is a building's, wall's or decoration's edge
TEXTURE_WINDOW = 15  # px on a screen 860 wide: edges are counted over this square
TEXTURE_BUSY = 0.25  # a share of edge pixels above this is among buildings; plain ground has hardly any


def unknown_ground(blocked: np.ndarray) -> bool:
    """``open_ground``'s map is no use: hardly any grass or dirt on screen."""
    return float(blocked.mean()) > GROUND_UNKNOWN


def texture(screen: np.ndarray) -> np.ndarray:
    """Share of sharp-edged pixels around each pixel: high among buildings,
    walls and decorations, low on open ground, whatever its colour (plain
    grass, snow, ice, a city's paving or a stone floor are all smooth next
    to what is built on them)."""
    grey = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY).astype(np.float32)
    step = np.hypot(cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3))
    k = 2 * round(scaled(TEXTURE_WINDOW, screen.shape[1]) / 2) + 1
    return cv2.blur((step > EDGE_STEP).astype(np.float32), (k, k))


CLUSTER_JOIN_PX = 22  # buildings closer than this (px on a screen 860 wide) are one cluster
CLUSTER_PART = 0.003  # of the screen's height squared: a smaller patch is a tree or a rock
CLUSTER_MIN_SHARE = 0.015  # of the screen: a smaller cluster is a stray object, not a base
CLUSTER_GRASS_SHARE = 0.5  # bright grass more than twice the cluster's size is the whole map
CLUSTER_STEP = 2  # the clusters are found on every second pixel
CLUSTER_OFFSET = 1.5  # the ring goes this many times ``offset_px`` out from the buildings


def building_cluster(screen: np.ndarray, cfg: ZoneConfig) -> np.ndarray | None:
    """Convex hull of the clusters of buildings, or ``None``.

    Buildings, walls and decorations are what isn't grass or dirt. Joined
    up, the base is the patches of them bigger than a tree or a rock that
    don't run off the screen (the forest round the map does). A small base
    can be in a few (its buildings, a Builder's Hut set apart)."""
    blocked = ~ground(screen)
    by_texture = float(blocked.mean()) > GROUND_UNKNOWN
    if by_texture:  # no grass to tell buildings by (city, stone): they're what's busy with edges
        blocked = texture(screen) > TEXTURE_BUSY
    blocked = blocked.astype(np.uint8) * 255
    _blank(blocked, cfg.exclude)
    # At half size: the shapes are big, and it takes a quarter of the time.
    blocked = blocked[::CLUSTER_STEP, ::CLUSTER_STEP]
    h, w = blocked.shape[:2]
    blocked = cv2.morphologyEx(blocked, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    k = 2 * round(scaled(CLUSTER_JOIN_PX, screen.shape[1]) / CLUSTER_STEP / 2) + 1
    blocked = cv2.morphologyEx(blocked, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(blocked)
    # (a big base on a plain floor runs up under the loot at the top: it may touch the top there)
    inner = [i for i in range(1, count)
             if stats[i, cv2.CC_STAT_LEFT] > 0 and (by_texture or stats[i, cv2.CC_STAT_TOP] > 0)
             and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < w
             and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < h]
    parts = [i for i in inner if stats[i, cv2.CC_STAT_AREA] >= CLUSTER_PART * h * h]
    if not parts:
        return None
    hull = cv2.convexHull(cv2.findNonZero(np.isin(labels, parts).astype(np.uint8))) * CLUSTER_STEP
    return hull if cv2.contourArea(hull) >= CLUSTER_MIN_SHARE * screen.shape[0] * screen.shape[1] else None


def base_outline(screen: np.ndarray, cfg: ZoneConfig) -> tuple[np.ndarray, float] | None:
    """The building area's hull and how far out (px on a screen 860 wide)
    the ring goes: the bright grass, or, where that is (nearly) the whole
    map, the cluster of buildings."""
    hull = building_area(screen, cfg)
    cluster = building_cluster(screen, cfg)
    if cluster is not None and (hull is None or cv2.contourArea(cluster) < CLUSTER_GRASS_SHARE * cv2.contourArea(hull)):
        log.debug("Deploy zone: the bright grass is the whole map; going round the buildings")
        return cluster, cfg.offset_px * CLUSTER_OFFSET
    return (hull, cfg.offset_px) if hull is not None else None


def detect(screen: np.ndarray, cfg: ZoneConfig) -> RedLine | None:
    blocked = open_ground(screen, cfg)
    outline = base_outline(screen, cfg)
    if unknown_ground(blocked):
        # no grass: the busy blob cut loose from the scenery, where it is the
        # bigger (the cluster of buildings can miss part of a busy city's
        # base); on a plain floor the cluster is the bigger, and the busy
        # blob may be only a heap of troops or decorations in the middle
        busy = busy_base(screen, cfg)
        if busy is not None and (outline is None or cv2.contourArea(busy) > cv2.contourArea(outline[0])):
            return _ring(screen, busy, cfg.offset_px * BUSY_OFFSET, cfg, None, 0.0)
    if outline is None:
        log.debug("Deploy zone: building area not found")
        return None
    hull, offset = outline
    most = cfg.max_blocked
    if unknown_ground(blocked):
        blocked, most = texture(screen), TEXTURE_BUSY
    return _ring(screen, hull, offset, cfg, blocked, most)


# Busy scenery round the map (sweets, a temple, city blocks, factories, a
# harbour): its clutter is as busy with edges as the base's, and decorations
# on the plain floor between them join the two up, so neither the grass nor
# the cluster finds the base. Looked at coarsely (how busy each cell's
# surroundings are), the base is the dense blob round the middle; worn away
# a little at a time, it comes loose from the scenery, and grown back as far
# as it was worn, it is the base alone.
BUSY_CELL = 6  # px on a screen 860 wide: how busy is judged cell by cell
BUSY_WINDOW = 5  # cells: over this square round each
BUSY_DENSE = 0.35  # a share of busy pixels above this is the base's (or the scenery's) clutter
BUSY_PART = 0.02  # of the cells: a smaller blob is a few decorations
BUSY_MOST_WORN = 25  # cells: worn away no further than this
BUSY_MIDDLE = (0.5, 0.45)  # where the base is looked for, in the screen's width and height
BUSY_OFFSET = 2.5  # the ring goes this many times ``offset_px`` out (the coarse look draws the blob a little in)


def busy_base(screen: np.ndarray, cfg: ZoneConfig) -> np.ndarray | None:
    """Hull of the dense, busy blob round the screen's middle, cut loose
    from busy scenery round the map, or ``None``."""
    h, w = screen.shape[:2]
    busy = (texture(screen) > TEXTURE_BUSY).astype(np.float32)
    _blank(busy, cfg.exclude)
    cell = max(2, round(scaled(BUSY_CELL, w)))
    cells = cv2.resize(busy, (w // cell, h // cell), interpolation=cv2.INTER_AREA)
    dense = (cv2.blur(cells, (BUSY_WINDOW, BUSY_WINDOW)) > BUSY_DENSE).astype(np.uint8)
    ch, cw = dense.shape
    mx, my = cw * BUSY_MIDDLE[0], ch * BUSY_MIDDLE[1]
    square = np.ones((3, 3), np.uint8)
    for worn in range(BUSY_MOST_WORN + 1):
        left = cv2.erode(dense, square, iterations=worn) if worn else dense
        count, labels, stats, centres = cv2.connectedComponentsWithStats(left)
        blobs = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= BUSY_PART * ch * cw]
        if not blobs:
            return None
        i = min(blobs, key=lambda i: np.hypot(centres[i][0] - mx, centres[i][1] - my))
        if _loose(stats[i], cw, ch):
            # the base can be in several dense parts (open ground between them): every loose one
            blob = np.isin(labels, [j for j in blobs if _loose(stats[j], cw, ch)]).astype(np.uint8)
            if worn:
                blob = cv2.dilate(blob, square, iterations=worn) & dense
            hull = cv2.convexHull(cv2.findNonZero(blob)) * cell + cell // 2
            return hull if cv2.contourArea(hull) >= CLUSTER_MIN_SHARE * h * w else None
    return None


def _loose(stats: np.ndarray, w: int, h: int) -> bool:
    """A blob that touches none of the screen's edges."""
    x, y, bw, bh = stats[:4]
    return x > 0 and y > 0 and x + bw < w and y + bh < h


def detect_busy(screen: np.ndarray, cfg: ZoneConfig) -> RedLine | None:
    """The ring round :func:`busy_base`. Its points aren't judged by the
    ground under them: outside the base's clutter, troops go down anywhere,
    on the scenery's decorations too."""
    hull = busy_base(screen, cfg)
    if hull is None:
        log.debug("Deploy zone: no busy base found")
        return None
    return _ring(screen, hull, cfg.offset_px * BUSY_OFFSET, cfg, None, 0.0)


def _ring(screen: np.ndarray, hull: np.ndarray, offset: float, cfg: ZoneConfig, blocked: np.ndarray | None,
          most: float) -> RedLine:
    """Points on ``hull`` pushed ``offset`` out (px on a screen 860 wide),
    per side, away from the screen's UI, and (with ``blocked``) on open
    ground."""
    h, w = screen.shape[:2]
    filled = np.zeros((h, w), np.uint8)
    cv2.fillPoly(filled, [hull.astype(np.int32)], 255)
    k = 2 * round(scaled(offset, w)) + 1
    grown = cv2.dilate(filled, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    contours, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = max(contours, key=cv2.contourArea).reshape(-1, 2)

    allowed = np.full((h, w), 255, np.uint8)
    _blank(allowed, cfg.exclude)
    moments = cv2.moments(hull)
    cx, cy = moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]

    sides: dict[str, list[tuple[float, Point]]] = {s: [] for s in SIDE_ANGLES}
    for x, y in outline[::cfg.step_px]:
        if not (0 <= x < w and 0 <= y < h) or not allowed[y, x]:
            continue
        if blocked is not None and blocked[y, x] > most:
            continue
        angle = float(np.degrees(np.arctan2(y - cy, x - cx)))
        for side, (lo, hi) in SIDE_ANGLES.items():
            if lo <= angle < hi or (side == "sw" and angle == 180.0):
                sides[side].append((angle, (int(x), int(y))))
                break
    ordered = {s: [p for _, p in sorted(pts)] for s, pts in sides.items()}
    log.debug("Deploy zone: centre (%d, %d), points %s", cx, cy, {s: len(p) for s, p in ordered.items()})
    return RedLine((round(cx), round(cy)), ordered)

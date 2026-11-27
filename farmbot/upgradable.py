"""What an account can still upgrade, learnt from the game's own Build list.

The village export says every building's level but not how far each can
go at this Town Hall. Rather than a table of the game's levels (out of date
with each update), the bot reads the list itself through, top to bottom:
what's in it can still be upgraded (or built); a pick that isn't, and that
the export doesn't show upgrading, is done for now. Kept beside the
account's village export (``profiles/<name>.upgradable.json``) for the
Town Hall and Laboratory levels it was read at: once either goes up it no
longer counts (all back at once), and it's read again once a day.

``which``: "buildings" (Buildings & Heroes) or "research" (Army Upgrades).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import gamedata, townhall

log = logging.getLogger(__name__)

KINDS = ("buildings", "research")
# The export's names for what each list holds (their ids -> names).
_NAMES = {"buildings": {**gamedata.BUILDINGS, **gamedata.TRAPS, **gamedata.HEROES},
          "research": {**gamedata.TROOPS, **gamedata.SPELLS}}


@dataclass
class Seen:
    town_hall: int
    lab: int
    on: str  # the day it was read (YYYY-MM-DD)
    names: frozenset[str]


def path_for(village_path: str | Path | None) -> Path | None:
    """Kept beside the village export: ``x.village.json`` -> ``x.upgradable.json``."""
    if village_path is None:
        return None
    p = Path(village_path)
    return p.with_name(p.name.replace("village", "upgradable") if "village" in p.name
                       else p.stem + ".upgradable.json")


def levels(village: townhall.Village) -> tuple[int, int]:
    return village.town_hall, village.buildings.get(townhall.LABORATORY, (0, 0))[0]


def load(path: str | Path | None) -> dict[str, Seen]:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {k: Seen(int(v["town_hall"]), int(v["lab"]), str(v["on"]), frozenset(map(str, v["names"])))
                for k, v in data.items() if k in KINDS}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def save(path: str | Path, which: str, village: townhall.Village, names: set[str], on: str) -> None:
    kept = {k: {"town_hall": v.town_hall, "lab": v.lab, "on": v.on, "names": sorted(v.names)}
            for k, v in load(path).items()}
    th, lab = levels(village)
    kept[which] = {"town_hall": th, "lab": lab, "on": on, "names": sorted(names)}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, indent=1), encoding="utf-8")


def current(path: str | Path | None, village: townhall.Village | None, which: str) -> Seen | None:
    """What was read for ``which``, if it was at this village's levels."""
    if village is None:
        return None
    seen = load(path).get(which)
    if seen is None or (seen.town_hall, seen.lab) != levels(village):
        return None
    return seen


def due(path: str | Path | None, village: townhall.Village | None, which: str, today: str) -> bool:
    """Read the list through again: never read at these levels, or not today."""
    seen = current(path, village, which)
    return village is not None and (seen is None or seen.on != today)


def done(path: str | Path | None, village: townhall.Village | None, which: str,
         choices: tuple[str, ...]) -> set[str]:
    """The ``choices`` there's nothing left to upgrade of now: not in the
    list when it was last read at these levels, nor upgrading in the export."""
    seen = current(path, village, which)
    if seen is None:
        return set()
    busy = {_NAMES[which].get(i) for i in village.upgrading}
    return {c for c in choices if c not in seen.names and c not in busy}


def busy(village: townhall.Village | None, which: str, choices: tuple[str, ...],
         now: float) -> dict[str, tuple[int, int, int | None]]:
    """The ``choices`` being upgraded (or researched), by the export: name ->
    (how many under way, how many there are (0: not known), when the first
    of them ends (seconds since 1970; None: it has, since the export))."""
    if village is None:
        return {}
    ids: dict[str, list[int]] = {}
    for i, name in _NAMES[which].items():
        if name in choices:
            ids.setdefault(name, []).append(i)
    out = {}
    for name, its in ids.items():
        ends = [t for i in its for t in village.finishing.get(i, ())]
        if not ends:
            continue
        left = [t for t in ends if t > now]
        out[name] = (len(ends), sum(village.counts.get(i, 0) for i in its), min(left) if left else None)
    return out


def left_to_start(path: str | Path | None, village: townhall.Village | None, which: str,
                  choices: tuple[str, ...] | None, now: float) -> set[str] | None:
    """What could still be started of ``choices`` (None: anything in the
    list): in the list when it was last read through at these levels, less
    what the export shows with every copy under way. None if the list
    wasn't read through at these levels."""
    seen = current(path, village, which)
    if seen is None:
        return None
    names = set(seen.names) if choices is None else set(choices) & seen.names
    under_way = busy(village, which, tuple(names), now)
    return {n for n in names if n not in under_way or under_way[n][0] < under_way[n][1]}


def item_levels(village: townhall.Village | None, which: str, choices: tuple[str, ...]) -> dict[str, int]:
    """The level each of ``choices`` is at, by the export (``which``:
    "research" or "equipment"); those it doesn't hold (not unlocked, or no
    export) are left out."""
    if village is None:
        return {}
    table = gamedata.EQUIPMENT if which == "equipment" else _NAMES[which]
    wanted = set(choices)
    out: dict[str, int] = {}
    for i, name in table.items():
        if name in wanted and i in village.levels:
            out[name] = max(village.levels[i], out.get(name, 0))
    return out


def owned_equipment(village: townhall.Village | None, by_hero: dict[str, tuple[str, ...]]) -> set[str] | None:
    """The pieces the player has, of ``by_hero`` (hero -> its pieces), by
    the export; None with no export (anything may be). The export lists
    every Common piece the Blacksmith has unlocked, the hero had or not, and
    every Epic piece at level 1 whether it's been got or not (an account
    with none of them lists all): a piece counts once its hero is had, and
    an Epic one once it's above level 1."""
    if village is None:
        return None
    heroes = {name for i, name in gamedata.HEROES.items() if i in village.levels}
    levels = item_levels(village, "equipment", tuple(n for names in by_hero.values() for n in names))
    return {n for hero, names in by_hero.items() if hero in heroes for n in names
            if n in levels and (n not in gamedata.EQUIPMENT_EPIC or levels[n] > 1)}


def maxed_equipment(levels: dict[str, int]) -> set[str]:
    """The pieces at their rarity's last level (``levels``: :func:`item_levels`)."""
    return {name for name, level in levels.items() if level >= gamedata.equipment_max(name)}


def time_left(seconds: float) -> str:
    """3d 18h, 5h 20m, 12m."""
    m = max(int(seconds // 60), 1)
    d, h, m = m // 1440, m // 60 % 24, m % 60
    return f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m"


class Survey:
    """For one round of upgrades: whether each list is due a read
    through, and where what's read is kept."""

    def __init__(self, path: str | Path | None, village: townhall.Village | None, today: str, on_saved=None):
        self.path, self.village, self.today, self.on_saved = path, village, today, on_saved

    def due(self, which: str) -> bool:
        return self.path is not None and due(self.path, self.village, which, self.today)

    def record(self, which: str, names: set[str]) -> None:
        if self.path is None or self.village is None:
            return
        try:
            save(self.path, which, self.village, names, self.today)
        except OSError as exc:
            log.info("Upgrades: couldn't keep what's left to upgrade: %s", exc)
            return
        if self.on_saved:
            self.on_saved()

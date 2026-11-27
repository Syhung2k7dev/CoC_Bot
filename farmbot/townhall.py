"""What an account has unlocked, from the game's own village export
(profile → Settings → More Settings → Data Export: "Copy"): the Town Hall's
level, and every building's. It's kept beside the account's profile
(``profiles/<name>.village.json``), or in the farm's folder without
profiles (``village.json``), and read again once a day.

With it the bot leaves out what this account can't do yet (research
before the Laboratory, the clan before the Clan Castle is rebuilt...),
and the window says so on those settings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import gamedata

log = logging.getLogger(__name__)

VILLAGE_FILE = "village.json"

# The game's ids for the buildings the export lists ("data").
TOWN_HALL = 1000001
LABORATORY = 1000007
WALL = 1000010
CLAN_CASTLE = 1000014
BUILDERS_HUT = 1000015
BLACKSMITH = 1000070
BOB_CONTROL = 1000065  # in the builder base: its builder (B.O.B) works in the home village too
OTTO_OUTPOST = 1000078  # the builder base's second builder (O.T.T.O)

# The export's lists whose items carry "timer" while upgrading (or researched).
UPGRADING_LISTS = ("buildings", "traps", "units", "spells", "siege_machines", "heroes", "pets")
# The home village's lists whose levels are kept (the builder base's own, "units2" and the like, aren't:
# a few of their names are the home village's too).
LEVEL_LISTS = ("units", "siege_machines", "spells", "heroes", "equipment")
# The builder base's lists, by who works on them: its builders (the Master Builder, O.T.T.O) or its Star Laboratory.
BUILDER_BASE_LISTS = {"buildings2": "builders", "traps2": "builders", "heroes2": "builders", "units2": "lab"}
# The helpers (the export's "helpers"): each speeds up the upgrade it's put on ("helper_recurrent"
# on it: put back on it each time it's ready) for an hour, saving its level in hours, once every
# HELPER_CYCLE (a cooldown they share). The Builder's Apprentice helps builders' upgrades, the
# Lab Assistant research.
BUILDERS_APPRENTICE = 93000000
LAB_ASSISTANT = 93000001
HELPED_BY = {"buildings": BUILDERS_APPRENTICE, "traps": BUILDERS_APPRENTICE, "heroes": BUILDERS_APPRENTICE,
             "units": LAB_ASSISTANT, "spells": LAB_ASSISTANT, "siege_machines": LAB_ASSISTANT}
HELPER_CYCLE = 23 * 3600  # s from one hour of help to the next
HELPER_HOUR = 3600


def helped_end(start: int, left: int, level: int, cooldown: int) -> float:
    """When an upgrade with ``left`` seconds to go at ``start`` is done,
    with a helper of ``level`` put on it each time it's ready (in
    ``cooldown`` seconds): each hour of help does ``level`` + 1 hours of it."""
    rate = level + 1
    t, left_ = float(start), float(left)
    # Its last hour of help began HELPER_CYCLE - cooldown before ``start``; ready (no cooldown): now.
    begun = start - (HELPER_CYCLE - cooldown) if cooldown > 0 else start
    for _ in range(400):  # (a year of help at most)
        help_from, help_to = max(begun, t), begun + HELPER_HOUR
        if help_to > t:  # an hour of help still to come, or under way
            if t + left_ <= help_from:
                return t + left_
            left_ -= help_from - t
            t = help_from
            if left_ <= (help_to - t) * rate:
                return t + left_ / rate
            left_ -= (help_to - t) * rate
            t = help_to
        begun += HELPER_CYCLE
    return t + left_

# Town Hall levels that open a feature (only those that are certain: a
# feature is left out only when it can't be there yet).
DARK_ELIXIR_AT = 7
HEROES_AT = 7
BUILDER_BASE_AT = 6  # the boat is repaired from Town Hall 6 (an account that repaired it earlier, when the
# game let it, keeps its builder base: see Village.builder_base)
SPELLS_AT = 5  # the Spell Factory
WALL_ELIXIR_AT = 5  # walls take elixir from level 5, which Town Hall 5 opens
SUPER_TROOPS_AT = 11
SIEGE_AT = 12  # the Workshop
PETS_AT = 14
BLACKSMITH_AT = 8

# What each feature is called, at the top of a page or tab it leaves out.
NAMES = {"research": "Research", "clan": "The clan", "heroes": "Heroes", "pets": "Pets",
         "dark": "Dark elixir", "spells": "Spells", "super_troops": "Super troops",
         "siege": "Siege machines", "builder_base": "The Builder Base", "wall_elixir": "Walls with elixir",
         "builder_heroes": "Builder base heroes", "equipment": "Hero equipment"}


@dataclass
class Village:
    """The export, as far as the bot needs it."""

    town_hall: int
    buildings: dict[int, tuple[int, int]] = field(default_factory=dict)  # id -> (level, how many)
    heroes: int = 0
    pets: int = 0
    builder_heroes: int = -1  # the builder base's (-1: not in the export)
    builders: int = 0  # the home village's builders: a hut each, and B.O.B (0: not in the export)
    builder_base_builders: int = 0  # the Master Builder, and O.T.T.O (0: no builder base in the export)
    timestamp: int = 0  # when the game made the export (seconds since 1970)
    town_hall_until: int = 0  # when the Town Hall's upgrade under way ends (seconds since 1970; 0: none)
    builder_base: bool = False  # the builder base is in use (it has troops or a hero): the boat is repaired
    read_on: str = ""  # the day the bot read it (YYYY-MM-DD)
    # What was being upgraded or researched when the export was made: the
    # game's id -> when each one under way ends (seconds since 1970).
    finishing: dict[int, tuple[int, ...]] = field(default_factory=dict)
    # The same for the builder base, by who works on it ("builders", "lab"): when each one under way
    # ends (a Clock Tower boost isn't counted: it ends sooner).
    builder_finishing: dict[str, tuple[int, ...]] = field(default_factory=dict)
    # The helpers unlocked: the game's id -> (level, seconds until it's ready again).
    helpers: dict[int, tuple[int, int]] = field(default_factory=dict)
    # What each helper is put on ("helper_recurrent": the game puts it back on that each time it's
    # ready), while that's still under way: the helper's id -> the upgrade's id.
    helping: dict[int, int] = field(default_factory=dict)
    # How many there are of each building and trap (the game's id), upgrading or not.
    counts: dict[int, int] = field(default_factory=dict)
    # The home village's troops, siege machines, spells, heroes and hero equipment: the game's id -> level.
    levels: dict[int, int] = field(default_factory=dict)

    @property
    def upgrading(self) -> frozenset[int]:
        return frozenset(self.finishing)

    def has(self, building: int) -> bool:
        return self.buildings.get(building, (0, 0))[1] > 0


def parse(text: str | None) -> Village | None:
    """The export the game copied (its JSON), or None if ``text`` isn't one."""
    if not text or not text.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("buildings"), list):
        return None
    buildings: dict[int, tuple[int, int]] = {}
    for b in data["buildings"]:
        if not isinstance(b, dict) or not isinstance(b.get("data"), int):
            continue
        level, count = int(b.get("lvl", 0) or 0), int(b.get("cnt", 1) or 1)
        old_level, old_count = buildings.get(b["data"], (0, 0))
        buildings[b["data"]] = (max(level, old_level), old_count + count)
    hall = buildings.get(TOWN_HALL, (0, 0))[0]
    if hall < 1:
        return None
    # A building being upgraded carries "timer": the seconds left when the export was made.
    left = max((b["timer"] for b in data["buildings"] if isinstance(b, dict) and b.get("data") == TOWN_HALL
                and isinstance(b.get("timer"), int)), default=0)
    count = lambda key: len(data.get(key) or []) if isinstance(data.get(key), list) else 0
    stamp = data.get("timestamp")
    base2 = [b.get("data") for b in (data.get("buildings2") if isinstance(data.get("buildings2"), list) else [])
             if isinstance(b, dict)]
    bob = BOB_CONTROL in base2
    huts = buildings.get(BUILDERS_HUT, (0, 0))[1]
    finishing: dict[int, tuple[int, ...]] = {}
    helping: dict[int, int] = {}
    counts: dict[int, int] = {}
    when = stamp if isinstance(stamp, int) else 0
    helpers = {h["data"]: (int(h.get("lvl", 0) or 0), int(h.get("helper_cooldown", 0) or 0))
               for h in (data.get("helpers") if isinstance(data.get("helpers"), list) else ())
               if isinstance(h, dict) and isinstance(h.get("data"), int)}
    for key in UPGRADING_LISTS:
        for item in data.get(key) if isinstance(data.get(key), list) else ():
            if not isinstance(item, dict) or not isinstance(item.get("data"), int):
                continue
            if key in ("buildings", "traps"):
                counts[item["data"]] = counts.get(item["data"], 0) + int(item.get("cnt", 1) or 1)
            if isinstance(item.get("timer"), int) and item["timer"] > 0:
                end: float = when + item["timer"]
                level, cooldown = helpers.get(HELPED_BY.get(key, 0), (0, 0))
                if item.get("helper_recurrent") and level > 0:
                    end = helped_end(when, item["timer"], level, cooldown)
                    helping[HELPED_BY[key]] = item["data"]
                finishing[item["data"]] = (*finishing.get(item["data"], ()), int(end))
    levels: dict[int, int] = {}
    for key in LEVEL_LISTS:
        for item in data.get(key) if isinstance(data.get(key), list) else ():
            if isinstance(item, dict) and isinstance(item.get("data"), int) and isinstance(item.get("lvl"), int):
                levels[item["data"]] = max(item["lvl"], levels.get(item["data"], 0))
    builder_finishing: dict[str, tuple[int, ...]] = {}
    for key, slot in BUILDER_BASE_LISTS.items():
        for item in data.get(key) if isinstance(data.get(key), list) else ():
            if isinstance(item, dict) and isinstance(item.get("timer"), int) and item["timer"] > 0:
                builder_finishing[slot] = (*builder_finishing.get(slot, ()), when + item["timer"])
    return Village(hall, buildings, heroes=count("heroes"), pets=count("pets"),
                   finishing={k: tuple(sorted(v)) for k, v in finishing.items()}, counts=counts, levels=levels,
                   builder_finishing={k: tuple(sorted(v)) for k, v in builder_finishing.items()},
                   helpers={k: v for k, v in helpers.items() if v[0] > 0}, helping=helping,
                   builder_heroes=count("heroes2") if isinstance(data.get("heroes2"), list) else -1,
                   builders=huts + bob if huts else 0,
                   builder_base_builders=(1 + (OTTO_OUTPOST in base2)) if base2 else 0,
                   timestamp=stamp if isinstance(stamp, int) else 0,
                   town_hall_until=stamp + left if isinstance(stamp, int) and left > 0 else 0,
                   builder_base=bool(count("units2") or count("heroes2")))


def apprentice_job(village: Village | None, now: float, ids: set[int] | frozenset[int] = frozenset(),
                   helper: int = BUILDERS_APPRENTICE) -> int | None:
    """The upgrade under way to put an idle ``helper`` on (the game's id),
    or None: not unlocked, already on one still under way, or none worth
    it. The one with the most time left: it gets every hour of help to
    come (an upgrade done within the hour would waste some). ``ids``: the
    upgrades it may help (by default the apprentice's: buildings, traps,
    heroes)."""
    if village is None or village.helpers.get(helper, (0, 0))[0] <= 0 or helper in village.helping:
        return None
    from farmbot import gamedata

    ids = ids or {*gamedata.BUILDINGS, *gamedata.TRAPS, *gamedata.HEROES}
    worth = [(max(ends), i) for i, ends in village.finishing.items() if i in ids and max(ends) > now + HELPER_HOUR]
    return max(worth)[1] if worth else None


def _read_kept(path: str | Path | None) -> tuple[dict, Village] | None:
    """What :func:`save` kept at ``path`` and the village in it; None if
    there's no file, or no export the game would give in it."""
    if path is None:
        return None
    try:
        kept = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict):
        return None
    village = parse(json.dumps(kept.get("export")))
    return None if village is None else (kept, village)


def load(path: str | Path | None) -> Village | None:
    """The export kept at ``path`` (see :func:`save`), if any."""
    read = _read_kept(path)
    if read is None:
        return None
    kept, village = read
    village.read_on = str(kept.get("read_on", ""))
    return village


def save(path: str | Path, text: str, read_on: str) -> None:
    """Keep the export the game copied (``text``) at ``path``, with the day."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = {"read_on": read_on, "export": json.loads(text)}
    path.write_text(json.dumps(kept, indent=1), encoding="utf-8")


def locked(village: Village | None) -> dict[str, str]:
    """What this account can't do yet, each with why: "research", "clan"
    (donations, requests, the Clan Capital), "heroes", "pets", "dark",
    "spells", "super_troops", "siege", "builder_base", "wall_elixir",
    "builder_heroes", "equipment".
    Nothing when it isn't known."""
    if village is None:
        return {}
    th = village.town_hall
    out: dict[str, str] = {}
    if not village.has(LABORATORY):
        out["research"] = ("the Laboratory comes at Town Hall 3" if th < 3 else
                           "there's no Laboratory in the village yet")
    if not village.has(CLAN_CASTLE):
        out["clan"] = "the Clan Castle isn't rebuilt yet (rebuild it in the game)"
    if village.heroes == 0:
        out["heroes"] = (f"the first hero comes at Town Hall {HEROES_AT}" if th < HEROES_AT else
                         "no hero in the village yet")
    if village.pets == 0:
        out["pets"] = (f"pets come at Town Hall {PETS_AT}" if th < PETS_AT else "no pet unlocked yet")
    if not village.has(BLACKSMITH):
        out["equipment"] = (f"the Blacksmith comes at Town Hall {BLACKSMITH_AT}" if th < BLACKSMITH_AT else
                            "there's no Blacksmith in the village yet")
    if th < DARK_ELIXIR_AT:
        out["dark"] = f"dark elixir comes at Town Hall {DARK_ELIXIR_AT}"
    if th < SPELLS_AT:
        out["spells"] = f"the Spell Factory comes at Town Hall {SPELLS_AT}"
    if th < WALL_ELIXIR_AT:
        out["wall_elixir"] = f"walls take elixir from level 5, at Town Hall {WALL_ELIXIR_AT}: gold only until then"
    if th < SUPER_TROOPS_AT:
        out["super_troops"] = f"super troops come at Town Hall {SUPER_TROOPS_AT}"
    if th < SIEGE_AT:
        out["siege"] = f"the Workshop comes at Town Hall {SIEGE_AT}"
    if th < BUILDER_BASE_AT and not village.builder_base:
        out["builder_base"] = f"the Builder Base opens at Town Hall {BUILDER_BASE_AT}"
    elif village.builder_heroes == 0:
        out["builder_heroes"] = "no hero in the builder base yet (the Battle Machine comes with the Builder Hall)"
    return out


def describe(village: Village | None) -> str:
    """"Town Hall 2", for the window."""
    return f"Town Hall {village.town_hall}" if village else ""




def load_export(path: str | Path | None) -> tuple[dict, str] | None:
    """The export kept at ``path`` as the game gave it, and the day it was
    read; None if there's none."""
    read = _read_kept(path)
    if read is None:
        return None
    kept, _ = read
    return kept["export"], str(kept.get("read_on", ""))


def overview(export: dict) -> dict[str, list[tuple[str, str]]]:
    """What the export holds, for people to read: section -> (name, detail)
    rows. Never the player tag."""

    def items(key: str) -> list[dict]:
        value = export.get(key)
        return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []

    def named(table: dict[int, str], data: int, base: int, kind: str) -> str:
        return table.get(data, f"{kind} #{data - base}")

    buildings: dict[str, list[tuple[int, int]]] = {}
    for b in items("buildings"):
        if isinstance(b.get("data"), int):
            name = named(gamedata.BUILDINGS, b["data"], 1_000_000, "Building")
            buildings.setdefault(name, []).append((int(b.get("lvl", 0) or 0), int(b.get("cnt", 1) or 1)))
    rows = []
    for name, levels in sorted(buildings.items(), key=lambda kv: (kv[0] != "Town Hall", kv[0])):
        total = sum(c for _, c in levels)
        by_level = ", ".join(f"{c} at level {lvl}" if c > 1 or len(levels) > 1 else f"level {lvl}"
                             for lvl, c in sorted(levels, reverse=True))
        rows.append((f"{name}" + (f" ×{total}" if total > 1 else ""), by_level))
    army = [(named(gamedata.TROOPS, u["data"], 4_000_000, "Troop"), f"level {u.get('lvl', 0)}")
            for u in items("units") + items("siege_machines") if isinstance(u.get("data"), int)]
    counts = [(label, str(len(items(key)))) for key, label in
              (("spells", "Spells"), ("heroes", "Heroes"), ("pets", "Pets"), ("siege_machines", "Siege machines"),
               ("equipment", "Hero equipment"), ("traps", "Traps"), ("obstacles", "Obstacles (trees, rocks...)"))]
    builder = [("Buildings", str(sum(int(b.get("cnt", 1) or 1) for b in items("buildings2")))),
               ("Heroes", str(len(items("heroes2")))), ("Troops", str(len(items("units2"))))]
    return {"Buildings": rows, "Troops": army, "Unlocked": counts, "Builder base": builder}

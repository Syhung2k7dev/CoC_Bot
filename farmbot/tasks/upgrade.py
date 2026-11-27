"""Upgrading once a storage is full: pets, heroes, research and buildings.

Only a full storage's resource is spent, or one holding the amount the
player set for upgrades to start at (``upgrade.start_gold`` and the like;
the bot works out which, see ``Bot._upgrades``). The kinds of upgrade take their
turn in the order chosen (by default pets, heroes, research, then
buildings), each spending only what it may:

- pets: dark elixir (the pet house's one slot),
- heroes: elixir or dark elixir (builders),
- research: elixir or dark elixir (the laboratory's one researcher),
- buildings: gold, elixir or dark elixir (builders; the kind of building
  chosen first, then the others).

Each picks the dearest upgrade the resource left covers, then the dearest
the rest covers, and so on (going from the dearest down spends nearly all
of it). One builder stays free for the walls when they're upgraded too.

Buildings not built yet come before the upgrades (the "New" filter): the
game puts each down at a free spot, and it's built there. New walls cost
nothing and take no builder: they (and any other free new building) are
put down first, one list trip each.
The Town Hall comes first among the buildings (after the new ones, which
it may need built): it's under none of the list's Defense, Resource or Army
types, so it's looked for on its own. While it can't be upgraded (the game
wants the buildings it lists built first), the next upgrade is started.
Everything is picked in the Build list (see build_list.py), sorted Cost
Max and filtered to the resource. With buildings picked (``upgrade.only``),
the list isn't filtered by type: each affordable row's name is read
(row_names.py) and only the picked ones are upgraded. Gems are never spent: an upgrade window
showing a gem (some events make upgrades cost gems too) is closed unpaid.

The builder base works the same way with its gold and elixir, its builders
and its Star Laboratory (no pets there): by default research, heroes, then
buildings; heroes and research take elixir, buildings gold or elixir.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable

from farmbot.config import BuilderConfig, Config
from farmbot.diag import FILE_ONLY
from farmbot.game import Game, T
from farmbot.tasks.build_list import (BUILDER, FAILED, HOME, HUD_SHIFT_PX, LOCKED, PLACED, BuildList, Row, busy,
                                      find_row, first_affordable, dearest_affordable, picked_rows, forget_filters, passed_over, skip_key,
                                      upgradable_names, free_builders, free_lab, free_rows, goblins,
                                      leaving_town_hall, list_shown, open_tab, place_free, rows, set_filter, started,
                                      tab_free,
                                      top_row_affordable, town_hall_row, upgrade_row)
from farmbot.tasks import equipment
from farmbot.tasks.helpers import APPRENTICE, LAB_ASSISTANT, assign_helper, needed
from farmbot.upgradable import Survey
from farmbot.tasks.search import Loot
from farmbot.tasks.village import close_all_windows, deselect

log = logging.getLogger(__name__)

NEEDED = (T.BUILD, T.CLOSE, T.LIST_FILTER, T.SORT_COST_MAX, T.UPGRADE_CONFIRM, T.COST_GOLD, T.COST_ELIXIR,
          T.COST_DARK)
BUILDER_NEEDED = (T.BUILD, T.CLOSE, T.LIST_FILTER, T.SORT_COST_MAX, T.BB_FILTER_GOLD, T.BB_FILTER_ELIXIR,
                  T.BB_COST_GOLD, T.BB_COST_ELIXIR)
KIND_FILTER = {"hero": T.FILTER_HERO, "defense": T.FILTER_DEFENSE, "resource": T.FILTER_RESOURCE,
               "army": T.FILTER_ARMY, "new": T.FILTER_NEW}
BUILDING_KINDS = ("defense", "resource", "army")  # the filter's types, heroes aside
MAX_FAILED_ROWS = 2  # rows a list may have that won't upgrade, before moving on (locked ones aside)
PASS_OVER_FOR = 3600.0  # seconds a row that wouldn't upgrade is passed over (not tapped again every round)
TOWN_HALL_MONEY = ("gold",)  # what the Town Hall's upgrade costs
# After a whole list in a resource had none of the buildings picked that it
# covered, that list isn't looked through again (a page of names read at a
# time) for this long, unless the resource has grown by PICKED_MORE.
PICKED_NONE_FOR = 1800.0
PICKED_MORE = 1.25
SURVEY_AGAIN = 3600.0  # s before a list that couldn't be read through is tried again
MAX_FREE_BUILDINGS = 5  # free new buildings (walls, mostly) put down in a round, a list trip each:
# the rest wait for later rounds, so the farm keeps attacking
# What each kind of upgrade may spend, in the order it's tried.
HOME_SPEND = {"pets": ("dark",), "hero": ("dark", "elixir"), "research": ("elixir", "dark"),
              "building": ("gold", "elixir", "dark")}
BUILDER_SPEND = {"hero": ("elixir",), "research": ("elixir",), "building": ("gold", "elixir")}

Reader = Callable[..., Loot | None]


def building_kinds(first: str, heroes: bool) -> list[str | None]:
    """The kinds of building in the order they get builders; ``None``: any
    kind, the dearest of anything (heroes too, so only while heroes are
    upgraded)."""
    if first == "none":
        return [None] if heroes else list(BUILDING_KINDS)
    rest = [k for k in BUILDING_KINDS if k != first]
    return [first, *rest] + ([None] if heroes else [])


def plan(order: list[str], enabled: dict[str, bool]) -> list[str]:
    """The kinds of upgrade that are on, in their order (the walls' place, "walls", left out)."""
    return [k for k in order if k != WALLS and enabled.get(k)]


WALLS = "walls"  # the walls' place in an upgrade order: they're upgraded by the village's own task


def around_walls(order: list[str], enabled: dict[str, bool], walls: bool) -> tuple[list[str], list[str]]:
    """The kinds of upgrade that are on, split at the walls' place in
    ``order``: those before the walls, and those after (none, with the
    walls off or last). The walls take their turn between the two."""
    kinds = plan(order, enabled)
    if not walls or WALLS not in order:
        return kinds, []
    place = order.index(WALLS)
    return [k for k in kinds if order.index(k) < place], [k for k in kinds if order.index(k) > place]


def home_kinds(ucfg) -> dict[str, bool]:
    """The home village's kinds of upgrade, each on or off (``upgrade.*``)."""
    return {"pets": ucfg.pets, "hero": ucfg.heroes, "research": ucfg.lab, "equipment": ucfg.equipment,
            "building": ucfg.buildings}


def builder_kinds(bcfg) -> dict[str, bool]:
    """The builder base's, the same (``builder.upgrade_*``)."""
    return {"hero": bcfg.upgrade_heroes, "research": bcfg.upgrade_lab, "building": bcfg.upgrade_buildings}


def upgrade(game: Game, cfg: Config, read_resources: Reader, full: set[str], last: bool = False,
            hand_over: dict | None = None, locked: dict[str, str] | None = None, total: int = 0,
            report: dict | None = None, survey: Survey | None = None, kinds: list[str] | None = None,
            walls_after: bool | None = None) -> int:
    """Spend the home village's ``full`` storages' resources on upgrades.
    ``kinds``: only these kinds of upgrade, of those on (the rest come
    before or after the walls; None: every one on). ``walls_after``: the
    walls are upgraded after these, so a builder is kept free for them
    (None: whenever the walls are on).
    What was upgraded is left zoomed in on (the walls, or the battle,
    next zoom out), and dropped unless ``last`` (a battle comes next, which
    drops it). ``hand_over``: the walls come next, so Buildings & Heroes
    is left open for them (one trip to the list, not two), and this gets
    what they need: "loot", the resources left (read before the upgrades,
    less what they spent), and "builders", the free builders read before
    (one of them was kept for the walls). Left empty if the list wasn't
    left open. ``locked``: what this account hasn't unlocked yet
    (``townhall.locked``): left out. ``total``: the village's builders,
    from its data (0: not known); with it, upgrades keep at most
    ``upgrade.builders`` of them busy (see :func:`_within`). ``report``
    gets "idle": nothing was started and nothing could be, because the
    buildings were looked through with a builder free and there was
    none to start, or because no builder may be used (all working, or
    the free ones kept free); not: the list didn't open, the builders
    couldn't be read, or a row wouldn't upgrade. And "town_hall": the
    Town Hall's upgrade was started; "builders_left": the builders it
    may use still free after it, and "lab_free": the laboratory's free
    researchers (None: not read; left out: research isn't upgraded). ``survey``: the lists due a read
    through for what's left to upgrade (``farmbot/upgradable.py``), done
    first. Returns how many were started."""
    ucfg = cfg.upgrade
    full = {k for k in full if k in HOME.resources}
    only_kinds = kinds
    kinds = [k for k in plan(ucfg.order, home_kinds(ucfg)) if only_kinds is None or k in only_kinds]
    # Equipment is paid in ore, not from the storages: it's looked at with none of them full too.
    ore = "equipment" in kinds and "equipment" not in (locked or {}) and equipment.due(game)
    if not ucfg.enabled or not (full or ore) or not all(game.has(n) for n in NEEDED):
        return 0
    if not full:
        kinds = ["equipment"]
    loot = read_resources()
    if not loot:  # (zoomed in on a building, the numbers can sit over busy art)
        game.zoom_out()
        loot = read_resources()
    if loot is None:
        return 0
    # No dark elixir before Town Hall 7: nothing is looked for in it (the research filter's dark button).
    budget = {k: getattr(loot, k) for k in full if not (k == "dark" and "dark" in (locked or {}))}
    for kind, feature in (("pets", "pets"), ("hero", "heroes"), ("research", "research"),
                          ("equipment", "equipment")):
        if kind in kinds and feature in (locked or {}):
            log.info("Upgrades: no %s: %s", "heroes" if kind == "hero" else kind, locked[feature])
            kinds.remove(kind)
    lab_busy = "research" in kinds and "lab" in goblins(game)
    if lab_busy:
        log.info("Upgrades: the laboratory is busy (only the Goblin Researcher, for gems)")
        kinds = [k for k in kinds if k != "research"]
    uses_builders = bool({"hero", "building"} & set(kinds))
    free = free_builders(game) if uses_builders or hand_over is not None else None
    if not uses_builders:
        builders = 0
    elif total:
        builders = _within(free, total, ucfg.builders)
    else:
        builders = _spare(free, cfg.walls.enabled if walls_after is None else walls_after)
    done, handed = 0, False
    lst = HOME if ucfg.town_hall else leaving_town_hall(HOME)
    try:
        forget_filters(game)  # a new round: its filters as the game has them, not known
        if not _open_list(game):
            return 0
        if survey is not None:
            _survey(game, survey, {"buildings": ucfg.buildings,
                                   "research": ucfg.lab and "research" not in (locked or {})}, lst)
        left = {"builders": builders}
        seen: dict | None = None if report is None else {}
        only = tuple(ucfg.only) or None  # (in the order they go first)
        if only and "building" in kinds:
            log.info("Upgrades: only these buildings, first to last: %s", ", ".join(only))
        research = tuple(ucfg.research_only) or None
        equipment_picks = tuple(ucfg.equipment_only) or None
        if research and "research" in kinds:
            log.info("Upgrades: only this research, first to last: %s", ", ".join(research))
        done = _in_order(game, kinds, HOME_SPEND, ucfg.first, ucfg.heroes, budget, builders, read_resources, lst,
                         new=ucfg.new_buildings, left=left, seen=seen, only=only, research=research,
                         equipment_picks=equipment_picks)
        if seen is not None:
            report["town_hall"] = bool(seen.get("town_hall"))
            # What's still free to start one (None: not read): the builders it may use, the laboratory.
            report["builders_left"] = left["builders"] if uses_builders and free is not None else None
            if lab_busy or left.get("research"):
                report["lab_free"] = 0
            elif "research" in kinds:
                report["lab_free"] = tab_free(game, "army") if _list_open(game, lst) else None
            no_builder = "building" in kinds and free is not None and builders <= 0
            report["idle"] = bool(not done and (seen.get("looked") or no_builder) and not seen.get("failed")
                                  and not seen.get("broken") and not _passed_over(game))
        _put_helpers_to_work(game, ucfg, lst, uses_builders, "research" in kinds, report)
        if hand_over is not None:
            # The walls need one free: what was free less what these upgrades just put to work.
            still_free = None if free is None else max(free - (builders - left["builders"]), 0)
            hand_over.update(loot=replace(loot, **budget), builders=still_free)
            handed = True
    finally:
        if not handed:
            close_all_windows(game)
            if not last:
                deselect(game)  # a pinch on what's still selected would move it
    return done


def _put_helpers_to_work(game: Game, ucfg, lst: BuildList, buildings: bool, research: bool,
                         report: dict | None) -> None:
    """The idle helpers, onto what's under way with the most time left: the
    Builder's Apprentice if buildings or heroes were upgraded, the Lab
    Assistant if research was (each from his own tab of the list)."""
    for on, wanted, helper, key in ((ucfg.apprentice, buildings, APPRENTICE, "apprentice"),
                                    (ucfg.lab_assistant, research, LAB_ASSISTANT, "lab_assistant")):
        if not (on and wanted and all(game.has(n) for n in needed(helper)) and _list_open(game, lst)):
            continue
        open_tab(game, helper.tab, lst)
        if assign_helper(game, helper) and report is not None:
            report[key] = True


def upgrade_builder_base(game: Game, bcfg: BuilderConfig, read_resources: Reader, full: set[str],
                         last: bool = False, total: int = 0, report: dict | None = None,
                         kinds: list[str] | None = None, walls_after: bool | None = None) -> int:
    """The same in the builder base, for its ``full`` gold or elixir
    storages. Unless ``last`` (a battle comes next, which zooms out by
    itself), what was upgraded is dropped and the view zoomed out. Returns
    how many upgrades were started. ``total``: the builder base's builders,
    from the village data (0: not known); with it, upgrades keep at most
    ``builder.upgrade_builders`` of them busy. ``report`` (a dict) gets,
    once the list was looked through: "builders_left" (builders it could
    still have used; None: not read, or no buildings or heroes), and
    "lab_free" (0: the Star Laboratory is busy; None: not read). ``kinds``
    and ``walls_after``: as for the home village's (:func:`upgrade`)."""
    full = {k for k in full if k in BUILDER.resources}
    if not bcfg.upgrade or not full or not all(game.has(n) for n in BUILDER_NEEDED):
        return 0
    budget = _open(game, read_resources, full)
    if budget is None:
        return 0
    done = 0
    opened = False  # (shut, nothing was tapped: nothing to close or drop)
    try:
        forget_filters(game)  # a new round: its filters as the game has them, not known
        only_kinds = kinds
        kinds = [k for k in plan(bcfg.upgrade_order, builder_kinds(bcfg)) if only_kinds is None or k in only_kinds]
        uses_builders = bool({"hero", "building"} & set(kinds))

        def usable(free_: int | None) -> int:
            return (_within(free_, total, bcfg.upgrade_builders) if total
                    else _spare(free_, bcfg.walls if walls_after is None else walls_after))

        # The counters over Build ("1/2" builders, "0/1" the Star Laboratory)
        # first: with nothing free, the list isn't opened at all.
        builders, free = 0, free_builders(game) if uses_builders else None
        if free is not None:
            builders = usable(free)
        lab_busy = "research" in kinds and free_lab(game) == 0
        if lab_busy:
            log.info("Upgrades: the star laboratory is busy")
            kinds.remove("research")
        if uses_builders and free is not None and builders <= 0:
            kinds = [k for k in kinds if k not in ("hero", "building")]
        if report is not None:
            if lab_busy:
                report["lab_free"] = 0
            if uses_builders and free is not None:
                report["builders_left"] = builders
        if not kinds:
            log.info("Upgrades: nothing can start (no builder to use%s): the Build list stays shut",
                     ", the star laboratory busy" if lab_busy else "")
            return 0
        if not _open_list(game):
            return 0
        opened = True
        if {"hero", "building"} & set(kinds):
            open_tab(game, "buildings", BUILDER)
            if free is None:  # (not read over Build: the list's tab has the same counter)
                free = tab_free(game, "buildings", BUILDER)
                builders = usable(free)
        left: dict = {}
        done = _in_order(game, kinds, BUILDER_SPEND, bcfg.upgrade_first, bcfg.upgrade_heroes, budget, builders,
                         read_resources, BUILDER, left=left)
        if report is not None:
            if {"hero", "building"} & set(kinds):
                report["builders_left"] = left.get("builders", builders) if free is not None else None
            if left.get("research"):
                report["lab_free"] = 0
            elif "research" in kinds:
                report["lab_free"] = tab_free(game, "army", BUILDER) if _list_open(game, BUILDER) else None
    finally:
        if opened:
            close_all_windows(game)
            # Walls next open the list themselves, which drops what's
            # selected: no opening and shutting it in between to drop it.
            if not last and not (walls_after if walls_after is not None else bcfg.walls):
                _leave(game)
    return done


def _in_order(game: Game, kinds: list[str], spend: dict[str, tuple[str, ...]], first: str, heroes: bool,
              budget: dict[str, int], builders: int, read_resources: Reader, lst: BuildList,
              new: bool = False, left: dict | None = None, seen: dict | None = None,
              only: tuple[str, ...] | None = None, research: tuple[str, ...] | None = None,
              equipment_picks: tuple[str, ...] | None = None) -> int:
    """Each kind of upgrade in turn, with the resources it may spend that
    are still in ``budget``; with ``new``, buildings not built yet come
    first among the buildings (free ones, like new walls, before anything).
    With ``only``, buildings (new ones too, free ones aside) are just those:
    looked for unfiltered by type, by their names; with ``research``,
    research the same. Returns how many were started."""
    done = 0
    if new and "building" in kinds:
        done += _free_buildings(game, lst)
    for kind in kinds:
        if kind == "equipment":  # (ore, not the budget's resources; no builder)
            done += equipment.upgrade_equipment(game, equipment_picks, lst)
            continue
        money = [r for r in spend[kind] if r in budget]
        if not money:
            continue
        if kind == "pets":
            done += _pets(game, budget, read_resources)
        elif kind == "research":
            started_ = _research(game, money, budget, read_resources, lst, research)
            done += started_
            if left is not None:
                left["research"] = started_
        elif builders > 0:
            picked = only if kind == "building" else None
            types = ["hero"] if kind == "hero" else [None] if picked else building_kinds(first, heroes)
            if kind == "building" and _upgrades_town_hall(lst):
                # Not under Defense, Resource or Army: looked for on its own, before those take the builders.
                types = ["town hall", *types]
            if new and kind == "building":
                types = ["new", *types]
            extra = {} if seen is None else {"seen": seen}
            if picked:
                extra["only"] = picked
            started = _buildings(game, types, money, budget, builders, read_resources, lst, **extra)
            builders -= started
            done += started
    if left is not None:
        left["builders"] = builders  # (of those it was given)
    return done


def _open(game: Game, read_resources: Reader, full: set[str]) -> dict[str, int] | None:
    """The budget: what's in the full storages."""
    loot = read_resources()
    if not loot:  # (zoomed in on a building, the numbers can sit over busy art)
        game.zoom_out()
        loot = read_resources()
    return None if loot is None else {k: getattr(loot, k) for k in full}


def builder_limit(total: int, chosen: int) -> int:
    """How many of ``total`` builders upgrades may keep busy: ``chosen``
    (``upgrade.builders``), or all but one when it's 0; none when it's
    negative (the slider at 0)."""
    if chosen < 0:
        return 0
    return min(chosen, total) if chosen > 0 else max(total - 1, 1)


def _within(free: int | None, total: int, chosen: int) -> int:
    """The free builders upgrades may use, keeping the ones over the limit
    free (for the walls, or for you): with 6 builders and a limit of 5, 3
    free -> 2."""
    if free is None:
        log.info("Upgrades: couldn't read the free builders")
        return 0
    limit = builder_limit(total, chosen)
    use = max(min(free, total) - (total - limit), 0)
    working = max(total - free, 0)
    kept = min(free, total) - use  # free, but over the limit
    log.info("Upgrades: %d of %d builders already working, %d free: %s%s", working, total, free,
             f"{use} more can start" if use else "none can start",
             f" ({kept} kept free: the limit is {limit} working)" if kept else
             f" (the limit is {limit} working)" if not use and free else "")
    return use


def _spare(builders: int | None, walls: bool) -> int:
    if builders is None:
        log.info("Upgrades: couldn't read the free builders")
        return 0
    if walls:
        builders -= 1  # one for the walls
    builders = max(builders, 0)
    log.info("Upgrades: %d builder%s to use", builders, "" if builders == 1 else "s")
    return builders


def _open_list(game: Game) -> bool:
    game.refresh()
    if not game.click(T.BUILD) or not game.wait_for(T.CLOSE, timeout=4):
        log.info("Upgrades: the Build list didn't open")
        return False
    game.wait(1.2)
    return True


def _leave(game: Game) -> None:
    """Upgrading moved the camera to what was upgraded and zoomed in: drop
    it and zoom out again. The camera isn't dragged back: what comes next
    (walls, more upgrades) goes by the Build list, and the boat home is
    looked for at the first base whatever the view."""
    deselect(game)  # a pinch on what's still selected would move it
    game.zoom_out()


def _spend(game: Game, row: Row, budget: dict[str, int], read_resources: Reader, what: str,
           lst: BuildList) -> str:
    """Upgrade ``row`` (or build it, if it's new) and check it was paid
    for; ``budget`` follows. What ``upgrade_row`` said, or FAILED if it
    wasn't paid for."""
    before = budget[row.kind]
    outcome = upgrade_row(game, row, lst)
    if not started(outcome):
        return outcome
    # The open list pushes the numbers over; building something new closed it.
    after = read_resources() if outcome == PLACED else read_resources(HUD_SHIFT_PX)
    if after is None:
        budget[row.kind] = before - row.price
    else:
        if getattr(after, row.kind) >= before:
            log.info("Upgrades: the upgrade (%s) didn't go through", what)
            return FAILED
        budget[row.kind] = getattr(after, row.kind)
    log.info("%s %s for %s %s", "Built" if outcome == PLACED else "Upgraded", what, f"{row.price:,}", row.kind)
    if outcome == PLACED:
        game.built_new += 1
    return outcome


def _list_open(game: Game, lst: BuildList) -> bool:
    """Open the list again if building something closed it (opening it
    also drops what was just built, which stays selected). It opens on
    the tab and filter it had, so the tab is tapped only if it isn't lit.
    False if it won't open."""
    game.refresh()
    if list_shown(game):
        return True
    if not _open_list(game):
        return False
    open_tab(game, "buildings", lst)
    return True


def _free_buildings(game: Game, lst: BuildList) -> int:
    """Put down what the list offers for nothing ("FREE": new walls, which
    take no builder, and some new buildings), up to MAX_FREE_BUILDINGS, one
    list trip each. Returns how many."""
    if not game.has(T.FREE_ROW):
        return 0
    open_tab(game, "buildings", lst)
    # Free is the cheapest: at the top, sorted Cost Min.
    sort = T.SORT_COST_MIN if game.has(T.SORT_COST_MIN) else T.SORT_COST_MAX
    if not set_filter(game, None, T.FILTER_NEW, sort, lst):
        return 0  # nothing new to build
    placed = 0
    while placed < MAX_FREE_BUILDINGS:
        game.refresh()
        free = free_rows(game, lst)
        if not free:
            break
        built = place_free(game, free[0])
        if not _list_open(game, lst) or not built:
            break
        placed += 1
    if placed:
        log.info("Upgrades: built %d free new building%s (walls and the like)", placed, "" if placed == 1 else "s")
    return placed


def _upgrades_town_hall(lst: BuildList) -> bool:
    return lst is not None and not lst.builder_base and T.TOWN_HALL_ROW not in lst.left_out


def _town_hall(game: Game, money: list[str], budget: dict[str, int], read_resources: Reader,
               lst: BuildList) -> int:
    """The Town Hall's upgrade, when ``budget`` covers it: 1 if started."""
    paid = [r for r in TOWN_HALL_MONEY if r in money]
    if not paid or not game.has(T.TOWN_HALL_ROW):
        return 0
    if not set_filter(game, lst.resource_filter[paid[0]], None, T.SORT_COST_MAX, lst):
        return 0
    row, seen = town_hall_row(game, tuple(paid), lst)
    if row is None:
        log.info("Upgrades: %s", "the Town Hall costs more than the gold there is" if seen else
                 "no Town Hall upgrade in the list (under way already, or the top level)")
        return 0
    if passed_over(row, _passed_over(game)):
        return 0  # locked a moment ago: the game wants other buildings first
    if row.price > budget[row.kind]:
        log.info("Upgrades: the Town Hall costs %s %s, more than the %s there is", f"{row.price:,}", row.kind,
                 f"{budget[row.kind]:,}")
        return 0
    outcome = _spend(game, row, budget, read_resources, "Town Hall", lst)
    if started(outcome):
        return 1
    _pass_over(game, row)
    return 0


def _buildings(game: Game, kinds: list[str | None], money: list[str], budget: dict[str, int], builders: int,
               read_resources: Reader, lst: BuildList, seen: dict | None = None,
               only: tuple[str, ...] | None = None) -> int:
    """Up to ``builders`` upgrades of the ``kinds`` of building (``None``:
    any), paid with ``money``; with ``only``, of just those buildings (the
    Town Hall aside: it has its own switch). Returns how many were started. ``seen``
    gets how it went: "looked" (every kind was looked through), "failed"
    (a row wouldn't upgrade), "broken" (the list was lost), "town_hall"
    (its upgrade was started)."""
    seen = {} if seen is None else seen
    open_tab(game, "buildings", lst)
    done = 0
    for kind in kinds:
        if kind is None and only:
            started_ = _picked(game, money, budget, builders, read_resources, lst, only, seen)
            builders -= started_
            done += started_
            if seen.get("broken"):
                return done
            continue
        if kind == "town hall":
            if builders > 0:
                started_ = _town_hall(game, money, budget, read_resources, lst)
                builders -= started_
                done += started_
                if started_:
                    seen["town_hall"] = True
                if not _list_open(game, lst):
                    seen["broken"] = True
                    return done
            continue
        # New buildings are few: one list of them in every resource (one
        # trip to the filter menu, not one per resource). Upgrades: a list
        # per resource, each sorted by its own price.
        groups = [tuple(money)] if kind == "new" and len(money) > 1 else [(r,) for r in money]
        for group in groups:
            if builders <= 0:
                return done
            alone = group[0] if len(group) == 1 else None
            what_for = alone or " or ".join(group)
            # (The two villages' lists apart: their resources share names.)
            looked_for = (f"builder base {kind}" if lst.builder_base else kind, group)
            # Picked buildings, or heroes: a list that had none lately isn't
            # looked through again until there's more to spend (or a while on).
            remembers = bool(only) or kind == "hero"
            if remembers and _none_picked_lately(game, looked_for, budget):
                log.debug("Upgrades: no %s for %s lately; not looked for again yet", kind or "picks", what_for)
                continue
            # One resource, no picks: the list sorted from whichever end
            # reached the row last time in fewer pages, at about this budget.
            sorted_key = (lst.builder_base, kind, alone)
            sort = _sort_for(game, sorted_key, budget[alone]) if alone and not only else T.SORT_COST_MAX
            if not set_filter(game, lst.resource_filter[alone] if alone else None, KIND_FILTER.get(kind),
                              sort, lst):
                if kind == "new":
                    log.info("Upgrades: nothing new to build for %s", what_for)
                else:
                    log.info("Upgrades: no %s upgrade%s for %s in the list", kind or "building",
                             "" if kind else "s", what_for)
                if kind == "hero":
                    _none_picked(game, looked_for, budget)
                continue  # nothing of that kind to upgrade
            spent = False
            skip = _passed_over(game)  # rows that wouldn't upgrade (lately): the next one
            failed = 0  # of those, the ones that weren't locked (a locked Town Hall doesn't count)
            first_look = True
            while builders > 0 and failed < MAX_FAILED_ROWS:
                if spent and alone and not _may_afford(game, alone, budget[alone], kind, lst, sort):
                    break
                pages: list[int] = []
                if sort == T.SORT_COST_MIN:
                    row = dearest_affordable(game, alone, budget[alone], lst, skip, pages)
                elif only:
                    row = first_affordable(game, {r: budget[r] for r in group}, lst, skip, only=only)
                else:
                    row = first_affordable(game, {r: budget[r] for r in group}, lst, skip, pages=pages)
                if first_look and alone and not only:
                    _sorted_pages(game, sorted_key, sort, sum(pages), budget[alone])
                first_look = False
                if row is None:
                    if kind == "hero" and not spent and not only:
                        _none_picked(game, looked_for, budget)
                    if only and not spent:
                        log.info("Upgrades: no %s of the buildings picked that %s covers",
                                 "new one" if kind == "new" else "upgrade", what_for)
                        _none_picked(game, looked_for, budget)
                    break
                what = "a new building" if kind == "new" else kind or "a building"
                outcome = _spend(game, row, budget, read_resources, what, lst)
                if not _list_open(game, lst):
                    seen["broken"] = True
                    return done
                if not started(outcome):
                    seen["failed"] = True
                    skip.add(skip_key(row))
                    _pass_over(game, row)
                    failed += outcome != LOCKED
                    continue
                spent = True
                builders -= 1
                done += 1
    seen["looked"] = True
    return done


def _picked(game: Game, money: list[str], budget: dict[str, int], builders: int, read_resources: Reader,
            lst: BuildList, picks: tuple[str, ...], seen: dict) -> int:
    """Up to ``builders`` upgrades of the buildings picked, the first
    picked first: each resource's list is looked through once for what
    it covers of them, then they're started in the order picked (of one
    building, the dearest first). Returns how many were started."""
    found: list[tuple[int, Row, str]] = []
    for resource in money:
        looked_for = (None, (resource,))
        if _none_picked_lately(game, looked_for, budget):
            continue
        if not set_filter(game, lst.resource_filter[resource], None, T.SORT_COST_MAX, lst):
            log.info("Upgrades: no upgrades for %s in the list", resource)
            continue
        rows_ = picked_rows(game, {resource: budget[resource]}, lst, picks, _passed_over(game))
        if rows_ is None:
            return 0  # the names can't be read (said in the log)
        if not rows_:
            log.info("Upgrades: no upgrade of the buildings picked that %s covers", resource)
            _none_picked(game, looked_for, budget)
            continue
        found += rows_
        if builders == 1 and any(rank == 0 for rank, _, _ in rows_):
            break  # the one builder goes to the top pick: no need to look further
    found.sort(key=lambda f: (f[0], -f[1].price))
    if found:
        log.info("Upgrades: the buildings picked that can be paid for, first to last: %s",
                 ", ".join(f"{name} ({row.price:,} {row.kind})" for _, row, name in found))
    done = failed = 0
    while builders > 0 and found and failed < MAX_FAILED_ROWS:
        _, row, name = found[0]
        if row.price > budget[row.kind] or not set_filter(game, lst.resource_filter[row.kind], None,
                                                          T.SORT_COST_MAX, lst):
            found.pop(0)  # spent on one before it
            continue
        here = find_row(game, row.kind, row.price, name, lst)
        if here is None:
            found.pop(0)  # (all of it upgrading now)
            continue
        outcome = _spend(game, here, budget, read_resources, name, lst)
        if not _list_open(game, lst):
            seen["broken"] = True
            return done
        if not started(outcome):
            seen["failed"] = True
            _pass_over(game, here)
            failed += outcome != LOCKED
            found.pop(0)
            continue
        builders -= 1
        done += 1  # (kept: "Cannon x 6" has more of the same; one gone isn't found next time)
    return done


def _none_picked(game: Game, looked_for: tuple, budget: dict[str, int]) -> None:
    """A whole list had none of the buildings picked that ``budget`` covered."""
    lately = game.__dict__.setdefault("none_picked", {})
    lately[looked_for] = (game.clock() + PICKED_NONE_FOR, sum(budget[r] for r in looked_for[1]))


def _none_picked_lately(game: Game, looked_for: tuple, budget: dict[str, int]) -> bool:
    """Whether that list had none lately, with about as much to spend."""
    lately = game.__dict__.get("none_picked", {})
    until, had = lately.get(looked_for, (0.0, 0))
    if game.clock() >= until or sum(budget[r] for r in looked_for[1]) >= had * PICKED_MORE:
        lately.pop(looked_for, None)
        return False
    return True


def _passed_over(game: Game) -> set[tuple]:
    """The rows that wouldn't upgrade in the last PASS_OVER_FOR seconds:
    (resource, price, look) each (see build_list.passed_over)."""
    rows_out = getattr(game, "unupgradable", None)
    if rows_out is None:
        return set()
    now = game.clock()
    for key in [k for k, until in rows_out.items() if until <= now]:
        del rows_out[key]
    return set(rows_out)


def _pass_over(game: Game, row: Row) -> None:
    rows_out = getattr(game, "unupgradable", None)
    if rows_out is not None:
        rows_out[skip_key(row)] = game.clock() + PASS_OVER_FOR


def _may_afford(game: Game, resource: str, left: int, kind: str | None, lst: BuildList,
                sort: str = T.SORT_COST_MAX) -> bool:
    """After an upgrade has spent most of the budget: the cheapest upgrade
    (sorted Cost Min, at the top) can be paid for. Saves scrolling the
    whole Cost Max list (a minute, at a big town hall) to find there is
    none. The list is sorted ``sort`` again if there may be one."""
    if not game.has(T.SORT_COST_MIN):
        return True
    if not set_filter(game, lst.resource_filter[resource], KIND_FILTER.get(kind), T.SORT_COST_MIN, lst):
        return True
    if top_row_affordable(game, (resource,), lst) is False:
        log.info("Upgrades: even the cheapest costs more than the %s %s left", f"{left:,}", resource)
        return False
    if sort != T.SORT_COST_MIN:
        set_filter(game, lst.resource_filter[resource], KIND_FILTER.get(kind), sort, lst)
    return True


# A list's pages to the row last time, by sort, kept for a budget within
# this factor of the one then (the storages are full each time: about the same).
SORT_BUDGET_NEAR = 1.5


def _sort_for(game: Game, key: tuple, amount: int) -> str:
    """Cost Max or Cost Min for a list (``key``: village, kind, resource)
    and ``amount`` to spend: the end the row was fewer pages from last time.
    Nothing known: Cost Max (the row is at the top when most can be paid
    for); known only for one end, and that took 2 pages or more: the other
    end is tried once."""
    if not game.has(T.SORT_COST_MIN):
        return T.SORT_COST_MAX
    known = {sort: pages for sort, (pages, had) in game.__dict__.get("sort_pages", {}).get(key, {}).items()
             if had / SORT_BUDGET_NEAR <= amount <= had * SORT_BUDGET_NEAR}
    most, least = known.get(T.SORT_COST_MAX), known.get(T.SORT_COST_MIN)
    if most is None and least is None:
        choice = T.SORT_COST_MAX
    elif least is None:
        choice = T.SORT_COST_MIN if most >= 2 else T.SORT_COST_MAX
    elif most is None:
        choice = T.SORT_COST_MAX if least >= 2 else T.SORT_COST_MIN
    else:
        choice = T.SORT_COST_MIN if least < most else T.SORT_COST_MAX
    if choice == T.SORT_COST_MIN:
        log.info("Upgrades: %s %s; sorted Cost Min (pages to the row last time: Cost Max %s, Cost Min %s)",
                 f"{amount:,}", key[2], "?" if most is None else most, "?" if least is None else least)
    return choice


def _sorted_pages(game: Game, key: tuple, sort: str, pages: int, amount: int) -> None:
    game.__dict__.setdefault("sort_pages", {}).setdefault(key, {})[sort] = (pages, amount)


def _research(game: Game, money: list[str], budget: dict[str, int], read_resources: Reader, lst: BuildList,
              picks: tuple[str, ...] | None = None) -> int:
    if not lst.builder_base and tab_free(game, "army") == 0:
        # The researcher's count under the tab ("0/1") shows from any tab:
        # a busy laboratory isn't opened.
        log.info("Upgrades: the laboratory is busy")
        return 0
    open_tab(game, "army", lst)
    if lst.builder_base:
        # The Star Laboratory's tab counts its researcher ("0/1": busy).
        free = tab_free(game, "army", lst)
        if not free:
            log.info("Upgrades: the star laboratory is busy" if free == 0 else
                     "Upgrades: couldn't read the star laboratory's researcher")
            return 0
    elif busy(game) or tab_free(game, "army") == 0:
        # The tab's counter ("0/1") says so even when the research under
        # way has a green bar rather than a grey one.
        log.info("Upgrades: the laboratory is busy")
        return 0
    if picks and not lst.builder_base:
        return _picked_research(game, money, budget, read_resources, lst, picks)
    for resource in money:
        # The Star Laboratory's research is all elixir: its filter only sorts.
        button = None if lst.builder_base else lst.resource_filter[resource]
        if not set_filter(game, button, None, T.SORT_COST_MAX, lst):
            continue
        row = first_affordable(game, {resource: budget[resource]}, lst)
        if row is not None:
            # One researcher: whatever happened, that's it for this round.
            return int(started(_spend(game, row, budget, read_resources, "research", lst)))
    return 0


def _picked_research(game: Game, money: list[str], budget: dict[str, int], read_resources: Reader,
                     lst: BuildList, picks: tuple[str, ...]) -> int:
    """The one researcher, on the first of the research picked that what's
    in ``budget`` covers (of one, the dearest). 1 if it was started."""
    found: list[tuple[int, Row, str]] = []
    for resource in money:
        looked_for = ("research", (resource,))
        if _none_picked_lately(game, looked_for, budget):
            continue
        if not set_filter(game, lst.resource_filter[resource], None, T.SORT_COST_MAX, lst):
            continue
        rows_ = picked_rows(game, {resource: budget[resource]}, lst, picks, which="research")
        if rows_ is None:
            return 0  # the names can't be read (said in the log)
        if not rows_:
            _none_picked(game, looked_for, budget)
        found += rows_
        if any(rank == 0 for rank, _, _ in rows_):
            break  # the top pick: nothing goes before it
    found.sort(key=lambda f: (f[0], -f[1].price))
    if not found:
        log.info("Upgrades: no research of that picked is covered by %s", " or ".join(money))
        return 0
    for _, row, name in found:
        if not set_filter(game, lst.resource_filter[row.kind], None, T.SORT_COST_MAX, lst):
            continue
        here = find_row(game, row.kind, row.price, name, lst, "research")
        if here is not None:
            # One researcher: whatever happened, that's it for this round.
            return int(started(_spend(game, here, budget, read_resources, name, lst)))
    return 0


def _survey(game: Game, survey: Survey, wanted: dict[str, bool], lst: BuildList) -> None:
    """Read through the lists due it (once a day at most): what's in them
    can still be upgraded; kept for the window to grey out the rest. A
    list that couldn't be read through isn't tried again for a while."""
    from farmbot.tasks.row_names import PICKS

    failed = game.__dict__.setdefault("survey_failed", {})
    for which, tab in (("buildings", "buildings"), ("research", "army")):
        if not wanted.get(which) or not survey.due(which):
            continue
        if which in failed and game.clock() - failed[which] < SURVEY_AGAIN:
            continue
        open_tab(game, tab, lst)
        names = upgradable_names(game, lst, which)
        if names is None:
            failed[which] = game.clock()
            log.info("Upgrades: couldn't read the whole %s list through; tried again in %d minutes", which,
                     SURVEY_AGAIN // 60)
            continue
        failed.pop(which, None)
        log.info("Upgrades: %d %s can still be upgraded", len(names), "buildings" if which == "buildings"
                 else "troops and spells")
        others = sorted(names - set(PICKS[which]))
        if others:  # (not pickable: for when the game adds one)
            log.info("Upgrades: in the %s list, not among the picks: %s", which, ", ".join(others),
                     extra=FILE_ONLY)
        survey.record(which, names)


def _pets(game: Game, budget: dict[str, int], read_resources: Reader) -> int:
    open_tab(game, "pets")
    # The tab's counter ("0/1") says so even when the pet's bar under way is
    # green rather than grey.
    if busy(game) or tab_free(game, "pets") == 0:
        log.info("Upgrades: the pet house is busy")
        return 0
    # The pets tab has no filter, and only a few rows: the dearest that fits.
    affordable = [r for r in rows(game, ("dark",)) if r.price <= budget["dark"]]
    if not affordable:
        return 0
    best = max(affordable, key=lambda r: r.price)
    return int(started(_spend(game, best, budget, read_resources, "pet", HOME)))

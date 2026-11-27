"""Which building a Build list row is, by the name on it.

The list's rows are found by their price icons (see build_list.py); their
names aren't pictures the bot has, so they're read with Windows' own OCR
(see ``redact.read_text``), about half a second a page. The OCR misreads
the game's font a little ("CaNNON X 6", "BanbaRiaN KiNg"), so a name is
taken as the known building it's closest to, out of all of them: "Archer
Tower" never passes for a Multi-Archer Tower, nor "Cannon" for a Giant
Cannon. Used only when the player picks which buildings to upgrade
(``upgrade.only``, ``upgrade.research_only``), and to learn which can
still be upgraded at all (see ``farmbot/upgradable.py``); a row whose name
can't be read is never upgraded.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from farmbot import gamedata
from farmbot.diag import FILE_ONLY
from farmbot.game import Game
from farmbot.tasks.build_list import (HOME, ICON_COLUMN, LIST_BOTTOM_FROM_BOTTOM, LIST_TOP, WALL_ROW_BAND,
                                      BuildList, Row)

log = logging.getLogger(__name__)

# The home village's buildings that can be picked, by the list's own types
# (the Town Hall and walls have their own settings; heroes their own switch).
HOME_BUILDINGS: dict[str, tuple[str, ...]] = {
    "Defenses": ("Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper", "Hidden Tesla",
                 "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery", "Scattershot", "Builder's Hut",
                 "Spell Tower", "Monolith", "Multi-Archer Tower", "Ricochet Cannon", "Firespitter",
                 "Multi-Gear Tower", "Revenge Tower", "Super Wizard Tower", "Spiky Tower", "Firecracker Tower"),
    "Traps": ("Bomb", "Spring Trap", "Giant Bomb", "Air Bomb", "Seeking Air Mine", "Skeleton Trap", "Tornado Trap",
              "Giga Bomb"),
    "Resources": ("Gold Mine", "Elixir Collector", "Dark Elixir Drill", "Gold Storage", "Elixir Storage",
                  "Dark Elixir Storage"),
    "Army": ("Army Camp", "Barracks", "Dark Barracks", "Laboratory", "Spell Factory", "Dark Spell Factory",
             "Workshop", "Pet House", "Blacksmith", "Hero Hall", "Clan Castle", "Helper Hut", "Crafting Station",
             "Squad Barracks"),
}
PICKABLE = tuple(name for names in HOME_BUILDINGS.values() for name in names)
# The home village laboratory's research that can be picked (the Army
# Upgrades tab), by what it costs.
HOME_RESEARCH: dict[str, tuple[str, ...]] = {
    "Troops": ("Barbarian", "Archer", "Giant", "Goblin", "Wall Breaker", "Balloon", "Wizard", "Healer", "Dragon",
               "P.E.K.K.A", "Baby Dragon", "Miner", "Electro Dragon", "Yeti", "Dragon Rider", "Electro Titan",
               "Root Rider", "Thrower", "Meteor Golem"),
    "Dark troops": ("Minion", "Hog Rider", "Valkyrie", "Golem", "Witch", "Lava Hound", "Bowler", "Ice Golem",
                    "Headhunter", "Apprentice Warden", "Druid", "Furnace"),
    "Spells": ("Lightning Spell", "Healing Spell", "Rage Spell", "Jump Spell", "Freeze Spell", "Clone Spell",
               "Invisibility Spell", "Recall Spell", "Revive Spell", "Poison Spell", "Earthquake Spell",
               "Haste Spell", "Skeleton Spell", "Bat Spell", "Overgrowth Spell", "Ice Block Spell", "Totem Spell",
               "Heroic Spell"),
    "Siege machines": ("Wall Wrecker", "Battle Blimp", "Stone Slammer", "Siege Barracks", "Log Launcher",
                       "Flame Flinger", "Battle Drill", "Troop Launcher", "Sky Wagon"),
}
RESEARCHABLE = tuple(name for names in HOME_RESEARCH.values() for name in names)
# Every other name the game has for a building, trap or hero (and a few
# newer ones): known too, so a look-alike is never taken for a picked building.
OTHERS: tuple[str, ...] = ()  # (the Dragon Duke: among the heroes now)
KNOWN = tuple(dict.fromkeys((*PICKABLE, *gamedata.BUILDINGS.values(), *gamedata.TRAPS.values(),
                             *gamedata.HEROES.values(), *OTHERS)))
NAMES_FROM_RIGHT = 440  # the rows' names start this far from the screen's right edge, at most
OCR_ZOOM = 1.5  # the list's text made this much bigger first: the OCR reads it better
LIKENESS = 0.75  # how alike a read name must be to the building it's closest to
COUNT = re.compile(r"\s*[x×]\s*\d+\s*$")  # "Cannon x 6": six of them, one upgrade each
# What the OCR mixes up in the game's font: each is read as the other.
SAME = str.maketrans({"0": "o", "1": "i", "l": "i", "|": "i", "!": "i", "r": "n", "q": "g", "5": "s"})
# A building new to the Town Hall level ("New" under it) has its name in
# green, which the OCR reads worse than the white of the rest: a row left
# without a name is read again with that green made white.
GREEN_HUE = (30, 90)
GREEN_MIN = (110, 150)  # saturation, brightness (0-255)

_warned = False


def _plain(text: str) -> str:
    return re.sub(r"[^a-z]", "", COUNT.sub("", text.strip().lower()).translate(SAME))


# Every name the Army Upgrades tab may show: troops, spells, sieges, heroes, pets.
RESEARCH_KNOWN = tuple(dict.fromkeys((*RESEARCHABLE, *gamedata.TROOPS.values(), *gamedata.SPELLS.values(),
                                      *gamedata.HEROES.values(), *gamedata.PETS.values())))
_PLAIN = {name: _plain(name) for name in KNOWN}
# The Hero Equipment tab's names (see ``farmbot/tasks/equipment.py``).
# Newer pieces seen in the game whose export ids aren't known yet, by name
# only (none now: Portal Pendant, seen 17 Nov 2026, has its id since).
NEWER_EQUIPMENT: tuple[str, ...] = ()
EQUIPMENT = tuple(dict.fromkeys((*gamedata.EQUIPMENT.values(), *NEWER_EQUIPMENT)))
# The picker's groups, by hero, as the Hero Equipment tab shows them (seen on
# 17 Nov 2026; every hero's pieces by the wiki, 18 Nov 2026): the
# Common pieces, then the Epic ones. A piece under no hero goes under "Other"
# (a tab only when there is one).
_BY_HERO = {
    "Barbarian King": ("Barbarian Puppet", "Rage Vial", "Earthquake Boots", "Vampstache", "Giant Gauntlet",
                       "Spiky Ball", "Snake Bracelet", "Stick Horse"),
    "Archer Queen": ("Archer Puppet", "Invisibility Vial", "Giant Arrow", "Healer Puppet", "Frozen Arrow",
                     "Magic Mirror", "Action Figure", "Monolith Arrow"),
    "Grand Warden": ("Eternal Tome", "Life Gem", "Rage Gem", "Healing Tome", "Fireball", "Lavaloon Puppet",
                     "Heroic Torch"),
    "Royal Champion": ("Royal Gem", "Seeking Shield", "Haste Vial", "Hog Rider Puppet", "Rocket Spear",
                       "Electro Boots", "Frost Flake"),
    "Minion Prince": ("Henchmen Puppet", "Dark Orb", "Metal Pants", "Noble Iron", "Dark Crown", "Meteor Staff",
                      "Portal Pendant"),
    "Dragon Duke": ("Fire Heart", "Flame Blower", "Stun Blaster", "Electro Fangs", "Rocket Backpack",
                    "Revenge Deck"),
}
_GROUPED = {name for names in _BY_HERO.values() for name in names}
_UNGROUPED = tuple(n for n in EQUIPMENT if n not in _GROUPED)
HOME_EQUIPMENT: dict[str, tuple[str, ...]] = {**_BY_HERO, **({"Other": _UNGROUPED} if _UNGROUPED else {})}
_PLAIN_FOR = {"buildings": _PLAIN, "research": {name: _plain(name) for name in RESEARCH_KNOWN},
              "equipment": {name: _plain(name) for name in EQUIPMENT}}
PICKS = {"buildings": PICKABLE, "research": RESEARCHABLE, "equipment": EQUIPMENT}


def building(text: str, which: str = "buildings") -> str | None:
    """The known building (or, ``which`` "research", troop or spell) a
    row's name ``text`` (as read) is, or None if it's like none of them."""
    plain = _plain(text)
    if len(plain) < 3:
        return None
    best, score = None, 0.0
    for name, known in _PLAIN_FOR[which].items():
        s = SequenceMatcher(None, plain, known).ratio()
        if s > score:
            best, score = name, s
    return best if score >= LIKENESS else None


def whiten_green(area: np.ndarray) -> np.ndarray:
    """``area`` with its green text made white (the OCR's best colour)."""
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    green = ((hsv[..., 0] >= GREEN_HUE[0]) & (hsv[..., 0] <= GREEN_HUE[1]) & (hsv[..., 1] >= GREEN_MIN[0])
             & (hsv[..., 2] >= GREEN_MIN[1]))
    out = area.copy()
    out[green] = 255
    return out


def read(game: Game, lst: BuildList = HOME, which: str = "buildings",
         green: bool = False) -> list[tuple[int, str | None]] | None:
    """Each line of text in the list's names column (on the screen now):
    its height on the screen, and the known name it is (None: not one).
    None if the OCR can't read (said once in the log). ``green``: the
    green names made white first (see :func:`whiten_green`)."""
    global _warned
    from farmbot.redact import read_text

    w, h = game.size
    x0, y0 = max(w - NAMES_FROM_RIGHT, 0), LIST_TOP
    area = game._current()[y0:h - LIST_BOTTOM_FROM_BOTTOM, x0:w - ICON_COLUMN // 2]
    if green and area.size:
        area = whiten_green(area)
    lines = read_text(area, OCR_ZOOM) if area.size else None
    if lines is None:
        if not _warned:
            _warned = True
            log.warning("Upgrades: couldn't read the names in the list (Windows' text reading isn't working): "
                        "only what's picked is upgraded, so nothing is")
        return None
    log.info("Upgrades: names read in the list: %s", ", ".join(f"{t!r}" for _, t in lines) or "none",
             extra=FILE_ONLY)  # (in the log file only: for when a pick isn't found)
    return [(y0 + r.y + r.h // 2, building(text, which)) for r, text in lines]


def match(found: list[Row], lines: list[tuple[int, str | None]]) -> dict[Row, str | None]:
    """The name of each of the rows ``found``: the nearest above its price
    ("New" may sit between them: not a name)."""
    out: dict[Row, str | None] = {}
    for row in found:
        above = [(y, name) for y, name in lines if name and WALL_ROW_BAND[0] <= y - row.y <= WALL_ROW_BAND[1]]
        out[row] = max(above, key=lambda a: a[0])[1] if above else None
    return out


def names(game: Game, found: list[Row], lst: BuildList = HOME,
          which: str = "buildings") -> dict[Row, str | None] | None:
    """The building (or research) each of the rows ``found`` (on the screen
    now) is: its name, read just above its price. None if the OCR can't
    read: then nothing is known to be a pick."""
    lines = read(game, lst, which)
    if lines is None:
        return None
    out = match(found, lines)
    if any(name is None for name in out.values()):
        again = read(game, lst, which, green=True) or []
        for row, name in match(found, again).items():
            if out[row] is None and name is not None:
                out[row] = name
    return out

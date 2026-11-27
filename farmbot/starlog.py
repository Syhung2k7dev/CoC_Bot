"""One line per battle fought for stars (ranked, war), in star_battles.csv.

The same attack (``attack.attack(for_stars=True)``) fights both, so their
results are written from one place, side by side: the stars and damage off
the result screen, the plan the attack made (the side it pushed from, the
army's kind, what it found on the base) and a rough sort of the base, so
the layouts the attack struggles with show up:

- ``footprint``: "compact" or "wide", the base's outline (the red line as
  first found) against the screen's width;
- ``air_defenses``: how many were found (only with an air army: they're
  looked for then), and ``ad_layout``: "core" when they stand near the
  centre, "spread" when out toward the edge.

The file sits beside the attack history (``bot.history``); "" turns both off.
"""

from __future__ import annotations

import csv
import logging
import math
from datetime import datetime
from pathlib import Path

from farmbot.config import Config

log = logging.getLogger(__name__)

NAME = "star_battles.csv"
FIELDS = ["time", "mode", "stars", "damage", "push", "army", "air_defenses", "ad_layout", "castle", "lure",
          "footprint", "red_line_sides", "deploy_s", "battle_s", "base_screen", "note"]
WIDE = 0.8  # of the screen's width: a base outline wider is "wide" (the median of 258 kept bases, zoomed out)
CORE = 0.4  # of the base's half-width: Air Defenses nearer the centre than this, on average, are "core"


def path(cfg: Config) -> Path | None:
    history = cfg.bot.history
    return Path(history).with_name(NAME) if history else None


def footprint(outline: list, width: int) -> str:
    if not outline or not width:
        return ""
    xs = [p[0] for p in outline]
    return "wide" if (max(xs) - min(xs)) / width > WIDE else "compact"


def ad_layout(air_defenses: list, center, outline: list) -> str:
    if not air_defenses or center is None or not outline:
        return ""
    xs = [p[0] for p in outline]
    half = max((max(xs) - min(xs)) / 2, 1)
    mean = sum(math.dist(a, center) for a in air_defenses) / len(air_defenses)
    return "core" if mean / half < CORE else "spread"


def row(game, mode: str, note: str = "") -> dict:
    """What's known of the battle just fought (see ``attack.attack``)."""
    plan = dict(getattr(game, "star_plan", None) or {})
    found = getattr(game, "last_result", None)
    width = game.size[0] if getattr(game, "size", None) else 0
    outline = plan.get("outline") or []
    origins = plan.get("origins") or {}
    times = plan.get("times") or {}
    deploy = times.get("battle", 0) - times.get("start", 0) if "battle" in times and "start" in times else None
    battle = times.get("end", 0) - times.get("battle", 0) if "end" in times and "battle" in times else None
    return {
        "time": datetime.now().isoformat(timespec="seconds"), "mode": mode,
        "stars": found.stars if found else "",
        "damage": found.damage if found and found.damage is not None else "",
        "push": "+".join(plan.get("push") or []) or "spread",
        "army": plan.get("kind") or "",
        "air_defenses": len(plan.get("air_defenses") or []) if plan.get("kind") == "air" else "",
        "ad_layout": ad_layout(plan.get("air_defenses") or [], plan.get("center"), outline),
        "castle": "yes" if plan.get("castle") else "", "lure": "yes" if plan.get("lure") else "",
        "footprint": footprint(outline, width),
        "red_line_sides": sum(o == "red line" for o in origins.values()),
        "deploy_s": "" if deploy is None else round(deploy, 1),
        "battle_s": "" if battle is None else round(battle, 1),
        "base_screen": plan.get("base_screen") or "", "note": note,
    }


def record(game, cfg: Config, mode: str, note: str = "") -> dict | None:
    """Append the battle just fought to star_battles.csv. Never fails the
    battle: a file that can't be written is only logged."""
    try:
        line = row(game, mode, note)
        log.info("Star battle (%s): %s star(s), %s%% damage, pushed from %s", mode,
                 line["stars"] if line["stars"] != "" else "?",
                 line["damage"] if line["damage"] != "" else "?", line["push"])
        target = path(cfg)
        if target is None:
            return line
        new = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, FIELDS, extrasaction="ignore")
            if new:
                writer.writeheader()
            writer.writerow(line)
        return line
    except Exception as exc:  # noqa: BLE001 - a record is never worth a battle
        log.warning("Couldn't record the star battle: %s", exc)
        return None

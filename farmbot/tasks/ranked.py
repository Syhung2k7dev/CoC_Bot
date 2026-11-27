"""Ranked battles: the day's ranked attacks, fought for stars.

The battle menu's Ranked Battle card has its own Find a Match (right of the
regular Battle's, which is the only one the farming search ever taps). It
gives one base, with no Next. As in a war, the army's window (its Attack!)
and "Confirm Attack" come first (``attack.into_battle``, shared with war);
then the army goes in as in a war battle, and the battle is left to run its
course (``attack.attack(for_stars=True)``), since a ranked battle counts by
its stars and percentage, not its loot. Each one is written to
star_battles.csv beside war's (``farmbot/starlog.py``).

While the tournament's sign-up is open the card shows Join Tournament
instead: the bot doesn't sign up (that's yours to decide), and looks again
later.
"""

from __future__ import annotations

import logging

from farmbot import screens, starlog
from farmbot.config import Config
from farmbot.game import Game, T
from farmbot.tasks import attack, search
from farmbot.vision import Match

log = logging.getLogger(__name__)

MOST = 20  # ranked attacks in one go at most (a day has fewer: a guard against going round for ever)
MENU_WAIT = 6  # s for the battle menu to open
BATTLE_WAIT = 40  # s from Find a Match to the base on screen (the search, the clouds)


class RankedError(RuntimeError):
    pass


def ranked_button(game: Game) -> Match | None:
    """Ranked Battle's Find a Match on the battle menu (on screen), or None:
    not signed up (Join Tournament shows there), or no attacks to make."""
    right = [m for m in game.find_all(T.FIND_MATCH) if m.x > search.REGULAR_MATCH_RIGHT]
    return min(right, key=lambda m: m.x) if right else None


def open_menu(game: Game) -> bool:
    """The battle menu, from the home village. True once it shows."""
    game.refresh()
    if not game.find(T.FIND_MATCH) and not game.click(T.BATTLE):
        return False
    deadline = game.clock() + MENU_WAIT
    while game.clock() < deadline:
        game.wait(0.5, exact=True)
        game.refresh()
        if game.find(T.FIND_MATCH) or (game.has(T.ATTACK_COOLDOWN) and game.find(T.ATTACK_COOLDOWN)):
            game.wait(0.5, exact=True)  # (the cards slide in one after the other)
            game.refresh()
            return True
    return False


def _to_battle(game: Game) -> bool:
    """From the tap on Find a Match to the base on screen: the Ranked
    Battle army's window, then "Confirm Attack", as in a war
    (``attack.into_battle``, shared with war). True once the battle's End
    Battle shows."""
    return attack.into_battle(game, BATTLE_WAIT, "Ranked")


def attacks(game: Game, cfg: Config, most: int = MOST) -> int:
    """Every ranked attack there is to make, from the home village and back
    to it. Returns how many were made."""
    done = 0
    while done < most:
        if not open_menu(game):
            raise RankedError("the battle menu didn't open; is the home village showing?")
        button = ranked_button(game)
        if button is None:
            log.info("Ranked: %s", "no more attacks to make" if done else
                     "nothing to start on the Ranked Battle card (not signed up for the tournament, or no "
                     "attacks left today)")
            break
        game.tap(button.x, button.y)
        if not _to_battle(game):
            log.info("Ranked: Find a Match led to no battle (no attacks left, most likely)")
            break
        log.info("Ranked battle %d: attacking for stars", done + 1)
        attack.attack(game, cfg, for_stars=True)
        starlog.record(game, cfg, "ranked")
        done += 1
        if screens.settle(game) is not screens.Screen.HOME:
            break
    screens.settle(game)  # (closes the battle menu, or whatever a tap left open)
    return done

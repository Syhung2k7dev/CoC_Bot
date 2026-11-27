"""Upgrades → "Put the helpers to work": an idle Builder's Apprentice or
Lab Assistant is put on the upgrade (or research) under way with the most
time left, kept on it until it's done (the game then puts him back on it
each time he's ready).

With the build list open, each helper has a bubble beside it: his face
and "Available" when idle, the time until he's ready otherwise. The
apprentice's shows on Buildings & Heroes, the Lab Assistant's on Army
Upgrades. Tapping it opens his window, which lists what's under way with
the most time left first, each with an Assign button; the top one's opens
"Speed up ...?", with "Keep assigned until upgrade is complete" (ticked
here) and Confirm. Nothing is paid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from farmbot.game import Game, T
from farmbot.geometry import Rect

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Helper:
    name: str
    face: str   # his face in his bubble beside the list
    title: str  # his window's title
    tab: str    # the list's tab his bubble shows on


APPRENTICE = Helper("Builder's Apprentice", T.APPRENTICE_FACE, T.APPRENTICE_TITLE, "buildings")
LAB_ASSISTANT = Helper("Lab Assistant", T.LAB_ASSISTANT_FACE, T.LAB_ASSISTANT_TITLE, "army")

SHARED = (T.HELPER_AVAILABLE, T.HELPER_ASSIGN, T.HELPER_KEEP, T.HELPER_CONFIRM, T.CLOSE)
# His face sits just right of his "Available": this far from the word's centre (screen pixels).
FACE_RIGHT = (40, 110)
FACE_ROW = 20
WINDOW_CLOSE = Rect(880, 90, 297, 130)  # the helper and confirm windows' Xs (not the list's, top right)


def needed(helper: Helper = APPRENTICE) -> tuple[str, ...]:
    return (helper.face, helper.title) + SHARED


def idle_bubble(game: Game, helper: Helper = APPRENTICE):
    """The helper's "Available" bubble (a match to tap), if he's idle."""
    faces = game.find_all(helper.face)
    for word in game.find_all(T.HELPER_AVAILABLE):
        for face in faces:
            if FACE_RIGHT[0] <= face.x - word.x <= FACE_RIGHT[1] and abs(face.y - word.y) <= FACE_ROW:
                return word
    return None


def assign_helper(game: Game, helper: Helper = APPRENTICE) -> bool:
    """With the list's tab for ``helper`` open: an idle helper is put on
    what's under way with the most time left. True if he was. The list is
    left open."""
    if not all(game.has(n) for n in needed(helper)):
        return False
    game.refresh()
    bubble = idle_bubble(game, helper)
    if bubble is None:
        return False
    game.tap_match(bubble)
    if game.wait_for(helper.title, 4) is None:
        log.info("%s: his window didn't open", helper.name)
        return False
    done = False
    try:
        game.refresh()
        rows = game.find_all(T.HELPER_ASSIGN)
        if not rows:
            log.info("%s: idle, but nothing under way to put him on", helper.name)
            return False
        game.tap_match(min(rows, key=lambda m: m.y))  # the top row: the most time left
        confirm = game.wait_for(T.HELPER_CONFIRM, 4)
        if confirm is None:
            log.info("%s: the assign window didn't open", helper.name)
            return False
        box = game.find(T.HELPER_KEEP)
        if box is not None:  # (unticked: ticked, so he stays on it each time he's ready)
            game.tap_match(box)
            game.wait(0.6)
        game.tap_match(confirm)
        game.wait(1.5)
        game.refresh()
        done = game.find(T.HELPER_CONFIRM) is None and idle_bubble(game, helper) is None
        if done:
            log.info("%s: put on what's under way with the most time left", helper.name)
        else:
            log.info("%s: couldn't tell he was put to work", helper.name)
        return done
    finally:
        for _ in range(2):  # his window (and the confirm one, if it stayed): not the list
            game.refresh()
            if not game.click(T.CLOSE, region=WINDOW_CLOSE):
                break
            game.wait(0.8)


def idle_apprentice(game: Game):
    return idle_bubble(game, APPRENTICE)


def assign_apprentice(game: Game) -> bool:
    return assign_helper(game, APPRENTICE)

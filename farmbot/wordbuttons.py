"""Buttons found by their words, for screens no picture knows.

Each game update can bring a screen the bot has no picture for (a new chest
room, an event's window, a news page), and the bot used to wait on it until
the round failed. The buttons that get past such screens say the same few
words whatever they look like, so when a screen stays unknown its text is
read (Windows' own OCR) and a button whose words mean "go on" or "close" is
tapped. Only words that never spend, buy or quit are on the list: "Okay" is
left out (it confirms quitting the game, and buying).
"""

from __future__ import annotations

import difflib
import logging
import re

from farmbot.geometry import Rect

log = logging.getLogger(__name__)

# Lower case, letters and spaces only. Tried in this order when several show.
SAFE_WORDS = ("skip", "tap to continue", "continue", "claim reward", "claim", "collect", "return home", "close",
              "got it", "not now", "later", "cancel")
CLOSE_ENOUGH = 0.8  # how alike a read and a word must be: the OCR reads "Battle" as "Baffle"
OCR_ZOOM = 1.5  # the screen made bigger first: small words read better
WORDS_MAX = 3  # a button says this many words at most (a sentence is never one)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", text.lower())).strip()


def safe_word(text: str) -> str | None:
    """The safe word ``text`` (a line the OCR read) says, if it says one and nothing else."""
    plain = _plain(text)
    if not plain or len(plain.split()) > WORDS_MAX:
        return None
    for word in SAFE_WORDS:
        if plain == word or (len(word) >= 5 and difflib.SequenceMatcher(None, plain, word).ratio() >= CLOSE_ENOUGH):
            return word
    return None


def find(lines: list[tuple[Rect, str]]) -> tuple[str, Rect] | None:
    """The first safe word's button among the OCR's ``lines``."""
    found = [(word, rect) for rect, text in lines if (word := safe_word(text))]
    if not found:
        return None
    return min(found, key=lambda f: SAFE_WORDS.index(f[0]))


def read(image) -> list[tuple[Rect, str]]:
    from farmbot import redact

    return redact.read_text(image, OCR_ZOOM) or []


def tap_safe_word(game) -> str | None:
    """On a screen no picture knows: tap the button saying a safe word, if
    one shows. Returns the word tapped."""
    from farmbot import gameupdate

    try:
        lines = read(game.refresh())
    except Exception as exc:  # (no OCR on this Windows, say: the bot carries on without it)
        log.debug("Couldn't read the screen's words: %s", exc)
        return None
    update = gameupdate.find_button(lines)  # the game's update window: Update, never its Later
    if update is not None:
        gameupdate.update(game, update)
        return "update"
    hit = find(lines)
    if hit is None:
        return None
    word, r = hit
    log.info("Unknown screen: tapped the words \"%s\" on it (no picture for this screen yet)", word)
    game.tap(r.x + r.w // 2, r.y + r.h // 2)
    game.screen = None
    return word

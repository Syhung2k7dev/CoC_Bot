"""The game's own "new version" window: Update pressed, the update installed
from the Play Store, the game started again.

When Supercell puts out an update, the game opens on a window asking for it
(its Update button, sometimes a Later beside it) and, once the update is
required, can't be played until it's installed. The window is told by its
words, not a picture (its look changes with the game's): a line about a
new version or an update, and a button saying just "Update". Never
"Upgrade", the village's buttons.

Update opens the game's page in the Play Store. The store isn't the game,
so its buttons are read from Android's own description of the screen
(``uiautomator``), not from pictures: "Update" pressed, then the game's
version watched until the new one is installed ("Play"/"Open" again).
A store that isn't signed in can't update: that's logged, and the game is
started again as it is.
"""

from __future__ import annotations

import logging
import re

from farmbot.geometry import Rect

log = logging.getLogger(__name__)

STORE = "com.android.vending"
GAME = "com.supercell.clashofclans"
BUTTON_WORDS = ("update", "update now")
# A line of the window's own text (its title or its sentence) says one of these.
WINDOW_WORDS = ("new version", "update available", "update required", "latest version", "please update",
                "needs to be updated", "update the game", "an update")
STORE_OPEN = 15.0  # s for the store to come up after Update
INSTALL_MOST = 20 * 60.0  # s the download and install may take
LOOK = 5.0  # s between looks at the store
NO_UPDATE = 30.0  # s on the store's page with no Update showing: there's none to install
FIRST_LOAD = 10 * 60.0  # s the first start after an update may load for
DUMP = "/sdcard/cocfarm_ui.xml"


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", text.lower())).strip()


def find_button(lines: list[tuple[Rect, str]]) -> Rect | None:
    """The window's Update button among the OCR's ``lines``, or None when
    the screen isn't the game's update window."""
    plain = [(rect, _plain(text)) for rect, text in lines]
    if not any(any(w in text for w in WINDOW_WORDS) for _, text in plain):
        return None
    return next((rect for rect, text in plain if text in BUTTON_WORDS), None)


def version(device, package: str) -> str | None:
    """The installed game's version ("19.32.4"), or None if it can't be told."""
    try:
        found = re.search(r"versionName=(\S+)", device.shell("dumpsys", "package", package))
    except Exception:
        return None
    return found.group(1) if found else None


def store_buttons(device) -> dict[str, tuple[int, int]]:
    """The store's words on screen (each node's text or description, lower
    case) and their middles in device pixels."""
    try:
        device.shell("rm", "-f", DUMP)
    except Exception:
        pass
    try:
        device.shell("uiautomator", "dump", DUMP)
    except Exception:
        pass  # (MuMu's uiautomator crashes once it has written the file)
    try:
        xml = device.shell("cat", DUMP)
    except Exception:
        return {}
    found: dict[str, tuple[int, int]] = {}
    for node in re.findall(r"<node [^>]*>", xml):
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bounds:
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        for attr in ("text", "content-desc"):
            words = re.search(rf' {attr}="([^"]*)"', node)
            if words and words.group(1).strip():
                found.setdefault(words.group(1).strip().lower(), ((x1 + x2) // 2, (y1 + y2) // 2))
    return found


def update(game, button: Rect, package: str | None = None) -> bool:
    """Press the window's Update, update the game in the Play Store, start it
    again. True once a new version is installed."""
    device = game.device
    package = package or _foreground(device) or GAME
    if package == STORE:
        package = GAME
    before = version(device, package)
    log.warning("The game asks for an update (version %s installed): pressing Update", before or "?")
    game.tap(button.x + button.w // 2, button.y + button.h // 2)
    game.screen = None
    start = game.clock()
    while _foreground(device) != STORE and game.clock() - start < STORE_OPEN:
        game.wait(1)
    if _foreground(device) != STORE:  # Update didn't open it: the game's page straight
        log.info("Opening the game's Play Store page")
        _open_page(device, package)
        game.wait(3)
    pressed_at = None
    start = game.clock()
    try:
        while game.clock() - start < INSTALL_MOST:
            now = version(device, package)
            buttons = store_buttons(device)
            if now and before and now != before and "update" not in buttons:
                log.info("Game updated: %s -> %s", before, now)
                return True
            if "sign in" in buttons:
                log.warning("The Play Store isn't signed in, so the game can't update: sign in to Google Play "
                            "in the emulator")
                return False
            if "update" in buttons and (pressed_at is None or game.clock() - pressed_at > 60):
                log.info("Pressing Update in the Play Store")
                device.tap(*buttons["update"])
                pressed_at = game.clock()
            elif pressed_at is None and game.clock() - start > NO_UPDATE and ({"play", "open"} & buttons.keys()):
                log.info("The Play Store has no update for the game yet (it shows Play): starting the game again")
                return False
            if _foreground(device) != STORE:
                _open_page(device, package)
            game.wait(LOOK)
        log.warning("The game's update didn't finish in %d minutes", INSTALL_MOST // 60)
        return False
    finally:
        # Closed first, then started: started straight from the store after an
        # install, it stayed on a black screen (an account's, 16 Nov 2026).
        try:
            device.stop_app(package)
        except Exception:
            pass
        game.wait(3)
        device.start_app(package)
        game.screen = None
        game.wait(5)
        _wait_loaded(game)


def _wait_loaded(game) -> None:
    """The first start after an update unpacks the new content: its loading
    screen can take minutes (an account's: over 3), and a restart in the middle
    starts it again. Waited out until anything known shows."""
    from farmbot import screens

    start = game.clock()
    while game.clock() - start < FIRST_LOAD:
        try:
            if screens.identify(game) is not screens.Screen.UNKNOWN:
                return
        except Exception as exc:  # (the emulator slow to answer while it unpacks)
            log.debug("No look at the screen while the game loads: %s", exc)
        game.wait(LOOK)
    log.info("The game still loading %d minutes after its update; carrying on", FIRST_LOAD // 60)


def _foreground(device) -> str | None:
    try:
        return device.foreground_package()
    except Exception:
        return None


def _open_page(device, package: str) -> None:
    try:
        device.shell("am", "start", "-a", "android.intent.action.VIEW", "-d", f"market://details?id={package}")
    except Exception as exc:
        log.info("Couldn't open the Play Store: %s", exc)

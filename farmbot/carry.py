"""Bringing your farms and accounts over from another COCFARM folder.

COCFARM keeps everything in its own folder: settings, account profiles,
farms. An update installed from inside COCFARM keeps them (farmbot/update.py),
but a new release unzipped into a new folder starts empty, and the Start
menu then opens the new one. So when COCFARM starts with nothing of its own
and Windows' Installed apps still points to another COCFARM folder that has
settings, it offers to copy them here. The other folder is never changed.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SETTINGS = "farmbot.toml"
# Copied whole (only when this folder has none of its own).
DATA = (SETTINGS, "profiles", "instances", "attacks.csv", "onboarding.json")
PICTURES = "templates"  # pictures you added: copied where this folder has none by that name

FOUND: Path | None = None  # the other folder, looked up at start (before this one is registered)


def registered_folder() -> Path | None:
    """The COCFARM folder Installed apps points to, if any."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        from farmbot.installed import KEY

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            location, _ = winreg.QueryValueEx(key, "InstallLocation")
    except OSError:
        return None
    return Path(location) if location else None


def has_data(folder: Path) -> bool:
    return (folder / SETTINGS).is_file() and (folder / "profiles").is_dir()


def other_copy(here: Path, registered: Path | None) -> Path | None:
    """``registered``, if it's another COCFARM folder with settings and
    accounts while ``here`` has no settings yet."""
    if registered is None or (here / SETTINGS).exists():
        return None
    try:
        same = registered.resolve() == here.resolve()
    except OSError:
        return None
    return None if same or not has_data(registered) else registered


def look(here: Path) -> Path | None:
    """At start, before this folder is registered in Installed apps."""
    global FOUND
    FOUND = other_copy(here, registered_folder())
    if FOUND:
        log.info("Another COCFARM folder has settings and accounts: %s", FOUND)
    return FOUND


def bring(old: Path, here: Path) -> list[str]:
    """Copy ``old``'s settings, accounts, farms, attack log and added
    pictures into ``here`` (which has none of them). What was copied."""
    copied = []
    for name in DATA:
        source, target = old / name, here / name
        if not source.exists() or target.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        copied.append(name)
    pictures = old / PICTURES
    added = 0
    if pictures.is_dir():
        for source in pictures.rglob("*"):
            target = here / PICTURES / source.relative_to(pictures)
            if source.is_file() and not target.exists():  # a shipped picture here is newer: kept
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                added += 1
    if added:
        copied.append(f"{added} picture{'s' * (added != 1)}")
    log.info("Brought over from %s: %s", old, ", ".join(copied) or "nothing")
    return copied

"""The display Android itself uses, checked against farmbot.standard.

The emulators' own settings are set to the standard when the bot connects
(farmbot.mumu, .bluestacks, .ldplayer), but what the game is drawn at is
what Android reports: an override (``wm size``, ``wm density``) left by an
app or by hand, or an emulator that didn't apply its own DPI setting, makes
the game draw its windows at another size than the pictures were taken at,
and buttons such as the upgrade window's Confirm go unseen. An emulator's
display is put back (overrides dropped, or the standard set); a phone or
an emulator the bot didn't set up ("manual") is only warned about.
"""

from __future__ import annotations

import logging
import re

from farmbot import standard

log = logging.getLogger(__name__)


def _values(out: str) -> tuple[str, str]:
    """``(physical, override)`` from ``wm size`` / ``wm density`` output
    (override empty when there's none)."""
    physical = override = ""
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key.lower().startswith("physical"):
            physical = value
        elif key.lower().startswith("override"):
            override = value
    return physical, override


def _size(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d+)\s*x\s*(\d+)", value)
    return tuple(sorted((int(m[1]), int(m[2])))) if m else None  # either way round


def _density(value: str) -> int | None:
    return int(value) if value.isdigit() else None


WANTED_SIZE = tuple(sorted((standard.WIDTH, standard.HEIGHT)))


def check(device, fix: bool) -> list[str]:
    """Check the display Android uses; with ``fix``, put it back to the
    standard. What was wrong (put back or not), one line each; empty if
    it's right or the device can't say."""
    shell = getattr(device, "shell", None)
    if shell is None:
        return []
    found: list[str] = []
    try:
        size_out, density_out = str(shell("wm", "size")), str(shell("wm", "density"))
    except Exception:  # noqa: BLE001 - a device that can't say is left alone
        return []
    want_size = f"{standard.WIDTH}x{standard.HEIGHT}"

    physical, override = _values(size_out)
    if _size(physical) is not None:
        if override and _size(override) != _size(physical):
            if fix and _size(physical) == WANTED_SIZE:
                shell("wm", "size", "reset")
                found.append(f"display size overridden to {override}: reset to {physical}")
            elif fix:
                shell("wm", "size", want_size)
                found.append(f"display size {override} (its own {physical}): set to {want_size}")
            else:
                found.append(f"display size overridden to {override} (its own {physical})")
        elif _size(override or physical) != WANTED_SIZE:
            if fix:
                shell("wm", "size", want_size)
                found.append(f"display size {physical}: set to {want_size}")
            else:
                found.append(f"display size {physical}, not {want_size}")

    physical, override = _values(density_out)
    if _density(physical) is not None:
        using = _density(override) or _density(physical)
        if using != standard.DPI:
            if fix and _density(physical) == standard.DPI:
                shell("wm", "density", "reset")
                found.append(f"density overridden to {using}: reset to {standard.DPI}")
            elif fix:
                shell("wm", "density", str(standard.DPI))
                found.append(f"density {using}: set to {standard.DPI}")
            else:
                found.append(f"density {using}, not {standard.DPI}")
    return found

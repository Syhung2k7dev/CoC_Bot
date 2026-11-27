"""Which emulator instances are open on this PC now, and so which farms'
are: the Farms page marks them, so you can see which account to switch to.

Each emulator is only asked (its own tool, or the list of its windows):
nothing is started or stopped. An emulator that can't be asked counts as
having none open.
"""

from __future__ import annotations

import logging

from farmbot.config import DeviceConfig
from farmbot.device import DeviceError
from farmbot.instances import Choice, same_instance

log = logging.getLogger(__name__)

EVERY = 12.0  # seconds between looks, from the Farms page (MuMu's tool takes a moment)


def open_choices() -> list[Choice]:
    """The emulator instances whose window is open now, as :class:`Choice`
    (for BlueStacks, ``label`` is the display name)."""
    from farmbot import bluestacks, ldplayer, mumu

    found: list[Choice] = []
    for install in ldplayer.find_installs():
        try:
            found += [Choice(str(i.index), i.title, "ldplayer", install.name, i.port)
                      for i in ldplayer.instances(install) if i.running]
        except (DeviceError, OSError) as exc:
            log.debug("Couldn't ask %s which instances are open: %s", install.name, exc)
    install = mumu.find_install()
    if install is not None:
        try:
            # started: its window is up (Android may still be starting)
            found += [Choice(str(i.index), i.name, "mumu", "", i.adb_port)
                      for i in mumu.instances(install) if i.started or i.running]
        except (DeviceError, OSError) as exc:
            log.debug("Couldn't ask MuMu Player which instances are open: %s", exc)
    install = bluestacks.find_install()
    if install is not None and install.instances:
        for _, shown in bluestacks.players():
            inst = install.instance(shown) if shown else install.instances[0]  # (no --instance: the main one)
            if inst is not None and not any(c.mode == "bluestacks" and c.key == inst.name for c in found):
                found.append(Choice(inst.name, inst.display_name, "bluestacks", "", inst.adb_port))
    return found


def _plays(device: DeviceConfig, choice: Choice) -> bool:
    """Whether a farm set to ``device`` plays the open instance ``choice``."""
    if device.mode == "manual":  # by its address: an open instance on that port
        return choice.port is not None and device.serial.rsplit(":", 1)[-1] == str(choice.port)
    if device.mode == "bluestacks" and choice.mode == "bluestacks":
        named = (device.bluestacks_instance or "").lower()
        if not named:  # the main instance (the master: no "_" in its internal name)
            return "_" not in choice.key
        return named in (choice.key.lower(), choice.label.lower())
    return same_instance(device, choice.device(device))


def open_farms(devices: dict[int, DeviceConfig], found: list[Choice]) -> set[int]:
    """The farms (of ``devices``) whose emulator instance is in ``found``."""
    return {n for n, device in devices.items() if any(_plays(device, c) for c in found)}

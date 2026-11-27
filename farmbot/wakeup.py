"""Upgrades → "Close COCFARM between upgrades": once every builder (and
the laboratory) the upgrades may use is busy, COCFARM closes the game and
itself, and a Windows scheduled task opens it again when the first of
those upgrades is done, to start the next one (farming first for the loot
if it's short), then close again. The builder base's builders and Star
Laboratory count too ("bb_builders", "bb_lab") when it's farmed and its
upgrades are on.

The task is one-off (``TASK``), replaced each time and deleted whenever
COCFARM starts, is stopped, or the setting goes off. Everything that runs
``schtasks`` takes a ``run`` (``subprocess.run`` by default), so tests
never touch the real Task Scheduler.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from . import gamedata, townhall

log = logging.getLogger(__name__)

TASK = "COCFARM wake-up"
START_FLAG = "--start"
SOON = timedelta(minutes=15)  # done sooner than this: waited out with COCFARM open
AFTER = timedelta(minutes=1)  # woken this long after the upgrade is done

# What each kind of slot works on, by the export's ids (pets have a house of their own: left out).
_SLOTS = {"builders": {*gamedata.BUILDINGS, *gamedata.TRAPS, *gamedata.HEROES},
          "lab": {*gamedata.TROOPS, *gamedata.SPELLS}}

Runner = Callable[..., subprocess.CompletedProcess]


def ends(village: townhall.Village | None, now: float) -> dict[str, list[float]]:
    """When what's under way ends, by slot ("builders", "lab", and the
    builder base's "bb_builders", "bb_lab"): seconds since 1970, those
    still to come only."""
    out: dict[str, list[float]] = {"builders": [], "lab": [], "bb_builders": [], "bb_lab": []}
    if village is None:
        return out
    for i, times in village.finishing.items():
        for slot, ids in _SLOTS.items():
            if i in ids:
                out[slot] += [t for t in times if t > now]
    for slot, times in village.builder_finishing.items():
        out["bb_" + slot] += [t for t in times if t > now]
    return out


def needing(wanted: dict[str, bool], free: dict[str, int | None], spent: dict[str, bool]) -> list[str]:
    """The slots free with something left for them (see :func:`decide`)."""
    return [slot for slot, on in wanted.items()
            if on and not spent.get(slot) and (free.get(slot) is None or free[slot] > 0)]


def decide(wanted: dict[str, bool], free: dict[str, int | None], spent: dict[str, bool],
           ends_by_slot: dict[str, list[float]]) -> tuple[str, float | None]:
    """After a round's upgrades: what next.

    ``wanted``: the slots the upgrades use ("builders", "lab"); ``free``:
    how many of each could still start one (None: not read); ``spent``:
    nothing is left to upgrade with it (what's left was read through);
    ``ends_by_slot``: see :func:`ends`.

    ("farm", None): a slot is free with something left for it (the loot
    is short, or its count couldn't be read): farm for it. ("leave", t):
    every slot is busy or has nothing left: back at ``t``, the first end.
    ("stop", None): nothing under way and nothing to start."""
    if needing(wanted, free, spent):
        return "farm", None
    times = [t for slot, on in wanted.items() if on for t in ends_by_slot.get(slot, ())]
    return ("leave", min(times)) if times else ("stop", None)


def command() -> tuple[str, list[str], str]:
    """What the task runs: (program, its arguments, the folder it runs in,
    where COCFARM finds its settings and logs)."""
    folder = str(Path.cwd())
    if getattr(sys, "frozen", False):
        return sys.executable, ["gui", START_FLAG], folder  # (packaging/farmbot_app.py: its arguments go to the CLI)
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    return str(windowed if windowed.is_file() else python), ["-m", "farmbot", "gui", START_FLAG], folder


def _quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg or not arg) else arg


def task_xml(at: datetime, program: str, args: list[str], folder: str) -> str:
    """The task, run once at ``at`` (the PC's local time) as whoever is
    signed in, on battery too; missed (the PC off or asleep): run once it
    can be."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Opens COCFARM when an upgrade it started is done (Upgrades: Close COCFARM between upgrades). COCFARM deletes it when it starts.</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{at:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(program)}</Command>
      <Arguments>{escape(" ".join(_quote(a) for a in args))}</Arguments>
      <WorkingDirectory>{escape(folder)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(run: Runner, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return run(["schtasks.exe", *args], capture_output=True, text=True, errors="replace", timeout=30,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("Wake-up: couldn't run schtasks: %s", exc)
        return None


def schedule(at: datetime, run: Runner = subprocess.run) -> bool:
    """Set the task to open COCFARM at ``at``, replacing any; True only
    once Windows is seen to hold it for that time."""
    if sys.platform != "win32" and run is subprocess.run:
        return False
    program, args, folder = command()
    path = Path(tempfile.gettempdir()) / "cocfarm-wakeup.xml"
    try:
        path.write_text(task_xml(at, program, args, folder), encoding="utf-16")
    except OSError as exc:
        log.info("Wake-up: couldn't write the task: %s", exc)
        return False
    try:
        made = _schtasks(run, "/Create", "/TN", TASK, "/XML", str(path), "/F")
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    if made is None or made.returncode:
        log.info("Wake-up: Windows didn't take the task: %s", (made.stderr or made.stdout).strip() if made else "")
        return False
    held = _schtasks(run, "/Query", "/TN", TASK, "/XML")
    if held is None or held.returncode or f"<StartBoundary>{at:%Y-%m-%dT%H:%M:%S}" not in (held.stdout or ""):
        log.info("Wake-up: the task isn't there as set: not relied on")
        cancel(run)
        return False
    log.info("Wake-up: Windows opens COCFARM at %s (the task \"%s\")", f"{at:%a %H:%M}", TASK)
    return True


def cancel(run: Runner = subprocess.run) -> bool:
    """Delete the task, if there is one. True if one was deleted."""
    if sys.platform != "win32" and run is subprocess.run:
        return False
    there = _schtasks(run, "/Query", "/TN", TASK)
    if there is None or there.returncode:
        return False
    gone = _schtasks(run, "/Delete", "/TN", TASK, "/F")
    if gone is not None and not gone.returncode:
        log.info("Wake-up: deleted the task \"%s\"", TASK)
        return True
    return False

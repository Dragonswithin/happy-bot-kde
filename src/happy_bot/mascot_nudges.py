"""Occasional local readings for the mascot's actionable desktop nudges.

The daemon runs these on a separate sampler so package-cache queries cannot
delay recording indicators or live system graphs. A reading is True, False,
or None (no reliable reading). Only the four condition IDs leave the daemon.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from .system_monitor import batteries
from .tools.shell import pending_reboot

SAMPLE_SECONDS = 60
UPDATE_SECONDS = 15 * 60
LOW_BATTERY_PERCENT = 20
LOW_DISK_PERCENT = 10
LOW_DISK_BYTES = 10 * 1024**3


def low_battery() -> bool | None:
    unknown = False
    for battery in batteries():
        level, status = battery["percent"], battery["status"]
        if status == "Discharging" and level is not None and level <= LOW_BATTERY_PERCENT:
            return True
        if level is None or status not in ("Charging", "Discharging", "Full", "Not charging"):
            unknown = True
    return None if unknown else False


def low_disk() -> bool | None:
    unknown = False
    for path in (Path.home(), Path("/")):
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            unknown = True
            continue
        if usage.total <= 0:
            unknown = True
        elif usage.free <= LOW_DISK_BYTES and usage.free * 100 <= usage.total * LOW_DISK_PERCENT:
            return True
    return None if unknown else False


def cached_updates() -> bool | None:
    """Look for upgrades in locally available distribution package metadata."""
    commands = []
    if shutil.which("pacman"):
        commands.append(["pacman", "-Quq"])
        # checkupdates may have a newer database than the one used for installs.
        # Query that existing cache directly; running checkupdates would refresh it.
        default_cache = Path(os.environ.get("TMPDIR") or "/tmp") / f"checkup-db-{os.getuid()}"
        cache = Path(os.environ.get("CHECKUPDATES_DB") or default_cache)
        if (cache / "local").is_dir() and (cache / "sync").is_dir():
            commands.append(["pacman", "-Quq", "--dbpath", str(cache)])
    elif shutil.which("apt"):
        commands.append(["apt", "list", "--upgradable"])
    elif shutil.which("dnf"):
        commands.append(["dnf", "--cacheonly", "--noplugins", "check-update"])

    unknown = not commands
    for command in commands:
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                                    env={**os.environ, "LC_ALL": "C"}, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            unknown = True
            continue
        if command[0] == "pacman":
            if result.returncode == 0 and result.stdout.strip():
                return True
            # pacman -Qu exits 1 with no output when there are no matches.
            if result.returncode not in (0, 1) or result.stderr.strip():
                unknown = True
        elif command[0] == "dnf" and result.returncode == 100:
            return True
        elif result.returncode != 0:
            unknown = True
        elif command[0] == "apt" and re.search(r"^[a-z0-9][a-z0-9.+-]*/", result.stdout, re.MULTILINE):
            return True
    return None if unknown else False


class NudgeReadings:
    def __init__(self, enabled: Callable[[], bool]) -> None:
        self._enabled = enabled
        self._next_update_check = 0.0
        self._updates: bool | None = None

    def snapshot(self) -> dict[str, bool | None]:
        if not self._enabled():
            self._next_update_check = 0.0
            return {}
        now = time.monotonic()
        if now >= self._next_update_check:
            self._updates = cached_updates()
            self._next_update_check = now + UPDATE_SECONDS
        return {"battery": low_battery(), "disk": low_disk(), "restart": bool(pending_reboot()), "updates": self._updates}

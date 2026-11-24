"""Conditions that start a routine when they become true: joining a network, the battery running low.

Neither has an event a user's systemd can wait for (network and battery
changes arrive on the system bus, where hooks need root), so such a routine
gets a timer that runs ``happy-bot routine-check`` every
``CHECK_EVERY`` (``routines.desired_units``). Each check evaluates the
condition and runs the routine's request only when it has just become true:
the last result is kept in ``$XDG_RUNTIME_DIR/happy-bot/conditions/``,
so "battery below 20%" fires once per discharge, not every two minutes, and
"on network Home" fires on joining it, not while connected.

- ``network``: a NetworkManager connection with this name (for Wi-Fi, the
  network's name) is active (``nmcli``).
- ``battery``: a battery is discharging and below this percentage
  (``upower``).

``check(name, kind, value, ask)`` returns what happened, for the CLI to
report; ``ask`` is the function that sends the request (the CLI passes its
``ask --notify`` path).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .runtime_paths import ensure_runtime_root

CHECK_EVERY = "*:0/2"
KINDS = ("network", "battery")


def _output(command: list[str]) -> str:
    if not shutil.which(command[0]):
        return ""
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def on_network(name: str) -> bool:
    active = _output(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"]).splitlines()
    return name.strip().lower() in (line.strip().replace("\\:", ":").lower() for line in active)


def battery_below(percent: int) -> bool:
    for device in _output(["upower", "-e"]).splitlines():
        if "battery_" not in device:
            continue
        info = _output(["upower", "-i", device.strip()])
        level = re.search(r"percentage:\s*([\d.]+)%", info)
        if level and "discharging" in info and float(level.group(1)) < percent:
            return True
    return False


def holds(kind: str, value: str) -> bool:
    if kind == "network":
        return on_network(value)
    if kind == "battery":
        return battery_below(int(value))
    raise ValueError(f"unknown condition {kind!r}")


def _state_file(name: str, kind: str, root: Path | None) -> Path:
    folder = (root or ensure_runtime_root()) / "conditions"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder / (re.sub(r"[^A-Za-z0-9_-]", "_", f"{name}-{kind}") + ".state")


def check(name: str, kind: str, value: str, ask: Callable[[], object], root: Path | None = None) -> str:
    """Run the routine if the condition just became true; returns ``ran``, ``still true`` or ``not true``."""
    now = holds(kind, value)
    state = _state_file(name, kind, root)
    before = state.exists() and state.read_text(encoding="utf-8").strip() == "true"
    state.write_text("true" if now else "false", encoding="utf-8")
    if now and not before:
        ask()
        return "ran"
    return "still true" if now else "not true"

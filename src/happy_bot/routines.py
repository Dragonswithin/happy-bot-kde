"""Routines: named requests the user saved, run when asked, on a schedule, when a folder changes,
when a drive is plugged in, on joining a network, or when the battery runs low.

A routine is an entry of the ``routines`` setting (``settings.py`` stores it;
this module validates it and owns what it means)::

    "routines": {
      "start work": {
        "request": "Open Kate and Konsole side by side and turn on Do Not Disturb",
        "schedule": "Mon..Fri 08:30",   # default ""; a systemd OnCalendar expression, "" = never on its own
        "watch_folder": "",             # default ""; run when something in this folder changes
        "drive_label": "",              # default ""; run when a drive with this label is plugged in
        "on_network": "",               # default ""; run on joining this network (connection or Wi-Fi name)
        "battery_below": 0,             # default 0 = never; run when the battery drops below this percent
        "enabled": true                 # default true; false keeps it but never runs it on its own
      }
    }

Names are 1 to 60 characters of letters, digits, spaces, ``_``, ``.`` and
``-``. The request is at most ``MAX_REQUEST_CHARS``. A schedule is checked
with ``systemd-analyze calendar`` (``user_timers.check_calendar``).

How routines run:

- When asked: their names and requests are listed in the system prompt
  (``prompt_lines``), so "start work" typed in the bar is carried out.
- On their own: ``sync`` keeps one pair of systemd user units per trigger in
  step with the setting (a ``.timer`` for ``schedule``, a ``.path`` for
  ``watch_folder``, and for ``drive_label`` a service the drive's device unit
  wants, so it runs when that drive is plugged in; for ``on_network`` and
  ``battery_below`` a timer that checks every two minutes and runs the
  routine when the condition has just become true, ``routine_conditions``), whose service runs ``happy-bot ask --notify``
  with the request. That command has no terminal, so any step needing
  approval is declined, never taken; the answer arrives as a notification.

``sync`` is called by the daemon whenever settings are saved and at start.
It only rewrites units that changed and only runs ``systemctl`` when
``manage`` is true (the user's real unit directory).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from . import user_timers
from .routine_conditions import CHECK_EVERY

KIND = "routine"
MAX_REQUEST_CHARS = 2000
_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,60}$")


class RoutineError(ValueError):
    """A routine entry is not valid; the message names it and says why."""


def validate_routines(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalised routines with defaults filled in, or ``RoutineError``."""
    if not isinstance(raw, dict):
        raise RoutineError("'routines' must be an object")
    routines = {}
    for name, entry in raw.items():
        where = f"routine '{name}'"
        if not isinstance(name, str) or not _NAME.match(name) or not name.strip():
            raise RoutineError(f"{where}: names use letters, digits, spaces, '_', '.' or '-' (max 60)")
        if not isinstance(entry, dict):
            raise RoutineError(f"{where} must be an object")
        unknown = set(entry) - {"request", "schedule", "watch_folder", "drive_label", "on_network", "battery_below",
                                "enabled"}
        if unknown:
            raise RoutineError(f"{where}: unknown setting {sorted(unknown)[0]!r}")
        request = entry.get("request")
        if not isinstance(request, str) or not request.strip() or len(request) > MAX_REQUEST_CHARS:
            raise RoutineError(f"{where}: 'request' must be text of 1 to {MAX_REQUEST_CHARS} characters")
        schedule = entry.get("schedule", "")
        if not isinstance(schedule, str):
            raise RoutineError(f"{where}: 'schedule' must be text")
        if schedule.strip():
            problem = user_timers.check_calendar(schedule.strip())
            if problem:
                raise RoutineError(f"{where}: the schedule {schedule!r} is not understood: {problem}")
        folder = entry.get("watch_folder", "")
        if not isinstance(folder, str) or (folder.strip() and not folder.strip().startswith(("/", "~"))):
            raise RoutineError(f"{where}: 'watch_folder' must be empty or an absolute path")
        label = entry.get("drive_label", "")
        if not isinstance(label, str) or len(label) > 64 or "/" in label or "\n" in label:
            raise RoutineError(f"{where}: 'drive_label' must be a drive's label (no '/')")
        network = entry.get("on_network", "")
        if not isinstance(network, str) or len(network) > 100 or "\n" in network:
            raise RoutineError(f"{where}: 'on_network' must be a network's name")
        battery = entry.get("battery_below", 0)
        if isinstance(battery, bool) or not isinstance(battery, int) or not 0 <= battery <= 99:
            raise RoutineError(f"{where}: 'battery_below' must be a whole percentage from 1 to 99, or 0 for none")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RoutineError(f"{where}: 'enabled' must be true or false")
        routines[name.strip()] = {
            "request": request.strip(),
            "schedule": schedule.strip(),
            "watch_folder": os.path.expanduser(folder.strip()) if folder.strip() else "",
            "drive_label": label.strip(),
            "on_network": network.strip(),
            "battery_below": battery,
            "enabled": enabled,
        }
    return routines


def prompt_lines(routines: dict[str, dict[str, Any]]) -> list[str]:
    """System-prompt lines that tell the model the user's routines."""
    if not routines:
        return []
    lines = ["", "The user's saved routines. When the user names one (or asks to run it), carry out its request:"]
    lines += [f"- {name}: {entry['request']}" for name, entry in sorted(routines.items())]
    return lines


def _ident(name: str, trigger: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "routine"
    return f"{slug}-{hashlib.sha1(name.encode()).hexdigest()[:6]}-{trigger}"


def desired_units(routines: dict[str, dict[str, Any]]) -> dict[str, tuple[str, list[str], str, str]]:
    """Unit name -> (description, command, trigger kind, trigger value) for every enabled trigger."""
    wanted = {}
    for name, entry in routines.items():
        if not entry["enabled"]:
            continue
        command = [user_timers.launcher(), "ask", "--background", "--notify", "--", entry["request"]]
        description = f"Assistant routine: {name}"
        if entry["schedule"]:
            wanted[user_timers.unit_name(KIND, _ident(name, "schedule"))] = (description, command, "timer", entry["schedule"])
        if entry["watch_folder"]:
            wanted[user_timers.unit_name(KIND, _ident(name, "watch"))] = (description, command, "path", entry["watch_folder"])
        if entry.get("drive_label"):
            device = user_timers.device_unit(f"/dev/disk/by-label/{entry['drive_label']}")
            wanted[user_timers.unit_name(KIND, _ident(name, "drive"))] = (description, command, "device", device)
        for kind, value in (("network", entry.get("on_network", "")), ("battery", entry.get("battery_below", 0))):
            if value:
                check = [user_timers.launcher(), "routine-check", "--kind", kind, "--value", str(value), "--", name]
                wanted[user_timers.unit_name(KIND, _ident(name, kind))] = (description, check, "timer", CHECK_EVERY)
    return wanted


def sync(routines: dict[str, dict[str, Any]], unit_dir: Path, manage: bool) -> list[str]:
    """Make the unit files match ``routines``; returns problems worth telling the user (usually none)."""
    problems: list[str] = []
    existing = user_timers.owned_units(unit_dir, KIND)
    wanted = desired_units(routines)
    changed: list[tuple[str, str]] = []
    for name, (description, command, trigger, value) in wanted.items():
        before = {path.name: path.read_text(encoding="utf-8") for path in existing.get(name, [])}
        user_timers.write_units(unit_dir, name, description, command, trigger, value)
        after = {path.name: path.read_text(encoding="utf-8") for path in unit_dir.glob(f"{name}.*")}
        if before != after:
            changed.append((name, trigger))
    removed = {name: paths for name, paths in existing.items() if name not in wanted}
    if manage and (changed or removed):
        for name, paths in removed.items():
            for path in paths:
                if path.suffix in (".timer", ".path"):
                    user_timers.systemctl("disable", "--now", path.name)
                elif path.suffix == ".service" and len(paths) == 1:
                    user_timers.systemctl("disable", path.name)
    for paths in removed.values():
        user_timers.remove_units(paths)
    if manage and (changed or removed):
        ok, message = user_timers.systemctl("daemon-reload")
        if not ok:
            problems.append(f"systemd did not reload the routines: {message}")
        for name, trigger in changed:
            # A device routine's service is only enabled (linked into the device's wants), never started now.
            command = ("enable", f"{name}.service") if trigger == "device" else ("enable", "--now", f"{name}.{trigger}")
            ok, message = user_timers.systemctl(*command)
            if not ok:
                problems.append(f"routine unit {name} could not be started: {message}")
    return problems

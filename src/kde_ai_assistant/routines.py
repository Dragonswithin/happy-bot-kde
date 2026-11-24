"""Routines: named requests the user saved, run when asked, on a schedule, or when a folder changes.

A routine is an entry of the ``routines`` setting (``settings.py`` stores it;
this module validates it and owns what it means)::

    "routines": {
      "start work": {
        "request": "Open Kate and Konsole side by side and turn on Do Not Disturb",
        "schedule": "Mon..Fri 08:30",   # default ""; a systemd OnCalendar expression, "" = never on its own
        "watch_folder": "",             # default ""; run when something in this folder changes
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
  ``watch_folder``), whose service runs ``kde-ai-assistant ask --notify``
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
import shutil
from pathlib import Path
from typing import Any

from . import user_timers

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
        unknown = set(entry) - {"request", "schedule", "watch_folder", "enabled"}
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
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RoutineError(f"{where}: 'enabled' must be true or false")
        routines[name.strip()] = {
            "request": request.strip(),
            "schedule": schedule.strip(),
            "watch_folder": os.path.expanduser(folder.strip()) if folder.strip() else "",
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


def _launcher() -> str:
    return shutil.which("kde-ai-assistant") or str(Path.home() / ".local" / "bin" / "kde-ai-assistant")


def _ident(name: str, trigger: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "routine"
    return f"{slug}-{hashlib.sha1(name.encode()).hexdigest()[:6]}-{trigger}"


def desired_units(routines: dict[str, dict[str, Any]]) -> dict[str, tuple[str, list[str], str, str]]:
    """Unit name -> (description, command, trigger kind, trigger value) for every enabled trigger."""
    wanted = {}
    for name, entry in routines.items():
        if not entry["enabled"]:
            continue
        command = [_launcher(), "ask", "--notify", "--", entry["request"]]
        description = f"Assistant routine: {name}"
        if entry["schedule"]:
            wanted[user_timers.unit_name(KIND, _ident(name, "schedule"))] = (description, command, "timer", entry["schedule"])
        if entry["watch_folder"]:
            wanted[user_timers.unit_name(KIND, _ident(name, "watch"))] = (description, command, "path", entry["watch_folder"])
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
    for paths in removed.values():
        user_timers.remove_units(paths)
    if manage and (changed or removed):
        ok, message = user_timers.systemctl("daemon-reload")
        if not ok:
            problems.append(f"systemd did not reload the routines: {message}")
        for name, trigger in changed:
            ok, message = user_timers.systemctl("enable", "--now", f"{name}.{trigger}")
            if not ok:
                problems.append(f"routine unit {name} could not be started: {message}")
    return problems

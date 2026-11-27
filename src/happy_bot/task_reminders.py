"""Reconcile the systemd timers owned by Tasks with the current checklist."""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import user_timers

KIND = "task-reminder"


def reconcile(tasks: list[dict[str, Any]]) -> None:
    folder = user_timers.default_unit_dir()
    existing = user_timers.owned_units(folder, KIND)
    wanted = {}
    now = dt.datetime.now()
    for task in tasks:
        if task["done"] or not task["reminder"] or not task["due"]:
            continue
        stamp = f"{task['due']} {task['reminder']}:00"
        try:
            when = dt.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        name = user_timers.unit_name(KIND, task["id"])
        timer = folder / f"{name}.timer"
        service = folder / f"{name}.service"
        command = [user_timers.launcher(), "task-reminder-due", task["id"], stamp]
        current = (user_timers.read_setting(timer, "OnCalendar") == stamp
                   and user_timers.read_setting(service, "ExecStart") == " ".join(map(user_timers.quote_exec, command)))
        if when > now or current:
            wanted[name] = (stamp, command, current)

    reload_needed = False
    for name in existing.keys() - wanted.keys():
        _systemctl("disable", "--now", f"{name}.timer")
        for path in existing[name]:
            path.unlink(missing_ok=True)
        reload_needed = True
    activate = []
    rewritten = []
    for name, (stamp, command, current) in wanted.items():
        enabled = (folder / "timers.target.wants" / f"{name}.timer").is_symlink()
        if not current:
            user_timers.write_units(folder, name, "Happy Bot task reminder", command, "timer", stamp)
            rewritten.append(folder / f"{name}.timer")
            reload_needed = True
        if not current or not enabled:
            activate.append((name, enabled))
    try:
        if reload_needed or activate:
            _systemctl("daemon-reload")
        for name, enabled in activate:
            if enabled:
                _systemctl("restart", f"{name}.timer")
            else:
                _systemctl("enable", "--now", f"{name}.timer")
    except OSError:
        # Keep the checklist change. An absent timer definition makes the next sync retry it.
        for timer in rewritten:
            timer.unlink(missing_ok=True)
        raise


def _systemctl(*arguments: str) -> None:
    ok, message = user_timers.systemctl(*arguments)
    if not ok:
        raise OSError(message or "Could not update the task reminder.")


def due_text(tasks: list[dict[str, Any]], ident: str, stamp: str) -> str:
    return next((task["text"] for task in tasks if task["id"] == ident and not task["done"]
                 and f"{task['due']} {task['reminder']}:00" == stamp), "")

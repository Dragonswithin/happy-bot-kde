"""Reminder and timer tools: "remind me at 4 to call the vet", "set a timer for 10 minutes".

A reminder is a pair of systemd user units written by ``user_timers``: a
timer for the chosen minute (``Persistent=true``, so one missed while the
computer was off is shown at the next start) and a service that shows a
desktop notification with the reminder's text. Being units, reminders fire
with the popup closed and survive the daemon, a logout and a reboot; they
need no process of this project to be running.

Units are named ``happy-bot-reminder-<id>``. ``upcoming`` (behind
``list_reminders`` and the settings page's ``GET /reminders``) reads them back (the text is the unit's description) and removes reminders whose
time has passed, so the directory does not fill up. ``cancel_reminder``
stops and removes one by id.

Times are local wall-clock time. ``at`` takes ``YYYY-MM-DD HH:MM`` (or
``HH:MM`` for the next time that clock time comes round); ``in_minutes``
counts from now. A time in the past is refused.

``_location`` gives the unit directory and whether to run ``systemctl``;
tests replace it to work in a temporary directory.
"""

from __future__ import annotations

import datetime
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .. import user_timers
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

KIND = "reminder"
MAX_TEXT = 300


def _location() -> tuple[Path, bool]:
    return user_timers.default_unit_dir(), True


def _now() -> datetime.datetime:
    return datetime.datetime.now().replace(second=0, microsecond=0)


def parse_when(arguments: dict[str, Any], now: datetime.datetime | None = None) -> datetime.datetime:
    """The reminder's local time from ``at`` or ``in_minutes``; raises ``ToolFailure`` if unclear or past."""
    now = now or _now()
    at, minutes = arguments.get("at"), arguments.get("in_minutes")
    if (at is None) == (minutes is None):
        raise ToolFailure("give exactly one of 'at' (YYYY-MM-DD HH:MM, or HH:MM) or 'in_minutes'")
    if minutes is not None:
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 525600:
            raise ToolFailure("'in_minutes' must be a number of minutes from 1 to 525600")
        return now + datetime.timedelta(minutes=round(minutes))
    text = str(at).strip().replace("T", " ")
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            clock = datetime.datetime.strptime(text, "%H:%M").time()
            when = datetime.datetime.combine(now.date(), clock)
            return when if when > now else when + datetime.timedelta(days=1)
        when = datetime.datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise ToolFailure(f"'at' must look like 2026-11-23 16:00 or 16:00, not {at!r}") from error
    if when <= now:
        raise ToolFailure(f"{when:%Y-%m-%d %H:%M} has already passed; it is now {now:%Y-%m-%d %H:%M}")
    return when


def set_reminder(arguments: dict[str, Any]) -> str:
    text = str(arguments.get("text") or "").strip()
    if not text:
        raise ToolFailure("'text' is required: what to remind the user of")
    if len(text) > MAX_TEXT:
        raise ToolFailure(f"'text' may be at most {MAX_TEXT} characters")
    when = parse_when(arguments)
    if not shutil.which("notify-send"):
        raise ToolFailure("notify-send is not installed, so a reminder could not be shown")
    unit_dir, manage = _location()
    ident = secrets.token_hex(4)
    name = user_timers.unit_name(KIND, ident)
    user_timers.write_units(unit_dir, name, text, [
        shutil.which("notify-send") or "notify-send", "--app-name=Happy Bot", "--urgency=critical",
        "--icon=appointment-soon", "Reminder", text,
    ], "timer", when.strftime("%Y-%m-%d %H:%M:00"))
    if manage:
        for command in (("daemon-reload",), ("enable", "--now", f"{name}.timer")):
            ok, message = user_timers.systemctl(*command)
            if not ok:
                user_timers.remove_units(list(unit_dir.glob(f"{name}.*")))
                raise ToolFailure(f"the reminder could not be scheduled: {message}")
    return f"Reminder {ident} set for {when:%A %d %B, %H:%M}: {text}"


def upcoming() -> list[dict[str, Any]]:
    """Every reminder, oldest time first; passed ones are removed on the way."""
    unit_dir, manage = _location()
    now = _now()
    found, finished = [], []
    for name, paths in user_timers.owned_units(unit_dir, KIND).items():
        timer = next((path for path in paths if path.suffix == ".timer"), None)
        when_text = user_timers.read_setting(timer, "OnCalendar") if timer else ""
        try:
            when = datetime.datetime.strptime(when_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = None
        if when is None or when <= now:
            finished.append((name, paths))
            continue
        found.append({"id": name.removeprefix(user_timers.unit_name(KIND, "")), "when": when,
                      "text": user_timers.read_setting(paths[0], "Description")})
    for name, paths in finished:
        if manage:
            user_timers.systemctl("disable", "--now", f"{name}.timer")
        user_timers.remove_units(paths)
    if finished and manage:
        user_timers.systemctl("daemon-reload")
    return sorted(found, key=lambda item: item["when"])


def list_reminders(arguments: dict[str, Any]) -> str:
    reminders = upcoming()
    if not reminders:
        return "No reminders are set."
    return "\n".join(f"{item['id']}  {item['when']:%a %d %b %H:%M}  {item['text']}" for item in reminders)


def cancel_reminder(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("id") or "").strip()
    reminders = upcoming()
    match = [item for item in reminders if item["id"] == wanted]
    if not match:
        listing = "; ".join(f"{item['id']} ({item['text']})" for item in reminders) or "none are set"
        raise ToolFailure(f"no reminder has the id '{wanted}'. Reminders: {listing}")
    unit_dir, manage = _location()
    name = user_timers.unit_name(KIND, wanted)
    if manage:
        user_timers.systemctl("disable", "--now", f"{name}.timer")
    user_timers.remove_units(list(unit_dir.glob(f"{name}.*")))
    if manage:
        user_timers.systemctl("daemon-reload")
    return f"Cancelled the reminder: {match[0]['text']}"


def reminder_tools() -> list[Tool]:
    return [
        Tool("set_reminder", "Show the user a reminder notification at a time, or after some minutes (a timer). It "
             "works even if the assistant is closed or the computer restarts.",
             object_schema({"text": {"type": "string"},
                            "at": {"type": "string", "description": "Local time: YYYY-MM-DD HH:MM, or HH:MM for the "
                                   "next time that clock time comes"},
                            "in_minutes": {"type": "number"}}, ["text"]),
             RISK_CHANGE, set_reminder,
             summarize=lambda a: f"Remind: {str(a.get('text', ''))[:120]}"),
        Tool("list_reminders", "The reminders and timers that are set, with their ids.", object_schema(), RISK_READ,
             list_reminders, summarize=lambda a: "List reminders"),
        Tool("cancel_reminder", "Cancel a reminder or timer by its id from list_reminders.",
             object_schema({"id": {"type": "string"}}, ["id"]), RISK_CHANGE, cancel_reminder,
             summarize=lambda a: f"Cancel reminder {a.get('id', '?')}"),
    ]

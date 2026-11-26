"""Instant commands typed into the search bar: "volume 30", "dark mode", "timer 10m", "lock".

The search bar finds and launches with no model involved; this module lets it
also *do* a few everyday things at once, through the same built-in tools the
AI uses, without asking the AI. ``match(text)`` recognises one command in the
typed text and returns a quick result for it (``quick_results.gather`` puts
it first); choosing that result sends ``{"type": "command", "target": text}``
back, and ``run`` recognises the text again and carries it out. The action
carries only the typed text, never a tool name or arguments, so a crafted
request can do no more than typing the same words into the bar.

Commands (case and extra spaces do not matter):

- ``volume 30`` / ``set volume to 30%`` (0 to 150), ``mute``, ``unmute``:
  ``set_volume``;
- ``brightness 60`` (1 to 100): ``set_brightness``;
- ``dark mode`` / ``light mode``: ``set_color_scheme`` BreezeDark / BreezeLight;
- ``night light on|off``: ``set_night_light``;
- ``wifi on|off``, ``bluetooth on|off`` (either word order, "turn" optional):
  ``set_radio``;
- ``timer 10m`` / ``timer 1h30m`` / ``10 minute timer`` (whole minutes, 1 to
  1440) and ``alarm 07:30`` use the alarm cue when due;
- ``lock`` / ``lock screen``: ``session_action`` lock;
- ``do not disturb`` / ``dnd 30m`` (an hour when no time is given), ``do not
  disturb off``: ``do_not_disturb``.

Text that is a command only when read loosely ("play", "sleep") is left out
on purpose, because these run as soon as the user presses Enter.

``run`` uses the tools the user has not switched off
(``tools.catalog.builtin_tools``). Choosing the result is the user's consent
to that one change, so the approval policy's ``change`` prompts do not
apply; anything the tool itself classes as ``danger`` is refused and the
user is pointed to Happy Bot instead. Every command that ran is written to
the action log (``permissions.append_audit``), and the tools record their
own undo steps. A command that ran shows its title in Plasma's on-screen
display (``org.kde.osdService.showText``, as a volume change does), so the
user sees it happened after the bar has closed; without Plasma's shell that
is skipped. ``run`` blocks while the tool runs (a few seconds at most).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUBTITLE = "Command · Press Enter to do it"
_DURATION = r"(?:(\d{1,2})\s*h(?:ours?|rs?)?)?\s*(?:(\d{1,4})\s*m(?:in(?:ute)?s?)?)?"


class CommandError(RuntimeError):
    """The command could not be carried out; the message says why, for the user."""


@dataclass(frozen=True)
class Command:
    title: str
    icon: str
    tool: str
    arguments: dict[str, Any]


def _minutes(hours: str | None, minutes: str | None) -> int | None:
    if not hours and not minutes:
        return None
    total = int(hours or 0) * 60 + int(minutes or 0)
    return total if 1 <= total <= 1440 else None


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _span(total: int) -> str:
    hours, minutes = divmod(total, 60)
    parts = ([_plural(hours, "hour")] if hours else []) + ([_plural(minutes, "minute")] if minutes else [])
    return " ".join(parts)


def parse(text: str) -> Command | None:
    """The command the text names, or None (see the module docstring)."""
    said = " ".join(text.lower().split()).rstrip(".!")
    match = re.fullmatch(r"(?:set )?(?:the )?volume (?:to )?(\d{1,3}) ?%?", said)
    if match and int(match.group(1)) <= 150:
        percent = int(match.group(1))
        return Command(f"Set the volume to {percent}%", "audio-volume-medium", "set_volume", {"percent": percent})
    if said in ("mute", "mute sound", "mute the sound", "unmute", "unmute sound", "unmute the sound"):
        mute = not said.startswith("unmute")
        return Command("Mute the sound" if mute else "Unmute the sound",
                       "audio-volume-muted" if mute else "audio-volume-high", "set_volume", {"mute": mute})
    match = re.fullmatch(r"(?:set )?(?:the )?(?:screen )?brightness (?:to )?(\d{1,3}) ?%?", said)
    if match and 1 <= int(match.group(1)) <= 100:
        percent = int(match.group(1))
        return Command(f"Set the screen brightness to {percent}%", "brightness-high", "set_brightness",
                       {"percent": percent})
    match = re.fullmatch(r"(?:switch to |turn on |use )?(dark|light) (?:mode|theme)", said)
    if match:
        dark = match.group(1) == "dark"
        return Command("Switch to dark mode" if dark else "Switch to light mode", "color-management",
                       "set_color_scheme", {"scheme": "BreezeDark" if dark else "BreezeLight"})
    match = (re.fullmatch(r"(?:turn )?night ?light (on|off)", said)
             or re.fullmatch(r"turn (on|off) (?:the )?night ?light", said))
    if match:
        on = match.group(1) == "on"
        return Command(f"Turn night light {'on' if on else 'off'}", "redshift-status-on" if on else "redshift-status-off",
                       "set_night_light", {"enabled": on})
    match = (re.fullmatch(r"(?:turn )?(wi-?fi|bluetooth) (on|off)", said)
             or re.fullmatch(r"turn (on|off) (?:the )?(wi-?fi|bluetooth)", said))
    if match:
        words = match.groups()
        radio_word, state = (words[0], words[1]) if words[0] not in ("on", "off") else (words[1], words[0])
        radio = "bluetooth" if radio_word == "bluetooth" else "wifi"
        name = "Bluetooth" if radio == "bluetooth" else "Wi-Fi"
        return Command(f"Turn {name} {state}", "network-bluetooth" if radio == "bluetooth" else "network-wireless",
                       "set_radio", {"radio": radio, "enabled": state == "on"})
    match = re.fullmatch(r"(?:set )?(?:an )?alarm (?:at |for )?([01]?\d|2[0-3]):([0-5]\d)", said)
    if match:
        when = f"{int(match.group(1)):02d}:{match.group(2)}"
        return Command(f"Set an alarm for {when}", "appointment-soon", "set_reminder",
                       {"text": f"Your alarm for {when}", "at": when, "kind": "alarm"})
    match = (re.fullmatch(r"(?:set )?(?:an? )?timer (?:for )?" + _DURATION, said)
             or re.fullmatch(r"(?:set )?(?:an? )?" + _DURATION + r" timer", said))
    if match:
        total = _minutes(*match.groups())
        if total:
            return Command(f"Start a timer for {_span(total)}", "chronometer", "set_reminder",
                           {"text": f"Time is up: your timer for {_span(total)}", "in_minutes": total, "kind": "alarm"})
    if said in ("lock", "lock screen", "lock the screen", "lock computer", "lock the computer"):
        return Command("Lock the screen", "system-lock-screen", "session_action", {"action": "lock"})
    match = re.fullmatch(r"(?:do not disturb|dnd)(?: (off|on|(?:for )?" + _DURATION + r"))?", said)
    if match:
        if match.group(1) == "off":
            return Command("Turn Do Not Disturb off", "notifications", "do_not_disturb", {"off": True})
        total = _minutes(match.group(2), match.group(3)) if match.group(1) not in (None, "on") else 60
        if total:
            return Command(f"Do Not Disturb for {_span(total)}", "notifications-disabled", "do_not_disturb",
                           {"minutes": total})
    return None


def match(text: str) -> list[dict[str, Any]]:
    """The quick result for a command in ``text``: a list of one, or empty."""
    command = parse(text)
    if command is None:
        return []
    return [{"kind": "quick", "title": command.title, "subtitle": SUBTITLE, "icon": command.icon,
             "action": {"type": "command", "target": " ".join(text.split())}}]


def run(text: str, agent_settings: dict[str, Any] | None, runtime_dir: Path) -> str:
    """Carry out the command in ``text``; returns the tool's report or raises ``CommandError``."""
    from .permissions import append_audit
    from .tools.catalog import builtin_tools
    from .tools.registry import RISK_DANGER, ToolRegistry

    command = parse(text)
    if command is None:
        raise CommandError("that is not a command Happy Bot knows")
    registry = ToolRegistry(builtin_tools(agent_settings))
    if registry.get(command.tool) is None:
        raise CommandError("the tools for this are switched off in Happy Bot's settings")
    risk, summary, detail = registry.assess(command.tool, command.arguments)
    if risk == RISK_DANGER:
        raise CommandError(f"'{summary}' needs your approval ({detail}); ask Happy Bot instead")
    impossible = registry.precheck(command.tool, command.arguments)
    ok, report = (False, impossible) if impossible else registry.run(command.tool, command.arguments)
    append_audit(runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": command.tool, "risk": risk,
                               "outcome": "ran from the search bar" if ok else "failed from the search bar",
                               "arguments": str(command.arguments)[:2000]})
    if not ok:
        raise CommandError(report)
    show_on_screen(command.icon, command.title)
    return report


def show_on_screen(icon: str, text: str) -> None:
    """Plasma's on-screen display shows ``text`` for a moment; does nothing if it cannot."""
    from . import session_dbus

    try:
        session_dbus.call("org.kde.plasmashell", "/org/kde/osdService", "org.kde.osdService", "showText", "ss",
                          (icon, text))
    except (session_dbus.DBusUnavailable, session_dbus.DBusError):
        pass

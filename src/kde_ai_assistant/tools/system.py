"""Desktop and system control tools: sound, media, network, displays, appearance,
settings, clipboard, notifications, session actions and generic DBus calls.

Each tool wraps the command-line program the desktop already ships for that
job (``wpctl``, ``nmcli``, ``bluetoothctl``, ``kscreen-doctor``,
``plasma-apply-colorscheme``, ``kwriteconfig6``, ``notify-send``, ``qdbus6``,
``busctl``, ``loginctl``, ``systemctl``) and runs it as the user with a
timeout. A missing program is reported as a tool failure that names it.

Risk: everything here is ``change`` except

- the read tools (volume, Wi-Fi list, display list, colour scheme list);
- ``session_action`` for logout, restart and shutdown, which are ``danger``
  because open applications lose unsaved work;
- ``dbus_call`` on the system bus with a method that is not an obvious query,
  which is ``danger`` because system services can change the OS;
- ``write_kde_setting`` aimed at a system path.

``configure_displays`` refuses a request that would leave no display enabled.

Changes to the volume, colour scheme, a KDE setting and the clipboard record
the previous value in ``undo_journal`` so they can be undone
(``tools/undo.py``).
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from .. import undo_journal
from ..desktop_context import run_command
from ..shell_risk import SYSTEM_PATHS
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

SINK = "@DEFAULT_AUDIO_SINK@"
MEDIA_ACTIONS = {"play_pause": "PlayPause", "play": "Play", "pause": "Pause", "stop": "Stop",
                 "next": "Next", "previous": "Previous"}
SESSION_ACTIONS = ("lock", "suspend", "logout", "restart", "shutdown")
_QUERY_METHOD = re.compile(r"^(Get|List|Is|Has|Can|Introspect|Ping|Describe|Enumerate|Find|Lookup|Query|Status)")


def _run(command: list[str], timeout: float = 20.0) -> str:
    """Run a program; return stdout, or raise ``ToolFailure`` with its error."""
    if not shutil.which(command[0]):
        raise ToolFailure(f"the '{command[0]}' command is not installed")
    result = run_command(command, timeout=timeout)
    if not result["ok"]:
        raise ToolFailure((result["stderr"] or result["stdout"]).strip() or f"{command[0]} failed")
    return result["stdout"].strip()


def _text(arguments: dict[str, Any], name: str, required: bool = True) -> str:
    value = arguments.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ToolFailure(f"'{name}' is required and must be text")
    return value


def volume_state() -> tuple[int | None, bool]:
    """The output volume in percent (None if unreadable) and whether it is muted."""
    output = _run(["wpctl", "get-volume", SINK])
    match = re.search(r"([0-9.]+)", output)
    return (round(float(match.group(1)) * 100) if match else None), "MUTED" in output


def get_volume(arguments: dict[str, Any]) -> str:
    percent, muted = volume_state()
    return f"Volume {percent}%" + (", muted" if muted else "")


def set_volume(arguments: dict[str, Any]) -> str:
    percent, mute = arguments.get("percent"), arguments.get("mute")
    if percent is None and mute is None:
        raise ToolFailure("give 'percent' (0 to 150), 'mute' (true or false), or both")
    if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float))
                                or not 0 <= percent <= 150):
        raise ToolFailure("'percent' must be a number from 0 to 150")
    if mute is not None and not isinstance(mute, bool):
        raise ToolFailure("'mute' must be true or false")
    previous, was_muted = volume_state()
    if percent is not None:
        _run(["wpctl", "set-volume", SINK, f"{percent / 100:.2f}"])
    if mute is not None:
        _run(["wpctl", "set-mute", SINK, "1" if mute else "0"])
    if previous is not None:
        undo_journal.record("volume", f"Changed the volume from {previous}%{' (muted)' if was_muted else ''}",
                            {"percent": previous, "mute": was_muted})
    return get_volume({})


def media_control(arguments: dict[str, Any]) -> str:
    action = arguments.get("action")
    if action not in MEDIA_ACTIONS:
        raise ToolFailure(f"'action' must be one of: {', '.join(MEDIA_ACTIONS)}")
    names = [line.split()[0] for line in _run(["busctl", "--user", "list", "--no-legend"]).splitlines()
             if line.startswith("org.mpris.MediaPlayer2.")]
    if not names:
        raise ToolFailure("no media player is running")
    wanted = _text(arguments, "player", required=False).lower()
    chosen = [name for name in names if wanted in name.lower()] if wanted else names[:1]
    if not chosen:
        raise ToolFailure(f"no running player matches '{wanted}'. Running: {', '.join(names)}")
    _run(["busctl", "--user", "call", chosen[0], "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
          MEDIA_ACTIONS[action]])
    return f"Sent {action} to {chosen[0].removeprefix('org.mpris.MediaPlayer2.')}."


def list_wifi_networks(arguments: dict[str, Any]) -> str:
    if _run(["nmcli", "-t", "-f", "WIFI", "radio"]) != "enabled":
        return "Wi-Fi is turned off. Use set_radio to turn it on."
    rows = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"], timeout=30.0)
    lines = []
    for row in rows.splitlines():
        in_use, ssid, signal, security = (row.replace("\\:", "\x00").split(":") + ["", "", "", ""])[:4]
        if ssid:
            lines.append(f"{'* ' if in_use.strip() else '  '}{ssid.replace(chr(0), ':')}  signal {signal}%  {security or 'open'}")
    return "\n".join(lines) or "No Wi-Fi networks are in range."


def connect_wifi(arguments: dict[str, Any]) -> str:
    ssid = _text(arguments, "ssid")
    command = ["nmcli", "device", "wifi", "connect", ssid]
    password = _text(arguments, "password", required=False)
    if password:
        command += ["password", password]
    return _run(command, timeout=60.0) or f"Connected to {ssid}."


def set_radio(arguments: dict[str, Any]) -> str:
    radio, enabled = arguments.get("radio"), arguments.get("enabled")
    if radio not in ("wifi", "bluetooth") or not isinstance(enabled, bool):
        raise ToolFailure("'radio' must be 'wifi' or 'bluetooth' and 'enabled' true or false")
    if radio == "wifi":
        _run(["nmcli", "radio", "wifi", "on" if enabled else "off"])
    else:
        _run(["bluetoothctl", "power", "on" if enabled else "off"])
    return f"{'Wi-Fi' if radio == 'wifi' else 'Bluetooth'} turned {'on' if enabled else 'off'}."


def _outputs() -> list[dict[str, Any]]:
    try:
        return json.loads(_run(["kscreen-doctor", "-j"]))["outputs"]
    except (ValueError, KeyError) as error:
        raise ToolFailure(f"could not read the display configuration: {error}") from error


def list_displays(arguments: dict[str, Any]) -> str:
    lines = []
    for output in _outputs():
        if not output.get("connected"):
            continue
        size = output.get("size") or {}
        lines.append(f"{output['name']}: {'on' if output.get('enabled') else 'off'}, "
                     f"{size.get('width', '?')}x{size.get('height', '?')}, scale {output.get('scale', 1)}"
                     + (", primary" if output.get("priority") == 1 else ""))
    return "\n".join(lines) or "No displays are connected."


def configure_displays(arguments: dict[str, Any]) -> str:
    enable, disable = arguments.get("enable") or [], arguments.get("disable") or []
    if not isinstance(enable, list) or not isinstance(disable, list) or not (enable or disable):
        raise ToolFailure("give 'enable' and/or 'disable' as lists of display names from list_displays")
    connected = {output["name"]: bool(output.get("enabled")) for output in _outputs() if output.get("connected")}
    unknown = [name for name in [*enable, *disable] if name not in connected]
    if unknown:
        raise ToolFailure(f"unknown display {unknown[0]!r}. Connected: {', '.join(connected)}")
    after = {name: (name in enable) or (state and name not in disable) for name, state in connected.items()}
    if not any(after.values()):
        raise ToolFailure("that would turn every display off; at least one must stay on")
    _run(["kscreen-doctor", *[f"output.{name}.enable" for name in enable],
          *[f"output.{name}.disable" for name in disable if name not in enable]], timeout=30.0)
    return "Displays now: " + ", ".join(f"{name} {'on' if state else 'off'}" for name, state in after.items())


def _color_schemes() -> tuple[list[str], str]:
    names, current = [], ""
    for line in _run(["plasma-apply-colorscheme", "--list-schemes"]).splitlines():
        match = re.match(r"^\s*\*\s+(\S+)(.*)$", line)
        if match:
            names.append(match.group(1))
            if "current" in match.group(2):
                current = match.group(1)
    return names, current


def list_color_schemes(arguments: dict[str, Any]) -> str:
    names, current = _color_schemes()
    return f"Current: {current}\nAvailable: {', '.join(names)}"


def set_color_scheme(arguments: dict[str, Any]) -> str:
    wanted = _text(arguments, "scheme").strip()
    names, current = _color_schemes()
    matches = [name for name in names if name.lower() == wanted.lower()]
    if not matches:
        raise ToolFailure(f"no colour scheme named '{wanted}'. Available: {', '.join(names)}")
    if matches[0] == current:
        return f"The colour scheme is already {current}."
    _run(["plasma-apply-colorscheme", matches[0]])
    undo_journal.record("color_scheme", f"Changed the colour scheme from {current} to {matches[0]}", {"scheme": current})
    return f"Colour scheme changed from {current} to {matches[0]}."


def classify_kde_setting(arguments: dict[str, Any]) -> tuple[str, str]:
    target = str(arguments.get("file") or "")
    if target.startswith("/") and any(target == root or target.startswith(root + "/") for root in SYSTEM_PATHS):
        return RISK_DANGER, f"{target} is a system location"
    return RISK_CHANGE, ""


def write_kde_setting(arguments: dict[str, Any]) -> str:
    file, group, key = (_text(arguments, name) for name in ("file", "group", "key"))
    value = arguments.get("value")
    if not isinstance(value, (str, int, float, bool)):
        raise ToolFailure("'value' is required")
    text = str(value).lower() if isinstance(value, bool) else str(value)
    previous = read_kde_value(file, group, key)
    _run(["kwriteconfig6", "--file", file, "--group", group, "--key", key, text])
    undo_journal.record("kde_setting", f"Set [{group}] {key} in {file}",
                        {"file": file, "group": group, "key": key, "previous": previous})
    return f"Set [{group}] {key} = {text} in {file}. Some applications apply it only after a restart."


_UNSET = "\x00unset\x00"


def read_kde_value(file: str, group: str, key: str) -> str | None:
    """A KDE setting's current value, or None when it is not set (or cannot be read)."""
    if not shutil.which("kreadconfig6"):
        return None
    result = run_command(["kreadconfig6", "--file", file, "--group", group, "--key", key, "--default", _UNSET], timeout=5)
    value = result["stdout"].rstrip("\n") if result["ok"] else _UNSET
    return None if value == _UNSET else value


def set_clipboard(arguments: dict[str, Any]) -> str:
    text = _text(arguments, "text")
    previous = run_command(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardContents"],
                           timeout=5) if shutil.which("qdbus6") else {"ok": False}
    _run(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", text])
    if previous["ok"]:
        undo_journal.record("clipboard", "Replaced the clipboard", {"text": previous["stdout"].rstrip("\n")})
    return f"Clipboard set ({len(text)} characters)."


def send_notification(arguments: dict[str, Any]) -> str:
    title = _text(arguments, "title")
    _run(["notify-send", "--app-name=AI Assistant", "--", title, _text(arguments, "body", required=False)])
    return "Notification shown."


def classify_session(arguments: dict[str, Any]) -> tuple[str, str]:
    action = arguments.get("action")
    if action in ("logout", "restart", "shutdown"):
        return RISK_DANGER, "open applications will close and may lose unsaved work"
    return RISK_CHANGE, ""


def session_action(arguments: dict[str, Any]) -> str:
    action = arguments.get("action")
    if action not in SESSION_ACTIONS:
        raise ToolFailure(f"'action' must be one of: {', '.join(SESSION_ACTIONS)}")
    if action == "lock":
        _run(["loginctl", "lock-session"])
    elif action == "suspend":
        _run(["systemctl", "suspend"])
    else:
        method = {"logout": "logout", "restart": "logoutAndReboot", "shutdown": "logoutAndShutdown"}[action]
        _run(["qdbus6", "org.kde.Shutdown", "/Shutdown", f"org.kde.Shutdown.{method}"])
    return f"Requested: {action}."


def classify_dbus(arguments: dict[str, Any]) -> tuple[str, str]:
    method = str(arguments.get("method") or "").rsplit(".", 1)[-1]
    if arguments.get("bus") == "system" and not _QUERY_METHOD.match(method):
        return RISK_DANGER, "calls a system service, which can change the operating system"
    return RISK_CHANGE, ""


def dbus_call(arguments: dict[str, Any]) -> str:
    bus = arguments.get("bus", "session")
    if bus not in ("session", "system"):
        raise ToolFailure("'bus' must be 'session' or 'system'")
    service, path, method = (_text(arguments, name) for name in ("service", "path", "method"))
    values = arguments.get("arguments") or []
    if not isinstance(values, list):
        raise ToolFailure("'arguments' must be a list")
    command = ["qdbus6", *(["--system"] if bus == "system" else []), service, path, method,
               *[str(value).lower() if isinstance(value, bool) else str(value) for value in values]]
    return _run(command) or "(the call returned nothing)"


def system_tools() -> list[Tool]:
    text = {"type": "string"}
    names = {"type": "array", "items": {"type": "string"}}

    def change(name, description, schema, handler, summary, classify=None) -> Tool:
        return Tool(name, description, schema, RISK_CHANGE, handler, classify=classify, summarize=summary)

    return [
        Tool("get_volume", "Current output volume and whether sound is muted.", object_schema(), RISK_READ, get_volume),
        change("set_volume", "Set the output volume in percent and/or mute or unmute sound.",
               object_schema({"percent": {"type": "number", "description": "0 to 150"}, "mute": {"type": "boolean"}}),
               set_volume, lambda a: f"Set volume {a.get('percent', '')} mute={a.get('mute', '')}".strip()),
        change("media_control", "Control the running media player: play_pause, play, pause, stop, next, previous.",
               object_schema({"action": {"type": "string", "enum": list(MEDIA_ACTIONS)},
                              "player": {"type": "string", "description": "Part of the player name, if several run"}},
                             ["action"]), media_control, lambda a: f"Media: {a.get('action', '')}"),
        Tool("list_wifi_networks", "Wi-Fi networks in range with signal and security; the connected one is starred.",
             object_schema(), RISK_READ, list_wifi_networks),
        change("connect_wifi", "Connect to a Wi-Fi network by name. Give the password only for a network that "
               "has not been used before.", object_schema({"ssid": text, "password": text}, ["ssid"]),
               connect_wifi, lambda a: f"Connect to Wi-Fi {a.get('ssid', '')}"),
        change("set_radio", "Turn Wi-Fi or Bluetooth on or off.",
               object_schema({"radio": {"type": "string", "enum": ["wifi", "bluetooth"]}, "enabled": {"type": "boolean"}},
                             ["radio", "enabled"]), set_radio,
               lambda a: f"Turn {a.get('radio', '')} {'on' if a.get('enabled') else 'off'}"),
        Tool("list_displays", "Connected displays: name, on or off, resolution, scale, which is primary.",
             object_schema(), RISK_READ, list_displays),
        change("configure_displays", "Turn displays on or off by name. To use only an external monitor, enable it "
               "and disable the others.", object_schema({"enable": names, "disable": names}), configure_displays,
               lambda a: f"Displays: enable {a.get('enable') or []}, disable {a.get('disable') or []}"),
        Tool("list_color_schemes", "The current Plasma colour scheme and the installed ones.", object_schema(),
             RISK_READ, list_color_schemes),
        change("set_color_scheme", "Switch the Plasma colour scheme, for example BreezeDark for dark mode or "
               "BreezeLight for light mode.", object_schema({"scheme": text}, ["scheme"]), set_color_scheme,
               lambda a: f"Colour scheme {a.get('scheme', '')}"),
        change("write_kde_setting", "Write one KDE configuration value (kwriteconfig6). Read it first with "
               "read_kde_setting.", object_schema({"file": text, "group": text, "key": text,
                                                   "value": {"type": ["string", "number", "boolean"]}},
                                                  ["file", "group", "key", "value"]), write_kde_setting,
               lambda a: f"Set {a.get('file', '')} [{a.get('group', '')}] {a.get('key', '')} = {a.get('value', '')}",
               classify_kde_setting),
        change("set_clipboard", "Put text on the clipboard.", object_schema({"text": text}, ["text"]), set_clipboard,
               lambda a: f"Set clipboard ({len(str(a.get('text', '')))} characters)"),
        change("send_notification", "Show a desktop notification.", object_schema({"title": text, "body": text}, ["title"]),
               send_notification, lambda a: f"Notify: {a.get('title', '')}"),
        change("session_action", "Lock the screen, suspend, log out, restart or shut down the computer.",
               object_schema({"action": {"type": "string", "enum": list(SESSION_ACTIONS)}}, ["action"]), session_action,
               lambda a: f"Session: {a.get('action', '')}", classify_session),
        change("dbus_call", "Call a DBus method on the session or system bus (via qdbus6), for desktop features no "
               "other tool covers. 'method' is the full name, for example org.kde.KWin.showDesktop.",
               object_schema({"bus": {"type": "string", "enum": ["session", "system"]}, "service": text, "path": text,
                              "method": text, "arguments": {"type": "array", "items": {}}}, ["service", "path", "method"]),
               dbus_call, lambda a: f"DBus {a.get('bus', 'session')}: {a.get('service', '')} {a.get('method', '')}",
               classify_dbus),
    ]

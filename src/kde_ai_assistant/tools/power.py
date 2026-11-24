"""Screen and power tools: brightness, power profile, night light, Do Not Disturb, battery.

- Brightness goes through PowerDevil's DBus interface
  (``org.kde.Solid.PowerManagement``), the same one the brightness slider
  uses; a computer without a controllable screen reports that.
- The power profile uses ``powerprofilesctl`` (power-profiles-daemon).
- Night light is KWin's Night Color: the ``kwinrc`` setting plus a KWin
  reconfigure, as System Settings does.
- Do Not Disturb uses the notification server's standard ``Inhibit`` call.
  The daemon holds the inhibition (it lasts while the daemon's DBus
  connection does) and lifts it at the chosen end time with a timer;
  ``_dnd`` keeps the cookie and timer, guarded by ``_dnd_lock``.
- Battery comes from ``upower``.

Changes record the previous value in ``undo_journal`` (kinds
``brightness``, ``power_profile``, ``night_light``) so they can be undone
(``tools/undo.py``). All of them are ``change``; reading is ``read``.
"""

from __future__ import annotations

import re
import shutil
import threading
from typing import Any

from .. import session_dbus, undo_journal
from ..desktop_context import run_command
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

BRIGHTNESS_SERVICE = "org.kde.Solid.PowerManagement"
BRIGHTNESS_PATH = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
BRIGHTNESS_INTERFACE = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"
NOTIFICATIONS = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications")
_dnd: dict[str, Any] = {"cookie": None, "timer": None}
_dnd_lock = threading.Lock()


def run_checked(command: list[str], timeout: float = 20.0) -> str:
    """Run a program; return its output, or raise ``ToolFailure`` naming what went wrong."""
    if not shutil.which(command[0]):
        raise ToolFailure(f"the '{command[0]}' command is not installed")
    result = run_command(command, timeout=timeout)
    if not result["ok"]:
        raise ToolFailure((result["stderr"] or result["stdout"]).strip() or f"{command[0]} failed")
    return result["stdout"].strip()


def _brightness_call(method: str, signature: str = "", arguments: tuple = ()) -> Any:
    try:
        reply = session_dbus.call(BRIGHTNESS_SERVICE, BRIGHTNESS_PATH, BRIGHTNESS_INTERFACE, method, signature, arguments)
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"screen brightness cannot be controlled here ({error})") from error
    return reply[0] if reply else None


def brightness_percent() -> int:
    maximum = _brightness_call("brightnessMax") or 0
    if maximum <= 0:
        raise ToolFailure("this screen's brightness cannot be controlled")
    return round(_brightness_call("brightness") * 100 / maximum)


def get_brightness(arguments: dict[str, Any]) -> str:
    return f"Screen brightness {brightness_percent()}%."


def set_brightness(arguments: dict[str, Any]) -> str:
    percent = arguments.get("percent")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 1 <= percent <= 100:
        raise ToolFailure("'percent' must be a number from 1 to 100")
    previous = brightness_percent()
    maximum = _brightness_call("brightnessMax")
    _brightness_call("setBrightness", "i", (round(maximum * percent / 100),))
    undo_journal.record("brightness", f"Changed the screen brightness from {previous}%", {"percent": previous})
    return f"Screen brightness set to {round(percent)}%."


def get_power_profile(arguments: dict[str, Any]) -> str:
    current = run_checked(["powerprofilesctl", "get"])
    profiles = re.findall(r"^\*?\s*([a-z-]+):\s*$", run_checked(["powerprofilesctl", "list"]), re.M)
    return f"Power profile: {current}. Available: {', '.join(profiles)}."


def set_power_profile(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("profile") or "").strip()
    if wanted not in ("power-saver", "balanced", "performance"):
        raise ToolFailure("'profile' must be power-saver, balanced or performance")
    previous = run_checked(["powerprofilesctl", "get"])
    run_checked(["powerprofilesctl", "set", wanted])
    undo_journal.record("power_profile", f"Changed the power profile from {previous}", {"profile": previous})
    return f"Power profile set to {wanted}."


def night_light_enabled() -> bool:
    try:
        state = session_dbus.properties("org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight")
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"night light is not available ({error})") from error
    return bool(state.get("enabled"))


def apply_night_light(enabled: bool) -> None:
    run_checked(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor", "--key", "Active", str(enabled).lower()])
    run_checked(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])


def set_night_light(arguments: dict[str, Any]) -> str:
    enabled = arguments.get("enabled")
    if not isinstance(enabled, bool):
        raise ToolFailure("'enabled' must be true or false")
    previous = night_light_enabled()
    apply_night_light(enabled)
    if previous != enabled:
        undo_journal.record("night_light", f"Turned night light {'on' if enabled else 'off'}", {"enabled": previous})
    return f"Night light is {'on' if enabled else 'off'}."


def _end_dnd() -> None:
    with _dnd_lock:
        cookie, _dnd["cookie"] = _dnd["cookie"], None
        if _dnd["timer"] is not None:
            _dnd["timer"].cancel()
            _dnd["timer"] = None
    if cookie is not None:
        try:
            session_dbus.call(*NOTIFICATIONS, "UnInhibit", "u", (cookie,))
        except (session_dbus.DBusUnavailable, session_dbus.DBusError):
            pass


def do_not_disturb(arguments: dict[str, Any]) -> str:
    minutes = arguments.get("minutes")
    if minutes == 0 or arguments.get("off") is True:
        _end_dnd()
        return "Do Not Disturb is off; notifications show again."
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 1440:
        raise ToolFailure("'minutes' must be a number from 1 to 1440, or 0 to turn Do Not Disturb off")
    _end_dnd()
    try:
        cookie = session_dbus.call(*NOTIFICATIONS, "Inhibit", "ssa{sv}", ("kde-ai-assistant", "Do Not Disturb", {}))[0]
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"notifications could not be silenced ({error})") from error
    timer = threading.Timer(minutes * 60, _end_dnd)
    timer.daemon = True
    with _dnd_lock:
        _dnd.update(cookie=cookie, timer=timer)
    timer.start()
    return f"Do Not Disturb is on for {round(minutes)} minutes."


def battery_status(arguments: dict[str, Any]) -> str:
    devices = [line.strip() for line in run_checked(["upower", "-e"]).splitlines() if "battery_" in line]
    if not devices:
        return "This computer has no battery."
    lines = []
    for device in devices:
        info = run_checked(["upower", "-i", device])
        fields = {key.strip(): value.strip() for key, _, value in
                  (line.partition(":") for line in info.splitlines()) if value}
        lines.append(f"{fields.get('model', device.rsplit('/', 1)[-1])}: {fields.get('percentage', '?')}, "
                     f"{fields.get('state', '?')}, health {fields.get('capacity', '?')}"
                     + (f", {fields['time to empty']} left" if "time to empty" in fields else ""))
    return "\n".join(lines)


def power_tools() -> list[Tool]:
    return [
        Tool("get_brightness", "The screen brightness in percent.", object_schema(), RISK_READ, get_brightness,
             summarize=lambda a: "Check the screen brightness"),
        Tool("set_brightness", "Set the screen brightness in percent.",
             object_schema({"percent": {"type": "number"}}, ["percent"]), RISK_CHANGE, set_brightness,
             summarize=lambda a: f"Set the brightness to {a.get('percent', '?')}%"),
        Tool("get_power_profile", "The power profile (power-saver, balanced, performance) and the ones available.",
             object_schema(), RISK_READ, get_power_profile, summarize=lambda a: "Check the power profile"),
        Tool("set_power_profile", "Switch the power profile.",
             object_schema({"profile": {"type": "string", "enum": ["power-saver", "balanced", "performance"]}},
                           ["profile"]), RISK_CHANGE, set_power_profile,
             summarize=lambda a: f"Switch to the {a.get('profile', '?')} power profile"),
        Tool("set_night_light", "Turn night light (warmer screen colours in the evening) on or off.",
             object_schema({"enabled": {"type": "boolean"}}, ["enabled"]), RISK_CHANGE, set_night_light,
             summarize=lambda a: f"Turn night light {'on' if a.get('enabled') else 'off'}"),
        Tool("do_not_disturb", "Silence notifications for some minutes ('quiet until 3pm': work out the minutes), "
             "or turn Do Not Disturb off with minutes 0.",
             object_schema({"minutes": {"type": "number"}}, ["minutes"]), RISK_CHANGE, do_not_disturb,
             summarize=lambda a: "Turn Do Not Disturb off" if a.get("minutes") == 0
             else f"Do Not Disturb for {a.get('minutes', '?')} minutes"),
        Tool("battery_status", "Battery charge, whether it is charging, its health and the time left.",
             object_schema(), RISK_READ, battery_status, summarize=lambda a: "Check the battery"),
    ]

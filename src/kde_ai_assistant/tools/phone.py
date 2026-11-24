"""Phone tools through KDE Connect: find, ring, battery, notifications, sending files, text and SMS.

KDE Connect is the desktop's own link to the user's paired phones and other
devices. Device state (type, battery) is read from its daemon over the
session DBus (``session_dbus``, service ``org.kde.kdeconnect.daemon``);
actions go through ``kdeconnect-cli``, which ships with it.

A device is chosen by the ``device`` argument (part of its name). Without
one, the only reachable paired device whose type is ``phone`` is used; when
there is none or more than one, the tool fails and lists them.

Risk: reading (devices, battery, notifications) is ``read``; ringing,
pinging and sending a file or text to the user's own device are ``change``.
``send_sms`` is ``danger``: it sends a message to another person, which
cannot be taken back, so the user always sees and approves it. This is a
deliberate addition to the narrow ``danger`` definition in docs/ROADMAP.md,
recorded there.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from .. import session_dbus
from ..desktop_context import run_command
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

SERVICE = "org.kde.kdeconnect.daemon"
DEVICE_PATH = "/modules/kdeconnect/devices/{}"


def _cli(arguments: list[str], timeout: float = 30.0) -> str:
    if not shutil.which("kdeconnect-cli"):
        raise ToolFailure("KDE Connect is not installed (kdeconnect-cli is missing)")
    result = run_command(["kdeconnect-cli", *arguments], timeout=timeout)
    if not result["ok"]:
        raise ToolFailure((result["stderr"] or result["stdout"]).strip() or "kdeconnect-cli failed")
    return result["stdout"]


def _device_info(device_id: str) -> dict[str, Any]:
    info: dict[str, Any] = {"id": device_id}
    try:
        state = session_dbus.properties(SERVICE, DEVICE_PATH.format(device_id), "org.kde.kdeconnect.device")
        info.update(name=state.get("name", device_id), type=state.get("type", "?"))
    except (session_dbus.DBusUnavailable, session_dbus.DBusError):
        info.update(name=device_id, type="?")
    try:
        battery = session_dbus.properties(SERVICE, DEVICE_PATH.format(device_id) + "/battery",
                                          "org.kde.kdeconnect.device.battery")
        if battery.get("hasBattery"):
            info["battery"] = f"{battery.get('charge')}%" + (", charging" if battery.get("isCharging") else "")
    except (session_dbus.DBusUnavailable, session_dbus.DBusError):
        pass
    return info


def available_devices() -> list[dict[str, Any]]:
    """Paired, reachable devices with their name, type and battery when known."""
    devices = []
    for line in _cli(["--list-available", "--id-name-only"]).splitlines():
        device_id, _, name = line.strip().partition(" ")
        if re.fullmatch(r"[0-9a-fA-F_]{8,}", device_id or ""):
            info = _device_info(device_id)
            info["name"] = info.get("name") if info.get("name") != device_id else name
            devices.append(info)
    return devices


def _describe(device: dict[str, Any]) -> str:
    battery = f", battery {device['battery']}" if device.get("battery") else ""
    return f"{device['name']} ({device['type']}{battery})"


def choose_device(arguments: dict[str, Any]) -> dict[str, Any]:
    devices = available_devices()
    if not devices:
        raise ToolFailure("no paired device is reachable. Check that KDE Connect is running on the phone and both "
                          "are on the same network.")
    wanted = str(arguments.get("device") or "").strip().lower()
    found = [device for device in devices if wanted in device["name"].lower()] if wanted \
        else [device for device in devices if device["type"] == "phone"]
    if len(found) != 1:
        listing = ", ".join(_describe(device) for device in devices)
        problem = (f"no reachable device matches '{wanted}'" if wanted else "no reachable phone") if not found \
            else f"{len(found)} devices match"
        raise ToolFailure(f"{problem}. Reachable: {listing}. Name one with 'device'.")
    return found[0]


def list_devices(arguments: dict[str, Any]) -> str:
    devices = available_devices()
    return "\n".join(_describe(device) for device in devices) if devices else "No paired device is reachable."


def ring_phone(arguments: dict[str, Any]) -> str:
    device = choose_device(arguments)
    _cli(["--device", device["id"], "--ring"])
    return f"Ringing {device['name']}."


def ping_device(arguments: dict[str, Any]) -> str:
    device = choose_device(arguments)
    message = str(arguments.get("message") or "").strip()
    _cli(["--device", device["id"], *(["--ping-msg", message] if message else ["--ping"])])
    return f"Sent a ping to {device['name']}."


def send_to_device(arguments: dict[str, Any]) -> str:
    device = choose_device(arguments)
    text, location = arguments.get("text"), arguments.get("file_or_url")
    if bool(text) == bool(location):
        raise ToolFailure("give exactly one of 'text' or 'file_or_url'")
    if location:
        location = str(location)
        if not re.match(r"^[a-z]+://", location):
            location = os.path.abspath(os.path.expanduser(location))
            if not os.path.exists(location):
                raise ToolFailure(f"{location} does not exist")
        _cli(["--device", device["id"], "--share", location], timeout=120)
        return f"Sent {location} to {device['name']}."
    _cli(["--device", device["id"], "--share-text", str(text)])
    return f"Sent the text to {device['name']}."


def phone_notifications(arguments: dict[str, Any]) -> str:
    device = choose_device(arguments)
    output = _cli(["--device", device["id"], "--list-notifications"]).strip()
    return output or f"{device['name']} shows no notifications."


def send_sms(arguments: dict[str, Any]) -> str:
    number = str(arguments.get("phone_number") or "").strip()
    message = str(arguments.get("message") or "").strip()
    if not re.fullmatch(r"\+?[0-9 ()-]{3,20}", number):
        raise ToolFailure("'phone_number' must be a phone number")
    if not message:
        raise ToolFailure("'message' is required")
    device = choose_device(arguments)
    _cli(["--device", device["id"], "--send-sms", message, "--destination", number])
    return f"Sent the SMS to {number} through {device['name']}."


def phone_tools() -> list[Tool]:
    device = {"type": "string", "description": "Part of the device's name; default is the one reachable phone"}
    return [
        Tool("list_phone_devices", "The user's paired devices that KDE Connect can reach now, with battery level.",
             object_schema(), RISK_READ, list_devices, summarize=lambda a: "Check connected phones"),
        Tool("ring_phone", "Make the phone ring loudly so the user can find it.", object_schema({"device": device}),
             RISK_CHANGE, ring_phone, summarize=lambda a: "Ring the phone"),
        Tool("ping_device", "Show a short message on the phone.",
             object_schema({"device": device, "message": {"type": "string"}}), RISK_CHANGE, ping_device,
             summarize=lambda a: "Send a ping to the phone"),
        Tool("send_to_device", "Send a file, a web link or some text to the user's phone.",
             object_schema({"device": device, "file_or_url": {"type": "string"}, "text": {"type": "string"}}),
             RISK_CHANGE, send_to_device,
             summarize=lambda a: f"Send {a.get('file_or_url') or 'text'} to the phone"),
        Tool("phone_notifications", "The notifications currently shown on the phone.",
             object_schema({"device": device}), RISK_READ, phone_notifications,
             summarize=lambda a: "Read the phone's notifications"),
        Tool("send_sms", "Send a text message (SMS) from the user's phone to a phone number. The user approves "
             "every message before it is sent.",
             object_schema({"phone_number": {"type": "string"}, "message": {"type": "string"}, "device": device},
                           ["phone_number", "message"]),
             RISK_DANGER, send_sms, classify=lambda a: (RISK_DANGER, "sends a message to another person"),
             summarize=lambda a: f"Send an SMS to {a.get('phone_number', '?')}: {str(a.get('message', ''))[:200]}"),
    ]

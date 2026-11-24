"""Device tools: removable drives, printers, VPN connections and temperatures.

- Drives: ``lsblk --json`` lists them; ``udisksctl`` mounts, unmounts and
  powers off removable ones (USB or card-reader media only: internal SATA
  disks also report "hotplug", and must never be powered off) as the user, through the same polkit rules the
  file manager uses (no root helper).
- Printers: CUPS's ``lpstat``, ``lpoptions -d`` (the user's default printer)
  and ``cancel``.
- VPN: NetworkManager connections of type vpn or wireguard, through ``nmcli``.
- Temperatures: ``sensors -j`` (lm_sensors), summarised per chip.
- Bluetooth: ``bluetoothctl`` lists known devices and connects, disconnects
  or pairs one by name (pairing scans for ten seconds first).

Risk: listing is ``read``; mounting, unmounting, powering off a drive,
choosing the default printer, cancelling a print job and switching a VPN
are ``change`` (nothing on a drive is deleted, and the file manager does the
same without asking).
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema


def _block_devices() -> list[dict[str, Any]]:
    output = run_checked(["lsblk", "--json", "-o", "NAME,PATH,LABEL,SIZE,MOUNTPOINTS,RM,HOTPLUG,TRAN,TYPE,FSTYPE"])
    flat: list[dict[str, Any]] = []

    def walk(devices: list[dict[str, Any]], parent: dict[str, Any] | None) -> None:
        for device in devices:
            # Only USB and card-reader media count. SATA disks report "hotplug"
            # too, and powering off an internal data disk must never happen.
            transport = device.get("tran") or (parent or {}).get("tran") or ""
            device["tran"] = transport
            device["removable"] = transport in ("usb", "mmc") and bool(
                device.get("rm") or device.get("hotplug") or (parent or {}).get("removable"))
            flat.append(device)
            walk(device.get("children") or [], device)

    walk(json.loads(output).get("blockdevices", []), None)
    return flat


def list_drives(arguments: dict[str, Any]) -> str:
    lines = []
    for device in _block_devices():
        if device.get("type") not in ("part", "disk", "crypt") or not (device.get("fstype") or device.get("type") == "disk"):
            continue
        mounts = [point for point in device.get("mountpoints") or [] if point]
        lines.append(f"{device['path']}  {device.get('label') or ''}  {device.get('size')}  "
                     f"{'removable' if device['removable'] else 'internal'}  "
                     + (f"mounted at {', '.join(mounts)}" if mounts else ("not mounted" if device.get("fstype") else "")))
    return "\n".join(lines) or "No drives found."


USER_MEDIA_ROOTS = ("/run/media/", "/media/")


def _removable(path: str) -> dict[str, Any]:
    """The removable drive ``path`` names, refusing any that is part of the system's own setup.

    A drive (or any partition on it) mounted somewhere other than the
    desktop's media folders was mounted on purpose by the system (fstab,
    for example ``/srv/data``) and is refused, whatever its transport says:
    USB disks are also used as permanent storage.
    """
    devices = _block_devices()
    for device in devices:
        if device.get("path") == path or device.get("label") == path:
            if not device["removable"]:
                raise ToolFailure(f"{path} is an internal drive; only removable drives are handled here")
            family = [item for item in devices if item.get("path", "").startswith(device["path"].rstrip("0123456789"))]
            fixed = [point for item in family for point in item.get("mountpoints") or []
                     if point and not point.startswith(USER_MEDIA_ROOTS)]
            if fixed:
                raise ToolFailure(f"{path} is mounted as part of the system's setup ({', '.join(fixed)}), so it is "
                                  "not unmounted or ejected here; the user can do it in a terminal if they mean to")
            return device
    raise ToolFailure(f"no drive {path}. {list_drives({})}")


def drive_action(arguments: dict[str, Any]) -> str:
    action, target = arguments.get("action"), str(arguments.get("drive") or "").strip()
    if action not in ("mount", "unmount", "eject"):
        raise ToolFailure("'action' must be mount, unmount or eject")
    device = _removable(target)
    if action == "mount":
        return run_checked(["udisksctl", "mount", "-b", device["path"]], timeout=60)
    if action == "unmount":
        return run_checked(["udisksctl", "unmount", "-b", device["path"]], timeout=60)
    for child in [item for item in _block_devices() if item.get("path", "").startswith(device["path"])]:
        if any(child.get("mountpoints") or []):
            run_checked(["udisksctl", "unmount", "-b", child["path"]], timeout=60)
    disk = device["path"].rstrip("0123456789").removesuffix("p") if device.get("type") == "part" else device["path"]
    run_checked(["udisksctl", "power-off", "-b", disk], timeout=60)
    return f"{device.get('label') or device['path']} can be unplugged now."


def printers(arguments: dict[str, Any]) -> str:
    if not shutil.which("lpstat"):
        raise ToolFailure("printing (CUPS) is not installed")
    listing = run_command(["lpstat", "-p", "-d"], timeout=10)
    text = (listing["stdout"] + listing["stderr"]).strip()
    if "No destinations added" in text or not text:
        return "No printers are set up. They are added in System Settings, Printers."
    jobs = run_command(["lpstat", "-o"], timeout=10)["stdout"].strip()
    return text + ("\nPrint jobs waiting:\n" + jobs if jobs else "\nNo print jobs are waiting.")


def printer_action(arguments: dict[str, Any]) -> str:
    action = arguments.get("action")
    if action == "set_default":
        name = str(arguments.get("printer") or "").strip()
        if not name:
            raise ToolFailure("'printer' is required")
        run_checked(["lpoptions", "-d", name])
        return f"{name} is now your default printer."
    if action == "cancel_job":
        job = str(arguments.get("job") or "").strip()
        if not job:
            raise ToolFailure("'job' is required: the job id from printers, or 'all'")
        run_checked(["cancel", "-a"] if job == "all" else ["cancel", job])
        return "Cancelled " + ("every print job." if job == "all" else f"print job {job}.")
    raise ToolFailure("'action' must be set_default or cancel_job")


def _vpns() -> list[tuple[str, str, bool]]:
    rows = run_checked(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE", "connection", "show"])
    found = []
    for row in rows.splitlines():
        parts = row.rsplit(":", 2)
        if len(parts) == 3 and parts[1] in ("vpn", "wireguard"):
            found.append((parts[0].replace("\\:", ":"), parts[1], parts[2] == "yes"))
    return found


def vpn_connections(arguments: dict[str, Any]) -> str:
    found = _vpns()
    return "\n".join(f"{name} ({kind}){' connected' if active else ''}" for name, kind, active in found) \
        or "No VPN connections are set up. They are added in System Settings, Wi-Fi & Networking."


def set_vpn(arguments: dict[str, Any]) -> str:
    name, connect = str(arguments.get("name") or "").strip(), arguments.get("connect")
    if not isinstance(connect, bool):
        raise ToolFailure("'connect' must be true or false")
    matches = [vpn for vpn in _vpns() if name.lower() in vpn[0].lower()] if name else _vpns()
    if len(matches) != 1:
        raise ToolFailure(f"say which VPN. {vpn_connections({})}")
    run_checked(["nmcli", "connection", "up" if connect else "down", "id", matches[0][0]], timeout=60)
    return f"{'Connected to' if connect else 'Disconnected from'} {matches[0][0]}."


def _bluetooth_devices() -> list[tuple[str, str, bool]]:
    """``(address, name, connected)`` for every device BlueZ knows (paired or seen)."""
    known = re.findall(r"^Device ([0-9A-F:]{17}) (.+)$", run_checked(["bluetoothctl", "devices"]), re.M)
    connected = {address for address, _ in re.findall(r"^Device ([0-9A-F:]{17}) (.+)$",
                 run_checked(["bluetoothctl", "devices", "Connected"]), re.M)}
    return [(address, name, address in connected) for address, name in known]


def bluetooth_devices(arguments: dict[str, Any]) -> str:
    devices = _bluetooth_devices()
    return "\n".join(f"{name}{' (connected)' if connected else ''}" for _, name, connected in devices) \
        or "No Bluetooth devices are known. Put the device in pairing mode and ask to pair it."


def bluetooth_action(arguments: dict[str, Any]) -> str:
    action, wanted = arguments.get("action"), str(arguments.get("device") or "").strip().lower()
    if action not in ("connect", "disconnect", "pair"):
        raise ToolFailure("'action' must be connect, disconnect or pair")
    if action == "pair":
        run_checked(["bluetoothctl", "--timeout", "10", "scan", "on"], timeout=20)
    matches = [device for device in _bluetooth_devices() if wanted and wanted in device[1].lower()]
    if len(matches) != 1:
        raise ToolFailure(f"say which device ({len(matches)} match '{wanted}'). Known: {bluetooth_devices({})}")
    address, name, _ = matches[0]
    if action == "pair":
        run_checked(["bluetoothctl", "pair", address], timeout=60)
        run_checked(["bluetoothctl", "trust", address], timeout=20)
    output = run_checked(["bluetoothctl", "disconnect" if action == "disconnect" else "connect", address], timeout=40)
    if action != "disconnect" and "successful" not in output.lower():
        raise ToolFailure(f"{name} did not connect: {output.strip()[-300:]}. Is it switched on and nearby?")
    return f"{'Disconnected' if action == 'disconnect' else 'Connected'} {name}."


def temperatures(arguments: dict[str, Any]) -> str:
    data = json.loads(run_checked(["sensors", "-j"]) or "{}")
    lines = []
    for chip, readings in data.items():
        values = [f"{label} {value:.0f}°C" for label, entry in readings.items() if isinstance(entry, dict)
                  for key, value in entry.items() if key.startswith("temp") and key.endswith("_input") and value]
        if values:
            lines.append(f"{chip.split('-')[0]}: {', '.join(values)}")
    return "\n".join(lines) or "No temperature sensors were found."


def device_tools() -> list[Tool]:
    return [
        Tool("list_drives", "Drives and partitions: size, label, removable or internal, where they are mounted.",
             object_schema(), RISK_READ, list_drives, summarize=lambda a: "List drives"),
        Tool("drive_action", "Mount, unmount or safely eject a removable drive (USB stick, external disk).",
             object_schema({"action": {"type": "string", "enum": ["mount", "unmount", "eject"]},
                            "drive": {"type": "string", "description": "Its /dev path or label from list_drives"}},
                           ["action", "drive"]), RISK_CHANGE, drive_action,
             summarize=lambda a: f"{str(a.get('action', '?')).capitalize()} {a.get('drive', '?')}"),
        Tool("printers", "Printers, which is the default, and waiting print jobs.", object_schema(), RISK_READ,
             printers, summarize=lambda a: "List printers"),
        Tool("printer_action", "Make a printer the default, or cancel a print job (or all).",
             object_schema({"action": {"type": "string", "enum": ["set_default", "cancel_job"]},
                            "printer": {"type": "string"}, "job": {"type": "string"}}, ["action"]),
             RISK_CHANGE, printer_action, summarize=lambda a: f"Printer: {a.get('action', '?')}"),
        Tool("vpn_connections", "The VPN connections that are set up and which is connected.", object_schema(),
             RISK_READ, vpn_connections, summarize=lambda a: "List VPN connections"),
        Tool("set_vpn", "Connect or disconnect a VPN.",
             object_schema({"name": {"type": "string"}, "connect": {"type": "boolean"}}, ["connect"]),
             RISK_CHANGE, set_vpn, summarize=lambda a: f"{'Connect' if a.get('connect') else 'Disconnect'} VPN {a.get('name', '')}"),
        Tool("bluetooth_devices", "Bluetooth devices this computer knows and which are connected.", object_schema(),
             RISK_READ, bluetooth_devices, summarize=lambda a: "List Bluetooth devices"),
        Tool("bluetooth_action", "Connect, disconnect or pair a Bluetooth device (headphones, mouse, phone) by name.",
             object_schema({"action": {"type": "string", "enum": ["connect", "disconnect", "pair"]},
                            "device": {"type": "string", "description": "Part of its name"}}, ["action", "device"]),
             RISK_CHANGE, bluetooth_action,
             summarize=lambda a: f"Bluetooth: {a.get('action', '?')} {a.get('device', '?')}"),
        Tool("temperatures", "CPU, GPU, disk and other temperatures.", object_schema(), RISK_READ, temperatures,
             summarize=lambda a: "Check temperatures"),
    ]

"""Writes, lists and removes the systemd user units behind reminders and routines.

Reminders (``tools/reminders.py``) and scheduled or folder-watching routines
(``routine_timers.py``) must fire while the assistant's popup is closed and
must survive a reboot, so each is a pair of unit files in the user's systemd
directory (``$XDG_CONFIG_HOME/systemd/user``): a ``.service`` that does the
work and a ``.timer`` (``OnCalendar=``, ``Persistent=true`` so a time missed
while the computer was off fires at the next start) or ``.path``
(``PathChanged=``) that starts it, or, for a device, a service the device's
own unit wants (it starts when the device is plugged in; ``device_unit``
names the unit as ``systemd-escape --path`` would). Every unit this project writes is named
``happy-bot-<kind>-<id>`` and carries ``X-HappyBot=`` in its
``[Unit]`` section, so nothing else in the directory is ever touched.

``systemctl --user`` is run only when ``manage`` is true, which callers set
for the user's real directory; tests write into a temporary one.

Arguments in ``ExecStart=`` are quoted with ``quote_exec`` (systemd's own
rules: double quotes, backslash escapes, ``%`` and ``$`` doubled), so any
text the user typed reaches the program as one argument.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

PREFIX = "happy-bot-"
MARKER = "X-HappyBot"


def default_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def quote_exec(argument: str) -> str:
    """One ``ExecStart=`` argument, quoted so systemd passes it through unchanged."""
    escaped = (argument.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
               .replace("%", "%%").replace("$", "$$"))
    return f'"{escaped}"'


def systemctl(*arguments: str) -> tuple[bool, str]:
    """Run ``systemctl --user``; returns ``(ok, message)``."""
    if not shutil.which("systemctl"):
        return False, "systemctl is not installed"
    try:
        completed = subprocess.run(["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return completed.returncode == 0, (completed.stderr or completed.stdout).strip()


def check_calendar(expression: str) -> str:
    """"" if systemd accepts the ``OnCalendar=`` expression, else its complaint."""
    if not expression.strip() or "\n" in expression:
        return "the schedule is empty or has more than one line"
    if not shutil.which("systemd-analyze"):
        return ""
    try:
        completed = subprocess.run(["systemd-analyze", "calendar", expression], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode == 0:
        return ""
    return (completed.stderr.strip().splitlines() or ["not a valid schedule"])[-1]


def device_unit(path: str) -> str:
    """systemd's ``.device`` unit name for a device path, as ``systemd-escape --path`` makes it."""
    escaped = []
    for index, part in enumerate(path.strip("/").split("/")):
        out = ""
        for position, character in enumerate(part):
            if character.isascii() and (character.isalnum() or character in ":_" or (character == "." and position)):
                out += character
            else:
                out += "".join(f"\\x{byte:02x}" for byte in character.encode())
        escaped.append(out)
    return "-".join(escaped) + ".device"


def unit_name(kind: str, ident: str) -> str:
    return PREFIX + kind + "-" + re.sub(r"[^A-Za-z0-9_-]", "-", ident)


def write_units(
    unit_dir: Path,
    name: str,
    description: str,
    exec_start: list[str],
    trigger: str,
    trigger_value: str,
) -> None:
    """Write ``<name>.service`` and its trigger: ``timer`` (``OnCalendar``), ``path`` (``PathChanged``), or
    ``device`` (no trigger file: the service is wanted by the device unit ``trigger_value``, so it starts
    when that device appears)."""
    unit_dir.mkdir(parents=True, exist_ok=True)
    one_line = description.replace("\n", " ")[:200].replace("%", "%%")  # % starts a systemd specifier
    after = f"After={trigger_value}\n" if trigger == "device" else ""
    install = f"\n[Install]\nWantedBy={trigger_value}\n" if trigger == "device" else ""
    (unit_dir / f"{name}.service").write_text(
        f"[Unit]\nDescription={one_line}\n{MARKER}=yes\n{after}\n"
        f"[Service]\nType=oneshot\nExecStart={' '.join(quote_exec(part) for part in exec_start)}\n{install}",
        encoding="utf-8")
    if trigger == "device":
        return
    if trigger == "timer":
        body = f"[Timer]\nOnCalendar={trigger_value}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
    elif trigger == "path":
        body = f"[Path]\nPathChanged={trigger_value}\n\n[Install]\nWantedBy=paths.target\n"
    else:
        raise ValueError(f"unknown trigger {trigger!r}")
    (unit_dir / f"{name}.{trigger}").write_text(f"[Unit]\nDescription={one_line}\n{MARKER}=yes\n\n{body}",
                                                encoding="utf-8")


def owned_units(unit_dir: Path, kind: str) -> dict[str, list[Path]]:
    """This project's unit files of one kind, grouped by unit name (without suffix)."""
    found: dict[str, list[Path]] = {}
    if not unit_dir.is_dir():
        return found
    for path in sorted(unit_dir.glob(f"{PREFIX}{kind}-*")):
        try:
            if f"{MARKER}=yes" not in path.read_text(encoding="utf-8", errors="replace"):
                continue
        except OSError:
            continue
        found.setdefault(path.name.rsplit(".", 1)[0], []).append(path)
    return found


def read_setting(path: Path, key: str) -> str:
    """The value of ``key=`` in a unit file, or "" (a ``Description`` with its ``%%`` back to ``%``)."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + "="):
                value = line[len(key) + 1:]
                return value.replace("%%", "%") if key == "Description" else value
    except OSError:
        pass
    return ""


def remove_units(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass

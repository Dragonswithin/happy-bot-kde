"""Built-in read-only tools: what the assistant can look at on the desktop.

Every tool here has risk ``read``: it inspects the session or the filesystem
as the user and changes nothing. They give a model its bearings (time, the
focused window, the clipboard, the machine) and let it answer questions about
files and disk usage without composing shell commands.

Handlers take the model's arguments, validate them, and return plain text.
Bad arguments and unreadable targets raise ``ToolFailure`` with a message the
model can act on. Tools that run a program (``qdbus6``, ``du``,
``kreadconfig6``) do so with a timeout through
``desktop_context.run_command``.
"""

from __future__ import annotations

import datetime
import os
import platform
import shutil
import stat
from pathlib import Path
from typing import Any

from .. import desktop_context, kwin_bridge
from .registry import RISK_READ, Tool, ToolFailure, object_schema

MAX_READ_CHARS = 20000
MAX_DIRECTORY_ENTRIES = 200


def _path_argument(arguments: dict[str, Any], name: str = "path") -> Path:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolFailure(f"'{name}' is required and must be a path")
    return Path(os.path.expanduser(value.strip())).resolve()


def _int_argument(arguments: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolFailure(f"'{name}' must be a number")
    return max(low, min(high, int(value)))


def _human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def current_time(arguments: dict[str, Any]) -> str:
    now = datetime.datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %H:%M:%S %Z (UTC%z)")


def active_window(arguments: dict[str, Any]) -> str:
    context = desktop_context.active_window_context()
    if not context.get("available"):
        raise ToolFailure(context.get("error") or "no active window information is available")
    window = context["window"]
    return "\n".join(f"{key}: {value}" for key, value in window.items() if value not in ("", None, False))


def list_windows(arguments: dict[str, Any]) -> str:
    try:
        windows = kwin_bridge.shared().run(kwin_bridge.LIST_WINDOWS_JS)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError) as error:
        raise ToolFailure(str(error)) from error
    if not windows:
        return "(no application windows are open)"
    lines = []
    for window in windows:
        flags = [name for name in ("active", "minimized", "fullscreen") if window.get(name)]
        lines.append(
            f"id {window['id']}  {window['app']}  \"{window['title']}\"  "
            f"{window['width']}x{window['height']} at {window['x']},{window['y']} on {window['screen']}"
            f"  desktop {window['desktop']}" + (f"  [{', '.join(flags)}]" if flags else ""))
    return "\n".join(lines)


def clipboard_text(arguments: dict[str, Any]) -> str:
    context = desktop_context.clipboard_context()
    if context.get("error"):
        raise ToolFailure(context["error"])
    return context["text"] if context.get("available") else "(the clipboard is empty or does not hold text)"


def system_info(arguments: dict[str, Any]) -> str:
    session = desktop_context.session_context()
    lines = [
        f"host: {platform.node()}",
        f"system: {platform.system()} {platform.release()} ({platform.machine()})",
        f"user: {session['user']} (home {session['home']})",
        f"desktop: {session['desktop']} on {session['session_type']}",
        f"cpu cores: {os.cpu_count()}",
    ]
    try:
        meminfo = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
        total = int(meminfo["MemTotal"].split()[0]) * 1024
        available = int(meminfo["MemAvailable"].split()[0]) * 1024
        lines.append(f"memory: {_human_size(available)} available of {_human_size(total)}")
    except (OSError, KeyError, ValueError):
        pass
    try:
        release = dict(
            line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
        lines.append(f"distribution: {release.get('PRETTY_NAME', '').strip(chr(34))}")
    except OSError:
        pass
    for mount in ("/", session["home"]):
        try:
            usage = shutil.disk_usage(mount)
            lines.append(f"disk {mount}: {_human_size(usage.free)} free of {_human_size(usage.total)}")
        except OSError:
            pass
    return "\n".join(lines)


def list_directory(arguments: dict[str, Any]) -> str:
    path = _path_argument(arguments)
    limit = _int_argument(arguments, "limit", 100, 1, MAX_DIRECTORY_ENTRIES)
    try:
        entries = sorted(os.scandir(path), key=lambda entry: entry.name.lower())
    except OSError as error:
        raise ToolFailure(f"cannot list {path}: {error.strerror or error}") from error
    lines = [f"{path} ({len(entries)} entries)"]
    for entry in entries[:limit]:
        try:
            info = entry.stat(follow_symlinks=False)
            kind = "dir " if stat.S_ISDIR(info.st_mode) else "link" if stat.S_ISLNK(info.st_mode) else "file"
            modified = datetime.datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
            size = "" if kind == "dir " else _human_size(info.st_size)
            lines.append(f"{kind}  {modified}  {size:>9}  {entry.name}")
        except OSError:
            lines.append(f"?     {entry.name}")
    if len(entries) > limit:
        lines.append(f"[{len(entries) - limit} more entries not shown]")
    return "\n".join(lines)


def read_text_file(arguments: dict[str, Any]) -> str:
    path = _path_argument(arguments)
    limit = _int_argument(arguments, "max_chars", 8000, 100, MAX_READ_CHARS)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(limit * 4 + 1)
    except OSError as error:
        raise ToolFailure(f"cannot read {path}: {error.strerror or error}") from error
    if b"\x00" in raw[:4096]:
        raise ToolFailure(f"{path} is a binary file ({_human_size(path.stat().st_size)}); it cannot be read as text")
    text = raw.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + f"\n[file continues; {_human_size(path.stat().st_size)} in total]"
    return text or "(the file is empty)"


def disk_usage(arguments: dict[str, Any]) -> str:
    path = _path_argument(arguments)
    if not path.is_dir():
        raise ToolFailure(f"{path} is not a folder")
    result = desktop_context.run_command(
        ["du", "--one-file-system", "--max-depth=1", "--block-size=1", "--", str(path)], timeout=45.0)
    rows = []
    for line in result["stdout"].splitlines():
        size, _, name = line.partition("\t")
        if size.isdigit():
            rows.append((int(size), name))
    if not rows:
        raise ToolFailure(result["stderr"].strip() or f"could not measure {path}")
    rows.sort(reverse=True)
    lines = [
        f"{_human_size(size):>10}  {name}" + ("  (whole folder)" if name == str(path) else "")
        for size, name in rows[:40]
    ]
    if result["returncode"] is None:
        lines.append("[measurement was cut short after 45 s; sizes are incomplete]")
    return "\n".join(lines)


def read_kde_setting(arguments: dict[str, Any]) -> str:
    for name in ("file", "group", "key"):
        if not isinstance(arguments.get(name), str) or not arguments[name]:
            raise ToolFailure("'file', 'group' and 'key' are required")
    result = desktop_context.run_command(
        ["kreadconfig6", "--file", arguments["file"], "--group", arguments["group"], "--key", arguments["key"]])
    if not result["ok"]:
        raise ToolFailure(result["stderr"].strip() or "kreadconfig6 failed")
    return result["stdout"].strip() or "(not set; the default applies)"


def observe_tools() -> list[Tool]:
    """The built-in read-only tools, in the order they are offered to a model."""
    path = {"type": "string", "description": "Absolute path, or one starting with ~"}
    return [
        Tool("current_time", "Current local date, time and time zone.", object_schema(), RISK_READ, current_time),
        Tool("active_window", "Title, application and process id of the window the user has focused.",
             object_schema(), RISK_READ, active_window),
        Tool("list_windows", "Every open application window: id, application, title, size, position, screen, "
             "virtual desktop and state.", object_schema(), RISK_READ, list_windows),
        Tool("clipboard_text", "The text currently on the user's clipboard.", object_schema(), RISK_READ,
             clipboard_text),
        Tool("system_info", "Host name, operating system, desktop, CPU count, memory and free disk space.",
             object_schema(), RISK_READ, system_info),
        Tool("list_directory", "List a folder's entries with type, modification time and size.",
             object_schema({"path": path, "limit": {"type": "integer", "description": "Maximum entries (default 100)"}},
                           ["path"]), RISK_READ, list_directory),
        Tool("read_text_file", "Read the beginning of a text file.",
             object_schema({"path": path, "max_chars": {"type": "integer", "description": "Default 8000, max 20000"}},
                           ["path"]), RISK_READ, read_text_file),
        Tool("disk_usage", "Sizes of a folder's immediate children, largest first. Use to find what takes space.",
             object_schema({"path": path}, ["path"]), RISK_READ, disk_usage),
        Tool("read_kde_setting", "Read one KDE configuration value, for example file 'kdeglobals', group 'KDE', "
             "key 'LookAndFeelPackage'.",
             object_schema({"file": {"type": "string"}, "group": {"type": "string"}, "key": {"type": "string"}},
                           ["file", "group", "key"]), RISK_READ, read_kde_setting),
    ]

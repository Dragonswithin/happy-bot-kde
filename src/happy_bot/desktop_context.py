"""Read-only capture of the user's KDE session state for the assistant.

Collects what the user is looking at so a request can be answered in context:
the active window's metadata from KWin, clipboard text from Klipper, basic
session facts, and an explicit screenshot through Spectacle. The window comes
from ``kwin_bridge`` (KWin has no non-interactive DBus query for it); the
clipboard and screenshot are reached by running ``qdbus6`` or ``spectacle`` as
a short child process with a timeout. Every call here can block for a few
seconds and must not run on a thread that has to stay responsive.

Nothing here changes desktop state except ``take_screenshot``, which writes a
PNG into the daemon's runtime directory. A missing tool, a DBus failure or a
timeout is reported in the returned dictionary (``available``/``error``),
never raised.
"""

from __future__ import annotations

import getpass
import os
import pwd
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTEXT_SCHEMA = "happy_bot_context.v1"
MAX_CLIPBOARD_CHARS = 12000
CONTEXT_KINDS = ("combined", "clipboard", "window")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 80].rstrip() + "\n[truncated by Happy Bot]"


def run_command(command: list[str], timeout: float = 5.0) -> dict[str, Any]:
    """Run a child process and return its outcome without raising."""
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"timed out after {timeout:g}s",
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def qdbus_call(args: list[str], timeout: float = 4.0) -> dict[str, Any]:
    command = [shutil.which("qdbus6") or "/usr/bin/qdbus6", *args]
    return run_command(command, timeout=timeout)


def clipboard_context() -> dict[str, Any]:
    result = qdbus_call(
        ["org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardContents"],
        timeout=3.0,
    )
    text = result["stdout"].strip() if result["ok"] else ""
    return {
        "available": bool(text),
        "source": "klipper",
        "text": short_text(text, MAX_CLIPBOARD_CHARS),
        "error": "" if result["ok"] else (result["stderr"].strip() or "Klipper DBus call failed"),
    }


def active_window_context() -> dict[str, Any]:
    """Describe the focused window through the KWin script bridge."""
    from . import kwin_bridge

    try:
        window = kwin_bridge.shared().run(kwin_bridge.ACTIVE_WINDOW_JS)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError) as error:
        return {"available": False, "source": "kwin", "error": str(error)}
    if not window:
        return {"available": False, "source": "kwin", "error": "no window is focused"}
    return {"available": True, "source": "kwin", "window": window, "error": ""}


def _desktop_entry(resource_class: str) -> dict[str, str]:
    """``Name`` and ``Icon`` from the main group of the desktop entry named after a window class, or {}."""
    cls = (resource_class or "").strip()
    if not cls:
        return {}
    dirs = [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
            *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")]
    for directory in dirs:
        for candidate in (cls, cls.lower()):
            path = os.path.join(directory, "applications", f"{candidate}.desktop")
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    entry: dict[str, str] = {}
                    in_main = False
                    for line in handle:
                        if line.startswith("["):
                            if in_main:
                                break  # actions groups have their own Name and Icon
                            in_main = line.strip() == "[Desktop Entry]"
                            continue
                        key, _, value = line.partition("=")
                        if in_main and key in ("Name", "Icon") and key not in entry:
                            entry[key] = value.strip()
                    return entry
            except OSError:
                continue
    return {}


def application_name(resource_class: str) -> str:
    """A window's application as people know it: the ``Name`` of its desktop entry, else its class."""
    cls = (resource_class or "").strip()
    if not cls:
        return ""
    return _desktop_entry(cls).get("Name") or cls.rsplit(".", 1)[-1].replace("-", " ").capitalize()


def current_application() -> dict[str, str]:
    """``{"app", "class", "title", "icon"}`` of the window the user is working in, or empty strings.

    The popup asks for this when it is opened from the floating button or the hotkey, so the
    assistant knows which application the question is about (``ask_stream`` adds app, class and
    title to the request) and the welcome screen can name it, with ``icon`` (its desktop entry's
    icon name), on its help shortcut.
    """
    context = active_window_context()
    window = context.get("window") or {}
    cls = str(window.get("app") or "")
    return {"app": application_name(cls), "class": cls, "title": str(window.get("title") or "")[:200],
            "icon": _desktop_entry(cls).get("Icon", "")}


def session_context() -> dict[str, Any]:
    entry = pwd.getpwuid(os.getuid())
    return {
        "user": getpass.getuser(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "home": entry.pw_dir,
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
    }


def combined_context(kind: str = "combined") -> dict[str, Any]:
    """Capture the requested sources; ``kind`` is one of ``CONTEXT_KINDS``."""
    include_clipboard = kind in {"combined", "clipboard"}
    include_window = kind in {"combined", "window", "active-window"}
    return {
        "schema": CONTEXT_SCHEMA,
        "generated_at": now_iso(),
        "kind": kind,
        "session": session_context(),
        "clipboard": clipboard_context() if include_clipboard else {"available": False},
        "active_window": active_window_context() if include_window else {"available": False},
    }


def take_screenshot(runtime_dir: Path) -> dict[str, Any]:
    """Save a full-desktop screenshot under ``runtime_dir`` and return its path."""
    spectacle = shutil.which("spectacle")
    if not spectacle:
        return {"ok": False, "error": "spectacle is not installed"}
    root = runtime_dir / "screenshots"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / f"desktop-context-{int(time.time())}.png"
    result = run_command([spectacle, "-b", "-n", "-o", str(target)], timeout=30.0)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"].strip() or "spectacle failed"}
    return {"ok": True, "path": str(target)}

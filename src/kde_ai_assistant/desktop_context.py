"""Read-only capture of the user's KDE session state for the assistant.

Collects what the user is looking at so a request can be answered in context:
the active window's metadata from KWin, clipboard text from Klipper, basic
session facts, and an explicit screenshot through Spectacle. Each source is
reached by running ``qdbus6`` or ``spectacle`` as a short child process with a
timeout, so every call here blocks for up to a few seconds and must not run
on a thread that has to stay responsive.

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

CONTEXT_SCHEMA = "kde_ai_assistant_context.v1"
MAX_CLIPBOARD_CHARS = 12000
CONTEXT_KINDS = ("combined", "clipboard", "window")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 80].rstrip() + "\n[truncated by KDE AI Assistant]"


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


def parse_qdbus_key_values(text: str) -> dict[str, str]:
    """Parse the ``key: value`` lines qdbus6 prints for a QVariantMap."""
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def active_window_context() -> dict[str, Any]:
    result = qdbus_call(["org.kde.KWin", "/KWin", "org.kde.KWin.queryWindowInfo"], timeout=5.0)
    if not result["ok"]:
        return {
            "available": False,
            "source": "kwin",
            "error": result["stderr"].strip() or "KWin DBus call failed",
        }
    parsed = parse_qdbus_key_values(result["stdout"])
    interesting = {
        key: parsed.get(key, "")
        for key in (
            "caption",
            "desktopFile",
            "resourceClass",
            "resourceName",
            "pid",
            "uuid",
            "fullscreen",
            "minimized",
        )
    }
    available = any(value for key, value in interesting.items() if key not in {"fullscreen", "minimized"})
    return {
        "available": available,
        "source": "kwin",
        "window": interesting,
        "error": "" if available else "KWin returned no active window details",
    }


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

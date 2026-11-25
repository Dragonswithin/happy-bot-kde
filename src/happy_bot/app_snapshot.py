"""Facts about the application window the user was in, read from the desktop for the assistant.

When Happy Bot is opened from an application (the floating button or the hotkey), the popup notes
that window (``desktop_context.current_application``: its KWin id, name, class and title) and sends
it with each request. ``app_context`` decides whether and for which AI that becomes background for
the model; this module only reads the facts, on the daemon's request thread:

- ``light_facts``: cheap and not private, sent with every request from an application: the
  application's version (from the package that owns its program, through ``pacman -Qo``,
  ``dpkg -S`` or ``rpm -qf``), the Plasma version (``plasmashell --version``) and the operating
  system (``/etc/os-release``). Versions are cached per program for the daemon's lifetime.
- ``full_facts``: read only for a chat started with the welcome screen's "Help with …" button:
  the text the user has selected (the primary selection, ``tools.screen.selected_text``), the
  window's visible controls (``tools.gui.ui_snapshot``, through the accessibility tree), and the
  file it most likely has open (the entry for that application in the desktop's recent files,
  ``recently-used.xbel``, whose name appears in the window title; the longest such name, then
  the newest).

- ``capture_window``: a PNG screenshot of the window, taken with Spectacle (``-b -n -a``, the
  active window only), only when the user chose "Help with …" (never when Happy Bot opens).
  Plasma lets helper programs capture only the active window, and by then Happy Bot has focus, so
  the window is made active first (``_activate``, through KWin) and is captured only once KWin
  reports that very window as active, so the picture can never show Happy Bot or another
  application; the popup takes focus back afterwards. Pictures go to ``screenshots/`` in the daemon's
  runtime directory (a memory-backed folder cleared at logout); ones older than
  ``SCREENSHOT_KEEP_SECONDS`` are removed whenever another is taken.

Every reader is best effort: a fact that cannot be read (no package manager, no accessibility,
the window has closed, nothing selected) is left out, never an error. Lengths are capped
(``MAX_SELECTION_CHARS``, ``MAX_CONTROLS_CHARS``) so a large window or selection cannot fill the
model's context. Nothing here decides who sees the facts; that is ``app_context``.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import time
import uuid
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .desktop_context import run_command

SCREENSHOT_KEEP_SECONDS = 24 * 3600
MAX_SELECTION_CHARS = 4000
MAX_CONTROLS_CHARS = 6000
_BOOKMARK_NS = "{http://www.freedesktop.org/standards/desktop-bookmarks}"


@functools.lru_cache(maxsize=1)
def system_description() -> str:
    """``"Plasma 6.5.4 on CachyOS"``, or whichever half could be read, or ""."""
    plasma = ""
    if shutil.which("plasmashell"):
        match = re.search(r"(\d+(?:\.\d+)+)", run_command(["plasmashell", "--version"], timeout=5).get("stdout", ""))
        plasma = f"Plasma {match.group(1)}" if match else ""
    system = ""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PRETTY_NAME="):
                system = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return " on ".join(part for part in (plasma, system) if part)


@functools.lru_cache(maxsize=64)
def _package_version(program: str) -> str:
    """The version of the installed package that owns ``program`` (an absolute path), or ""."""
    if shutil.which("pacman"):
        result = run_command(["pacman", "-Qo", program], timeout=5)
        match = re.search(r" is owned by \S+ (\S+)", result.get("stdout", ""))
        if match:
            return match.group(1)
    if shutil.which("dpkg"):
        owner = run_command(["dpkg", "-S", program], timeout=5).get("stdout", "").split(":", 1)[0].strip()
        if owner:
            version = run_command(["dpkg-query", "-W", "-f=${Version}", owner], timeout=5).get("stdout", "").strip()
            if version:
                return version
    if shutil.which("rpm"):
        version = run_command(["rpm", "-qf", "--queryformat", "%{VERSION}", program], timeout=5).get("stdout", "").strip()
        if version and "not owned" not in version:
            return version
    return ""


def application_version(pid: int) -> str:
    """The version of the application running as ``pid``, from its package, or ""."""
    try:
        program = os.readlink(f"/proc/{pid}/exe")
    except (OSError, ValueError):
        return ""
    return _package_version(program)


def light_facts(window: dict[str, Any]) -> dict[str, str]:
    """``{"version", "system"}`` for a KWin window description (with ``pid``); missing ones are ""."""
    pid = window.get("pid")
    return {"version": application_version(int(pid)) if isinstance(pid, int) and pid > 0 else "",
            "system": system_description()}


def open_document(resource_class: str, title: str, recent_file: Path | None = None) -> str:
    """The file the application most likely has open: of its recent files whose name is in the title, the one
    with the longest name (so "old notes.txt" wins over "notes.txt" inside it), then the newest."""
    path = recent_file or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "recently-used.xbel"
    wanted = {resource_class.lower(), resource_class.lower().rsplit(".", 1)[-1]} - {""}
    if not wanted or not title:
        return ""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return ""
    best, rank = "", (0, "")
    for bookmark in root.iter("bookmark"):
        location = urlparse(bookmark.get("href", ""))
        if location.scheme != "file":
            continue
        name = os.path.basename(unquote(location.path))
        if not name or name not in title:
            continue
        for application in bookmark.iter(_BOOKMARK_NS + "application"):
            candidate = (len(name), application.get("modified", ""))
            if application.get("name", "").lower() in wanted and candidate > rank:
                best, rank = unquote(location.path), candidate
    return best


def full_facts(window: dict[str, Any]) -> dict[str, str]:
    """``{"selection", "controls", "document"}`` for a KWin window description; missing ones are ""."""
    from .tools import gui, screen
    from .tools.registry import ToolFailure

    facts = {"selection": "", "controls": "", "document": ""}
    try:
        selection = screen.selected_text({})
        if selection and selection != "No text is selected right now.":
            facts["selection"] = selection[:MAX_SELECTION_CHARS]
    except ToolFailure:
        pass
    if window.get("id"):
        try:
            facts["controls"] = gui.ui_snapshot({"window": str(window["id"])})[:MAX_CONTROLS_CHARS]
        except ToolFailure:
            pass
    facts["document"] = open_document(str(window.get("app") or ""), str(window.get("title") or ""))
    return facts


def _active_window_id() -> str:
    from . import kwin_bridge

    try:
        found = kwin_bridge.shared().run("return { id: workspace.activeWindow ? String(workspace.activeWindow.internalId) : '' };")
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError):
        return ""
    return str((found or {}).get("id") or "")


def _activate(window_id: str) -> None:
    from . import kwin_bridge

    script = ("var list = workspace.windowList();\n"
              "for (var i = 0; i < list.length; i++) {\n"
              "  if (String(list[i].internalId) == %s) { workspace.activeWindow = list[i]; return { found: true }; }\n"
              "}\n"
              "return { found: false };") % json.dumps(window_id)
    try:
        kwin_bridge.shared().run(script)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError):
        pass


def capture_window(window_id: str, directory: Path) -> str:
    """A screenshot of the window ``window_id``, made active first, as a PNG path, or "" (see above)."""
    if not window_id or not shutil.which("spectacle"):
        return ""
    _activate(window_id)
    for _attempt in range(10):
        if _active_window_id() == window_id:
            break
        time.sleep(0.1)
    else:
        return ""
    time.sleep(0.15)  # let the window draw itself as active before it is captured
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cutoff = time.time() - SCREENSHOT_KEEP_SECONDS
    for old in directory.glob("*.png"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    target = directory / f"{uuid.uuid4().hex}.png"
    run_command(["spectacle", "-b", "-n", "-a", "-o", str(target)], timeout=10)
    try:
        if target.stat().st_size > 0:
            target.chmod(0o600)
            return str(target)
    except OSError:
        pass
    return ""

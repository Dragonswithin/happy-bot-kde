"""Offline Wikipedia on this computer: the settings, the archives, and where they are kept.

Happy Bot reads Wikipedia offline from Kiwix ZIM archives (``wikipedia_<lang>_<selection>_<flavour>
_<YYYY-MM>.zim``, for example ``wikipedia_en_all_nopic_2026-06.zim``) through a reader tool
server (openzim-mcp, ``wikipedia_reader``). This module owns the local side:

- the ``wikipedia`` settings group (``validate_wikipedia``)::

      "wikipedia": {
        "server": "",        # the tool server that reads the archives; "" = not set up
        "folder": "",        # absolute path of the folder holding the archives
        "book": "",          # the Kiwix book kept current, e.g. "wikipedia_en_all_nopic"; "" = none
        "auto_update": false # true: download newer builds of "book" once a month (wikipedia_catalog)
      }

- ``archives(folder)``: the Wikipedia archives in a folder, newest build of each book first;
- ``find_folders``: folders on this computer that already hold Wikipedia archives, so setup can
  offer them before suggesting a download of tens of gigabytes: Happy Bot's own folder
  (``own_folder``), the Kiwix desktop application's folders, the user's Downloads and Documents,
  and the folders given to a ZIM reader the user set up for another AI program (``mcp_discovery``)
  or for Happy Bot;
- ``updated_elsewhere(folder)``: why Happy Bot must not update a folder itself, or "": another
  program's updater keeps it (its lock file ``FOREIGN_LOCK``, as the maintainer's own monthly
  updater uses), or Happy Bot may not write there;
- ``sync_timer``: the monthly user timer (``user_timers``, kind ``wikipedia``) that runs
  ``happy-bot wikipedia update`` while ``auto_update`` is on, and nothing otherwise.

Nothing here downloads or reads an archive's contents; a folder that cannot be read simply holds no
archives.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import user_timers

ARCHIVE_NAME = re.compile(r"^(wikipedia_([a-z]{2,3}(?:-[a-z]+)?)_[a-z0-9-]+_(maxi|nopic|mini))_(\d{4}-\d{2})\.zim$")
OWN_LOCK = ".happy-bot-update.lock"
FOREIGN_LOCK = ".update.lock"
TIMER_KIND = "wikipedia"
TIMER_CALENDAR = "*-*-05 04:30:00"  # monthly; Kiwix publishes new builds every few months
DEFAULTS = {"server": "", "folder": "", "book": "", "auto_update": False}


class WikipediaError(ValueError):
    """A ``wikipedia`` setting is wrong; the message says which and why."""


@dataclass(frozen=True)
class Archive:
    path: str
    book: str       # wikipedia_en_all_nopic
    language: str   # en
    flavour: str    # maxi (with pictures), nopic (no pictures), mini (introductions only)
    build: str      # 2026-06
    size: int       # bytes

    def describe(self) -> dict[str, Any]:
        return {"path": self.path, "book": self.book, "language": self.language, "flavour": self.flavour,
                "build": self.build, "size": self.size}


def validate_wikipedia(raw: Any) -> dict[str, Any]:
    """The ``wikipedia`` settings group with defaults filled in; raises ``WikipediaError``."""
    if not isinstance(raw, dict):
        raise WikipediaError("'wikipedia' must be an object")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise WikipediaError(f"'wikipedia': unknown setting(s) {', '.join(sorted(unknown))}")
    merged = {**DEFAULTS, **raw}
    for key in ("server", "folder", "book"):
        if not isinstance(merged[key], str):
            raise WikipediaError(f"'wikipedia.{key}' must be text")
    if merged["folder"] and not merged["folder"].startswith("/"):
        raise WikipediaError("'wikipedia.folder' must be an absolute path")
    if merged["book"] and not re.fullmatch(r"wikipedia_[a-z0-9_-]+", merged["book"]):
        raise WikipediaError("'wikipedia.book' must be a Kiwix Wikipedia book name such as wikipedia_en_all_nopic")
    if not isinstance(merged["auto_update"], bool):
        raise WikipediaError("'wikipedia.auto_update' must be true or false")
    return merged


def parse_archive(path: Path) -> Archive | None:
    match = ARCHIVE_NAME.match(path.name)
    if not match:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    return Archive(str(path), match.group(1), match.group(2), match.group(3), match.group(4), size)


def archives(folder: str | Path) -> list[Archive]:
    """Wikipedia archives in ``folder`` (not its subfolders), newest build of each book first."""
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return []
    found = [archive for entry in entries if entry.is_file() and (archive := parse_archive(entry))]
    return sorted(found, key=lambda archive: (archive.book, archive.build), reverse=True)


def own_folder() -> Path:
    """Where Happy Bot keeps archives it downloads: ``$XDG_DATA_HOME/happy-bot/wikipedia``."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "happy-bot" / "wikipedia"


def _reader_folders(command: str, args: list[str] | tuple[str, ...]) -> list[str]:
    """Folders given to a ZIM reader server on its command line (openzim-mcp takes them as arguments)."""
    if "zim" not in (command + " " + " ".join(args)).lower():
        return []
    return [arg for arg in args if arg.startswith("/") and os.path.isdir(arg)]


def find_folders(settings: dict[str, Any], home: Path | None = None) -> list[str]:
    """Folders on this computer that hold Wikipedia archives, most likely first, each once."""
    from . import mcp_discovery
    from .agent_loop import user_folders

    base = home or Path.home()
    folders = [str(own_folder()), str(base / ".local/share/kiwix-desktop"), str(base / ".local/share/kiwix"),
               str(base / ".var/app/org.kiwix.desktop/data/kiwix-desktop")]
    for entry in (settings.get("tool_servers") or {}).values():
        folders += _reader_folders(str(entry.get("command", "")), entry.get("args") or [])
    try:
        for candidate in mcp_discovery.discover_servers(home):
            folders += _reader_folders(candidate.command, candidate.args)
    except Exception:  # noqa: BLE001 - another program's unreadable configuration hides only its folders
        pass
    standard = user_folders(settings.get("folders"))
    folders += [standard[name] for name in ("Downloads", "Documents") if name in standard]
    unique = list(dict.fromkeys(os.path.realpath(folder) for folder in folders))
    return [folder for folder in unique if archives(folder)]


def updated_elsewhere(folder: str) -> str:
    """Why Happy Bot should not update archives in ``folder`` itself, or "" when it may."""
    path = Path(folder)
    if (path / FOREIGN_LOCK).exists():
        return "Another program on this computer keeps these archives up to date."
    if path.exists() and not os.access(path, os.W_OK):
        return "Happy Bot may not write to this folder, so it cannot update the archives in it."
    return ""


def free_space(folder: str | Path) -> int:
    """Bytes free where ``folder`` is (or would be created)."""
    path = Path(folder)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def sync_timer(wikipedia: dict[str, Any], unit_dir: Path, manage: bool) -> None:
    """Have the monthly update timer exactly when ``auto_update`` is on for a book Happy Bot keeps."""
    import sys

    name = user_timers.unit_name(TIMER_KIND, "update")
    wanted = bool(wikipedia.get("auto_update") and wikipedia.get("book") and wikipedia.get("folder"))
    existing = [path for paths in user_timers.owned_units(unit_dir, TIMER_KIND).values() for path in paths]
    if not wanted:
        if existing:
            if manage:
                user_timers.systemctl("disable", "--now", f"{name}.timer")
            user_timers.remove_units(existing)
            if manage:
                user_timers.systemctl("daemon-reload")
        return
    launcher = shutil.which("happy-bot") or str(Path.home() / ".local" / "bin" / "happy-bot")
    command = [launcher, "wikipedia", "update"] if os.path.exists(launcher) else [sys.executable, "-m",
                                                                                  "happy_bot.cli", "wikipedia", "update"]
    user_timers.write_units(unit_dir, name, "Happy Bot: download a newer offline Wikipedia when there is one",
                            command, "timer", TIMER_CALENDAR)
    if manage:
        user_timers.systemctl("daemon-reload")
        user_timers.systemctl("enable", "--now", f"{name}.timer")

"""What the user opened recently, read from KDE's activity manager: applications, files, settings, websites.

Plasma's activity manager (``kactivitymanagerd``) records each application
started from the launcher or the task manager and each file, System Settings
page and web page that applications report opening. The application
launcher's "Recent" lists read the same records. ``recent_resources`` reads
them for the search bar's empty-bar suggestions (``quick_results.recent``),
newest first, one entry per resource across every activity:

- ``applications:org.kde.dolphin.desktop``: an application, by desktop id;
- ``kcm:kcm_bluetooth``: a System Settings page;
- ``/home/…`` or ``file:///home/…``: a file or folder;
- ``https://…``: a web page (a browser that reports to KDE, such as Chromium).

The database is ``$XDG_DATA_HOME/kactivitymanagerd/resources/database``
(SQLite, table ``ResourceScoreCache``, with titles in ``ResourceInfo``). It is
opened read-only and never changed; the daemon keeps it open with a write-
ahead log, which a read-only reader shares. When it is missing, locked or of
an unknown layout the result is empty, never an error. Nothing read here
leaves this computer: the caller decides what to show, and web pages are
shown only when the user switched recent websites on.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MAX_ROWS = 300


@dataclass(frozen=True)
class Resource:
    target: str
    title: str
    mimetype: str
    last_used: int  # seconds since the epoch


def database_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "kactivitymanagerd" / "resources" / "database"


def recent_resources(database: Path | None = None, limit: int = MAX_ROWS) -> list[Resource]:
    """The most recently used resources, newest first (see the module docstring)."""
    path = database or database_path()
    if not path.is_file():
        return []
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT cache.targettedResource, COALESCE(info.title, ''), COALESCE(info.mimetype, ''),"
            " MAX(cache.lastUpdate) AS used FROM ResourceScoreCache AS cache"
            " LEFT JOIN ResourceInfo AS info ON info.targettedResource = cache.targettedResource"
            " GROUP BY cache.targettedResource ORDER BY used DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [Resource(str(target), str(title), str(mimetype), int(used or 0)) for target, title, mimetype, used in rows]

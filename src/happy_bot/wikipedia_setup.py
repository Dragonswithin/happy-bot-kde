"""Setting up offline Wikipedia from the settings page: what to offer, using it, downloading it, turning it off.

The "Offline Wikipedia" section of the Search & Tools page asks ``choices`` what is possible and
sends the user's pick to ``use``:

- ``folder:<path>``: Wikipedia archives already on this computer (``wikipedia_library.find_folders``,
  which finds, for example, the folder another AI program's ZIM reader was given). Nothing is
  downloaded. When another program keeps that folder up to date (``updated_elsewhere``), Happy Bot
  never updates it, whatever the user ticks.
- ``download:<book>``: one of Kiwix's sizes for the user's language (``wikipedia_catalog.available``:
  introductions only, every article without pictures, or everything), downloaded into Happy Bot's
  own folder (``wikipedia_library.own_folder``) by a background ``DownloadJob``; the settings page
  follows it through ``status``. The size that fits with room to spare is recommended: every article
  without pictures when it fits, else the introductions.

Either way, ``_apply`` adds the reader tool server and saves the ``wikipedia`` settings: the reader
is openzim-mcp in its "advanced" mode with the archives' folder as its argument, run from the
``openzim-mcp`` program when one is installed and otherwise through ``uvx`` at ``READER_VERSION``
(checked 2026-11-25 on PyPI and started against a real archive). Its entry is marked read-only and
lends the AI only ``AI_TOOLS``, so the AI can look things up in it without approval. It is
started once and asked for a title before anything is saved; if that fails the settings are left
as they were. ``auto_update`` turns the monthly timer on (``wikipedia_library.sync_timer``, run by
the daemon after every settings change).

``turn_off`` removes the reader and the settings; the archives stay on disk, and the message says
where, so the user can delete them. ``scheduled_update`` is what the monthly timer runs
(``happy-bot wikipedia update``): it downloads a newer build only while ``auto_update`` is on and no
other program keeps the folder. Everything here runs on the request's thread except the
download itself.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import wikipedia_catalog, wikipedia_library
from .mcp_client import McpError, McpServerSpec, McpSession

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

READER_VERSION = "3.5.2"
SERVER_NAME = "wikipedia"
AI_TOOLS = ["zim_query", "zim_search", "zim_get"]
FIRST_START_SECONDS = 240.0
TITLES = {"mini": "Introductions only", "nopic": "Every article, no pictures", "maxi": "Everything, with pictures"}
DETAILS = {"mini": "The opening section of every article. Quick to download.",
           "nopic": "Every article in full, without pictures. Best for looking things up.",
           "maxi": "Every article in full, with its pictures, as on the website."}


class SetupError(RuntimeError):
    """The choice could not be used; the message says why."""


def language_code() -> str:
    value = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en"
    code = value.split(".")[0].split("@")[0].split("_")[0].lower()
    return code if code.isalpha() and code not in ("c", "posix") else "en"


def reader_entry(folder: str) -> dict[str, Any]:
    """The tool-server entry that reads the archives in ``folder``."""
    installed = shutil.which("openzim-mcp")
    if installed:
        command, args = installed, ["--mode", "advanced", folder]
    elif shutil.which("uvx"):
        command, args = "uvx", ["--from", f"openzim-mcp=={READER_VERSION}", "openzim-mcp", "--mode", "advanced", folder]
    else:
        raise SetupError("Reading Wikipedia needs uv (the 'uvx' program) or openzim-mcp. Install uv with your "
                         "package manager, then try again.")
    return {"command": command, "args": args, "env": {}, "enabled": True, "read_only": True, "tools": list(AI_TOOLS)}


def choices(settings: dict[str, Any]) -> dict[str, Any]:
    """``{"found", "downloads", "language", "folder", "free"}`` for the settings page (see the module docstring)."""
    found = []
    for folder in wikipedia_library.find_folders(settings):
        books = wikipedia_library.archives(folder)
        found.append({"id": f"folder:{folder}", "folder": folder, "archives": [book.describe() for book in books],
                      "size": sum(book.size for book in books),
                      "updated_elsewhere": wikipedia_library.updated_elsewhere(folder)})
    own = wikipedia_library.own_folder()
    free = wikipedia_library.free_space(own)
    language = language_code()
    problem = ""
    try:
        offered = wikipedia_catalog.available(language) or wikipedia_catalog.available("en")
    except wikipedia_catalog.CatalogError as error:
        offered, problem = [], str(error)
    downloads = []
    for item in offered:
        fits = free > item["size"] + wikipedia_catalog.FREE_SPACE_MARGIN
        downloads.append({"id": f"download:{item['book']}", "book": item["book"], "flavour": item["flavour"],
                          "title": TITLES[item["flavour"]], "detail": DETAILS[item["flavour"]], "size": item["size"],
                          "build": item["build"], "fits": fits, "recommended": False})
    fitting = [item for item in downloads if item["fits"]]
    best = next((item for item in fitting if item["flavour"] == "nopic"), fitting[0] if fitting else None)
    if best and not found:
        best["recommended"] = True
    return {"found": found, "downloads": downloads, "language": language, "folder": str(own), "free": free,
            "problem": problem}


def _test(entry: dict[str, Any], folder: str) -> None:
    """Start the reader once and look up one title, so nothing broken is saved."""
    archive = wikipedia_library.archives(folder)[0].path
    spec = McpServerSpec(SERVER_NAME, entry["command"], tuple(entry["args"]), ())
    try:
        session = McpSession(spec, startup_timeout=FIRST_START_SECONDS)
    except McpError as error:
        raise SetupError(f"The Wikipedia reader would not start: {error}") from error
    try:
        result = session.call_tool("zim_search", {"query": "Earth", "mode": "title", "limit": 1,
                                                  "zim_file_path": archive}, 60)
    except McpError as error:
        raise SetupError(f"The Wikipedia reader started but did not answer: {error}") from error
    finally:
        session.close()
    if result.is_error:
        raise SetupError(f"The Wikipedia reader could not read the archive: {result.text[:200]}")


def _apply(server: "AssistantServer", folder: str, auto_update: bool) -> dict[str, Any]:
    books = wikipedia_library.archives(folder)
    if not books:
        raise SetupError(f"There is no Wikipedia archive in {folder} any more.")
    entry = reader_entry(folder)
    _test(entry, folder)
    keep = auto_update and not wikipedia_library.updated_elsewhere(folder)
    previous = server.settings
    updated = {**previous, "tool_servers": {**previous["tool_servers"], SERVER_NAME: entry},
               "wikipedia": {"server": SERVER_NAME, "folder": folder, "book": books[0].book, "auto_update": keep}}
    server.replace_settings(updated)
    server.mcp.restart(SERVER_NAME)
    return {"ok": True, "message": "Offline Wikipedia is ready." + (" Happy Bot keeps it up to date." if keep else "")}


class DownloadJob:
    """One background download at a time, for setup (``start``) and the settings page (``progress``)."""

    def __init__(self) -> None:
        self.progress = wikipedia_catalog.Progress()
        self.cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, server: "AssistantServer", book: str, auto_update: bool) -> None:
        if self.running:
            raise SetupError("A download is already running.")
        self.cancel.clear()
        self.progress.set(state="downloading", book=book, done_bytes=0, total_bytes=0, message="Starting…")
        self._thread = threading.Thread(target=self._run, args=(server, book, auto_update), daemon=True,
                                        name="wikipedia-download")
        self._thread.start()

    def _run(self, server: "AssistantServer", book: str, auto_update: bool) -> None:
        folder = str(wikipedia_library.own_folder())
        try:
            wikipedia_catalog.update(folder, book, self.progress, self.cancel)
            message = _apply(server, folder, auto_update)["message"]
            self.progress.set(state="done", message=message)
        except (wikipedia_catalog.CatalogError, SetupError, OSError) as error:
            self.progress.set(state="failed", message=str(error))


def use(server: "AssistantServer", choice: str, auto_update: bool) -> dict[str, Any]:
    """Use one of ``choices``; a download starts in the background and returns at once."""
    kind, _, value = choice.partition(":")
    try:
        if kind == "folder":
            if value not in wikipedia_library.find_folders(server.settings):
                raise SetupError("That folder no longer holds Wikipedia.")
            return _apply(server, value, auto_update)
        if kind == "download":
            reader_entry(str(wikipedia_library.own_folder()))  # say now, not after hours, if it could not be read
            server.wikipedia_download.start(server, value, auto_update)
            return {"ok": True, "started": True, "message": "Downloading… you can close this; it carries on."}
        raise SetupError("That choice is not offered any more.")
    except SetupError as error:
        return {"ok": False, "error": str(error)}


def set_auto_update(server: "AssistantServer", enabled: bool) -> dict[str, Any]:
    wikipedia = server.settings["wikipedia"]
    if enabled and wikipedia_library.updated_elsewhere(wikipedia["folder"]):
        return {"ok": False, "error": wikipedia_library.updated_elsewhere(wikipedia["folder"])}
    server.replace_settings({**server.settings, "wikipedia": {**wikipedia, "auto_update": enabled}})
    return {"ok": True}


def turn_off(server: "AssistantServer") -> dict[str, Any]:
    server.wikipedia_download.cancel.set()
    folder = server.settings["wikipedia"]["folder"]
    servers = {name: entry for name, entry in server.settings["tool_servers"].items()
               if name != server.settings["wikipedia"]["server"]}
    server.replace_settings({**server.settings, "tool_servers": servers,
                             "wikipedia": dict(wikipedia_library.DEFAULTS)})
    where = f" The archives are still in {folder}; delete them there to free the space." if folder else ""
    return {"ok": True, "message": "Offline Wikipedia is off." + where}


def scheduled_update(settings: dict[str, Any]) -> dict[str, Any]:
    """What the monthly timer does: download a newer build of the kept book, when Happy Bot keeps it."""
    wikipedia = settings.get("wikipedia") or {}
    if not (wikipedia.get("auto_update") and wikipedia.get("folder") and wikipedia.get("book")):
        return {"ok": True, "action": "off"}
    elsewhere = wikipedia_library.updated_elsewhere(wikipedia["folder"])
    if elsewhere:
        return {"ok": True, "action": "updated_elsewhere", "reason": elsewhere}
    try:
        return {"ok": True, **wikipedia_catalog.update(wikipedia["folder"], wikipedia["book"])}
    except (wikipedia_catalog.CatalogError, OSError) as error:
        return {"ok": False, "error": str(error)}


def status(server: "AssistantServer") -> dict[str, Any]:
    wikipedia = server.settings["wikipedia"]
    books = wikipedia_library.archives(wikipedia["folder"]) if wikipedia["folder"] else []
    return {"set_up": bool(wikipedia["server"] and books), "folder": wikipedia["folder"], "book": wikipedia["book"],
            "auto_update": wikipedia["auto_update"], "archives": [book.describe() for book in books],
            "updated_elsewhere": wikipedia_library.updated_elsewhere(wikipedia["folder"]) if wikipedia["folder"] else "",
            "download": server.wikipedia_download.progress.snapshot()}

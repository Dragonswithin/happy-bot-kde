"""The daemon's offline Wikipedia endpoints, kept apart from ``daemon_routes`` and merged into its ``ROUTES``.

- ``GET /wikipedia``: whether it is set up, its folder, archives and updating, and the download's
  progress (``wikipedia_setup.status``); the settings page polls it while a download runs.
- ``POST /wikipedia/choices``: archives found on this computer and Kiwix's sizes to download
  (``wikipedia_setup.choices``); it reads Kiwix's list, so it takes a second or two.
- ``POST /wikipedia/use`` (``{"choice", "auto_update"}``): use one; a download starts in the background.
- ``POST /wikipedia/auto-update`` (``{"enabled"}``), ``POST /wikipedia/cancel`` (stop a download,
  keeping what was downloaded), ``POST /wikipedia/off`` (remove the reader; the archives stay).
- ``POST /wikipedia/reload``: the reader reopens its archives; ``happy-bot wikipedia update`` calls it
  after replacing an archive.
- ``GET /wikipedia/search?q=``: the web finder's Wikipedia articles (``wikipedia_reader``).
- ``GET /wikipedia/page?path=``: ``{"url"}``, where the article view loads the article's own page
  (``wikipedia_pages``, a separate loopback server with a secret address).
- ``GET /wikipedia/article?path=``: the article as light Markdown, for the text view used where Happy
  Bot cannot show web pages.

Errors are ``{"ok": false, "error", "code"}``: ``not_configured`` when offline Wikipedia is not set
up, ``tool_failed`` when the reader did not answer, ``invalid`` for a bad request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from . import wikipedia_reader, wikipedia_setup

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

Reply = tuple[int, dict[str, Any]]
MAX_QUERY_CHARS = 300


def _first(query: dict[str, list[str]], name: str) -> str:
    return (query.get(name) or [""])[0]


def _reader_error(error: wikipedia_reader.ReaderError) -> Reply:
    code = "not_configured" if "not set up" in str(error) else "tool_failed"
    return (409 if code == "not_configured" else 502), {"ok": False, "error": str(error), "code": code}


def _result(result: dict[str, Any]) -> Reply:
    return (200, result) if result.get("ok") else (400, {**result, "code": "invalid"})


def status(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **wikipedia_setup.status(server)}


def choices(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **wikipedia_setup.choices(server.settings)}


def use(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return _result(wikipedia_setup.use(server, str(body.get("choice") or ""), body.get("auto_update") is True))


def auto_update(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return _result(wikipedia_setup.set_auto_update(server, body.get("enabled") is True))


def cancel(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    server.wikipedia_download.cancel.set()
    return 200, {"ok": True}


def turn_off(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return _result(wikipedia_setup.turn_off(server))


def reload(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    name = server.settings["wikipedia"]["server"]
    if name:
        server.mcp.restart(name)
    return 200, {"ok": True}


def search(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    if not text:
        return 200, {"ok": True, "query": "", "hits": []}
    try:
        return 200, {"ok": True, "query": text, "hits": wikipedia_reader.search(server.mcp, server.settings, text)}
    except wikipedia_reader.ReaderError as error:
        return _reader_error(error)


def page(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    path = _first(query, "path").strip()
    if not path:
        return 400, {"ok": False, "error": "path is required", "code": "invalid"}
    try:
        wikipedia_reader.current_archive(server.settings)
    except wikipedia_reader.ReaderError as error:
        return _reader_error(error)
    if not server.settings["wikipedia"]["server"]:
        return _reader_error(wikipedia_reader.ReaderError("Offline Wikipedia is not set up."))
    return 200, {"ok": True, "url": server.wikipedia_pages.url(path)}


def article(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, **wikipedia_reader.article(server.mcp, server.settings, _first(query, "path"))}
    except wikipedia_reader.ReaderError as error:
        return _reader_error(error)


ROUTES: dict[tuple[str, str], Callable[["AssistantServer", dict[str, list[str]], dict[str, Any]], Reply]] = {
    ("GET", "/wikipedia"): status,
    ("POST", "/wikipedia/choices"): choices,
    ("POST", "/wikipedia/use"): use,
    ("POST", "/wikipedia/auto-update"): auto_update,
    ("POST", "/wikipedia/cancel"): cancel,
    ("POST", "/wikipedia/off"): turn_off,
    ("POST", "/wikipedia/reload"): reload,
    ("GET", "/wikipedia/search"): search,
    ("GET", "/wikipedia/page"): page,
    ("GET", "/wikipedia/article"): article,
}

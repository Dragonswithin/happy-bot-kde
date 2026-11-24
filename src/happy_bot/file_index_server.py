"""``happy-bot file-index-serve``: the file indexes the computer already keeps, offered as a search tool.

These are setup's built-in choices for file search (``search_setup``). Each runs as a small stdio MCP
server, so the ``file_search`` role, the bar's instant search, the self-check and the model's tool
list treat it exactly like any other tool server. It reads an index that already exists and never
builds one:

- ``kde``: KDE's file index (Baloo, read with ``baloosearch6``): file names and, when KDE indexes
  file contents, words inside documents. It must be switched on (``balooctl6 enable``), which
  ``search_setup`` offers to do.
- ``locate``: the system's file-name database (``plocate``, refreshed daily by the distribution's
  timer). Names only. The database covers the whole disk, so results are kept to the user's home
  folder, and hidden folders and package caches are skipped.

One tool, ``find_files(query, limit)``, returns JSON ``{"results": [{"path", "name"}]}``, which
``instant_search.extract_hits`` reads. The protocol loop is ``mcp_serve.serve_lines``. Each search
runs the index program once with a ``SEARCH_TIMEOUT_SECONDS`` limit; a missing program or index
comes back as a tool error whose text says what to do, never as a crash.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import __version__
from .mcp_client import PROTOCOL_VERSION

INDEXES = ("kde", "locate")
TOOL_NAME = "find_files"
DEFAULT_LIMIT = 8
MAX_LIMIT = 50
MAX_WORDS = 6
SEARCH_TIMEOUT_SECONDS = 6
# plocate stops after this many matches across the whole disk; those outside home are dropped after.
LOCATE_SCAN = 2000
# Folders whose files are never what a person is looking for.
SKIPPED_FOLDERS = {"node_modules", "__pycache__", "site-packages", "venv", "target", "build", "dist"}

TOOL = {
    "name": TOOL_NAME,
    "description": "Find the user's files and folders by name (and, with KDE's file index, by words inside "
                   "documents). Returns paths.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words in the file's name, or in the document"},
            "limit": {"type": "integer", "description": f"Most results to return (default {DEFAULT_LIMIT})"},
        },
        "required": ["query"],
    },
}


class IndexUnavailable(RuntimeError):
    """The index program or its database is missing or switched off; the message says what to do."""


def _lines(command: list[str]) -> list[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=SEARCH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise IndexUnavailable("The file index took too long to answer.") from error
    return [line for line in completed.stdout.splitlines() if line.startswith("/")]


def _wanted(path: str, home: str) -> bool:
    if not path.startswith(home + os.sep):
        return False
    parts = path[len(home) + 1:].split(os.sep)
    return not any(part.startswith(".") or part in SKIPPED_FOLDERS for part in parts)


def _ranked(paths: list[str], words: list[str], limit: int) -> list[str]:
    """Names that contain the whole query first, then shorter paths (nearer the top of home)."""
    phrase = " ".join(words).lower()

    def key(path: str) -> tuple[int, int]:
        return (0 if phrase in os.path.basename(path).lower() else 1, path.count(os.sep))

    unique = list(dict.fromkeys(paths))
    return sorted(unique, key=key)[:limit]


def search_kde(words: list[str], limit: int, home: str) -> list[str]:
    if not shutil.which("baloosearch6"):
        raise IndexUnavailable("KDE's file index is not installed (the 'baloosearch6' program is missing).")
    found = [path for path in _lines(["baloosearch6", "-l", str(limit * 4), "-d", home, *words])
             if _wanted(path, home)]
    return _ranked(found, words, limit)


def search_locate(words: list[str], limit: int, home: str) -> list[str]:
    program = shutil.which("plocate")
    if not program:
        raise IndexUnavailable("The file-name database is not installed (the 'plocate' program is missing).")
    found = [path for path in _lines([program, "-i", "-b", "-l", str(LOCATE_SCAN), "--", *words])
             if _wanted(path, home)]
    return _ranked(found, words, limit)


def find_files(index: str, query: str, limit: int = DEFAULT_LIMIT, home: str | None = None) -> list[dict[str, str]]:
    words = query.split()[:MAX_WORDS]
    if not words:
        return []
    limit = max(1, min(MAX_LIMIT, limit))
    home = (home or str(Path.home())).rstrip(os.sep)
    paths = search_kde(words, limit, home) if index == "kde" else search_locate(words, limit, home)
    return [{"path": path, "name": os.path.basename(path)} for path in paths]


def handle(message: dict[str, Any], index: str) -> dict[str, Any] | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    if "id" not in message:
        return None
    method, ident = message.get("method"), message["id"]

    def reply(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    if method == "initialize":
        return reply({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": f"happy-bot-files-{index}", "version": __version__}})
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": [TOOL]})
    if method == "tools/call":
        params = message.get("params") or {}
        arguments = params.get("arguments") or {}
        if params.get("name") != TOOL_NAME:
            return reply({"content": [{"type": "text", "text": f"unknown tool {params.get('name')!r}"}], "isError": True})
        try:
            limit = int(arguments.get("limit") or DEFAULT_LIMIT)
            results = find_files(index, str(arguments.get("query") or ""), limit)
        except (IndexUnavailable, OSError, ValueError) as error:
            return reply({"content": [{"type": "text", "text": str(error)}], "isError": True})
        structured = {"results": results}
        return reply({"content": [{"type": "text", "text": json.dumps(structured)}], "structuredContent": structured})
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(index: str) -> int:
    from .mcp_serve import serve_lines

    return serve_lines(lambda message: handle(message, index))

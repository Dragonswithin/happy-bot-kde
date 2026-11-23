"""The search bar's no-model path: query the user's file-search tool, return hits.

While the user types, the applet asks the daemon for matches and shows them
without involving a model. This module runs the tool assigned to the
``file_search`` role and converts whatever it returns into a uniform list of
hits the applet can display and open.

Search tools do not share an output format, so ``extract_hits`` is
deliberately tolerant: it takes the tool's structured content if present,
else parses its text as JSON, and walks the result for objects that carry a
location under a commonly used key (``path``, ``url``, ...). If nothing
parses, absolute paths and URLs are pulled from the raw text. A tool whose
output yields no locations simply produces no hits.

A hit is ``{"title", "location", "snippet", "kind"}`` where ``kind`` is
``file``, ``folder`` or ``link``. ``location`` is an absolute path or an
http(s) URL. Paths are not checked for existence beyond telling folders from
files, because the index may know files on unmounted media.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import unquote, urlparse

from .mcp_client import McpError, McpManager, ToolResult
from .tool_roles import call_role

SEARCH_TIMEOUT_SECONDS = 8.0
MAX_HITS = 20
SNIPPET_CHARS = 200
LOCATION_KEYS = ("path", "file_path", "filepath", "file", "filename", "uri", "url", "link", "href", "location")
TITLE_KEYS = ("title", "name", "caption", "label")
SNIPPET_KEYS = ("excerpt", "snippet", "summary", "description", "content", "text", "preview")
_TEXT_LOCATION = re.compile(r"""(https?://[^\s"'<>)\]]+|(?<![\w.])/(?:[^\s"'<>:|]+/)*[^\s"'<>:|/]+)""")


def _normalise_location(value: Any) -> tuple[str, str] | None:
    """Return ``(location, kind)`` for an absolute path or web URL, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return text, "link"
    if text.startswith("file://"):
        text = unquote(urlparse(text).path)
    if not text.startswith("/") or "\n" in text:
        return None
    return text, "folder" if os.path.isdir(text) else "file"


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _hit_from_object(item: dict[str, Any]) -> dict[str, str] | None:
    for key in LOCATION_KEYS:
        located = _normalise_location(item.get(key))
        if located is None:
            continue
        location, kind = located
        title = _first_text(item, TITLE_KEYS)
        if not title:
            title = location if kind == "link" else (os.path.basename(location.rstrip("/")) or location)
        snippet = " ".join(_first_text(item, SNIPPET_KEYS).split())
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[: SNIPPET_CHARS - 1].rstrip() + "…"
        return {"title": title, "location": location, "snippet": snippet, "kind": kind}
    return None


def _walk(value: Any, found: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        hit = _hit_from_object(value)
        if hit is not None:
            found.append(hit)
            return
        for child in value.values():
            _walk(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk(child, found)


def extract_hits(result: ToolResult, limit: int = MAX_HITS) -> list[dict[str, str]]:
    """Convert a search tool's result into at most ``limit`` unique hits, in order."""
    found: list[dict[str, str]] = []
    data = result.structured
    if data is None and result.text.strip():
        try:
            data = json.loads(result.text)
        except ValueError:
            data = None
    if data is not None:
        _walk(data, found)
    if not found:
        for match in _TEXT_LOCATION.findall(result.text):
            located = _normalise_location(match.rstrip(".,;"))
            if located is not None:
                location, kind = located
                title = location if kind == "link" else os.path.basename(location.rstrip("/"))
                found.append({"title": title, "location": location, "snippet": "", "kind": kind})
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for hit in found:
        if hit["location"] not in seen:
            seen.add(hit["location"])
            unique.append(hit)
        if len(unique) >= limit:
            break
    return unique


def search_files(
    manager: McpManager,
    settings: dict[str, Any],
    query: str,
    limit: int = MAX_HITS,
    timeout: float = SEARCH_TIMEOUT_SECONDS,
) -> list[dict[str, str]]:
    """Run the ``file_search`` role. Raises ``RoleNotConfigured`` or ``McpError``."""
    result = call_role(manager, settings, "file_search", query, timeout)
    if result.is_error:
        raise McpError(f"the file search tool reported an error: {result.text[:300]}")
    return extract_hits(result, limit)

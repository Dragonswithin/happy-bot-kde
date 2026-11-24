"""Export and import of everything the assistant keeps for the user: settings and conversations.

``export_data`` gathers the settings in their redacted form (API keys, header
values and tool-server environment values are left out as ``null``, so an
export file never carries a secret) and every saved conversation in full.
``import_data`` takes such a file back: its settings replace the current
ones through ``AssistantServer.replace_settings`` (validated like any save;
a ``null`` secret keeps the value stored on this computer, or is dropped if
there is none), and each conversation not already present is added to the
archive. The CLI's ``export`` and ``import`` commands write and read the file
(``GET /export``, ``POST /import``); moving to another computer is export
there, import here, then typing the API keys again.

The file format is ``{"format": FORMAT, "version": 1, "exported", "settings",
"conversations": [...]}``; anything else is refused.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from . import settings as settings_store
from .conversation_archive import valid_id

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

FORMAT = "happy-bot-export"
VERSION = 1


class BadExport(ValueError):
    """The file is not an export this version understands; the message says why."""


def export_data(server: "AssistantServer") -> dict[str, Any]:
    archive = server.conversations.archive
    conversations = [record for record in (archive.load(item["id"]) for item in archive.list()) if record]
    return {"format": FORMAT, "version": VERSION, "exported": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "settings": settings_store.redacted(server.settings), "conversations": conversations}


def import_data(server: "AssistantServer", data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BadExport("this is not a Happy Bot export file")
    if data.get("version") != VERSION:
        raise BadExport(f"export version {data.get('version')} is not supported")
    stored = server.replace_settings(settings_store.merge_redacted(data.get("settings"), server.settings))
    archive = server.conversations.archive
    existing = {item["id"] for item in archive.list()}
    added = 0
    for record in data.get("conversations") or []:
        if isinstance(record, dict) and valid_id(str(record.get("id", ""))) and record["id"] not in existing:
            archive.save(record)
            added += 1
    missing = [name for name, model in stored["models"].items() if not model.get("api_key")
               and not model["base_url"].startswith(("http://127.", "http://localhost"))]
    return {"conversations_added": added, "models_needing_keys": missing}

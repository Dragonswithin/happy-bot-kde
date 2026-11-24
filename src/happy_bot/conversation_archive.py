"""Saves conversations to disk so the user can go back to them later.

Each conversation is one JSON file, written 0600 in
``$XDG_DATA_HOME/happy-bot/conversations/`` (default
``~/.local/share/...``, directory 0700). A file holds:

- ``id``, ``title`` (the first request, shortened), ``created`` and
  ``updated`` (Unix seconds);
- ``messages``: the model-level history (``conversation.Message`` objects,
  tool calls and results included), so a reopened conversation continues
  with full context;
- ``pinned``: the user pinned it: listed first and never expired;
- ``events``: what the popup needs to redraw it, in order: the user's
  requests, text, tool calls and results, approvals, errors. Consecutive
  text pieces are stored joined.

Conversations can contain whatever the assistant read for the user
(clipboard text, file contents, web pages), which is why the files are
private to the user and kept only for ``days`` days after their last use:
older files are deleted on start, on every save, and when the setting
changes, except ``pinned`` ones, which the user chose to keep. ``days`` 0
means nothing is saved and existing files are removed.

Conversation ids are checked against the id alphabet before they are used
in a path. Reads skip unreadable or malformed files rather than fail.
Writes are atomic (``runtime_paths.write_private_file``). Calls are not
locked here; ``ConversationStore`` serialises them.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .conversation import Message, ToolCall
from .runtime_paths import APP_DIR_NAME, write_private_file

ARCHIVE_VERSION = 1
TITLE_CHARS = 80
MAX_LISTED = 200
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def archive_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME / "conversations"


def valid_id(conversation_id: str) -> bool:
    return bool(_ID_PATTERN.match(conversation_id or ""))


def make_title(request: str) -> str:
    text = " ".join(request.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def message_to_json(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.role, "text": message.text}
    if message.tool_calls:
        data["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments, "arguments_error": call.arguments_error}
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.echo:
        data["echo"] = message.echo
    if message.context:
        data["context"] = message.context
    if message.private:
        data["private"] = True
    for call, saved in zip(message.tool_calls, data.get("tool_calls") or []):
        if call.echo:
            saved["echo"] = call.echo
    return data


def message_from_json(data: dict[str, Any]) -> Message:
    calls = tuple(
        ToolCall(str(call["id"]), str(call["name"]), dict(call.get("arguments") or {}), str(call.get("arguments_error") or ""),
                 str(call.get("echo") or ""))
        for call in data.get("tool_calls") or []
    )
    return Message(str(data["role"]), str(data.get("text") or ""), calls, str(data.get("tool_call_id") or ""),
                   str(data.get("echo") or ""), str(data.get("context") or ""), data.get("private") is True)


class ConversationArchive:
    def __init__(self, directory: Path | None = None, days: int = 30) -> None:
        self.directory = directory or archive_dir()
        self.days = days

    @property
    def enabled(self) -> bool:
        return self.days > 0

    def _path(self, conversation_id: str) -> Path | None:
        return self.directory / f"{conversation_id}.json" if valid_id(conversation_id) else None

    def _files(self) -> list[Path]:
        try:
            return [path for path in self.directory.iterdir() if path.suffix == ".json"]
        except OSError:
            return []

    def save(self, record: dict[str, Any]) -> None:
        """Write one conversation (see the module docstring for the fields)."""
        if not self.enabled:
            return
        path = self._path(str(record.get("id", "")))
        if path is None:
            return
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private_file(path, json.dumps({"version": ARCHIVE_VERSION, **record}, ensure_ascii=False))
        self.prune()

    def load(self, conversation_id: str) -> dict[str, Any] | None:
        path = self._path(conversation_id)
        if path is None:
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or record.get("id") != conversation_id:
            return None
        return record

    def list(self) -> list[dict[str, Any]]:
        """Summaries, newest first: ``{id, title, created, updated, requests}``."""
        summaries = []
        for path in self._files():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or not valid_id(str(record.get("id", ""))):
                continue
            events = record.get("events") or []
            summaries.append({
                "id": record["id"],
                "title": str(record.get("title") or ""),
                "created": float(record.get("created") or 0),
                "updated": float(record.get("updated") or 0),
                "pinned": record.get("pinned") is True,
                "requests": sum(1 for event in events if isinstance(event, dict) and event.get("type") == "user"),
            })
        summaries.sort(key=lambda item: item["updated"], reverse=True)
        return summaries[:MAX_LISTED]

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        if path is None:
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def delete_all(self) -> int:
        removed = 0
        for path in self._files():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def prune(self, now: float | None = None) -> int:
        """Delete conversations unused for longer than ``days`` (all of them when 0)."""
        if not self.enabled:
            return self.delete_all()
        cutoff = (now or time.time()) - self.days * 86400
        removed = 0
        for path in self._files():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                updated = float(record.get("updated") or 0) if isinstance(record, dict) else 0
                pinned = isinstance(record, dict) and record.get("pinned") is True
            except (OSError, ValueError):
                updated, pinned = (path.stat().st_mtime if path.exists() else 0), False
            if updated < cutoff and not pinned:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

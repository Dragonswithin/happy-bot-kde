"""Conversations between the user and the assistant, in memory and on disk.

The daemon keeps each conversation's message history so follow-up requests
have context. A conversation is identified by an opaque id the client holds.
``ConversationStore`` keeps the most recently used ones in memory (up to
``MAX_CONVERSATIONS``) and, through a ``ConversationArchive``, saves each one
after every turn and loads it again when the user goes back to it, so a
conversation survives the popup closing, the daemon restarting and logout,
for as long as the archive keeps it.

Each ``Conversation`` carries, besides the model history, the display
``events`` the popup replays to redraw it, a title and timestamps. Its
``turn_lock`` is held by the caller for the length of a turn, so one
conversation never runs two turns at once, and its ``cancel`` event is what
that turn checks to stop.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .conversation import Message
from .conversation_archive import ConversationArchive, make_title, message_from_json, message_to_json

MAX_CONVERSATIONS = 20
MAX_EVENT_TEXT = 20000


@dataclass
class Conversation:
    id: str
    history: list[Message] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    title: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    turn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    last_used: float = field(default_factory=time.monotonic)

    def record(self, event: dict[str, Any]) -> None:
        """Keep an event for replay. Text pieces are joined; liveness-only events (start, thinking,
        progress lines) are dropped."""
        kind = event.get("type")
        if kind in ("start", "thinking", "tool_progress"):
            return
        if kind == "text_delta" and self.events and self.events[-1].get("type") == "text_delta":
            joined = self.events[-1]["text"] + str(event.get("text", ""))
            self.events[-1] = {"type": "text_delta", "text": joined[:MAX_EVENT_TEXT]}
            return
        if kind == "tool_result":
            event = {**event, "text": str(event.get("text", ""))[:500]}
        self.events.append(dict(event))

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "created": self.created, "updated": self.updated,
            "messages": [message_to_json(message) for message in self.history], "events": self.events,
        }


def conversation_from_record(record: dict[str, Any]) -> Conversation:
    return Conversation(
        id=str(record["id"]),
        history=[message_from_json(item) for item in record.get("messages") or [] if isinstance(item, dict)],
        events=[item for item in record.get("events") or [] if isinstance(item, dict)],
        title=str(record.get("title") or ""),
        created=float(record.get("created") or time.time()),
        updated=float(record.get("updated") or time.time()),
    )


class ConversationStore:
    def __init__(self, archive: ConversationArchive | None = None) -> None:
        self._lock = threading.Lock()
        self._conversations: dict[str, Conversation] = {}
        self.archive = archive or ConversationArchive(days=0)

    def _evict(self) -> None:
        idle = sorted(
            (item for item in self._conversations.values() if not item.turn_lock.locked()),
            key=lambda item: item.last_used,
        )
        while len(self._conversations) > MAX_CONVERSATIONS and idle:
            del self._conversations[idle.pop(0).id]

    def get(self, conversation_id: str) -> Conversation | None:
        """The conversation with this id from memory or the archive, else None."""
        if not conversation_id:
            return None
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                record = self.archive.load(conversation_id)
                if record is None:
                    return None
                conversation = conversation_from_record(record)
                self._conversations[conversation.id] = conversation
                self._evict()
            conversation.last_used = time.monotonic()
            return conversation

    def get_or_create(self, conversation_id: str = "") -> Conversation:
        """Return the conversation with this id, or a new one if it is unknown or empty."""
        conversation = self.get(conversation_id)
        if conversation is not None:
            return conversation
        with self._lock:
            conversation = Conversation(id=secrets.token_urlsafe(12))
            self._conversations[conversation.id] = conversation
            self._evict()
            return conversation

    def begin_turn(self, conversation: Conversation, request: str) -> None:
        """Note a new request: sets the title on the first one and records it for replay."""
        if not conversation.title:
            conversation.title = make_title(request)
        conversation.record({"type": "user", "text": request})

    def save(self, conversation: Conversation) -> None:
        conversation.updated = time.time()
        try:
            self.archive.save(conversation.to_record())
        except OSError:
            pass  # history is a convenience; a full disk must not fail the turn

    def forget(self, conversation_id: str) -> None:
        """Drop a conversation from memory without saving it (requests marked ephemeral)."""
        with self._lock:
            self._conversations.pop(conversation_id, None)

    def list(self) -> list[dict[str, Any]]:
        """Saved conversations, newest first, plus unsaved ones still in memory."""
        listed = {item["id"]: item for item in self.archive.list()}
        with self._lock:
            for conversation in self._conversations.values():
                if conversation.id not in listed and conversation.events:
                    listed[conversation.id] = {
                        "id": conversation.id, "title": conversation.title, "created": conversation.created,
                        "updated": conversation.updated,
                        "requests": sum(1 for event in conversation.events if event.get("type") == "user"),
                    }
        return sorted(listed.values(), key=lambda item: item["updated"], reverse=True)

    def delete(self, conversation_id: str) -> bool:
        with self._lock:
            in_memory = self._conversations.pop(conversation_id, None) is not None
        return self.archive.delete(conversation_id) or in_memory

    def delete_all(self) -> int:
        with self._lock:
            idle = [key for key, item in self._conversations.items() if not item.turn_lock.locked()]
            for key in idle:
                del self._conversations[key]
        return self.archive.delete_all()

    def cancel(self, conversation_id: str) -> bool:
        """Ask a running turn to stop. Returns False if the conversation is unknown."""
        with self._lock:
            conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return False
        conversation.cancel.set()
        return True

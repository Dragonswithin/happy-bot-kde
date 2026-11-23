"""In-memory conversations between the user and the assistant.

The daemon keeps each conversation's message history so follow-up requests
have context. A conversation is identified by an opaque id the client holds;
nothing is written to disk, and conversations vanish when the daemon stops.

``ConversationStore`` hands out conversations and forgets the least recently
used ones beyond ``MAX_CONVERSATIONS``. Each ``Conversation`` carries a lock
that the caller holds for the length of a turn, so one conversation never
runs two turns at once, and a ``cancel`` event the turn checks.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from .conversation import Message

MAX_CONVERSATIONS = 20


@dataclass
class Conversation:
    id: str
    history: list[Message] = field(default_factory=list)
    turn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    last_used: float = field(default_factory=time.monotonic)


class ConversationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conversations: dict[str, Conversation] = {}

    def get_or_create(self, conversation_id: str = "") -> Conversation:
        """Return the conversation with this id, or a new one if it is unknown or empty."""
        with self._lock:
            conversation = self._conversations.get(conversation_id) if conversation_id else None
            if conversation is None:
                conversation = Conversation(id=secrets.token_urlsafe(12))
                self._conversations[conversation.id] = conversation
                idle = sorted(
                    (item for item in self._conversations.values() if not item.turn_lock.locked()),
                    key=lambda item: item.last_used,
                )
                while len(self._conversations) > MAX_CONVERSATIONS and idle:
                    del self._conversations[idle.pop(0).id]
            conversation.last_used = time.monotonic()
            return conversation

    def cancel(self, conversation_id: str) -> bool:
        """Ask a running turn to stop. Returns False if the conversation is unknown."""
        with self._lock:
            conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return False
        conversation.cancel.set()
        return True

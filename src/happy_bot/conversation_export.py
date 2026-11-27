"""Save user-visible chat messages to a private Markdown file selected in Settings."""

from __future__ import annotations

import os
import tempfile
from itertools import groupby
from pathlib import Path

from .conversations import Conversation, ConversationStore


def _turns(messages):
    turns = []
    for role, text in messages:
        if not text or role not in ("user", "assistant"):
            continue
        if role == "user" or not turns:
            turns.append([])
        turns[-1].append((role, text))
    return turns


def _markdown(chat: Conversation, level: int) -> str:
    # Model history has complete replies. Replay events can also contain partial
    # replies from interrupted turns, but their saved text is length-limited.
    events_snapshot = chat.events.copy()
    full = _turns((m.role, m.text) for m in chat.history.copy())
    display = []
    for kind, events in groupby(events_snapshot, key=lambda e: e.get("type")):
        if kind == "user":
            display.extend(("user", e["text"]) for e in events)
        elif kind == "text_delta":
            display.append(("assistant", "".join(e.get("text", "") for e in events)))
    visible = _turns(display)
    title = " ".join(chat.title.split()) or "Untitled conversation"
    parts = [f"{'#' * level} {title}"]
    for index in range(max(len(full), len(visible))):
        messages = list(full[index]) if index < len(full) else []
        if index < len(visible):
            # A cancelled stream may have displayed another reply before it
            # could append that reply to the provider history.
            messages.extend(visible[index][len(messages):])
        for role, text in messages:
            speaker = "You" if role == "user" else "Happy Bot"
            parts.append(f"{'#' * (level + 1)} {speaker}\n\n{text}")
    return "\n\n".join(parts)


def save_markdown(store: ConversationStore, path: Path, conversation_id: str | None) -> int:
    if not path.is_absolute() or path.suffix.lower() != ".md":
        raise ValueError("Choose a local Markdown (.md) file.")
    if conversation_id is None:
        ids = [item["id"] for item in sorted(store.list(), key=lambda item: (item["created"], item["id"]))]
    else:
        ids = [conversation_id]
    if not ids:
        raise ValueError("There are no conversations to export.")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            if conversation_id is None:
                output.write("# Happy Bot conversations\n\n")
            for index, chat_id in enumerate(ids):
                chat = store.get(chat_id)
                if chat is None:
                    raise ValueError("A selected conversation is no longer available. Reopen the export picker.")
                if index:
                    output.write("\n")
                output.write(_markdown(chat, 1 if conversation_id is not None else 2) + "\n")
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return len(ids)

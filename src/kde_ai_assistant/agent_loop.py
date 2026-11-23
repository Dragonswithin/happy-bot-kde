"""Runs one user turn: model request, tool calls, results, repeat until an answer.

This is the provider-neutral and tool-neutral core of the assistant. Given a
conversation history, a ``ModelProvider`` and a ``ToolRegistry``, ``run_turn``
sends the conversation to the model, relays streamed text, runs each tool the
model asks for, appends the results, and asks again, until the model answers
without tool calls, ``MAX_STEPS`` model requests have been made, the turn is
cancelled, or the provider fails.

Progress is reported through ``emit`` as JSON-serialisable events, in order:

- ``{"type": "thinking"}`` (at most once per model request)
- ``{"type": "text_delta", "text": ...}``
- ``{"type": "tool_call", "id", "name", "arguments", "risk"}``
- ``{"type": "tool_result", "id", "name", "ok", "text"}``
- then exactly one of ``{"type": "done", "stop": "answered"|"cancelled"|"step_limit"}``
  or ``{"type": "error", "message": ...}``

History contract: ``history`` is mutated in place and is always left valid
for the next request. An assistant message is appended only when its stream
completed, and every tool call in it gets a tool message, including calls
skipped because the turn was cancelled. A failed or cancelled model request
appends nothing.

Blocking: runs on the caller's thread for the whole turn; tools run
sequentially in the model's order.
"""

from __future__ import annotations

import datetime
import os
import platform
import threading
from typing import Any, Callable

from .conversation import Message, TextDelta, ThinkingDelta, ToolCallReady, TurnEnd, trim_history
from .providers.base import ModelProvider, ProviderError
from .tools.registry import ToolRegistry

MAX_STEPS = 12
EVENT_RESULT_CHARS = 2000
Emit = Callable[[dict[str, Any]], None]


def system_prompt() -> str:
    """Instructions given to the model at the start of every conversation."""
    now = datetime.datetime.now().astimezone().strftime("%A, %d %B %Y, %H:%M %Z")
    return "\n".join([
        "You are the assistant built into the user's KDE Plasma desktop. The user types a request into a "
        "search bar on their panel and you carry it out or answer it.",
        "",
        "How to work:",
        "- Use the tools. Do not guess at facts about this computer, its files, or current events; look them up.",
        "- To find the user's files or documents, use the tool described as preferred for local files. Search "
        "words, not sentences, and try other wording if the first search misses.",
        "- For news or anything that may have changed recently, use the tool described as preferred for the web, "
        "and give the links you relied on.",
        "- You can only do what the tools allow. If nothing fits, say so plainly instead of pretending.",
        "- Answers appear in a small popup. Be brief and direct. Give full paths for files and full URLs for "
        "links, each on its own line, so the user can open them.",
        "- If a tool fails, read the error, fix the call or try another way, and tell the user if it still fails.",
        "",
        f"Now: {now}. User: {os.environ.get('USER', '')}. Home: {os.path.expanduser('~')}. "
        f"Host: {platform.node()}.",
    ])


def run_turn(
    provider: ModelProvider,
    history: list[Message],
    registry: ToolRegistry,
    emit: Emit,
    cancel: threading.Event,
    context_window: int = 32768,
    max_steps: int = MAX_STEPS,
) -> None:
    """Run the turn whose user message is the last entry of ``history`` (see module docstring)."""
    specs = registry.specs()
    for _step in range(max_steps):
        if cancel.is_set():
            emit({"type": "done", "stop": "cancelled"})
            return
        text_parts: list[str] = []
        calls = []
        thinking_reported = False
        try:
            for event in provider.stream(trim_history(history, context_window), specs, cancel):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    emit({"type": "text_delta", "text": event.text})
                elif isinstance(event, ThinkingDelta):
                    if not thinking_reported:
                        thinking_reported = True
                        emit({"type": "thinking"})
                elif isinstance(event, ToolCallReady):
                    calls.append(event.call)
                elif isinstance(event, TurnEnd) and event.stop_reason == "cancelled":
                    cancel.set()
        except ProviderError as error:
            emit({"type": "error", "message": str(error)})
            return
        if cancel.is_set():
            emit({"type": "done", "stop": "cancelled"})
            return

        history.append(Message("assistant", "".join(text_parts), tuple(calls)))
        if not calls:
            emit({"type": "done", "stop": "answered"})
            return

        for call in calls:
            tool = registry.get(call.name)
            if cancel.is_set():
                history.append(Message("tool", "Not run: the user cancelled.", tool_call_id=call.id))
                continue
            emit({
                "type": "tool_call", "id": call.id, "name": call.name,
                "arguments": call.arguments, "risk": tool.risk if tool else "",
            })
            if call.arguments_error:
                ok, text = False, f"The call was not run: {call.arguments_error}. Send the arguments as a JSON object."
            else:
                ok, text = registry.run(call.name, call.arguments)
            history.append(Message("tool", text, tool_call_id=call.id))
            emit({"type": "tool_result", "id": call.id, "name": call.name, "ok": ok, "text": text[:EVENT_RESULT_CHARS]})

    emit({"type": "done", "stop": "step_limit"})

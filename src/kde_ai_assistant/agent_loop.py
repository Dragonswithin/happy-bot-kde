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
- ``{"type": "tool_call", "id", "name", "arguments", "risk", "summary"}``
- approval events from the permission gate, when the call needs the user
  (see ``permissions``)
- ``{"type": "tool_result", "id", "name", "ok", "text"}``
- then exactly one of ``{"type": "done", "stop": "answered"|"cancelled"|"step_limit"}``
  or ``{"type": "error", "message": ...}``

History contract: ``history`` is mutated in place and is always left valid
for the next request. An assistant message is appended only when its stream
completed, and every tool call in it gets a tool message, including calls
skipped because the turn was cancelled. A failed or cancelled model request
appends nothing.

Each call is assessed (``ToolRegistry.assess``), prechecked so a call that
cannot succeed fails without bothering the user, and, when a ``gate`` is
given, passed to it before running. A call the gate refuses is not run and
its refusal text becomes the tool result, so the model can respond to it.

Blocking: runs on the caller's thread for the whole turn; tools run
sequentially in the model's order, and a turn waits while the user decides
on an approval.
"""

from __future__ import annotations

import datetime
import os
import platform
import threading
from typing import Any, Callable

from .conversation import Message, TextDelta, ThinkingDelta, ToolCallReady, TurnEnd, trim_history
from .permissions import PermissionGate
from .providers.base import ModelProvider, ProviderError
from .tools.registry import ToolRegistry

# Operating an application's interface takes a snapshot, an action and a
# check per step of the task, so a turn needs room for a few dozen requests.
MAX_STEPS = 40
EVENT_RESULT_CHARS = 2000
Emit = Callable[[dict[str, Any]], None]


def user_folders(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """The user's standard folders (Desktop, Documents, ...).

    Each comes from the first source that names it: ``overrides`` (the
    assistant's ``folders`` setting), then the system's ``user-dirs.dirs``
    (what KDE's Locations page writes), then ``~/<Name>``.
    """
    home = os.path.expanduser("~")
    folders = {name: os.path.join(home, name) for name in ("Desktop", "Documents", "Downloads", "Pictures")}
    config = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "user-dirs.dirs")
    keys = {"XDG_DESKTOP_DIR": "Desktop", "XDG_DOCUMENTS_DIR": "Documents", "XDG_DOWNLOAD_DIR": "Downloads",
            "XDG_PICTURES_DIR": "Pictures", "XDG_MUSIC_DIR": "Music", "XDG_VIDEOS_DIR": "Videos"}
    try:
        with open(config, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key in keys and value:
                    folders[keys[key]] = value.strip('"').replace("$HOME", home)
    except OSError:
        pass
    folders.update(overrides or {})
    return folders


def system_prompt(folder_overrides: dict[str, str] | None = None) -> str:
    """Instructions given to the model at the start of every conversation."""
    now = datetime.datetime.now().astimezone().strftime("%A, %d %B %Y, %H:%M %Z")
    lines = [
        "You are the assistant built into the user's KDE Plasma desktop. The user types a request into a "
        "search bar on their panel and you carry it out or answer it.",
        "",
        "How to work:",
        "- Use the tools. Do not guess at facts about this computer, its files, or current events; look them up.",
        "- You can act on this computer with the tools: open and arrange windows, start applications, change "
        "settings, sound, network and displays, work with files, and run shell commands. Prefer a specific tool "
        "over a shell command when one fits. Do the task; do not just describe how.",
        "- To operate another application's window (click a button, choose a menu entry, fill a field), call "
        "ui_snapshot first, then ui_press or ui_set_text with a ref from it, then ui_snapshot again to see what "
        "changed. 'This window' or 'this dialog' means the window named 'current'. Window titles change as you "
        "work, so after the first call refer to a window by the id the tools report. A press can open a dialog, "
        "which is a separate window with its own id; the result tells you.",
        "- Actions that delete things or change the operating system pause for the user's approval automatically. "
        "Do not ask for permission yourself, and if the user declines, do not try another route to the same result.",
        "- To find the user's files or documents, use the tool described as preferred for local files. Search "
        "words, not sentences, and try other wording if the first search misses.",
        "- For news or anything that may have changed recently, use the tool described as preferred for the web, "
        "and give the links you relied on.",
        "- You can only do what the tools allow. If nothing fits, say so plainly instead of pretending.",
        "- Answers appear in a small popup. Be brief and direct. Give full paths for files and full URLs for "
        "links, each on its own line, so the user can open them. After acting, say in one line what you did.",
        "- If a tool fails, read the error, fix the call or try another way, and tell the user if it still fails.",
        "",
        f"Now: {now}. User: {os.environ.get('USER', '')}. Home: {os.path.expanduser('~')}. "
        f"Host: {platform.node()}.",
        "Folders: " + ", ".join(f"{name} is {path}" for name, path in user_folders(folder_overrides).items()) + ".",
    ]
    return "\n".join(lines)


def run_turn(
    provider: ModelProvider,
    history: list[Message],
    registry: ToolRegistry,
    emit: Emit,
    cancel: threading.Event,
    context_window: int = 32768,
    max_steps: int = MAX_STEPS,
    gate: PermissionGate | None = None,
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
            if cancel.is_set():
                history.append(Message("tool", "Not run: the user cancelled.", tool_call_id=call.id))
                continue
            risk, summary, detail = registry.assess(call.name, call.arguments)
            emit({
                "type": "tool_call", "id": call.id, "name": call.name,
                "arguments": call.arguments, "risk": risk, "summary": summary,
            })
            if call.arguments_error:
                ok, text = False, f"The call was not run: {call.arguments_error}. Send the arguments as a JSON object."
            elif registry.get(call.name) is None:
                ok, text = registry.run(call.name, call.arguments)
            else:
                impossible = registry.precheck(call.name, call.arguments)
                if impossible:
                    ok, text = False, impossible
                else:
                    allowed, refusal = (True, "") if gate is None else gate.check(
                        call.id, call.name, call.arguments, risk, summary, detail)
                    ok, text = registry.run(call.name, call.arguments) if allowed else (False, refusal)
            history.append(Message("tool", text, tool_call_id=call.id))
            emit({"type": "tool_result", "id": call.id, "name": call.name, "ok": ok, "text": text[:EVENT_RESULT_CHARS]})

    emit({"type": "done", "stop": "step_limit"})

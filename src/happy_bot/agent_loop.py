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
- ``{"type": "tool_progress", "id", "text"}`` while a long tool runs (at most
  one per ``PROGRESS_INTERVAL_SECONDS``; see ``tools.registry.call_context``)
- ``{"type": "tool_result", "id", "name", "ok", "text"}``, plus ``"card"`` when
  the tool draws its successful result as a card (``Tool.card``)
- then exactly one of ``{"type": "done", "stop": "answered"|"cancelled"|"step_limit",
  "actions": [...]}`` or ``{"type": "error", "message": ...}``

``usage`` adds up the tokens the service reported over the turn's model
requests (``{"input_tokens", "output_tokens", "requests"}``), for the
spending record (``spend``) and the popup.

``actions`` is the turn's record of every call that was not a pure read:
``{"summary", "outcome"}`` with outcome ``done``, ``failed``, ``declined``
(the permission gate refused it) or ``not_run`` (it could not run, or the
turn was cancelled first). The popup shows what was not done after the
answer, so a model that claims an action it was refused is contradicted by
the record rather than believed.

When ``redact`` is true (a hosted model), tool results pass through
``redaction.redact`` before they are added to the history, so passwords,
API keys and private keys a tool happened to read are not sent off the
computer; the popup's own copy of the result is redacted the same way.

History contract: ``history`` is mutated in place and is always left valid
for the next request. An assistant message is appended only when its stream
completed, and every tool call in it gets a tool message, including calls
skipped because the turn was cancelled. A failed or cancelled model request
appends nothing.

Each call is assessed (``ToolRegistry.assess``), prechecked so a call that
cannot succeed fails without bothering the user, and, when a ``gate`` is
given, passed to it before running. A call the gate refuses is not run and
its refusal text becomes the tool result, so the model can respond to it.

A ``danger`` call (one that needs approval) identical to one that already
succeeded earlier in the same turn is not run and not put to the user: the
model is told the step is done. Local models sometimes lose track after a
long install and start the task again; a failed call can still be retried.

Blocking: runs on the caller's thread for the whole turn; tools run
sequentially in the model's order, and a turn waits while the user decides
on an approval.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import threading
import time
from typing import Any, Callable

from .conversation import Message, TextDelta, ThinkingDelta, ToolCallReady, TurnEnd, trim_history
from .redaction import redact as redact_secrets
from .routines import prompt_lines
from .permissions import PermissionGate
from .providers.base import ModelProvider, ProviderError
from .tools.registry import RISK_DANGER, RISK_READ, CallContext, ToolRegistry, call_context

# Operating an application's interface takes a snapshot, an action and a
# check per step of the task, so a turn needs room for a few dozen requests.
MAX_STEPS = 40
PROGRESS_INTERVAL_SECONDS = 1.0
EVENT_RESULT_CHARS = 2000
ALREADY_DONE = ("Not run: this exact step already succeeded earlier in this request; its result is above. "
                "Do not repeat finished steps. Continue with what is left, or answer the user.")
Emit = Callable[[dict[str, Any]], None]


def user_folders(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """The user's standard folders (Desktop, Documents, ...).

    Each comes from the first source that names it: ``overrides`` (the
    assistant's ``folders`` setting), then the system's ``user-dirs.dirs``
    (what KDE's Locations page writes), then ``~/<Name>``.
    """
    home = os.path.expanduser("~")
    folders = {name: os.path.join(home, name)
               for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")}
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


def system_prompt(
    folder_overrides: dict[str, str] | None = None,
    instructions: str = "",
    unavailable: list[str] | None = None,
    confirm_plans: bool = False,
    routines: dict[str, Any] | None = None,
) -> str:
    """Instructions given to the model at the start of every conversation.

    ``instructions`` is the user's own text from the settings page (``agent.
    instructions``) and comes last, so it can change the guidance above it;
    the permission gate is enforced in code and is not affected by it. The
    user's preferences (where to install software from, asking before
    third-party sources, not stopping programs) live there, not here, so the
    user can see and change them; ``settings.SUGGESTED_INSTRUCTIONS`` is the
    starting text.
    ``unavailable`` describes the built-in tool groups the user switched off
    (``tools.catalog.GROUP_DESCRIPTIONS``). ``confirm_plans`` (the user's
    ``agent.confirm_plans`` setting) asks for a plan before multi-step
    changes. ``routines`` (the ``routines`` setting) are listed so the
    user can run one by name (``routines.prompt_lines``).
    """
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
        "- If a tool fails, read the error, fix the call or try another way, and tell the user if it still fails. "
        "Never repeat a command that failed or was stopped without changing something.",
        "- Installing software, and anything else that needs the user's password or takes many minutes (builds, "
        "large downloads), goes in run_in_terminal: the user watches it and types their password there. Tell the "
        "user it is waiting for them in the terminal. It returns when the command is done; report the outcome.",
        "- An install is finished only when the application can be opened. After installing an application, "
        "call verify_app_install. If it reports that the app is not visible, call refresh_app_menu, then tell "
        "the user what happened. Report success only after verification, and say how to open the app.",
        "",
        f"Now: {now}. User: {os.environ.get('USER', '')}. Home: {os.path.expanduser('~')}. "
        f"Host: {platform.node()}.",
        "Folders: " + ", ".join(f"{name} is {path}" for name, path in user_folders(folder_overrides).items()) + ".",
    ]
    lines += prompt_lines(routines or {})
    if confirm_plans:
        lines += ["", "Before a request that will change more than one thing, first reply with a short numbered "
                  "plan of the changes and ask the user to confirm. Look things up first if needed, but change "
                  "nothing until they agree. A single change, or anything read-only, needs no plan."]
    if unavailable:
        lines += ["", "The user has switched off these abilities in the assistant's settings: " + "; ".join(unavailable)
                  + ". If a request needs one, say that it is switched off in the settings; do not work around it."]
    if instructions.strip():
        lines += ["", "The user's own instructions. Follow them; where they differ from the guidance above, they win:",
                  instructions.strip()]
    return "\n".join(lines)


def _run_with_context(registry: ToolRegistry, call, emit: Emit, cancel: threading.Event) -> tuple[bool, str]:
    """Run one tool with a throttled progress reporter and the turn's cancel event."""
    last = [0.0]

    def progress(text: str) -> None:
        now = time.monotonic()
        if now - last[0] >= PROGRESS_INTERVAL_SECONDS:
            last[0] = now
            emit({"type": "tool_progress", "id": call.id, "text": " ".join(str(text).split())[:300]})

    token = call_context.set(CallContext(progress, cancel))
    try:
        return registry.run(call.name, call.arguments)
    finally:
        call_context.reset(token)


def run_turn(
    provider: ModelProvider,
    history: list[Message],
    registry: ToolRegistry,
    emit: Emit,
    cancel: threading.Event,
    context_window: int = 32768,
    max_steps: int = MAX_STEPS,
    gate: PermissionGate | None = None,
    redact: bool = False,
) -> None:
    """Run the turn whose user message is the last entry of ``history`` (see module docstring)."""
    specs = registry.specs()
    succeeded: set[tuple[str, str]] = set()  # danger calls that already succeeded this turn
    actions: list[dict[str, str]] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}

    def finish(stop: str) -> None:
        emit({"type": "done", "stop": stop, "actions": actions, "usage": usage})

    for _step in range(max_steps):
        if cancel.is_set():
            finish("cancelled")
            return
        text_parts: list[str] = []
        calls = []
        echo = ""
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
                elif isinstance(event, TurnEnd):
                    usage["requests"] += 1
                    usage["input_tokens"] += event.input_tokens
                    usage["output_tokens"] += event.output_tokens
                    echo = event.echo
                    if event.stop_reason == "cancelled":
                        cancel.set()
        except ProviderError as error:
            emit({"type": "error", "message": str(error)})
            return
        if cancel.is_set():
            finish("cancelled")
            return

        history.append(Message("assistant", "".join(text_parts), tuple(calls), echo=echo))
        if not calls:
            finish("answered")
            return

        for call in calls:
            if cancel.is_set():
                history.append(Message("tool", "Not run: the user cancelled.", tool_call_id=call.id))
                continue
            risk, summary, detail = registry.assess(call.name, call.arguments)
            outcome = "not_run"
            emit({
                "type": "tool_call", "id": call.id, "name": call.name,
                "arguments": call.arguments, "risk": risk, "summary": summary,
            })
            key = (call.name, json.dumps(call.arguments, sort_keys=True))
            if risk == RISK_DANGER and key in succeeded:
                ok, text = False, ALREADY_DONE
            elif call.arguments_error:
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
                    ok, text = _run_with_context(registry, call, emit, cancel) if allowed else (False, refusal)
                    outcome = ("done" if ok else "failed") if allowed else "declined"
            if ok and risk == RISK_DANGER:
                succeeded.add(key)
            if risk != RISK_READ:
                actions.append({"summary": summary, "outcome": outcome})
            if redact:
                text = redact_secrets(text)
            history.append(Message("tool", text, tool_call_id=call.id))
            event = {"type": "tool_result", "id": call.id, "name": call.name, "ok": ok, "text": text[:EVENT_RESULT_CHARS]}
            card = registry.card(call.name, text) if ok else None
            if card:
                event["card"] = card
            emit(event)

    finish("step_limit")

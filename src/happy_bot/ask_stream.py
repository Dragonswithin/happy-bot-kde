"""Serves one assistant turn for ``POST /ask`` as a stream of events.

Connects the HTTP layer to the agent loop: it picks the active model, builds
the tool registry, finds or creates the conversation, appends the user's
message, and runs ``agent_loop.run_turn``, forwarding every event to the
client as it happens. ``daemon_http`` owns the socket and passes ``send``, a
callable that writes one event and raises ``ClientGone`` when the client has
disconnected.

A body with ``"ephemeral": true`` is not kept in the conversation history
(``eval`` uses it). A body may name a configured ``model`` to use for this request instead of
the active one (``happy-bot eval --model``).

Routines and dry runs: the system prompt lists the user's routines, and the
registry includes the routine tools, which change settings through
``server.replace_settings`` exactly as the settings page does. A body with
``"dry_run": true`` offers only tools that cannot change anything
(``ToolRegistry.reads_only``) and asks the model to list the steps it would
take; ``happy-bot ask --dry-run`` uses it to try a routine safely.

Event stream, in addition to the agent loop's events (see ``agent_loop``):

- first: ``{"type": "start", "conversation_id", "model", "tools": [...],
  "warnings": [...]}``. The client sends ``conversation_id`` with follow-ups.
- an ``error`` event with ``code`` ``not_configured`` when no model is set
  up, or ``busy`` when this conversation already has a turn running.

Every tool is offered. A ``PermissionGate`` built from the
``approval_policy`` setting and the server's ``ApprovalBroker`` decides, per
call, whether it runs at once or waits for the user; its approval events
travel in this same stream and the answer arrives through ``POST /approve``.

Every event is also recorded on the conversation, and the conversation is
saved when the turn ends however it ends, so it can be reopened later (see
``conversations``).

The user's ``agent`` settings shape the turn: their instructions and the
abilities they switched off go into a new conversation's system prompt, the
switched-off tool groups are left out of the registry, and ``max_steps``
caps the model requests. A turn that takes longer than
``notify_after_seconds`` (0: never) ends with a desktop notification, so the
user learns it finished even with the popup closed; its Open button opens
the popup again.

Models: a priced model is refused once this month's spending reaches
``agent.monthly_spend_cap`` (``spend``). Every finished turn's tokens and
cost are recorded, and the ``done`` event names the model and its cost. If
the chosen model fails before it produced anything and a local
``agent.fallback_model`` is set, the turn is run again on the fallback, with
a ``{"type": "notice", "message"}`` event saying so; a hosted fallback is
never used automatically, so nothing is sent off the computer unasked.

Quick model: when ``agent.quick_model`` is set (and the request names no
model), every request starts on it with at most ``QUICK_MODEL_STEPS`` model
requests. If it fails, at any point, or uses them all without finishing, the
chosen model takes over the same conversation, which already holds the quick
model's steps and their results, after a notice saying so; the final ``done``
lists the actions of both. The quick model is skipped when it would break
"local only" or the spending cap, so the hand-over never sends anything
further than the chosen model would. When
a local model service says all its slots are busy (``model_busy``; services
with one slot queue requests), a notice says the request is waiting. With a hosted model
(``redaction.is_local_address`` false) tool results are redacted before they
are sent (see ``agent_loop``).
Work a tool deferred to after the turn (a Plasma shell restart requested by
``tools.app_visibility``) runs once the turn has finished streaming.

If the client disconnects, the turn is cancelled: the model request is
dropped at the next chunk and no further tools run. The history is left
valid either way.
"""

from __future__ import annotations

import copy
import json
import shutil
import threading
import urllib.request
import time
from typing import TYPE_CHECKING, Any, Callable

from . import desktop_actions
from . import settings as settings_store
from . import spend
from .agent_loop import run_turn, system_prompt
from .conversation import Message
from .desktop_context import run_command
from .permissions import PermissionGate
from .redaction import is_local_address
from .tools import app_visibility
from .providers import ProviderError, create_provider
from .tools.catalog import GROUP_DESCRIPTIONS, build_registry

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

MAX_MESSAGE_CHARS = 20000
DRY_RUN_PREFIX = ("Dry run: do not change anything (only look-up tools are available). Look up what you need, "
                  "then list exactly the steps you would take for this request, one per line:\n")


class ClientGone(ConnectionError):
    """The client closed the connection while events were being streamed."""


def stream_ask(server: "AssistantServer", body: dict[str, Any], send: Callable[[dict[str, Any]], None]) -> None:
    """Run one turn and stream its events through ``send``. Never raises ``ClientGone``."""
    message = str(body.get("message") or "").strip()[:MAX_MESSAGE_CHARS]
    try:
        if not message:
            send({"type": "error", "message": "message is required", "code": "invalid"})
            return
        settings = server.settings
        chosen = str(body.get("model") or "")
        if chosen and chosen not in settings.get("models", {}):
            send({"type": "error", "message": f"There is no model named {chosen}.", "code": "invalid"})
            return
        if chosen:
            settings = {**settings, "active_model": chosen}
        model = settings_store.active_model(settings)
        if model is None:
            send({"type": "error", "message": "No AI model is set up yet.", "code": "not_configured"})
            return
        if (settings.get("agent") or {}).get("local_only") and not is_local_address(model["base_url"]):
            send({"type": "error", "code": "not_configured", "message": "Local only is switched on, but the chosen "
                  "model is hosted. Choose a model on this computer, or switch local only off under Behaviour."})
            return
        cap = (settings.get("agent") or {}).get("monthly_spend_cap", 0)
        if spend.over_cap(model, cap):
            send({"type": "error", "code": "not_configured", "message": f"This month's spending on hosted models "
                  f"has reached the cap of {cap}. Raise the cap under Behaviour, or choose a local model."})
            return
        try:
            provider = create_provider(model)
        except ProviderError as error:
            send({"type": "error", "message": str(error), "code": "not_configured"})
            return
        conversation = server.conversations.get_or_create(str(body.get("conversation_id") or ""))
        if not conversation.turn_lock.acquire(blocking=False):
            send({"type": "error", "message": "The assistant is still working on the previous request.", "code": "busy"})
            return
    except ClientGone:
        return

    started = time.monotonic()
    agent = settings.get("agent") or settings_store.default_agent()
    try:
        conversation.cancel.clear()
        def update_settings(mutate):
            changed = copy.deepcopy(server.settings)
            mutate(changed)
            return server.replace_settings(changed)

        registry, warnings = build_registry(server.mcp, settings, lambda: server.settings, update_settings)
        dry_run = body.get("dry_run") is True
        if dry_run:
            registry = registry.reads_only()
            message = (DRY_RUN_PREFIX + message)[:MAX_MESSAGE_CHARS]
        if not conversation.history:
            unavailable = [GROUP_DESCRIPTIONS[group] for group in agent["disabled_tool_groups"]]
            conversation.history.append(
                Message("system", system_prompt(settings.get("folders"), agent["instructions"], unavailable,
                                                agent["confirm_plans"], settings.get("routines"))))
        conversation.history.append(Message("user", message))
        server.conversations.begin_turn(conversation, message)
        server.state.update(status="thinking", last_error="")

        def emit(event: dict[str, Any]) -> None:
            conversation.record(event)
            try:
                send(event)
            except ClientGone:
                conversation.cancel.set()

        emit({
            "type": "start",
            "conversation_id": conversation.id,
            "model": ("" if chosen else _quick(settings, settings.get("active_model", ""))) or settings.get("active_model", ""),
            "tools": registry.names(),
            "warnings": warnings,
        })
        gate = PermissionGate(
            settings.get("approval_policy", "danger"), server.approvals, emit, conversation.cancel, server.runtime_dir)
        if is_local_address(model["base_url"]) and model_busy(model["base_url"]):
            emit({"type": "notice", "message": "The model is busy with another program; your request will start "
                                               "when it is free."})
        model_name = settings.get("active_model", "")
        quick_name = "" if chosen else _quick(settings, model_name)
        try:
            quick_provider = create_provider(settings["models"][quick_name]) if quick_name else None
        except ProviderError:
            quick_name, quick_provider = "", None
        if quick_name:
            handed = _attempt(quick_provider, quick_name, settings["models"][quick_name],
                              conversation, registry, emit, gate, agent, hold_first_error=True, hand_over=True)
            if handed is None:
                return
            reason = handed["message"] if handed["type"] == "error" else "it needed more steps"
            emit({"type": "notice", "message": f"{quick_name} handed this to {model_name} ({reason})."})
            emit = _with_earlier_actions(emit, handed.get("actions", []))
        held = _attempt(provider, model_name, model, conversation, registry, emit, gate, agent,
                        hold_first_error=bool(_fallback(settings, model_name)))
        if held is not None:
            fallback_name = _fallback(settings, model_name)
            fallback = settings["models"][fallback_name]
            emit({"type": "notice", "message": f"{model_name} did not answer ({held['message']}); "
                                               f"{fallback_name} on this computer answered instead."})
            _attempt(create_provider(fallback), fallback_name, fallback, conversation, registry, emit, gate, agent,
                     hold_first_error=False)
    finally:
        if body.get("ephemeral") is True:
            server.conversations.forget(conversation.id)
        else:
            server.conversations.save(conversation)
        conversation.turn_lock.release()
        server.state.update(status="idle")
        notify_after = agent["notify_after_seconds"]
        if notify_after and time.monotonic() - started > notify_after:
            notify_finished(conversation.title)
        app_visibility.run_after_turn()


def _with_earlier_actions(emit: Callable[[dict[str, Any]], None], earlier: list[dict[str, str]]):
    """``emit``, with the quick model's actions put first in the final ``done`` so none goes unreported."""
    def forward(event: dict[str, Any]) -> None:
        if event["type"] == "done" and earlier:
            event = {**event, "actions": [*earlier, *event.get("actions", [])]}
        emit(event)
    return forward


def model_busy(base_url: str) -> bool:
    """Whether a local llama.cpp-style service reports every slot busy (``GET /slots``); False if it cannot say."""
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(root + "/slots", timeout=1) as response:
            slots = json.loads(response.read(200_000))
    except (OSError, ValueError):
        return False
    return isinstance(slots, list) and bool(slots) and all(isinstance(slot, dict) and slot.get("is_processing")
                                                           for slot in slots)


QUICK_MODEL_STEPS = 4


def _quick(settings: dict[str, Any], current: str) -> str:
    """The quick model's name when it is set, different, and allowed by local only and the spending cap; else ""."""
    agent = settings.get("agent") or {}
    name = agent.get("quick_model", "")
    model = settings.get("models", {}).get(name)
    if not name or name == current or not model:
        return ""
    if agent.get("local_only") and not is_local_address(model["base_url"]):
        return ""
    return "" if spend.over_cap(model, agent.get("monthly_spend_cap", 0)) else name


def _fallback(settings: dict[str, Any], current: str) -> str:
    """The fallback model's name when it is set, different and on this computer; else ""."""
    name = (settings.get("agent") or {}).get("fallback_model", "")
    model = settings.get("models", {}).get(name)
    return name if name and name != current and model and is_local_address(model["base_url"]) else ""


def _attempt(provider, name: str, model: dict[str, Any], conversation, registry, emit, gate, agent,
             hold_first_error: bool, hand_over: bool = False) -> dict[str, Any] | None:
    """Run the turn on one model; return a held event, or None when the turn ended here.

    With ``hold_first_error``, an error before anything happened is returned instead of shown, so the
    caller can try the fallback; the history is unchanged then. With ``hand_over`` (the quick model),
    any error, and a ``done`` for running out of its ``QUICK_MODEL_STEPS``, are returned instead, so
    the caller can let the chosen model continue; the history then holds the steps taken so far."""
    progressed = [False]
    held: list[dict[str, Any]] = []

    def guarded(event: dict[str, Any]) -> None:
        if event["type"] == "error" and (hand_over or (hold_first_error and not progressed[0])):
            held.append(event)
            return
        if event["type"] in ("thinking", "text_delta", "tool_call"):
            progressed[0] = True
        if event["type"] == "done":
            usage = event.get("usage") or {}
            event = {**event, "model": name,
                     "cost": spend.record(name, model, usage.get("input_tokens", 0), usage.get("output_tokens", 0))}
            if hand_over and event["stop"] == "step_limit":
                held.append(event)
                return
        emit(event)

    run_turn(provider, conversation.history, registry, guarded, conversation.cancel, model["context_window"],
             max_steps=QUICK_MODEL_STEPS if hand_over else agent["max_steps"], gate=gate,
             redact=not is_local_address(model["base_url"]))
    return held[0] if held else None


def notify_finished(title: str) -> None:
    """Desktop notification that a long request finished, with an Open button; failures are ignored.

    ``notify-send --wait`` blocks until the notification is used or closed,
    so it runs on its own thread; choosing Open opens the popup on the
    conversation (``desktop_actions.open_assistant_popup``).
    """
    if not shutil.which("notify-send"):
        return

    def show() -> None:
        result = run_command(["notify-send", "--app-name=Happy Bot", "--icon=tools-wizard", "--action=open=Open",
                              "--wait", "--", "The assistant finished", title or "Your request is done."], timeout=3600)
        if result.get("stdout", "").strip() == "open":
            try:
                desktop_actions.open_assistant_popup()
            except desktop_actions.DesktopActionError:
                pass

    threading.Thread(target=show, name="finished-notification", daemon=True).start()

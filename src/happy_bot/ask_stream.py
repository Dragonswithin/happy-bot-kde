"""Serves one assistant turn for ``POST /ask`` as a stream of events.

Connects the HTTP layer to the agent loop: it picks the active model, builds
the tool registry, finds or creates the conversation, appends the user's
message, and runs ``agent_loop.run_turn``, forwarding every event to the
client as it happens. ``daemon_http`` owns the socket and passes ``send``, a
callable that writes one event and raises ``ClientGone`` when the client has
disconnected.

A body with ``"ephemeral": true`` is not kept in the conversation history
(``eval`` uses it). A body may name a configured ``model`` to use for this request instead of
the user's order (the popup's per-chat picker, ``happy-bot eval --model``);
the name, or "" for the order, is kept on the conversation as its ``model``
so the popup can show the pick again when the chat is reopened. A body may
also carry ``about_window`` (``{"app", "class", "title", "window"}``, from
``GET /context/app``) when the popup was opened from the floating button or
the hotkey, and ``full_context: true`` in a chat started from the welcome
screen's "Help with …" button. ``app_context.background_note`` turns it into
a note about that application (with ``full_context``, also its selection,
controls and open file), stored on the user's message (``Message.context``);
the application is read only when the user's ``agent.app_context`` lets some
AI in the chain see it. Each model then gets the history through
``app_context.for_model``, which shows the note and what tools read inside
applications only to the AIs that setting allows, and hides secrets again
for a hosted one. The conversation shows the request as typed.

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

Models: requests go down the user's ``model_order`` (a request that names a
``model`` uses only that one). Models that cannot be used are skipped with a
notice: an online one while "local only" is on, one whose ``monthly_cap`` is
reached (``spend.over_cap``), one whose settings cannot make a provider.
Each model in turn gets the request; when it fails before producing
anything, the next one runs it again from the same history, after a
``{"type": "notice", "message"}`` saying so. A model marked
``hand_over_long`` gets at most ``HAND_OVER_STEPS`` model requests; when it
uses them all, or fails at any point, the next one continues the same
conversation, which already holds its steps and their results. The last
model in the list always finishes. The final ``done`` lists every model's
actions, names the model that answered and its cost; every model's tokens
and cost are recorded. Online models may be anywhere in the order: the user
placed them there, and the settings page marks them online. When
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

from . import app_context, desktop_actions
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
        names = [chosen] if chosen else list(settings.get("model_order") or [])
        if not names:
            send({"type": "error", "message": "No AI model is set up yet.", "code": "not_configured"})
            return
        chain, skipped = _usable(settings, names)
        if not chain:
            send({"type": "error", "code": "not_configured", "message": "No AI in your list can answer: "
                  + "; ".join(skipped) + ". Change this on the AI Model page."})
            return
        conversation = server.conversations.get_or_create(str(body.get("conversation_id") or ""))
        conversation.model = chosen
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
        policy = agent.get("app_context", app_context.DEFAULT_POLICY)
        # Read the application only when some AI in the chain may be told about it.
        note = app_context.background_note(body.get("about_window"), full=body.get("full_context") is True) \
            if any(app_context.shows_context(policy, is_local_address(model["base_url"])) for _, model, _ in chain) else ""
        conversation.history.append(Message("user", message, context=note))
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
            "model": chain[0][0],
            "tools": registry.names(),
            "warnings": warnings,
        })
        gate = PermissionGate(
            settings.get("approval_policy", "danger"), server.approvals, emit, conversation.cancel, server.runtime_dir)
        for reason in skipped:
            emit({"type": "notice", "message": f"Skipped {reason}."})
        first = chain[0][1]
        if is_local_address(first["base_url"]) and model_busy(first["base_url"]):
            emit({"type": "notice", "message": "The model is busy with another program; your request will start "
                                               "when it is free."})
        _run_chain(chain, conversation, registry, emit, gate, agent)
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
    """``emit``, with earlier models' actions put first in the final ``done`` so none goes unreported."""
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


HAND_OVER_STEPS = 4


def _usable(settings: dict[str, Any], names: list[str]) -> tuple[list[tuple[str, dict[str, Any], Any]], list[str]]:
    """``(name, model, provider)`` for each model that may answer, in order, and why the others were skipped."""
    local_only = (settings.get("agent") or {}).get("local_only")
    chain, skipped = [], []
    for name in names:
        model = settings["models"][name]
        if local_only and not is_local_address(model["base_url"]):
            skipped.append(f"{name} (online, and local only is on)")
        elif spend.over_cap(name, model):
            skipped.append(f"{name} (it reached its monthly limit of {model['monthly_cap']})")
        else:
            try:
                chain.append((name, model, create_provider(model)))
            except ProviderError as error:
                skipped.append(f"{name} ({error})")
    return chain, skipped


def _run_chain(chain, conversation, registry, emit, gate, agent) -> None:
    """Give the request to each model in turn until one finishes it (see the module docstring)."""
    carried: list[dict[str, str]] = []
    forward = emit
    for index, (name, model, provider) in enumerate(chain):
        last = index == len(chain) - 1
        held = _attempt(provider, name, model, conversation, registry, forward, gate, agent,
                        hold_first_error=not last, hand_over=model.get("hand_over_long", False) and not last)
        if held is None:
            return
        following = chain[index + 1][0]
        if held["type"] == "error":
            emit({"type": "notice", "message": f"{name} did not answer ({held['message']}); {following} is "
                                               f"answering instead."})
        else:
            emit({"type": "notice", "message": f"{name} handed this to {following} (it needed more steps)."})
        carried += held.get("actions", [])
        forward = _with_earlier_actions(emit, carried)


def _attempt(provider, name: str, model: dict[str, Any], conversation, registry, emit, gate, agent,
             hold_first_error: bool, hand_over: bool = False) -> dict[str, Any] | None:
    """Run the turn on one model; return a held event, or None when the turn ended here.

    With ``hold_first_error``, an error before anything happened is returned instead of shown, so the
    caller can try the next model; the history is unchanged then. With ``hand_over``, any error, and a
    ``done`` for running out of its ``HAND_OVER_STEPS``, are returned instead, so
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

    local = is_local_address(model["base_url"])
    policy = agent.get("app_context", app_context.DEFAULT_POLICY)
    run_turn(provider, conversation.history, registry, guarded, conversation.cancel, model["context_window"],
             max_steps=HAND_OVER_STEPS if hand_over else agent["max_steps"], gate=gate, redact=not local,
             prepare=lambda history: app_context.for_model(history, policy, local))
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

"""Serves one assistant turn for ``POST /ask`` as a stream of events.

Connects the HTTP layer to the agent loop: it picks the active model, builds
the tool registry, finds or creates the conversation, appends the user's
message, and runs ``agent_loop.run_turn``, forwarding every event to the
client as it happens. ``daemon_http`` owns the socket and passes ``send``, a
callable that writes one event and raises ``ClientGone`` when the client has
disconnected.

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

A turn that takes longer than ``NOTIFY_AFTER_SECONDS`` ends with a desktop
notification, so the user learns it finished even with the popup closed.
Work a tool deferred to after the turn (a Plasma shell restart requested by
``tools.app_visibility``) runs once the turn has finished streaming.

If the client disconnects, the turn is cancelled: the model request is
dropped at the next chunk and no further tools run. The history is left
valid either way.
"""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING, Any, Callable

from . import settings as settings_store
from .agent_loop import run_turn, system_prompt
from .conversation import Message
from .desktop_context import run_command
from .permissions import PermissionGate
from .tools import app_visibility
from .providers import ProviderError, create_provider
from .tools.catalog import build_registry

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

MAX_MESSAGE_CHARS = 20000
NOTIFY_AFTER_SECONDS = 60


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
        model = settings_store.active_model(settings)
        if model is None:
            send({"type": "error", "message": "No AI model is set up yet.", "code": "not_configured"})
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
    try:
        conversation.cancel.clear()
        registry, warnings = build_registry(server.mcp, settings)
        if not conversation.history:
            conversation.history.append(Message("system", system_prompt(settings.get("folders"))))
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
            "model": settings.get("active_model", ""),
            "tools": registry.names(),
            "warnings": warnings,
        })
        gate = PermissionGate(
            settings.get("approval_policy", "danger"), server.approvals, emit, conversation.cancel, server.runtime_dir)
        run_turn(provider, conversation.history, registry, emit, conversation.cancel, model["context_window"], gate=gate)
    finally:
        server.conversations.save(conversation)
        conversation.turn_lock.release()
        server.state.update(status="idle")
        if time.monotonic() - started > NOTIFY_AFTER_SECONDS:
            notify_finished(conversation.title)
        app_visibility.run_after_turn()


def notify_finished(title: str) -> None:
    """Desktop notification that a long request finished; failures are ignored."""
    if shutil.which("notify-send"):
        run_command(["notify-send", "--app-name=AI Assistant", "--icon=tools-wizard", "--",
                     "The assistant finished", title or "Your request is done."], timeout=5)

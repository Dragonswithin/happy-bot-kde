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

Only read-risk tools are offered until the permission gate exists
(``ALLOWED_RISKS``).

If the client disconnects, the turn is cancelled: the model request is
dropped at the next chunk and no further tools run. The history is left
valid either way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from . import settings as settings_store
from .agent_loop import run_turn, system_prompt
from .conversation import Message
from .providers import ProviderError, create_provider
from .tools.mcp_bridge import build_registry
from .tools.registry import RISK_READ

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

ALLOWED_RISKS = (RISK_READ,)
MAX_MESSAGE_CHARS = 20000


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

    try:
        conversation.cancel.clear()
        registry, warnings = build_registry(server.mcp, settings, ALLOWED_RISKS)
        if not conversation.history:
            conversation.history.append(Message("system", system_prompt()))
        conversation.history.append(Message("user", message))
        server.state.update(status="thinking", last_error="")

        def emit(event: dict[str, Any]) -> None:
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
        run_turn(provider, conversation.history, registry, emit, conversation.cancel, model["context_window"])
    finally:
        conversation.turn_lock.release()
        server.state.update(status="idle")

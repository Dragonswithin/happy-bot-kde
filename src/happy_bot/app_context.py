"""Who may see what Happy Bot reads from the user's applications, and how the model is told it.

Opened from an application (the floating button or the hotkey), Happy Bot knows which window the
user was in, and its tools can read inside windows (their controls, their text, the selected text).
The user's ``agent.app_context`` setting (``settings.py``, the Behaviour page) decides which AI may
see any of it:

- ``"off"``: no AI is told about the application, and what tools read inside applications is
  never shown to an online AI. ``/context/app`` answers empty, so nothing is noted at all.
- ``"local"`` (default): AIs on this computer (``redaction.is_local_address``) get it all; online
  AIs get none of it, even when a local AI read it earlier in the same request and then handed
  the request over (``ask_stream``'s fallback down the model order).
- ``"any"``: every AI gets it.

How it is kept: ``background_note`` turns the noted window into a background note (name, title,
version and system from ``app_snapshot.light_facts``; with ``full``, for a chat started from the
"Help with …" button, also the selected text, the window's controls and its open file from
``app_snapshot.full_facts``). The note is stored on the user's message (``Message.context``), not in
its text, and tool results from tools marked ``private`` (``tools.registry.Tool``) are stored with
``Message.private``. Right before each model request, ``for_model`` builds that model's copy of
the history: the note joined to the message or left out, private results kept or replaced by
``WITHHELD``, and for an online AI every tool result and note passed through
``redaction.redact`` again, so a secret a local AI read is hidden before an online one sees it.
The history itself is never changed, so a later local model still sees everything.
"""

from __future__ import annotations

from typing import Any

from . import app_snapshot
from .conversation import Message
from .redaction import redact
from .settings import APP_CONTEXT_DEFAULT as DEFAULT_POLICY, APP_CONTEXT_POLICIES as POLICIES  # noqa: F401

MAX_TITLE_CHARS = 200
WITHHELD = ("[Not shown: this was read from the user's application, and their privacy setting keeps that on "
            "their computer, away from online AIs.]")


def shows_context(policy: str, local_model: bool) -> bool:
    """Whether a model is given the background note about the user's application."""
    return policy == "any" or (policy == "local" and local_model)


def shows_private_results(policy: str, local_model: bool) -> bool:
    """Whether a model is given what tools read inside the user's applications."""
    return local_model or policy == "any"


def background_note(about: Any, full: bool = False) -> str:
    """The note about the application the user was in, or "" when there is none.

    ``about`` is the popup's ``about_window`` (``{"app", "class", "title", "window"}``); the window
    is looked up again by its KWin id for the facts, and when it has closed only the name and title
    are used.
    """
    if not isinstance(about, dict):
        return ""
    app = str(about.get("app") or about.get("class") or "").strip()[:100]
    title = str(about.get("title") or "").strip()[:MAX_TITLE_CHARS]
    if not app and not title:
        return ""
    window = _window(str(about.get("window") or ""))
    light = app_snapshot.light_facts(window) if window else {"version": "", "system": app_snapshot.system_description()}
    name = f"{app} {light['version']}".strip() if app else ""
    where = f"the application {name}" + (f' (window title: "{title}")' if title else "") if app else f'the window "{title}"'
    lines = [f"[Background from the user's computer, not part of the request: they had {where} open when they "
             f"asked" + (f", on {light['system']}" if light["system"] else "") + "."]
    if full and window:
        facts = app_snapshot.full_facts(window)
        if facts["document"]:
            lines.append(f"The file it has open: {facts['document']}")
        if facts["selection"]:
            lines.append(f"Text they have selected:\n\"\"\"\n{facts['selection']}\n\"\"\"")
        if facts["controls"]:
            lines.append(f"What the window shows (its controls):\n{facts['controls']}")
    lines.append("If the request is about the application they are in (\"this\", \"here\", \"how do I…\" without a "
                 "name), it is this one, so do not ask which; use the version above for exact steps. If they name "
                 "another application or ask about something else, answer that and ignore this note.]")
    return "\n".join(lines)


def _window(window_id: str) -> dict[str, Any] | None:
    """KWin's description of the window (with its pid), or None when it is gone or KWin cannot say."""
    if not window_id:
        return None
    from .tools import windows
    from .tools.registry import ToolFailure

    try:
        return windows.describe_window(window_id)
    except ToolFailure:
        return None


def for_model(history: list[Message], policy: str, local_model: bool) -> list[Message]:
    """The history as one model may see it (see the module docstring); ``history`` is not changed."""
    context, private = shows_context(policy, local_model), shows_private_results(policy, local_model)
    prepared = []
    for message in history:
        text = message.text
        if message.context and context:
            text = f"{message.context}\n\n{text}"
        if message.private and not private:
            text = WITHHELD
        if not local_model and (message.role == "tool" or (message.context and context)):
            text = redact(text)
        if text == message.text and not message.context and not message.private:
            prepared.append(message)
        else:
            prepared.append(Message(message.role, text, message.tool_calls, message.tool_call_id, message.echo))
    return prepared

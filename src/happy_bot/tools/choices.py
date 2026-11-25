"""Clickable answers: the assistant asks a short question with buttons, or offers next steps.

Typing an answer to a question the assistant could have offered as choices is slow, so two tools
let the model put buttons under the conversation, drawn by the popup as a card (ChoicesCard.qml):

- ``ask_user`` (``question``, 2 to ``MAX_CHOICES`` ``choices``): when a request is unclear and one
  short question would settle it ("Which edition?": "Java", "Bedrock").
- ``suggest_next`` (1 to ``MAX_SUGGESTIONS`` ``suggestions``): after an answer, the likely next
  requests ("Install Prism Launcher", "Open it").

A click sends that button's text as the user's next message; the user can always type something
else instead. Both tools end the turn (``Tool.ends_turn``): the agent loop stops after them, so
the model waits for the user rather than guessing an answer. Their result text, which the model
reads, says what was shown; ``choices_card`` reads that same text back into the card, so a saved
conversation shows its buttons again. Each button text is one line of at most
``MAX_CHOICE_CHARS`` characters without ``|``, the separator in that text.

They change nothing (``read``) and are offered only when the request comes from Happy Bot's own
window, which can draw the buttons (``ask_stream``: the request's ``buttons`` flag), never to
KRunner, routines or the command line.
"""

from __future__ import annotations

from typing import Any

from .registry import RISK_READ, Tool, ToolFailure, object_schema

MAX_CHOICES = 4
MAX_SUGGESTIONS = 3
MAX_CHOICE_CHARS = 60
_QUESTION = "Asked the user: "
_SUGGESTED = "Suggested next: "
_CHOICES = "Buttons: "
_AFTER = "They are on screen as buttons. Stop now: the user's choice, or their own words, comes as their next message."


def _buttons(raw: Any, least: int, most: int, name: str) -> list[str]:
    if not isinstance(raw, list):
        raise ToolFailure(f"'{name}' must be a list of short texts")
    cleaned = []
    for item in raw:
        text = " ".join(str(item).replace("|", "/").split())[:MAX_CHOICE_CHARS].strip()
        if text and text not in cleaned:
            cleaned.append(text)
    if not least <= len(cleaned) <= most:
        raise ToolFailure(f"'{name}' needs {least} to {most} different short texts")
    return cleaned


def ask_user(arguments: dict[str, Any]) -> str:
    question = " ".join(str(arguments.get("question") or "").split())
    if not question:
        raise ToolFailure("'question' is required")
    choices = _buttons(arguments.get("choices"), 2, MAX_CHOICES, "choices")
    return f"{_QUESTION}{question}\n{_CHOICES}{' | '.join(choices)}\n{_AFTER}"


def suggest_next(arguments: dict[str, Any]) -> str:
    suggestions = _buttons(arguments.get("suggestions"), 1, MAX_SUGGESTIONS, "suggestions")
    return f"{_SUGGESTED}\n{_CHOICES}{' | '.join(suggestions)}\n{_AFTER}"


def choices_card(text: str) -> dict[str, Any] | None:
    """The buttons card for either tool's text, or None if the text is not in its format."""
    lines = text.splitlines()
    if len(lines) < 2 or not lines[1].startswith(_CHOICES):
        return None
    if lines[0].startswith(_QUESTION):
        question, follow_up = lines[0][len(_QUESTION):], False
    elif lines[0].startswith(_SUGGESTED.rstrip()):
        question, follow_up = "", True
    else:
        return None
    choices = [item.strip() for item in lines[1][len(_CHOICES):].split("|") if item.strip()]
    return {"kind": "choices", "question": question, "choices": choices, "follow_up": follow_up} if choices else None


def choice_tools() -> list[Tool]:
    texts = {"type": "array", "items": {"type": "string"}}
    return [
        Tool("ask_user", "Ask the user one short question with 2-4 answers shown as buttons, when the request is "
             "unclear and the answer changes what you would do. Do not ask what you can find out yourself or "
             "reasonably assume. Ends your turn: the user's choice arrives as their next message.",
             object_schema({"question": {"type": "string"},
                            "choices": {**texts, "description": "2 to 4 short answers, a few words each"}},
                           ["question", "choices"]),
             RISK_READ, ask_user, summarize=lambda a: "Ask you a question", card=choices_card, ends_turn=True),
        Tool("suggest_next", "After answering, offer 1-3 likely next requests as buttons (for example \"Install "
             "it\", \"Open it\"), each a short request in the user's words. Only when there is a clear next step. "
             "Ends your turn.",
             object_schema({"suggestions": {**texts, "description": "1 to 3 short requests, a few words each"}},
                           ["suggestions"]),
             RISK_READ, suggest_next, summarize=lambda a: "Suggest what to do next", card=choices_card,
             ends_turn=True),
    ]

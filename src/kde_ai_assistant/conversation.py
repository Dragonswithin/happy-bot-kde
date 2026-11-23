"""Vendor-neutral conversation types shared by the agent loop and providers.

The agent loop builds a list of ``Message`` objects; a provider translates
that list into one vendor's wire format and yields ``ProviderEvent`` objects
back. Nothing here knows about HTTP, a particular model API, or any tool.

Roles: ``system`` (instructions), ``user``, ``assistant`` (text and/or tool
calls) and ``tool`` (the result of one tool call, linked by ``tool_call_id``).
An assistant message that requested tools must be followed by exactly one
``tool`` message per call before the next model request; ``trim_history``
preserves that by only ever dropping whole user turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Rough characters-per-token ratio used only to decide when history is too
# long for a model's context window. It errs on the side of trimming early.
CHARS_PER_TOKEN = 3


@dataclass(frozen=True)
class ToolCall:
    """A model's request to run one tool. ``arguments_error`` is set when the
    model produced arguments that are not a JSON object; ``arguments`` is then empty."""

    id: str
    name: str
    arguments: dict[str, Any]
    arguments_error: str = ""


@dataclass(frozen=True)
class Message:
    role: str
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class ToolSpec:
    """What a model is told about a tool: name, purpose and JSON-schema parameters."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    """The model produced hidden reasoning; carries no content, only liveness."""


@dataclass(frozen=True)
class ToolCallReady:
    call: ToolCall


@dataclass(frozen=True)
class TurnEnd:
    """End of one model response. ``stop_reason`` is the provider's own word for why."""

    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


ProviderEvent = TextDelta | ThinkingDelta | ToolCallReady | TurnEnd


def message_chars(message: Message) -> int:
    size = len(message.text)
    for call in message.tool_calls:
        size += len(call.name) + len(str(call.arguments))
    return size


def trim_history(history: list[Message], context_window: int) -> list[Message]:
    """Drop the oldest whole user turns until the history fits about 70% of the window.

    System messages and the most recent turn are always kept, so one oversized
    turn is sent as is and the provider reports the failure.
    """
    budget = int(context_window * CHARS_PER_TOKEN * 0.7)
    system = [message for message in history if message.role == "system"]
    rest = [message for message in history if message.role != "system"]
    turns: list[list[Message]] = []
    for message in rest:
        if message.role == "user" or not turns:
            turns.append([])
        turns[-1].append(message)
    total = sum(message_chars(message) for message in history)
    while len(turns) > 1 and total > budget:
        total -= sum(message_chars(message) for message in turns.pop(0))
    return system + [message for turn in turns for message in turn]

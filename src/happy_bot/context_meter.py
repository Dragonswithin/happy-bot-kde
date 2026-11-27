"""Context usage for a single model request, independent of billing totals."""

from __future__ import annotations

import json
from collections.abc import Sequence

from .conversation import CHARS_PER_TOKEN, Message, ToolSpec

# Use a working limit for trimming when the provider's capacity is unknown.
FALLBACK_WINDOW = 32768


def estimate(messages: Sequence[Message], tools: Sequence[ToolSpec], capacity: int) -> dict:
    sizes = sum(
        len(message.text)
        + sum(len(call.name) + len(json.dumps(call.arguments, ensure_ascii=False)) for call in message.tool_calls)
        for message in messages
    )
    sizes += sum(len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters, ensure_ascii=False))
                 for tool in tools)
    return {
        "used": (sizes + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN + 4 * len(messages),
        "capacity": capacity or None,
        "estimated": True,
        "image_count": sum(len(message.images) for message in messages),
    }

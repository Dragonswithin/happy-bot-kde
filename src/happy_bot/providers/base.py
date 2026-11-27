"""The contract every model provider implements.

A provider receives the whole conversation and the available tools for one
model request and yields ``ProviderEvent`` objects as the reply streams in:
any number of ``TextDelta``/``ThinkingDelta``, then one ``ToolCallReady`` per
tool call the model made (complete, in the model's order), then exactly one
``TurnEnd``. It must stop promptly once ``cancel`` is set and must release its
connection when the generator is closed.

Providers hold no conversation state between calls and never run tools. All
failures are raised as ``ProviderError`` with a message written for the user.

``image_data_url`` turns a message's picture (``Message.images``, a PNG
path) into the ``data:`` URL both OpenAI-style formats accept; a picture that
is missing, unreadable or larger than ``MAX_IMAGE_BYTES`` is left out.
"""

from __future__ import annotations

import base64
import threading
from typing import Iterator, Protocol, Sequence

from ..conversation import Message, ProviderEvent, ToolSpec


MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ProviderError(RuntimeError):
    """The model could not be reached or refused the request."""


def image_data_url(path: str) -> str:
    """``data:image/png;base64,...`` for a PNG file, or "" when it cannot be sent."""
    if isinstance(path, str) and path.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
        return path
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        return ""
    if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\x89PNG"):
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


class ModelProvider(Protocol):
    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        cancel: threading.Event,
    ) -> Iterator[ProviderEvent]:
        """Send one request and yield the reply as events (see module docstring)."""
        ...

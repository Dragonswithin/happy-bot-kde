"""The contract every model provider implements.

A provider receives the whole conversation and the available tools for one
model request and yields ``ProviderEvent`` objects as the reply streams in:
any number of ``TextDelta``/``ThinkingDelta``, then one ``ToolCallReady`` per
tool call the model made (complete, in the model's order), then exactly one
``TurnEnd``. It must stop promptly once ``cancel`` is set and must release its
connection when the generator is closed.

Providers hold no conversation state between calls and never run tools. All
failures are raised as ``ProviderError`` with a message written for the user.
"""

from __future__ import annotations

import threading
from typing import Iterator, Protocol, Sequence

from ..conversation import Message, ProviderEvent, ToolSpec


class ProviderError(RuntimeError):
    """The model could not be reached or refused the request."""


class ModelProvider(Protocol):
    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        cancel: threading.Event,
    ) -> Iterator[ProviderEvent]:
        """Send one request and yield the reply as events (see module docstring)."""
        ...

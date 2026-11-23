"""What a tool is, and the registry that runs one by name.

A ``Tool`` is everything the assistant needs to offer an action to a model
and carry it out: a model-facing name, description and JSON-schema
parameters, a risk class, and a handler that takes the model's arguments and
returns text for the model to read.

Risk classes (see docs/ROADMAP.md, Permission Gate):

- ``read``: no state change.
- ``change``: changes state but is not deletion and not an OS-level change.
- ``danger``: deletion, or an OS-level change that could crash the system or
  stop it booting.

``ToolRegistry.run`` never raises for a tool's own failure: a handler signals
an expected failure with ``ToolFailure`` and anything else is caught, and both
come back as ``(False, message)`` so the model can react. Results longer than
``MAX_RESULT_CHARS`` are cut with a visible marker to protect the model's
context window. Handlers run on the calling thread and may block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ..conversation import ToolSpec

RISK_READ = "read"
RISK_CHANGE = "change"
RISK_DANGER = "danger"
MAX_RESULT_CHARS = 8000
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ToolFailure(RuntimeError):
    """An expected tool failure; the message is shown to the model."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: str
    handler: Callable[[dict[str, Any]], str]
    source: str = "builtin"

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters)


def object_schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    """Build the JSON schema for a tool's arguments."""
    return {"type": "object", "properties": properties or {}, "required": required or []}


def shorten(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n[result cut: {len(text) - limit} more characters not shown]"


class ToolRegistry:
    """The tools offered for one turn, addressed by their model-facing names."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if not _NAME_PATTERN.match(tool.name):
                raise ValueError(f"invalid tool name: {tool.name!r}")
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def run(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Run a tool; return ``(succeeded, text for the model)``."""
        tool = self._tools.get(name)
        if tool is None:
            return False, f"There is no tool named '{name}'. Available: {', '.join(self._tools) or 'none'}."
        try:
            return True, shorten(tool.handler(arguments)) or "(no output)"
        except ToolFailure as failure:
            return False, shorten(str(failure))
        except Exception as error:  # noqa: BLE001 - a tool bug must not end the turn
            return False, f"The tool failed unexpectedly: {type(error).__name__}: {error}"

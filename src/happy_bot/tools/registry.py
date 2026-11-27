"""What a tool is, and the registry that runs one by name.

A ``Tool`` is everything the assistant needs to offer an action to a model
and carry it out: a model-facing name, description and JSON-schema
parameters, a risk class, and a handler that takes the model's arguments and
returns text for the model to read.

A tool's ``risk`` is its default. A tool whose effect depends on its
arguments (a shell command, a file write) also supplies ``classify``, which
returns ``(risk, reason)`` for one specific call; the permission gate uses
that. ``summarize`` gives the one-line, human description of a call that the
approval card shows. ``precheck`` raises ``ToolFailure`` for a call that
cannot succeed (a missing file, for example); it runs before the permission
gate so the user is never asked to approve something that would fail.
``card`` turns a successful result's text into a small dict the popup draws
as a card (the weather, for example); it belongs to the tool that writes
the text, so the two stay in step. ``ToolRegistry.card`` calls it and never
raises: a result that does not parse simply has no card.

Risk classes (see docs/ROADMAP.md, Permission Gate):

- ``read``: no state change.
- ``change``: changes state but is not deletion and not an OS-level change.
- ``danger``: deletion, or an OS-level change that could crash the system or
  stop it booting.

While a tool runs, ``call_context`` holds what the agent loop gave this
call: a ``progress(text)`` function that shows a status line under the step
in the popup, and the turn's ``cancel`` event. Long-running handlers (the
shell tool) use them to report output as it arrives and to stop at once
when the user presses Stop; ``report_progress`` and ``cancel_requested`` are
safe to call when nothing is set.

``ToolRegistry.run`` never raises for a tool's own failure: a handler signals
an expected failure with ``ToolFailure`` and anything else is caught, and both
come back as ``(False, message)`` so the model can react. Results longer than
``MAX_RESULT_CHARS`` are cut with a visible marker to protect the model's
context window. Handlers run on the calling thread and may block.
"""

from __future__ import annotations

import re
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable

from ..conversation import ToolSpec

RISK_READ = "read"
RISK_CHANGE = "change"
RISK_DANGER = "danger"
MAX_RESULT_CHARS = 8000
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class CallContext:
    progress: Callable[[str], None]
    cancel: threading.Event


call_context: ContextVar[CallContext | None] = ContextVar("call_context", default=None)


def report_progress(text: str) -> None:
    context = call_context.get()
    if context is not None:
        context.progress(text)


def cancel_requested() -> bool:
    context = call_context.get()
    return context is not None and context.cancel.is_set()


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
    classify: Callable[[dict[str, Any]], tuple[str, str]] | None = None
    summarize: Callable[[dict[str, Any]], str] | None = None
    precheck: Callable[[dict[str, Any]], None] | None = None
    card: Callable[[str], dict[str, Any] | None] | None = None
    # Reads inside the user's applications (their controls, text, selection): its results are kept
    # from online AIs unless the user's app_context setting allows them (app_context.for_model).
    private: bool = False
    # Hands the turn back to the user once it has run (tools/choices.py: buttons the user answers),
    # so the agent loop stops instead of asking the model again.
    ends_turn: bool = False

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

    def with_tools(self, extra: list[Tool]) -> "ToolRegistry":
        """This registry plus ``extra`` tools (a name already here wins)."""
        return ToolRegistry([*self._tools.values(), *(tool for tool in extra if tool.name not in self._tools)])

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def without(self, names: set[str] | frozenset[str]) -> "ToolRegistry":
        return ToolRegistry([tool for tool in self._tools.values() if tool.name not in names])

    def reads_only(self) -> "ToolRegistry":
        """The same tools minus every one that can change anything, for a dry run."""
        return ToolRegistry([tool for tool in self._tools.values() if tool.risk == RISK_READ and tool.classify is None])

    def assess(self, name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
        """Return ``(risk, summary, detail)`` for one call, for the permission gate.

        ``summary`` is a short human description; ``detail`` adds the reason a
        call was classed as dangerous, when there is one. A classifier that
        fails is treated as ``danger`` so a bug cannot wave a call through.
        """
        tool = self._tools.get(name)
        if tool is None:
            return RISK_READ, name, ""
        risk, reason = tool.risk, ""
        if tool.classify is not None:
            try:
                risk, reason = tool.classify(arguments)
            except Exception as error:  # noqa: BLE001 - fail closed
                risk, reason = RISK_DANGER, f"could not be checked ({error})"
        summary = name
        if tool.summarize is not None:
            try:
                summary = tool.summarize(arguments)
            except Exception:  # noqa: BLE001 - a summary is cosmetic
                summary = name
        return risk, summary, reason

    def card(self, name: str, text: str) -> dict[str, Any] | None:
        """The popup card for a successful result of ``name``, or None."""
        tool = self._tools.get(name)
        if tool is None or tool.card is None:
            return None
        try:
            return tool.card(text)
        except Exception:  # noqa: BLE001 - a card is decoration; the answer must not fail for it
            return None

    def precheck(self, name: str, arguments: dict[str, Any]) -> str:
        """Return why this call cannot succeed, or "" if nothing rules it out."""
        tool = self._tools.get(name)
        if tool is None or tool.precheck is None:
            return ""
        try:
            tool.precheck(arguments)
        except ToolFailure as failure:
            return str(failure)
        except Exception:  # noqa: BLE001 - a faulty precheck must not block the call
            return ""
        return ""

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

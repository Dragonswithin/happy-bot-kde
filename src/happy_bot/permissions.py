"""The permission gate: which tool calls run at once and which wait for the user.

Every tool call the model makes passes through ``PermissionGate.check``
before it runs. The gate compares the call's risk class with the user's
approval policy; if approval is needed it emits an ``approval_required``
event, blocks until the user answers through ``ApprovalBroker.resolve``, and
reports the outcome. The gate lives in the daemon so the panel and the CLI
behave identically.

Policies (``approval_policy`` setting):

- ``danger`` (default): only ``danger`` calls ask.
- ``changes``: ``change`` and ``danger`` calls ask.
- ``everything``: every call asks, including reads.

A user may answer "allow for this session" for a non-danger tool, after which
that tool no longer asks until the daemon restarts. ``danger`` calls can only
be allowed once, each time.

Events emitted (through the turn's ``emit``):

- ``{"type": "approval_required", "id", "call_id", "tool", "risk", "summary",
  "detail", "can_remember"}``
- ``{"type": "approval_resolved", "id", "decision"}`` where decision is
  ``allow``, ``deny``, ``timeout`` or ``cancelled``.

Blocking: ``check`` blocks the turn's thread for up to
``APPROVAL_TIMEOUT_SECONDS`` and returns early when the turn is cancelled.
An unanswered request is treated as a denial, never as consent.

Every ``change`` and ``danger`` call that is decided, run or refused is
appended to ``actions.jsonl`` in the runtime directory (transient, 0600) as a
record of what the assistant did.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .tools.registry import RISK_CHANGE, RISK_DANGER, RISK_READ

POLICIES = ("danger", "changes", "everything")
DEFAULT_POLICY = "danger"
APPROVAL_TIMEOUT_SECONDS = 300.0
AUDIT_MAX_BYTES = 1_000_000
AUDIT_ARGUMENT_CHARS = 2000
_audit_lock = threading.Lock()


def needs_approval(policy: str, risk: str) -> bool:
    if risk == RISK_DANGER:
        return True
    if risk == RISK_CHANGE:
        return policy in ("changes", "everything")
    return policy == "everything"


@dataclass
class _Pending:
    answered: threading.Event = field(default_factory=threading.Event)
    decision: str = ""
    remember: bool = False


class ApprovalBroker:
    """Holds requests waiting for the user and the tools allowed for the session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._session_grants: set[str] = set()

    def is_granted(self, tool: str) -> bool:
        with self._lock:
            return tool in self._session_grants

    def open(self) -> str:
        approval_id = secrets.token_urlsafe(9)
        with self._lock:
            self._pending[approval_id] = _Pending()
        return approval_id

    def wait(self, approval_id: str, cancel: threading.Event, timeout: float) -> tuple[str, bool]:
        """Block until answered, cancelled or timed out. Returns ``(decision, remember)``."""
        with self._lock:
            pending = self._pending[approval_id]
        deadline = time.monotonic() + timeout
        decision = "timeout"
        while time.monotonic() < deadline:
            if pending.answered.wait(0.2):
                decision = pending.decision
                break
            if cancel.is_set():
                decision = "cancelled"
                break
        with self._lock:
            self._pending.pop(approval_id, None)
        return decision, pending.remember and decision == "allow"

    def resolve(self, approval_id: str, decision: str, remember: bool = False) -> bool:
        """Record the user's answer. Returns False if the request is unknown or already closed."""
        if decision not in ("allow", "deny"):
            return False
        with self._lock:
            pending = self._pending.get(approval_id)
            if pending is None or pending.answered.is_set():
                return False
            pending.decision = decision
            pending.remember = remember
            pending.answered.set()
            return True

    def grant_for_session(self, tool: str) -> None:
        with self._lock:
            self._session_grants.add(tool)


def append_audit(runtime_dir: Path, record: dict[str, Any]) -> None:
    """Append one line to the transient action log; failures are ignored."""
    path = runtime_dir / "actions.jsonl"
    try:
        with _audit_lock:
            if path.exists() and path.stat().st_size > AUDIT_MAX_BYTES:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            path.chmod(0o600)
    except OSError:
        pass


def clear_activity(runtime_dir: Path) -> None:
    """Forget the action log, including entries retained by its in-place rotation."""
    with _audit_lock:
        (runtime_dir / "actions.jsonl").unlink(missing_ok=True)


class PermissionGate:
    """Gate for one turn. ``emit`` and ``cancel`` are the turn's own."""

    def __init__(
        self,
        policy: str,
        broker: ApprovalBroker,
        emit: Callable[[dict[str, Any]], None],
        cancel: threading.Event,
        runtime_dir: Path | None = None,
        timeout: float = APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        self.policy = policy if policy in POLICIES else DEFAULT_POLICY
        self.broker = broker
        self.emit = emit
        self.cancel = cancel
        self.runtime_dir = runtime_dir
        self.timeout = timeout

    def _audit(self, tool: str, arguments: dict[str, Any], risk: str, outcome: str) -> None:
        if self.runtime_dir is None or risk == RISK_READ:
            return
        append_audit(self.runtime_dir, {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "risk": risk, "outcome": outcome,
            "arguments": json.dumps(arguments, ensure_ascii=False)[:AUDIT_ARGUMENT_CHARS],
        })

    def check(self, call_id: str, tool: str, arguments: dict[str, Any], risk: str, summary: str, detail: str) -> tuple[bool, str]:
        """Return ``(may_run, message_for_the_model_if_not)``; blocks while the user decides."""
        if not needs_approval(self.policy, risk) or (risk != RISK_DANGER and self.broker.is_granted(tool)):
            self._audit(tool, arguments, risk, "ran without asking")
            return True, ""
        approval_id = self.broker.open()
        self.emit({
            "type": "approval_required", "id": approval_id, "call_id": call_id, "tool": tool, "risk": risk,
            "summary": summary, "detail": detail, "can_remember": risk != RISK_DANGER,
        })
        decision, remember = self.broker.wait(approval_id, self.cancel, self.timeout)
        self.emit({"type": "approval_resolved", "id": approval_id, "decision": decision})
        self._audit(tool, arguments, risk, decision)
        if decision == "allow":
            if remember and risk != RISK_DANGER:
                self.broker.grant_for_session(tool)
            return True, ""
        if decision == "deny":
            return False, "The user declined this action. Do not retry it. Ask what they would like instead."
        if decision == "cancelled":
            return False, "Not run: the user cancelled."
        return False, "Not run: the user did not answer the approval request in time."

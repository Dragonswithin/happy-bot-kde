"""MCP client and supervisor for the tool servers the daemon uses.

The assistant gets file search, web search and any other user-supplied tools
from Model Context Protocol servers. Each server is a child process that
speaks JSON-RPC 2.0, one JSON object per line, on its stdin and stdout. This
module starts those processes, performs the MCP handshake, lists and calls
their tools, and stops them. Nothing here knows what any particular server
does.

Servers reached over HTTP instead (a spec with ``url``) are handled by
``mcp_http.McpHttpSession``; both share ``ToolCalls`` for listing and calling
tools, and the manager treats them alike.

``McpSession`` is one running server. A reader thread owns the child's stdout
and routes each reply to the caller waiting on its request id; callers block
in ``request`` until their reply arrives or their timeout expires, so many
threads may call one session at once. Requests the server makes of us are
answered minimally (``ping`` succeeds, everything else is "method not
found"), and notifications are ignored except ``tools/list_changed``, which
drops the cached tool list.

``McpManager`` owns the sessions for the daemon's lifetime: it starts a
server on first use, replaces a session whose process has died (no more often
than ``RESTART_INTERVAL_SECONDS``), and terminates every child on
``close_all``. Children run in their own process group so a server's own
subprocesses die with it.

Failures surface as ``McpError`` with a message meant for the user; the last
lines of the server's stderr are included because that is usually where the
real reason is.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "happy-bot", "version": "0.2"}
STARTUP_TIMEOUT_SECONDS = 30.0
LIST_TIMEOUT_SECONDS = 15.0
RESTART_INTERVAL_SECONDS = 5.0
STDERR_TAIL_LINES = 12
MAX_TOOL_PAGES = 50


class McpError(RuntimeError):
    """A tool server could not be started, reached, or returned a protocol error."""


@dataclass(frozen=True)
class McpServerSpec:
    """How to reach one server: launch ``command`` (stdio), or, when ``url`` is set,
    talk to it over HTTP (``mcp_http``) with ``headers`` added to every request.
    ``env`` is added to a launched server's environment."""

    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    read_only: bool = False
    url: str = ""
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ToolResult:
    """Outcome of ``tools/call``: joined text blocks, error flag, structured content."""

    text: str
    is_error: bool = False
    structured: Any = None


@dataclass
class _Pending:
    replies: "queue.Queue[dict[str, Any]]" = field(default_factory=lambda: queue.Queue(maxsize=1))


class ToolCalls:
    """Listing and calling tools over any transport that provides ``request``.

    Subclasses set ``spec``, ``_state_lock`` and ``_tools`` (the cached list,
    None until fetched) and implement ``request(method, params, timeout)``.
    """

    spec: McpServerSpec
    _state_lock: threading.Lock
    _tools: list[dict[str, Any]] | None

    def request(self, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        raise NotImplementedError

    def list_tools(self) -> list[dict[str, Any]]:
        """Return every tool the server offers (name, description, inputSchema)."""
        with self._state_lock:
            if self._tools is not None:
                return list(self._tools)
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_TOOL_PAGES):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, LIST_TIMEOUT_SECONDS)
            tools.extend(tool for tool in result.get("tools", []) if isinstance(tool, dict) and tool.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        with self._state_lock:
            self._tools = tools
        return list(tools)

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float) -> ToolResult:
        result = self.request("tools/call", {"name": name, "arguments": arguments}, timeout)
        texts = [
            str(block.get("text", ""))
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return ToolResult(
            text="\n".join(texts),
            is_error=bool(result.get("isError")),
            structured=result.get("structuredContent"),
        )


class McpSession(ToolCalls):
    """One started and initialised MCP server process."""

    def __init__(self, spec: McpServerSpec, startup_timeout: float = STARTUP_TIMEOUT_SECONDS) -> None:
        self.spec = spec
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._next_id = 1
        self._tools: list[dict[str, Any]] | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)
        self._closed = False
        try:
            self._process = subprocess.Popen(
                [spec.command, *spec.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **dict(spec.env)},
                start_new_session=True,
            )
        except OSError as exc:
            raise McpError(f"could not start tool server '{spec.name}': {exc}") from exc
        threading.Thread(target=self._read_stdout, name=f"mcp-{spec.name}-out", daemon=True).start()
        threading.Thread(target=self._read_stderr, name=f"mcp-{spec.name}-err", daemon=True).start()
        try:
            self.request(
                "initialize",
                {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
                timeout=startup_timeout,
            )
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpError:
            self.close()
            raise

    @property
    def alive(self) -> bool:
        return not self._closed and self._process.poll() is None

    def _describe_failure(self, reason: str) -> str:
        tail = " | ".join(line for line in self._stderr_tail if line)
        return f"tool server '{self.spec.name}' {reason}" + (f" ({tail[-600:]})" if tail else "")

    def _send(self, message: dict[str, Any]) -> None:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                assert self._process.stdin is not None
                self._process.stdin.write(data)
                self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(self._describe_failure("is not running")) from exc

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for raw in self._process.stdout:
            try:
                message = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue  # servers sometimes print stray log lines on stdout
            if not isinstance(message, dict):
                continue
            if "method" in message:
                self._handle_incoming(message)
            elif "id" in message:
                with self._state_lock:
                    pending = self._pending.pop(message["id"], None)
                if pending is not None:
                    pending.replies.put(message)
        # The process closed stdout: wake every caller still waiting.
        with self._state_lock:
            waiting, self._pending = list(self._pending.values()), {}
        for pending in waiting:
            pending.replies.put({"error": {"message": "connection closed"}, "_closed": True})

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for raw in self._process.stderr:
            self._stderr_tail.append(raw.decode("utf-8", errors="replace").strip())

    def _handle_incoming(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if "id" not in message:
            if method == "notifications/tools/list_changed":
                with self._state_lock:
                    self._tools = None
            return
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        if method == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": f"method not supported: {method}"}
        try:
            self._send(reply)
        except McpError:
            pass

    def request(self, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        """Send one JSON-RPC request and return its ``result`` object."""
        pending = _Pending()
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = pending
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._send(message)
            reply = pending.replies.get(timeout=timeout)
        except queue.Empty:
            raise McpError(self._describe_failure(f"did not answer within {timeout:g}s")) from None
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if reply.get("_closed"):
            raise McpError(self._describe_failure("stopped unexpectedly"))
        if "error" in reply:
            error = reply["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(f"tool server '{self.spec.name}' reported: {detail}")
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        """Stop the server: close stdin, then SIGTERM, then SIGKILL its process group."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        except OSError:
            pass
        for sig, wait in ((None, 1.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            if sig is not None:
                try:
                    os.killpg(self._process.pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                self._process.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        for stream in (self._process.stdout, self._process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass


class McpManager:
    """Owns the configured servers and their sessions for the daemon's lifetime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._specs: dict[str, McpServerSpec] = {}
        self._sessions: dict[str, ToolCalls] = {}
        self._start_locks: dict[str, threading.Lock] = {}
        self._last_start: dict[str, float] = {}

    def configure(self, specs: list[McpServerSpec]) -> None:
        """Replace the server set. Sessions of removed or changed servers are stopped."""
        wanted = {spec.name: spec for spec in specs}
        with self._lock:
            stale = [name for name, spec in self._specs.items() if wanted.get(name) != spec]
            closing = [self._sessions.pop(name) for name in stale if name in self._sessions]
            for name in stale:
                self._last_start.pop(name, None)
            self._specs = wanted
        for session in closing:
            session.close()

    def server_names(self) -> list[str]:
        with self._lock:
            return sorted(self._specs)

    def spec(self, name: str) -> McpServerSpec | None:
        with self._lock:
            return self._specs.get(name)

    def session(self, name: str) -> "ToolCalls":
        """Return a live session for ``name``, starting or restarting it if needed."""
        with self._lock:
            spec = self._specs.get(name)
            if spec is None:
                raise McpError(f"tool server '{name}' is not set up")
            start_lock = self._start_locks.setdefault(name, threading.Lock())
        with start_lock:
            with self._lock:
                session = self._sessions.get(name)
                last_start = self._last_start.get(name, 0.0)
            if session is not None and session.alive:
                return session
            if session is not None:
                session.close()
            wait = RESTART_INTERVAL_SECONDS - (time.monotonic() - last_start)
            if last_start and wait > 0:
                raise McpError(f"tool server '{name}' is not running; retrying shortly")
            with self._lock:
                self._last_start[name] = time.monotonic()
                self._sessions.pop(name, None)
            if spec.url:
                from .mcp_http import McpHttpSession

                session = McpHttpSession(spec)
            else:
                session = McpSession(spec)
            with self._lock:
                if self._specs.get(name) != spec:
                    session.close()
                    raise McpError(f"tool server '{name}' was reconfigured; try again")
                self._sessions[name] = session
            return session

    def list_tools(self, name: str) -> list[dict[str, Any]]:
        return self.session(name).list_tools()

    def call_tool(self, name: str, tool: str, arguments: dict[str, Any], timeout: float) -> ToolResult:
        return self.session(name).call_tool(tool, arguments, timeout)

    def status(self) -> dict[str, str]:
        """``running`` or ``stopped`` for each configured server, without starting any."""
        with self._lock:
            return {
                name: "running" if (name in self._sessions and self._sessions[name].alive) else "stopped"
                for name in sorted(self._specs)
            }

    def close_all(self) -> None:
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for session in sessions:
            session.close()

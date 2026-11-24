"""MCP over HTTP ("streamable HTTP"): a tool server the assistant reaches by web address.

Some tool servers run as services rather than programs the assistant starts:
the user gives their address (``url`` in a ``tool_servers`` entry,
``settings.py``) and any headers they need (``headers``, for example an API
key, stored and redacted like environment values). ``McpHttpSession`` speaks
JSON-RPC to that address the way the MCP specification's HTTP transport
describes: every message is a ``POST`` with ``Accept: application/json,
text/event-stream``; the reply is either one JSON object or an event stream
whose ``data:`` lines carry the reply; the ``Mcp-Session-Id`` header the
server returns on ``initialize`` is sent on every later request, and a
``DELETE`` ends the session on ``close``.

It offers the same calls as the stdio ``McpSession`` (through
``mcp_client.ToolCalls``), so ``McpManager`` and everything above it treat
both alike. Requests are synchronous with the caller's timeout; there is no
background process, so ``alive`` is true until ``close``. Server-initiated
requests (sampling, elicitation) are not supported and are ignored.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from .mcp_client import (
    CLIENT_INFO,
    PROTOCOL_VERSION,
    STARTUP_TIMEOUT_SECONDS,
    McpError,
    McpServerSpec,
    ToolCalls,
)


def _from_event_stream(body: str, request_id: int) -> dict[str, Any] | None:
    """The JSON-RPC reply with ``request_id`` in an event stream, if present."""
    data: list[str] = []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            try:
                message = json.loads("\n".join(data))
            except ValueError:
                message = None
            data = []
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
    return None


class McpHttpSession(ToolCalls):
    """One initialised session with an HTTP MCP server."""

    def __init__(self, spec: McpServerSpec, startup_timeout: float = STARTUP_TIMEOUT_SECONDS) -> None:
        if not spec.url.startswith(("http://", "https://")):
            raise McpError(f"tool server '{spec.name}': its address must start with http:// or https://")
        self.spec = spec
        self._state_lock = threading.Lock()
        self._tools: list[dict[str, Any]] | None = None
        self._session_id = ""
        self._next_id = 1
        self._closed = False
        self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
                     startup_timeout)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, startup_timeout)

    @property
    def alive(self) -> bool:
        return not self._closed

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION, **dict(self.spec.headers)}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, message: dict[str, Any], timeout: float) -> tuple[str, str]:
        request = urllib.request.Request(self.spec.url, data=json.dumps(message).encode(), method="POST",
                                         headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self._session_id = session
                return response.headers.get_content_type(), response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            raise McpError(f"tool server '{self.spec.name}' answered HTTP {error.code}"
                           + (" (check its API key or headers)" if error.code in (401, 403) else "")) from error
        except (OSError, ValueError) as error:
            raise McpError(f"tool server '{self.spec.name}' at {self.spec.url} could not be reached: {error}") from error

    def request(self, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        """Send one JSON-RPC request and return its ``result`` object."""
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        kind, body = self._post(message, timeout)
        if kind == "text/event-stream":
            reply = _from_event_stream(body, request_id)
        else:
            try:
                reply = json.loads(body) if body.strip() else None
            except ValueError:
                reply = None
        if not isinstance(reply, dict):
            raise McpError(f"tool server '{self.spec.name}' sent a reply that is not MCP")
        if "error" in reply:
            error = reply["error"]
            raise McpError(f"tool server '{self.spec.name}' reported: "
                           f"{error.get('message') if isinstance(error, dict) else error}")
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._session_id:
            request = urllib.request.Request(self.spec.url, method="DELETE", headers=self._headers())
            try:
                urllib.request.urlopen(request, timeout=3).close()
            except (OSError, ValueError):
                pass

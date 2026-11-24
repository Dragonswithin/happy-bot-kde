"""``happy-bot mcp-serve``: lends the assistant's built-in desktop tools to other AI programs over MCP.

Another agent (a coding assistant, a chat app) lists this command as a stdio
MCP server. It then sees the assistant's built-in tools (windows, settings,
files, ...) and can call them, while the assistant's own rules still apply:
the daemon (``GET /tools/catalog``, ``POST /tools/run`` in ``daemon_routes``)
refuses everything unless the user switched on "Let other AI programs use
these tools" in the settings, refuses any call the approval policy would put
to the user, and writes every change to the action log.

This module is the stdio side only: newline-delimited JSON-RPC 2.0 on stdin
and stdout, answering ``initialize``, ``ping``, ``tools/list`` and
``tools/call``, and ignoring notifications. It talks to the daemon with the
CLI's authenticated ``request_json``; nothing but protocol messages is ever
written to stdout. The stdio loop itself (``serve_lines``) is shared with
``file_index_server``, Happy Bot's other built-in MCP server.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from . import __version__
from .mcp_client import PROTOCOL_VERSION

Request = Callable[..., dict[str, Any]]


def handle(message: dict[str, Any], request_json: Request) -> dict[str, Any] | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    if "id" not in message:
        return None
    method, ident = message.get("method"), message["id"]

    def reply(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def failure(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}

    if method == "initialize":
        return reply({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "happy-bot", "version": __version__}})
    if method == "ping":
        return reply({})
    if method == "tools/list":
        answer = request_json("GET", "/tools/catalog")
        if answer.get("ok") is False:
            return failure(-32000, answer.get("error", "the assistant refused"))
        return reply({"tools": answer["tools"]})
    if method == "tools/call":
        params = message.get("params") or {}
        answer = request_json("POST", "/tools/run", {"name": params.get("name"), "arguments": params.get("arguments") or {}},
                              timeout=600.0)
        if answer.get("ok") is False:
            return failure(-32000, answer.get("error", "the assistant refused"))
        return reply({"content": [{"type": "text", "text": answer["text"]}], "isError": not answer["succeeded"]})
    return failure(-32601, f"method not found: {method}")


def serve(request_json: Request, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    return serve_lines(lambda message: handle(message, request_json), stdin, stdout)


def serve_lines(handler: Callable[[dict[str, Any]], dict[str, Any] | None],
                stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """The stdio loop shared with ``file_index_server``: one JSON-RPC message per line, one reply per request.

    A line that is not JSON gets a parse error; an exception in ``handler`` becomes that request's error
    reply, so the server never dies mid-session.
    """
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        try:
            answer = handler(message) if isinstance(message, dict) else None
        except Exception as error:  # noqa: BLE001 - the daemon or an index may be down; answer instead of dying
            answer = {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32000, "message": str(error)}}
        if answer is not None:
            stdout.write(json.dumps(answer) + "\n")
            stdout.flush()
    return 0

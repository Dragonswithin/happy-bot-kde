"""An in-process HTTP server that imitates an OpenAI-compatible model service.

Tests script it by queueing replies. Each ``POST .../chat/completions`` pops
the next reply and the request body is recorded in ``requests`` for
assertions. A reply is either a list of stream chunks (dicts sent as
``data:`` events, followed by ``[DONE]``), or a ``(status, body)`` tuple for
an error response. ``GET .../models`` returns ``models``.

``chunks_for`` builds the chunk list for a typical reply: text split into
pieces, tool calls split into argument fragments the way real services send
them, a finish reason and a usage record.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def chunks_for(text: str = "", tool_calls: list[tuple[str, str, str]] | None = None,
               reasoning: bool = False, finish: str | None = None) -> list[dict[str, Any]]:
    """Chunks for a reply. ``tool_calls`` is ``[(id, name, arguments_json), ...]``."""
    chunks: list[dict[str, Any]] = [{"choices": [{"delta": {"role": "assistant", "content": None}}]}]
    if reasoning:
        chunks.append({"choices": [{"delta": {"reasoning_content": "thinking..."}}]})
    for index in range(0, len(text), 5):
        chunks.append({"choices": [{"delta": {"content": text[index:index + 5]}}]})
    for index, (call_id, name, arguments) in enumerate(tool_calls or []):
        half = max(1, len(arguments) // 2)
        chunks.append({"choices": [{"delta": {"tool_calls": [{
            "index": index, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments[:half]}}]}}]})
        chunks.append({"choices": [{"delta": {"tool_calls": [{
            "index": index, "function": {"arguments": arguments[half:]}}]}}]})
    chunks.append({"choices": [{"delta": {}, "finish_reason": finish or ("tool_calls" if tool_calls else "stop")}]})
    chunks.append({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7}})
    return chunks


class FakeModelService:
    def __init__(self) -> None:
        self.replies: list[Any] = []
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.models: Any = {"data": [{"id": "fake-model", "meta": {"n_ctx": 4096}}, {"id": "other"}]}
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:  # noqa: N802
                service.headers.append({key.lower(): value for key, value in self.headers.items()})
                if self.path.endswith("/models") and self.path.startswith("/v1"):
                    self._send(200, service.models)
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                service.requests.append(body)
                service.headers.append({key.lower(): value for key, value in self.headers.items()})
                reply = service.replies.pop(0) if service.replies else (500, {"error": {"message": "no reply scripted"}})
                if isinstance(reply, tuple):
                    self._send(*reply)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    self.wfile.write(b": comment line\n\n")
                    for chunk in reply:
                        self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                except OSError:
                    pass

            def _send(self, status: int, payload: Any) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

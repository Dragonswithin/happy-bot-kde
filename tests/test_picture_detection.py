"""Tests for asking a local model service whether a model accepts images (``model_discovery.sees_pictures``).

A small HTTP server on loopback plays each kind of service: llama.cpp's model list (an entry's
``architecture.input_modalities``, or a ``models`` entry's ``capabilities``), an Ollama-style
``POST /api/show`` (as FastFlowLM answers), and one that says nothing about pictures. No real
model service is asked.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.model_discovery import sees_pictures  # noqa: E402


class Service(BaseHTTPRequestHandler):
    """Answers with ``server.answers[path]`` (a JSON document), else 404."""

    def _answer(self) -> None:
        document = self.server.answers.get(self.path)
        if document is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(document).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        self._answer()

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._answer()

    def log_message(self, *args) -> None:
        pass


class PictureDetectionTests(unittest.TestCase):
    def serve(self, answers: dict[str, object]) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
        server.answers = answers
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/v1"

    def test_llama_cpp_input_modalities(self) -> None:
        base = self.serve({"/v1/models": {"data": [{"id": "qwen", "architecture": {"input_modalities": ["text", "image"]}}]}})
        self.assertIs(sees_pictures(base, "qwen"), True)
        self.assertIs(sees_pictures(base, "other"), None)

    def test_model_capabilities_in_the_list(self) -> None:
        base = self.serve({"/v1/models": {"data": [{"id": "m"}], "models": [{"name": "m", "capabilities": ["completion"]}]}})
        self.assertIs(sees_pictures(base, "m"), False)

    def test_ollama_style_show(self) -> None:
        base = self.serve({"/v1/models": {"data": [{"id": "qwen"}]}, "/api/show": {"capabilities": ["chat", "vision"]}})
        self.assertIs(sees_pictures(base, "qwen"), True)

    def test_a_service_that_says_nothing(self) -> None:
        self.assertIsNone(sees_pictures(self.serve({"/v1/models": {"data": [{"id": "m"}]}}), "m"))


if __name__ == "__main__":
    unittest.main()

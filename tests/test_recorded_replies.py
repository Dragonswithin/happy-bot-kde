"""Replays real AI services' recorded replies through the providers, with no network.

Each folder under tests/fixtures/model_replies/ holds what one service really streamed back for
model_check's fixed requests (recorded with scripts/record_model_replies.py) and a cases.json with
the provider kind and what a correct reading is: the tool calls (name and arguments, in order) or
text the answer contains. A local HTTP server sends each recording back as the service did, and the
provider must read it the same way. A change that misreads one service's stream (as Gemini's
index-less tool calls once were) fails here before it reaches anyone. To refresh a recording, run
the script again for that service.
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

from happy_bot import model_check  # noqa: E402
from happy_bot.conversation import Message  # noqa: E402
from happy_bot.providers import create_provider  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "model_replies"


class Replay(BaseHTTPRequestHandler):
    """Answers every POST with the recording in ``server.body``, as a stream."""

    def do_POST(self) -> None:  # noqa: N802 (http.server's name)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *args) -> None:
        pass


class RecordedReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Replay)
        cls.server.body = b""
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_there_are_recordings(self) -> None:
        self.assertTrue(list(FIXTURES.glob("*/cases.json")), "no recorded replies; see scripts/record_model_replies.py")

    def test_every_recorded_reply_is_read_correctly(self) -> None:
        base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        for manifest_path in sorted(FIXTURES.glob("*/cases.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            provider = create_provider({"provider": manifest["provider"], "base_url": base_url,
                                        "model": manifest["model"], "api_key": "replay"})
            for case, expected in manifest["cases"].items():
                with self.subTest(service=manifest_path.parent.name, case=case):
                    self.server.body = (manifest_path.parent / f"{case}.sse").read_bytes()
                    tools = [] if case == "text" else [model_check.WEATHER, model_check.CLOCK]
                    reply = model_check._Reply(provider, [Message("user", "replayed")], tools)
                    self.assertEqual([call.arguments_error for call in reply.calls if call.arguments_error], [])
                    if "calls" in expected:
                        self.assertEqual([[call.name, call.arguments] for call in reply.calls], expected["calls"])
                        self.assertEqual(len({call.id for call in reply.calls}), len(reply.calls))  # kept apart
                    if "text_contains" in expected:
                        self.assertIn(expected["text_contains"], reply.text.lower())


if __name__ == "__main__":
    unittest.main()

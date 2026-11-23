"""Access-control tests for the daemon's loopback HTTP server.

Each test starts a real ``AssistantServer`` on an ephemeral loopback port
with a temporary runtime directory and sends raw requests with
``http.client``, so the ``Host``, ``Origin`` and ``Authorization`` headers are
exactly what the test sets. Only ``/health``, ``/ask`` and unknown paths are
requested, with a settings file inside the temporary directory, so nothing
here touches the desktop session or the user's configuration.

Run with ``python3 -m unittest discover -s tests`` from the repository root.
"""

from __future__ import annotations

import http.client
import json
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kde_ai_assistant.daemon_http import AssistantServer  # noqa: E402
from kde_ai_assistant.runtime_paths import read_token, state_path, token_path  # noqa: E402


class AccessControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runtime_dir = Path(self._tmp.name) / "runtime"
        self.server = AssistantServer("127.0.0.1", 0, self.runtime_dir, Path(self._tmp.name) / "config.json")
        self.port = self.server.server_address[1]
        self.token = self.server.auth_token
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)
        self._tmp.cleanup()

    def call(self, method: str = "GET", path: str = "/health", *, token: str | None = "valid",
             host: str | None = None, extra: dict[str, str] | None = None, body: bytes | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest(method, path, skip_host=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        if token is not None:
            connection.putheader("Authorization", f"Bearer {self.token if token == 'valid' else token}")
        for name, value in (extra or {}).items():
            connection.putheader(name, value)
        if body is not None:
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, payload, headers

    def test_valid_token_reaches_health(self) -> None:
        status, payload, headers = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(payload["base_url"], f"http://127.0.0.1:{self.port}")
        self.assertNotIn("access-control-allow-origin", headers)

    def test_localhost_host_header_is_accepted(self) -> None:
        status, _, _ = self.call(host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_missing_token_is_refused(self) -> None:
        status, payload, _ = self.call(token=None)
        self.assertEqual(status, 401)
        self.assertNotIn("base_url", payload)

    def test_wrong_token_is_refused(self) -> None:
        self.assertEqual(self.call(token="not-the-token")[0], 401)
        self.assertEqual(self.call(token=self.token[:-1])[0], 401)
        self.assertEqual(self.call(token="")[0], 401)

    def test_non_bearer_scheme_is_refused(self) -> None:
        status, _, _ = self.call(token=None, extra={"Authorization": f"Basic {self.token}"})
        self.assertEqual(status, 401)

    def test_browser_origin_is_refused_even_with_token(self) -> None:
        for origin in ("https://evil.example", f"http://127.0.0.1:{self.port}", "null"):
            with self.subTest(origin=origin):
                self.assertEqual(self.call(extra={"Origin": origin})[0], 403)

    def test_foreign_host_header_is_refused_even_with_token(self) -> None:
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1:1", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(self.call(host=host)[0], 403)

    def test_preflight_is_refused_without_cors_headers(self) -> None:
        status, _, headers = self.call("OPTIONS", "/ask", token=None, extra={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertFalse([name for name in headers if name.startswith("access-control-")])

    def test_post_requires_token_before_any_handler_runs(self) -> None:
        status, _, _ = self.call("POST", "/ask", token=None, body=b'{"message": "hi"}')
        self.assertEqual(status, 401)
        self.assertEqual(self.server.state.last_error, "")

    def test_authenticated_ask_streams_a_not_configured_error(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/ask", body=b'{"message": "hi"}', headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/event-stream"))
        events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
        connection.close()
        self.assertEqual([(event["type"], event.get("code")) for event in events], [("error", "not_configured")])

    def test_oversized_and_malformed_bodies_are_rejected(self) -> None:
        self.assertEqual(self.call("POST", "/ask", body=b"{not json")[0], 400)
        self.assertEqual(self.call("POST", "/ask", body=b"[1, 2]")[0], 400)
        status, _, _ = self.call("POST", "/ask", extra={"Content-Length": "99999999"})
        self.assertEqual(status, 400)

    def test_unknown_endpoint_is_404_only_when_authenticated(self) -> None:
        self.assertEqual(self.call(path="/open-full-ui")[0], 404)
        self.assertEqual(self.call(path="/open-full-ui", token=None)[0], 401)

    def test_runtime_files_are_private_and_removed_on_shutdown(self) -> None:
        self.assertEqual(stat.S_IMODE(self.runtime_dir.stat().st_mode), 0o700)
        for path in (token_path(self.runtime_dir), state_path(self.runtime_dir)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)
        self.assertEqual(read_token(self.runtime_dir), self.token)
        self.assertNotIn(self.token, state_path(self.runtime_dir).read_text(encoding="utf-8"))
        self.server.remove_runtime_files()
        self.assertEqual(read_token(self.runtime_dir), "")

    def test_each_server_gets_a_new_token(self) -> None:
        other = AssistantServer("127.0.0.1", 0, Path(self._tmp.name) / "other", Path(self._tmp.name) / "c2.json")
        try:
            self.assertNotEqual(other.auth_token, self.token)
        finally:
            other.server_close()


class BindAddressTests(unittest.TestCase):
    def test_non_loopback_bind_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for host in ("0.0.0.0", "192.168.1.10", "example.com"):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    AssistantServer(host, 0, Path(tmp), Path(tmp) / "config.json")


if __name__ == "__main__":
    unittest.main()

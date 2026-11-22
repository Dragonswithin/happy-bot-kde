"""Loopback HTTP server of the per-user daemon: routing, access control, state.

This is the process the systemd user unit runs. It exposes the assistant to
the panel applet and the CLI over ``http://127.0.0.1:<port>`` and is the only
component allowed to act for the user, so every request must pass three
checks before any handler runs (see ``Handler._authorize``):

1. ``Host`` must be the address the server is bound to. A page that reached
   the port through DNS rebinding sends its own hostname and is refused.
2. No ``Origin`` header. Browsers attach one to cross-site requests; the
   applet and the CLI never do. There are no CORS headers and no preflight.
3. ``Authorization: Bearer <token>``. The token is generated at every start
   and written 0600 into the runtime directory (``runtime_paths.token_path``),
   which keeps out other local users, who can reach loopback.

The server refuses to bind to a non-loopback address.

State: one ``DaemonState`` per server, mirrored to ``daemon.json`` in the
runtime directory so clients can find the base URL. Both that file and the
token are removed on clean shutdown. Requests are served on one thread each
(``ThreadingHTTPServer``); ``DaemonState`` guards its fields with a lock.

Desktop capture is delegated to ``desktop_context``. ``/ask`` has no model
behind it yet and answers 503.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import ipaddress
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import desktop_context
from .runtime_paths import (
    DEFAULT_HOST,
    default_port,
    ensure_runtime_root,
    state_path,
    token_path,
    write_private_file,
)

SCHEMA = "kde_ai_assistant_daemon.v1"
MAX_BODY_BYTES = 2_000_000


def user_in_group(group_name: str) -> bool:
    try:
        import grp

        group = grp.getgrnam(group_name)
    except KeyError:
        return False
    return getpass.getuser() in group.gr_mem or os.getgid() == group.gr_gid


def root_broker_status() -> dict[str, Any]:
    """Report whether the external root broker named in the environment exists."""
    broker_path = os.environ.get("KDE_AI_ASSISTANT_ROOT_BROKER", "").strip()
    admin_group = os.environ.get("KDE_AI_ASSISTANT_ADMIN_GROUP", "").strip()
    return {
        "available": bool(broker_path) and Path(broker_path).exists(),
        "path": broker_path,
        "admin_group": bool(admin_group) and user_in_group(admin_group),
        "group": admin_group,
    }


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class DaemonState:
    """Mutable daemon status shared by request threads and mirrored to disk."""

    host: str
    port: int
    runtime_dir: Path
    status: str = "idle"
    last_error: str = ""
    last_context_kind: str = ""
    last_activity_at: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": self.status,
            "user": getpass.getuser(),
            "uid": os.getuid(),
            "pid": os.getpid(),
            "base_url": self.base_url,
            "last_error": self.last_error,
            "last_context_kind": self.last_context_kind,
            "last_activity_at": self.last_activity_at,
            "root_broker": root_broker_status(),
        }

    def update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                if key.startswith("_") or not hasattr(self, key):
                    raise AttributeError(f"unknown daemon state field: {key}")
                setattr(self, key, value)
            self.last_activity_at = desktop_context.now_iso()
            self.persist()

    def persist(self) -> None:
        write_private_file(state_path(self.runtime_dir), json.dumps(self.as_dict(), indent=2))


class AssistantServer(ThreadingHTTPServer):
    """HTTP server carrying the per-instance token, state and allowed hosts."""

    daemon_threads = True

    def __init__(self, host: str, port: int, runtime_dir: Path) -> None:
        if not is_loopback_host(host):
            raise ValueError(f"refusing to listen on non-loopback address {host!r}")
        super().__init__((host, port), Handler)
        bound_port = self.server_address[1]
        self.runtime_dir = ensure_runtime_root(runtime_dir)
        self.auth_token = secrets.token_urlsafe(32)
        self.allowed_hosts = frozenset({f"{host}:{bound_port}", f"localhost:{bound_port}"})
        self.state = DaemonState(host=host, port=bound_port, runtime_dir=self.runtime_dir)
        write_private_file(token_path(self.runtime_dir), self.auth_token)
        self.state.persist()

    def remove_runtime_files(self) -> None:
        for path in (state_path(self.runtime_dir), token_path(self.runtime_dir)):
            try:
                path.unlink()
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "KDEAiAssistant/0.2"
    server: AssistantServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _authorize(self) -> bool:
        """Apply the Host, Origin and bearer-token checks; reply and return False on failure."""
        if self.headers.get("Host", "") not in self.server.allowed_hosts:
            self._json(403, {"ok": False, "error": "forbidden host"})
            return False
        if self.headers.get("Origin") is not None:
            self._json(403, {"ok": False, "error": "browser requests are not allowed"})
            return False
        scheme, _, presented = self.headers.get("Authorization", "").partition(" ")
        expected = self.server.auth_token
        if scheme != "Bearer" or not hmac.compare_digest(presented.strip().encode(), expected.encode()):
            self._json(401, {"ok": False, "error": "missing or invalid token"})
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler name
        self._json(403, {"ok": False, "error": "browser requests are not allowed"})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        state = self.server.state
        if parsed.path == "/health":
            self._json(200, state.as_dict())
            return
        if parsed.path == "/context":
            kind = (parse_qs(parsed.query).get("kind") or ["combined"])[0]
            context = desktop_context.combined_context(kind)
            state.update(status="idle", last_context_kind=kind)
            self._json(200, {"ok": True, "context": context})
            return
        self._json(404, {"ok": False, "error": "unknown endpoint"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/ask":
            self._handle_ask(body)
            return
        if parsed.path == "/screenshot":
            self._json(200, desktop_context.take_screenshot(self.server.runtime_dir))
            return
        self._json(404, {"ok": False, "error": "unknown endpoint"})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _handle_ask(self, body: dict[str, Any]) -> None:
        message = str(body.get("message") or "").strip()
        if not message:
            self._json(400, {"ok": False, "error": "message is required"})
            return
        context_kind = str(body.get("contextKind") or "combined")
        error = "No AI model is set up yet."
        self.server.state.update(last_error=error, last_context_kind=context_kind)
        self._json(503, {"ok": False, "error": error})


def serve(host: str, port: int, runtime_dir: Path | None = None) -> int:
    server = AssistantServer(host, port, ensure_runtime_root(runtime_dir))
    print(f"KDE AI Assistant daemon listening on {host}:{server.state.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.server_close()
        finally:
            server.remove_runtime_files()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KDE AI Assistant desktop daemon.")
    parser.add_argument("--host", default=os.environ.get("KDE_AI_ASSISTANT_DAEMON_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KDE_AI_ASSISTANT_DAEMON_PORT", default_port())),
    )
    parser.add_argument("--foreground", action="store_true", help="Run the HTTP bridge in the foreground.")
    parser.add_argument(
        "--print-context",
        choices=desktop_context.CONTEXT_KINDS,
        help="Print captured context and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_context:
        print(json.dumps(desktop_context.combined_context(args.print_context), indent=2, ensure_ascii=False))
        return 0
    if not args.foreground:
        raise SystemExit("use --foreground under systemd or during manual testing")
    return serve(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())

"""Loopback HTTP server of the per-user daemon: access control, dispatch, state.

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

The server object is also where the daemon's long-lived parts hang: its
``DaemonState`` (mirrored to ``daemon.json`` in the runtime directory so
clients can find the base URL), the current settings, and the ``McpManager``
that owns the tool-server child processes. ``replace_settings`` is the single
path that changes settings: it validates, saves, then reconfigures the
manager, under one lock. Unreadable settings at start do not stop the daemon;
it runs with defaults and reports ``settings_error`` in ``/health``.

Requests are served on one thread each (``ThreadingHTTPServer``). What each
endpoint does lives in ``daemon_routes``; this module only authenticates,
parses and dispatches. On shutdown the state file and token are removed and
every tool server is stopped.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import ipaddress
import json
import os
import secrets
import signal
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import desktop_context
from . import settings as settings_store
from .daemon_routes import ROUTES
from .mcp_client import McpManager
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

    def __init__(self, host: str, port: int, runtime_dir: Path, config_file: Path | None = None) -> None:
        if not is_loopback_host(host):
            raise ValueError(f"refusing to listen on non-loopback address {host!r}")
        super().__init__((host, port), Handler)
        bound_port = self.server_address[1]
        self.runtime_dir = ensure_runtime_root(runtime_dir)
        self.auth_token = secrets.token_urlsafe(32)
        self.allowed_hosts = frozenset({f"{host}:{bound_port}", f"localhost:{bound_port}"})
        self.state = DaemonState(host=host, port=bound_port, runtime_dir=self.runtime_dir)
        self.config_file = config_file or settings_store.config_path()
        self.mcp = McpManager()
        self._settings_lock = threading.Lock()
        self.settings_error = ""
        try:
            self.settings = settings_store.load_settings(self.config_file)
        except settings_store.SettingsError as exc:
            self.settings = settings_store.default_settings()
            self.settings_error = str(exc)
        self.mcp.configure(settings_store.server_specs(self.settings))
        write_private_file(token_path(self.runtime_dir), self.auth_token)
        self.state.persist()

    def replace_settings(self, new_settings: Any) -> dict[str, Any]:
        """Validate and store new settings, then restart affected tool servers."""
        with self._settings_lock:
            stored = settings_store.save_settings(new_settings, self.config_file)
            self.settings = stored
            self.settings_error = ""
            self.mcp.configure(settings_store.server_specs(stored))
            return stored

    def shutdown_tools(self) -> None:
        self.mcp.close_all()

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

    def _dispatch(self, method: str) -> None:
        if not self._authorize():
            return
        parsed = urlparse(self.path)
        route = ROUTES.get((method, parsed.path))
        if route is None:
            self._json(404, {"ok": False, "error": "unknown endpoint"})
            return
        body: dict[str, Any] = {}
        if method != "GET":
            try:
                body = self._read_json()
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
        status, payload = route(self.server, parse_qs(parsed.query), body)
        self._json(status, payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler name
        self._dispatch("PUT")

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


def serve(host: str, port: int, runtime_dir: Path | None = None) -> int:
    server = AssistantServer(host, port, ensure_runtime_root(runtime_dir))
    print(f"KDE AI Assistant daemon listening on {host}:{server.state.port}", flush=True)

    def stop_on_signal(signum: int, frame: Any) -> None:
        # systemd stops the unit with SIGTERM; unwind like Ctrl+C so the
        # cleanup below removes the token and stops the tool servers.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.server_close()
        finally:
            server.shutdown_tools()
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

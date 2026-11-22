"""Command-line client for the per-user daemon (``kde-ai-assistant``).

Sends one request to the daemon's loopback HTTP API and prints the JSON
reply. It finds the daemon through ``KDE_AI_ASSISTANT_DAEMON_URL``, else the
``base_url`` in the daemon's state file, else the default per-uid port, and
authenticates with the bearer token the daemon writes into the runtime
directory (see ``runtime_paths``).

If the daemon does not answer, the client starts the systemd user unit and
waits a few seconds. The token is re-read on every request because it changes
each time the daemon starts. Failures are printed as ``{"ok": false, ...}``
with exit status 1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .runtime_paths import DEFAULT_HOST, default_port, read_token, state_path

SERVICE_NAME = "kde-ai-assistant-daemon.service"
CONTEXT_KINDS = ("combined", "clipboard", "window")


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def base_url() -> str:
    env_url = os.environ.get("KDE_AI_ASSISTANT_DAEMON_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    raw = str(read_state().get("base_url") or "").strip()
    return raw.rstrip("/") if raw else f"http://{DEFAULT_HOST}:{default_port()}"


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Call the daemon. HTTP error replies are returned as their JSON body."""
    data = None
    headers = {"Authorization": f"Bearer {read_token()}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url()}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        body.setdefault("ok", False)
        body.setdefault("error", f"daemon returned HTTP {exc.code}")
        body["http_status"] = exc.code
        return body


def daemon_ready() -> bool:
    try:
        return "schema" in request_json("GET", "/health", timeout=1.0)
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def ensure_daemon(timeout: float = 6.0) -> None:
    if daemon_ready():
        return
    subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_ready():
            return
        time.sleep(0.25)
    raise RuntimeError("KDE AI Assistant daemon is not reachable")


def emit(value: dict[str, Any], pretty: bool) -> None:
    print(json.dumps(value, indent=2 if pretty else None, ensure_ascii=False))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Talk to the KDE AI Assistant daemon.")
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("endpoint", help="Print the daemon base URL.")
    sub.add_parser("status", help="Show daemon health/status.")

    context = sub.add_parser("context", help="Capture KDE desktop context.")
    context.add_argument("--kind", choices=CONTEXT_KINDS, default="combined")

    ask = sub.add_parser("ask", help="Send a request to the assistant.")
    ask.add_argument("message", nargs="+")
    ask.add_argument("--context-kind", choices=CONTEXT_KINDS, default="combined")

    sub.add_parser("screenshot", help="Take an explicit context screenshot into XDG_RUNTIME_DIR.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ensure_daemon()
        if args.command == "endpoint":
            print(base_url())
            return 0
        if args.command == "status":
            reply = request_json("GET", "/health")
        elif args.command == "context":
            reply = request_json("GET", f"/context?kind={args.kind}")
        elif args.command == "ask":
            payload = {"message": " ".join(args.message), "contextKind": args.context_kind}
            reply = request_json("POST", "/ask", payload, timeout=360.0)
        else:
            reply = request_json("POST", "/screenshot", {}, timeout=40.0)
    except (RuntimeError, URLError, TimeoutError, OSError) as exc:
        emit({"ok": False, "error": str(exc)}, args.pretty)
        return 1
    emit(reply, args.pretty)
    return 1 if reply.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

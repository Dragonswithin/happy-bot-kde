#!/usr/bin/env python3
"""Small CLI client for the KDE AI Assistant daemon."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE_PORT = 19000


def default_port() -> int:
    return BASE_PORT + max(0, os.getuid() - 1000)


DEFAULT_URL = f"http://127.0.0.1:{default_port()}"


def runtime_root() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / "kde-ai-assistant"
    return Path("/tmp") / f"kde-ai-assistant-{os.getuid()}"


def state_path() -> Path:
    return runtime_root() / "daemon.json"


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
    state = read_state()
    raw = str(state.get("base_url") or "").strip()
    return raw.rstrip("/") if raw else DEFAULT_URL


def request_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url()}{path}", data=data, method=method, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_daemon(timeout: float = 6.0) -> None:
    try:
        request_json("GET", "/health", timeout=1.0)
        return
    except Exception:
        pass

    subprocess.run(["systemctl", "--user", "start", "kde-ai-assistant-daemon.service"], check=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request_json("GET", "/health", timeout=1.0)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("KDE AI Assistant daemon is not reachable")


def emit(value: dict[str, Any], pretty: bool) -> None:
    print(json.dumps(value, indent=2 if pretty else None, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Talk to the KDE AI Assistant daemon.")
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("endpoint", help="Print the daemon base URL.")
    sub.add_parser("status", help="Show daemon health/status.")

    context = sub.add_parser("context", help="Capture KDE desktop context.")
    context.add_argument("--kind", choices=("combined", "clipboard", "window"), default="combined")

    ask = sub.add_parser("ask", help="Ask the assistant through OpenCode.")
    ask.add_argument("message", nargs="+")
    ask.add_argument("--context-kind", choices=("combined", "clipboard", "window"), default="combined")

    sub.add_parser("open-full-ui", help="Open the user's full assistant UI.")
    sub.add_parser("open-openchamber", help="Compatibility alias for open-full-ui.")
    sub.add_parser("screenshot", help="Take an explicit context screenshot into XDG_RUNTIME_DIR.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "endpoint":
        ensure_daemon()
        print(base_url())
        return 0

    try:
        ensure_daemon()
        if args.command == "status":
            emit(request_json("GET", "/health"), args.pretty)
        elif args.command == "context":
            emit(request_json("GET", f"/context?kind={args.kind}"), args.pretty)
        elif args.command == "ask":
            payload = {"message": " ".join(args.message), "contextKind": args.context_kind}
            emit(request_json("POST", "/ask", payload, timeout=360.0), args.pretty)
        elif args.command in {"open-full-ui", "open-openchamber"}:
            emit(request_json("POST", "/open-full-ui", {"open": True}), args.pretty)
        elif args.command == "screenshot":
            emit(request_json("POST", "/screenshot", {}), args.pretty)
        else:
            raise RuntimeError(f"unknown command: {args.command}")
    except (RuntimeError, URLError, TimeoutError) as exc:
        emit({"ok": False, "error": str(exc)}, args.pretty)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

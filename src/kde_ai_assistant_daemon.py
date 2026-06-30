#!/usr/bin/env python3
"""Per-user desktop bridge for the KDE AI Assistant plasmoid."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


SCHEMA = "kde_ai_assistant_daemon.v1"
BASE_PORT = 19000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PUBLIC_ASSISTANT_URL = "https://ai.example.com"
MAX_CLIPBOARD_CHARS = 12000
MAX_PROMPT_CHARS = 60000
SERVICE_NAME = "kde-ai-assistant-daemon.service"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_port() -> int:
    return BASE_PORT + max(0, os.getuid() - 1000)


def runtime_root() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / "kde-ai-assistant"
    return Path("/tmp") / f"kde-ai-assistant-{os.getuid()}"


def state_path() -> Path:
    return runtime_root() / "daemon.json"


def default_workspace() -> Path:
    return Path.home() / "AI Assistant"


def short_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 80].rstrip() + "\n[truncated by KDE AI Assistant]"


def run_command(command: list[str], timeout: float = 5.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"timed out after {timeout:g}s",
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def qdbus_call(args: list[str], timeout: float = 4.0) -> dict[str, Any]:
    command = [shutil.which("qdbus6") or "/usr/bin/qdbus6", *args]
    return run_command(command, timeout=timeout)


def clipboard_context() -> dict[str, Any]:
    result = qdbus_call(
        [
            "org.kde.klipper",
            "/klipper",
            "org.kde.klipper.klipper.getClipboardContents",
        ],
        timeout=3.0,
    )
    text = result["stdout"].strip() if result["ok"] else ""
    return {
        "available": bool(text),
        "source": "klipper",
        "text": short_text(text, MAX_CLIPBOARD_CHARS),
        "error": "" if result["ok"] else (result["stderr"].strip() or "Klipper DBus call failed"),
    }


def parse_qdbus_key_values(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def active_window_context() -> dict[str, Any]:
    result = qdbus_call(
        ["org.kde.KWin", "/KWin", "org.kde.KWin.queryWindowInfo"],
        timeout=5.0,
    )
    if not result["ok"]:
        return {
            "available": False,
            "source": "kwin",
            "error": result["stderr"].strip() or "KWin DBus call failed",
        }
    parsed = parse_qdbus_key_values(result["stdout"])
    interesting = {
        "caption": parsed.get("caption", ""),
        "desktopFile": parsed.get("desktopFile", ""),
        "resourceClass": parsed.get("resourceClass", ""),
        "resourceName": parsed.get("resourceName", ""),
        "pid": parsed.get("pid", ""),
        "uuid": parsed.get("uuid", ""),
        "fullscreen": parsed.get("fullscreen", ""),
        "minimized": parsed.get("minimized", ""),
    }
    available = any(value for key, value in interesting.items() if key not in {"fullscreen", "minimized"})
    return {
        "available": available,
        "source": "kwin",
        "window": interesting,
        "error": "" if available else "KWin returned no active window details",
    }


def session_context() -> dict[str, Any]:
    entry = pwd.getpwuid(os.getuid())
    return {
        "user": getpass.getuser(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "home": entry.pw_dir,
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
    }


def combined_context(kind: str = "combined") -> dict[str, Any]:
    include_clipboard = kind in {"combined", "clipboard"}
    include_window = kind in {"combined", "window", "active-window"}
    return {
        "schema": "kde_ai_assistant_context.v1",
        "generated_at": now_iso(),
        "kind": kind,
        "session": session_context(),
        "clipboard": clipboard_context() if include_clipboard else {"available": False},
        "active_window": active_window_context() if include_window else {"available": False},
    }


def discover_full_ui_url() -> str:
    configured = (
        os.environ.get("KDE_AI_ASSISTANT_FULL_UI_URL", "")
        or os.environ.get("KDE_AI_ASSISTANT_OPENCHAMBER_URL", "")
    ).strip()
    if configured:
        return configured

    run_dir = Path.home() / ".config" / "openchamber" / "run"
    candidates = sorted(run_dir.glob("openchamber-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        port = data.get("port") or str(candidate.stem).rsplit("-", 1)[-1]
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            continue
        url = f"http://127.0.0.1:{port_int}"
        if url_ok(f"{url}/health", timeout=0.8):
            return url

    if url_ok("http://127.0.0.1:3000/health", timeout=0.8):
        return "http://127.0.0.1:3000"
    return DEFAULT_PUBLIC_ASSISTANT_URL


def url_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def find_opencode() -> str | None:
    for candidate in (
        os.environ.get("OPENCODE_BINARY", ""),
        str(Path.home() / ".local" / "bin" / "opencode"),
        shutil.which("opencode") or "",
        "/usr/bin/opencode",
    ):
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
    return None


def format_prompt(message: str, context: dict[str, Any]) -> str:
    parts = ["You are the KDE AI Assistant for this local desktop session."]
    parts.append("Answer the user directly and use the attached desktop context only when it is relevant.")
    parts.append("")
    parts.append("[Desktop Context]")
    parts.append(json.dumps(context, indent=2, ensure_ascii=False))
    parts.append("")
    parts.append("[User Request]")
    parts.append(message.strip())
    return short_text("\n".join(parts), MAX_PROMPT_CHARS)


@dataclass
class SharedState:
    host: str
    port: int
    status: str = "idle"
    last_error: str = ""
    last_context_kind: str = ""
    last_activity_at: str = ""

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
            "full_ui_url": discover_full_ui_url(),
            "openchamber_url": discover_full_ui_url(),
            "last_error": self.last_error,
            "last_context_kind": self.last_context_kind,
            "last_activity_at": self.last_activity_at,
            "root_broker": root_broker_status(),
        }


STATE_LOCK = threading.Lock()
STATE: SharedState | None = None


def user_in_group(group_name: str) -> bool:
    try:
        import grp

        group = grp.getgrnam(group_name)
    except KeyError:
        return False
    user = getpass.getuser()
    return user in group.gr_mem or os.getgid() == group.gr_gid


def root_broker_status() -> dict[str, Any]:
    broker_path = os.environ.get("KDE_AI_ASSISTANT_ROOT_BROKER", "").strip()
    admin_group = os.environ.get("KDE_AI_ASSISTANT_ADMIN_GROUP", "").strip()
    return {
        "available": bool(broker_path) and Path(broker_path).exists(),
        "path": broker_path,
        "admin_group": bool(admin_group) and user_in_group(admin_group),
        "group": admin_group,
    }


def write_state_file(state: SharedState) -> None:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    path = state_path()
    path.write_text(json.dumps(state.as_dict(), indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "KDEAiAssistant/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler name
        self._json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, current_state().as_dict())
            return
        if parsed.path == "/context":
            query = parse_qs(parsed.query)
            kind = (query.get("kind") or ["combined"])[0]
            context = combined_context(kind)
            update_state(status="idle", last_context_kind=kind)
            self._json(200, {"ok": True, "context": context})
            return
        self._json(404, {"ok": False, "error": "unknown endpoint"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/ask":
            self._handle_ask(body)
            return
        if parsed.path in {"/open-full-ui", "/open-openchamber"}:
            url = discover_full_ui_url()
            if body.get("open", True):
                webbrowser.open(url)
            self._json(200, {"ok": True, "url": url})
            return
        if parsed.path == "/screenshot":
            self._json(200, take_screenshot())
            return
        self._json(404, {"ok": False, "error": "unknown endpoint"})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 2_000_000))
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
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
        context = combined_context(context_kind)
        prompt = format_prompt(message, context)
        update_state(status="thinking", last_context_kind=context_kind)
        try:
            answer = run_opencode(prompt)
        except Exception as exc:  # noqa: BLE001 - user-facing bridge should compact failures.
            update_state(status="idle", last_error=str(exc))
            self._json(500, {"ok": False, "error": str(exc), "context": context})
            return
        update_state(status="idle", last_error="")
        self._json(200, {"ok": True, "answer": answer, "context": context})


def update_state(**changes: Any) -> None:
    state = current_state()
    with STATE_LOCK:
        for key, value in changes.items():
            if hasattr(state, key):
                setattr(state, key, value)
        state.last_activity_at = now_iso()
        write_state_file(state)


def current_state() -> SharedState:
    if STATE is None:
        raise RuntimeError("daemon state is not initialized")
    return STATE


def run_opencode(prompt: str) -> str:
    binary = find_opencode()
    if not binary:
        raise RuntimeError("OpenCode binary was not found in OPENCODE_BINARY, ~/.local/bin, or PATH")
    workspace = Path(
        os.environ.get("KDE_AI_ASSISTANT_WORKSPACE", "")
        or str(default_workspace())
    ).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    timeout = float(os.environ.get("KDE_AI_ASSISTANT_ASK_TIMEOUT", "300"))
    agent = os.environ.get("KDE_AI_ASSISTANT_OPENCODE_AGENT", "ops")
    command = [binary, "run", "--dir", str(workspace), "--agent", agent, prompt]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "OpenCode run failed").strip())
    return (completed.stdout or "").strip()


def take_screenshot() -> dict[str, Any]:
    spectacle = shutil.which("spectacle")
    if not spectacle:
        return {"ok": False, "error": "spectacle is not installed"}
    root = runtime_root() / "screenshots"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"desktop-context-{int(time.time())}.png"
    result = run_command([spectacle, "-b", "-n", "-o", str(target)], timeout=30.0)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"].strip() or "spectacle failed"}
    return {"ok": True, "path": str(target)}


def serve(host: str, port: int) -> int:
    global STATE
    STATE = SharedState(host=host, port=port)
    write_state_file(STATE)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"KDE AI Assistant daemon listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        try:
            server.server_close()
        finally:
            try:
                state_path().unlink()
            except OSError:
                pass
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KDE AI Assistant desktop daemon.")
    parser.add_argument("--host", default=os.environ.get("KDE_AI_ASSISTANT_DAEMON_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KDE_AI_ASSISTANT_DAEMON_PORT", default_port())),
    )
    parser.add_argument("--foreground", action="store_true", help="Run the HTTP bridge in the foreground.")
    parser.add_argument("--print-context", choices=("combined", "clipboard", "window"), help="Print captured context and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.print_context:
        print(json.dumps(combined_context(args.print_context), indent=2, ensure_ascii=False))
        return 0
    if not args.foreground:
        raise SystemExit("use --foreground under systemd or during manual testing")
    return serve(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())

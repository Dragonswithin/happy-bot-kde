"""Command-line client for the per-user daemon (``kde-ai-assistant``).

Sends one request to the daemon's loopback HTTP API and prints the JSON
reply. It finds the daemon through ``KDE_AI_ASSISTANT_DAEMON_URL``, else the
``base_url`` in the daemon's state file, else the default per-uid port, and
authenticates with the bearer token the daemon writes into the runtime
directory (see ``runtime_paths``).

Besides the basic commands it is the scriptable way to do what the settings
page does: ``tools`` discovers, imports and removes tool servers, and ``role``
assigns a tool to file search or web search. Both go through the daemon's
``/settings`` endpoint, which validates and saves; this client never writes
the configuration file itself.

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
from urllib.parse import quote
from urllib.request import Request, urlopen

from .runtime_paths import DEFAULT_HOST, default_port, read_token, state_path

SERVICE_NAME = "kde-ai-assistant-daemon.service"
CONTEXT_KINDS = ("combined", "clipboard", "window")
ROLE_NAMES = ("file_search", "web_search")


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
        with exc:
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

    search = sub.add_parser("search", help="Search files with the configured file-search tool.")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=8)

    open_cmd = sub.add_parser("open", help="Open a file, folder or web link.")
    open_cmd.add_argument("location")

    tools = sub.add_parser("tools", help="Manage the tool servers the assistant can use.")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("discover", help="List tool servers found in other programs' settings.")
    tools_sub.add_parser("list", help="List configured tool servers, their tools and suggested roles.")
    tools_import = tools_sub.add_parser("import", help="Add a discovered tool server.")
    tools_import.add_argument("name")
    tools_import.add_argument("--as", dest="new_name", default="", help="Store it under a different name.")
    tools_import.add_argument("--read-only", action="store_true", help="Declare that none of its tools change anything.")
    tools_remove = tools_sub.add_parser("remove", help="Remove a configured tool server.")
    tools_remove.add_argument("name")

    role = sub.add_parser("role", help="Choose which tool does file search or web search.")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    role_set = role_sub.add_parser("set", help="Assign a tool to a role.")
    role_set.add_argument("role", choices=ROLE_NAMES)
    role_set.add_argument("server")
    role_set.add_argument("tool")
    role_set.add_argument("--query-argument", default="", help="Tool argument that receives the search text.")
    role_clear = role_sub.add_parser("clear", help="Remove a role assignment.")
    role_clear.add_argument("role", choices=ROLE_NAMES)
    return parser.parse_args(argv)


def current_settings() -> dict[str, Any]:
    reply = request_json("GET", "/settings")
    if reply.get("ok") is False:
        raise RuntimeError(str(reply.get("error")))
    return reply["settings"]


def run_tools(args: argparse.Namespace) -> dict[str, Any]:
    if args.tools_command == "discover":
        return request_json("GET", "/tools/discover")
    if args.tools_command == "list":
        return request_json("GET", "/tools/servers", timeout=90.0)
    if args.tools_command == "import":
        payload = {"name": args.name, "as": args.new_name, "read_only": args.read_only}
        return request_json("POST", "/tools/import", payload)
    settings = current_settings()
    if args.name not in settings["tool_servers"]:
        return {"ok": False, "error": f"no tool server named '{args.name}' is set up"}
    del settings["tool_servers"][args.name]
    settings["roles"] = {name: role for name, role in settings["roles"].items() if role["server"] != args.name}
    return request_json("PUT", "/settings", {"settings": settings})


def run_role(args: argparse.Namespace) -> dict[str, Any]:
    settings = current_settings()
    if args.role_command == "clear":
        settings["roles"].pop(args.role, None)
        return request_json("PUT", "/settings", {"settings": settings})
    listing = request_json("GET", f"/tools/servers?name={quote(args.server)}", timeout=90.0)
    servers = listing.get("servers") or []
    if not servers:
        return {"ok": False, "error": f"no tool server named '{args.server}' is set up"}
    if servers[0]["error"]:
        return {"ok": False, "error": servers[0]["error"]}
    if args.tool not in [tool["name"] for tool in servers[0]["tools"]]:
        return {"ok": False, "error": f"'{args.server}' has no tool named '{args.tool}'"}
    config: dict[str, Any] = {"server": args.server, "tool": args.tool, "query_argument": "query", "arguments": {}}
    for proposal in servers[0]["proposals"]:
        if proposal["config"]["tool"] == args.tool:
            config = proposal["config"]
    if args.query_argument:
        config["query_argument"] = args.query_argument
    settings["roles"][args.role] = config
    return request_json("PUT", "/settings", {"settings": settings})


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
        elif args.command == "search":
            reply = request_json("GET", f"/search?q={quote(' '.join(args.query))}&limit={args.limit}", timeout=20.0)
        elif args.command == "open":
            reply = request_json("POST", "/open", {"location": args.location})
        elif args.command == "tools":
            reply = run_tools(args)
        elif args.command == "role":
            reply = run_role(args)
        else:
            reply = request_json("POST", "/screenshot", {}, timeout=40.0)
    except (RuntimeError, URLError, TimeoutError, OSError) as exc:
        emit({"ok": False, "error": str(exc)}, args.pretty)
        return 1
    emit(reply, args.pretty)
    return 1 if reply.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

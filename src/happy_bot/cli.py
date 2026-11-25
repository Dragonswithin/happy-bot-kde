"""Command-line client for the per-user daemon (``happy-bot``).

Sends one request to the daemon's loopback HTTP API and prints the JSON
reply. It finds the daemon through ``HAPPY_BOT_DAEMON_URL``, else the
``base_url`` in the daemon's state file, else the default per-uid port, and
authenticates with the bearer token the daemon writes into the runtime
directory (see ``runtime_paths``).

``ask`` streams: the assistant's text is printed as it arrives and tool
activity is reported on stderr, so stdout holds only the answer. When an
action needs approval it asks on the terminal; without a terminal it declines
at once, so a script can never approve a dangerous action by accident.
``ask --dry-run`` lets the model only look things up and list its steps;
``ask --notify`` also shows the answer and anything not done as a desktop
notification (with the mascot as its icon when that is chosen), which is how routines started by a systemd timer report back
(``routines.py``). Every other command prints one JSON reply.

``routine-check`` is what a network or battery routine's timer runs
(``routine_conditions.py``).
``app`` talks to the Happy Bot app through the daemon (``app_control.py``):
``show`` opens the floating Happy Bot of a running app (``happy-bot-app``
calls it when the app is already running), ``settings`` opens its settings
(starting it first if needed), ``start`` starts it, and
``autostart-on``/``autostart-off`` say whether it starts at login.
``eval`` runs ``evaluation.SCENARIOS`` as dry runs against a model and
prints pass or fail with timings. ``model check`` (one model, or ``--all``)
runs the compatibility check (``model_check.py``, ``POST /models/check``):
whether Happy Bot talks to each AI correctly, not how well it chooses.
``mcp-serve`` speaks MCP on stdin and stdout so another AI program can use
the built-in tools (``mcp_serve.py``). ``file-index-serve`` is the MCP server
behind setup's built-in file search choices (``file_index_server.py``); the
daemon starts it like any tool server, and it needs no daemon itself.
``doctor`` runs the daemon's self-check and prints each result with its fix.
``history`` lists saved conversations or prints one (continue it with ``ask
--conversation ID``); ``export`` writes settings without secrets plus all
conversations to a new 0600 file, and ``import`` loads such a file.

Besides the basic commands it is the scriptable way to do what the settings
page does: ``tools`` discovers, imports and removes tool servers, ``role``
assigns a tool to file search or web search, and ``model`` adds, selects and
tests AI models. All of them go through the daemon's
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
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .runtime_paths import DEFAULT_HOST, default_port, read_token, state_path

SERVICE_NAME = "happy-bot-daemon.service"
CONTEXT_KINDS = ("combined", "clipboard", "window")
ROLE_NAMES = ("file_search", "web_search")
FOLDER_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def base_url() -> str:
    env_url = os.environ.get("HAPPY_BOT_DAEMON_URL", "").strip()
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


def _assistant_icon() -> str:
    """The notification icon the user chose (the mascot or the wand), from the settings file; the wand if unreadable."""
    from . import settings as settings_store, ui_settings
    try:
        return ui_settings.assistant_icon(settings_store.load_settings().get("ui"))
    except Exception:  # a missing or broken settings file must not stop the answer being shown
        return ui_settings.WAND_ICON


def stream_ask(message: str, conversation_id: str = "", dry_run: bool = False, notify: bool = False) -> int:
    """Send one request and print the streamed turn. Returns the process exit status.

    ``dry_run`` offers the model only look-up tools and asks for the steps it
    would take. ``notify`` also shows the answer (or the error) as a desktop
    notification; routines started by a timer use it, since nobody watches
    their output.
    """
    payload = json.dumps({"message": message, "conversation_id": conversation_id, "dry_run": dry_run}).encode("utf-8")
    headers = {"Authorization": f"Bearer {read_token()}", "Content-Type": "application/json"}
    request = Request(f"{base_url()}/ask", data=payload, method="POST", headers=headers)
    status = 0
    wrote_text = False
    answer: list[str] = []
    problems: list[str] = []
    with urlopen(request, timeout=900.0) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            kind = event.get("type")
            if kind == "text_delta":
                sys.stdout.write(event["text"])
                sys.stdout.flush()
                wrote_text = True
                answer.append(event["text"])
            elif kind == "start":
                for warning in event.get("warnings", []):
                    print(f"[warning] {warning}", file=sys.stderr)
                print(f"[conversation {event['conversation_id']} model {event['model']}]", file=sys.stderr)
            elif kind == "tool_call":
                print(f"[tool] {event['name']} {json.dumps(event['arguments'], ensure_ascii=False)}", file=sys.stderr)
            elif kind == "approval_required":
                answer_approval(event)
            elif kind == "tool_progress":
                print(f"[progress] {event['text'][:160]}", file=sys.stderr)
            elif kind == "tool_result" and not event["ok"]:
                print(f"[tool failed] {event['name']}: {event['text'][:200]}", file=sys.stderr)
            elif kind == "error":
                print(f"[error] {event['message']}", file=sys.stderr)
                problems.append(event["message"])
                status = 1
            elif kind == "done":
                if event.get("stop") != "answered":
                    print(f"[stopped: {event.get('stop')}]", file=sys.stderr)
                problems += [f"Not done: {action['summary']} ({action['outcome']})"
                             for action in event.get("actions", []) if action.get("outcome") != "done"]
    if wrote_text:
        sys.stdout.write("\n")
    if notify and shutil.which("notify-send"):
        body = ("".join(answer).strip() + ("\n" + "\n".join(problems) if problems else "")).strip()
        subprocess.run(["notify-send", "--app-name=Happy Bot", f"--icon={_assistant_icon()}", "--",
                        "Assistant: " + message[:80], body[:1500] or "Done."], check=False, timeout=10)
    return status


def ask_events(message: str, model: str = "") -> Any:
    """Send one dry-run request in a new conversation and yield its events (for ``eval``)."""
    payload = json.dumps({"message": message, "dry_run": True, "model": model, "ephemeral": True}).encode("utf-8")
    headers = {"Authorization": f"Bearer {read_token()}", "Content-Type": "application/json"}
    with urlopen(Request(f"{base_url()}/ask", data=payload, method="POST", headers=headers), timeout=900.0) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("data:"):
                yield json.loads(line[5:])


def answer_approval(event: dict[str, Any]) -> None:
    """Ask on the terminal whether a waiting action may run, and tell the daemon."""
    print(f"\n[approval needed] {event['summary']}", file=sys.stderr)
    if event.get("detail"):
        print(f"                  Reason: {event['detail']}", file=sys.stderr)
    decision = "deny"
    if sys.stdin.isatty():
        try:
            reply = input("                  Allow this once? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            reply = ""
        decision = "allow" if reply.strip().lower() in ("y", "yes") else "deny"
    else:
        print("                  No terminal to ask on; declined.", file=sys.stderr)
    request_json("POST", "/approve", {"id": event["id"], "decision": decision})


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
    raise RuntimeError("Happy Bot daemon is not reachable")


def emit(value: dict[str, Any], pretty: bool) -> None:
    print(json.dumps(value, indent=2 if pretty else None, ensure_ascii=False))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Talk to the Happy Bot daemon.")
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("endpoint", help="Print the daemon base URL.")
    sub.add_parser("status", help="Show daemon health/status.")
    sub.add_parser("doctor", help="Check the model, tools and everything else the assistant needs, with fixes.")
    export = sub.add_parser("export", help="Save settings (without secrets) and conversations to a file.")
    export.add_argument("file")
    import_cmd = sub.add_parser("import", help="Load settings and conversations from an export file.")
    import_cmd.add_argument("file")
    evaluate = sub.add_parser("eval", help="Try a model on everyday requests as dry runs (nothing changes) and "
                              "report which pass and how long they take.")
    evaluate.add_argument("--model", default="", help="A configured model; default is the active one.")
    routine_check = sub.add_parser("routine-check", help="Run a routine if its network or battery condition has just "
                                   "become true (started by the routine's timer).")
    routine_check.add_argument("--kind", required=True, choices=("network", "battery"))
    routine_check.add_argument("--value", required=True)
    routine_check.add_argument("name")
    app = sub.add_parser("app", help="The Happy Bot app (the floating Happy Bot): show it, start it, or say "
                         "whether it starts when you log in.")
    app.add_argument("action", choices=("show", "settings", "status", "start", "autostart-on", "autostart-off"))
    file_index = sub.add_parser("file-index-serve", help="Run as an MCP server (stdio) that searches a file index "
                                "the computer already keeps (started by the assistant when file search uses it).")
    file_index.add_argument("--index", required=True, choices=("kde", "locate"))
    sub.add_parser("mcp-serve", help="Run as an MCP server (stdio) lending the built-in tools to another AI "
                   "program; needs 'Let other AI programs use these tools' in the settings.")
    history = sub.add_parser("history", help="List saved conversations, or print one by id.")
    history.add_argument("id", nargs="?", default="")

    context = sub.add_parser("context", help="Capture KDE desktop context.")
    context.add_argument("--kind", choices=CONTEXT_KINDS, default="combined")

    ask = sub.add_parser("ask", help="Send a request to the assistant and print its answer as it arrives.")
    ask.add_argument("message", nargs="+")
    ask.add_argument("--conversation", default="", help="Continue the conversation with this id.")
    ask.add_argument("--dry-run", action="store_true",
                     help="Only look things up and list the steps that would be taken; change nothing.")
    ask.add_argument("--notify", action="store_true", help="Also show the answer as a desktop notification.")

    model = sub.add_parser("model", help="Manage the AI models the assistant can use.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list", help="List configured models.")
    model_probe = model_sub.add_parser("probe", help="List the models a service offers.")
    model_probe.add_argument("url", help="Service address, for example http://127.0.0.1:8080")
    model_probe.add_argument("--key-stdin", action="store_true", help="Read an API key from standard input.")
    model_add = model_sub.add_parser("add", help="Add or replace a model and make it the active one.")
    model_add.add_argument("name")
    model_add.add_argument("--url", required=True, help="Service address; /v1 is tried automatically.")
    model_add.add_argument("--model", default="", help="Model id; may be omitted if the service offers one model.")
    model_add.add_argument("--key-stdin", action="store_true", help="Read the API key from standard input.")
    model_add.add_argument("--header", action="append", default=[], metavar="NAME=VALUE",
                           help="Extra request header the service needs; may be repeated.")
    model_add.add_argument("--context-window", type=int, default=0, help="Tokens; default is what the service reports.")
    model_add.add_argument("--vision", action="store_true", help="The model accepts images.")
    model_use = model_sub.add_parser("use", help="Choose which configured model answers requests.")
    model_use.add_argument("name")
    model_remove = model_sub.add_parser("remove", help="Remove a configured model.")
    model_remove.add_argument("name")
    model_test = model_sub.add_parser("test", help="Check that a model answers and can call tools.")
    model_test.add_argument("name", nargs="?", default="")
    model_check = model_sub.add_parser(
        "check", help="Check that Happy Bot works with a model: answers, tool calls (one and two at once), tool "
                      "results, continuing another AI's chat, pictures. A few small requests per model.")
    model_check.add_argument("name", nargs="?", default="", help="Default: the first in the order.")
    model_check.add_argument("--all", action="store_true", help="Check every model in the order.")

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
    tools_set = tools_sub.add_parser("set", help="Change how a configured tool server is used.")
    tools_set.add_argument("name")
    tools_set.add_argument("--read-only", choices=("yes", "no"), help="Whether none of its allowed tools change anything.")
    tools_set.add_argument("--allow", help="Comma-separated tool names to offer; 'all' offers every tool.")
    tools_set.add_argument("--enabled", choices=("yes", "no"))

    folders = sub.add_parser("folders", help="Show or override where Desktop, Documents, Downloads and so on are.")
    folders.add_argument("name", nargs="?", choices=FOLDER_NAMES)
    folders.add_argument("path", nargs="?", help="New location; 'default' goes back to the system's location.")

    policy = sub.add_parser("policy", help="Show or set which actions wait for your approval.")
    policy.add_argument("value", nargs="?", choices=("danger", "changes", "everything"))

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
    if args.tools_command == "set":
        server = settings["tool_servers"][args.name]
        if args.read_only:
            server["read_only"] = args.read_only == "yes"
        if args.enabled:
            server["enabled"] = args.enabled == "yes"
        if args.allow:
            server["tools"] = None if args.allow == "all" else [item.strip() for item in args.allow.split(",") if item.strip()]
        return request_json("PUT", "/settings", {"settings": settings})
    del settings["tool_servers"][args.name]
    settings["roles"] = {name: role for name, role in settings["roles"].items() if role["server"] != args.name}
    return request_json("PUT", "/settings", {"settings": settings})


def run_model(args: argparse.Namespace) -> dict[str, Any]:
    command = args.model_command
    if command == "test":
        return request_json("POST", "/models/test", {"name": args.name}, timeout=300.0)
    if command == "check":
        names = current_settings().get("model_order", []) if args.all else [args.name]
        reports = [request_json("POST", "/models/check", {"name": name}, timeout=900.0) for name in names]
        return {"ok": all(report.get("ok") is not False for report in reports),
                "passed": all(report.get("passed") is True for report in reports), "models": reports}
    api_key = sys.stdin.readline().strip() if getattr(args, "key_stdin", False) else ""
    if command == "probe":
        return request_json("POST", "/models/probe", {"base_url": args.url, "api_key": api_key}, timeout=30.0)
    settings = current_settings()
    if command == "list":
        return {"ok": True, "active_model": settings["active_model"], "model_order": settings.get("model_order", []),
                "models": settings["models"]}
    if command in ("use", "remove") and args.name not in settings["models"]:
        return {"ok": False, "error": f"no model named '{args.name}' is set up"}
    if command == "use":
        settings["active_model"] = args.name
    elif command == "remove":
        del settings["models"][args.name]
        if settings["active_model"] == args.name:
            settings["active_model"] = ""  # the next model in the order becomes first
    else:
        headers = dict(item.split("=", 1) for item in args.header if "=" in item)
        probe = request_json(
            "POST", "/models/probe", {"base_url": args.url, "api_key": api_key, "headers": headers}, timeout=30.0)
        if probe.get("ok") is False:
            # Some services do not offer a model list. With an explicit model
            # id the address is taken as given; `model test` proves it works.
            if not args.model:
                return probe
            print(f"[note] could not list models ({probe.get('error')}); using the address as given.", file=sys.stderr)
            probe = {"base_url": args.url.rstrip("/"), "models": [{"id": args.model, "context_window": 0}]}
        offered = {item["id"]: item for item in probe["models"]}
        model_id = args.model or (next(iter(offered)) if len(offered) == 1 else "")
        if not model_id:
            return {"ok": False, "error": "choose one with --model", "models": sorted(offered)}
        if model_id not in offered:
            return {"ok": False, "error": f"the service does not offer '{model_id}'", "models": sorted(offered)}
        entry: dict[str, Any] = {
            "provider": "openai_compatible", "base_url": probe["base_url"], "model": model_id,
            "api_key": api_key, "headers": headers, "vision": args.vision,
        }
        window = args.context_window or offered[model_id]["context_window"]
        if window:
            entry["context_window"] = window
        settings["models"][args.name] = entry
        settings["active_model"] = args.name
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
    if args.command == "file-index-serve":
        # Started by the daemon as a tool server: it needs no daemon, and stdout carries only MCP.
        from .file_index_server import serve as serve_index

        return serve_index(args.index)
    try:
        ensure_daemon()
        if args.command == "endpoint":
            print(base_url())
            return 0
        if args.command == "status":
            reply = request_json("GET", "/health")
        elif args.command == "context":
            reply = request_json("GET", f"/context?kind={args.kind}")
        elif args.command == "doctor":
            reply = request_json("GET", "/check", timeout=120.0)
            if reply.get("ok") is not False and not args.pretty:
                for item in reply["checks"]:
                    mark = "ok  " if item["ok"] else "FAIL"
                    print(f"{mark} {item['name']}: {item['detail']}" + (f"\n     Fix: {item['fix']}" if item["fix"] else ""))
                return 0 if reply["healthy"] else 1
        elif args.command == "eval":
            from . import evaluation
            from .tools.mcp_bridge import bridged_name

            role = current_settings().get("roles", {}).get("file_search")
            results = evaluation.run(ask_events, args.model, bridged_name(role["server"], role["tool"]) if role else "")
            for item in results:
                mark = "pass" if item["passed"] else "FAIL"
                print(f"{mark} {item['seconds']:>5}s  {item['request']}  [{', '.join(item['tools']) or 'no tools'}]"
                      + (f"  {item['problem']}" if item["problem"] else ""))
            print(f"{sum(item['passed'] for item in results)} of {len(results)} passed")
            return 0 if all(item["passed"] for item in results) else 1
        elif args.command == "routine-check":
            from .routine_conditions import check

            routine = current_settings().get("routines", {}).get(args.name)
            if not routine or not routine.get("enabled", True):
                reply = {"ok": True, "result": "no such routine, or it is paused"}
            else:
                reply = {"ok": True, "result": check(args.name, args.kind, args.value,
                                                      lambda: stream_ask(routine["request"], notify=True))}
        elif args.command == "app":
            if args.action in ("show", "settings"):
                if args.action == "settings" and not request_json("GET", "/app").get("running"):
                    request_json("POST", "/app", {"start": True})
                reply = request_json("POST", "/app/show", {"action": "open" if args.action == "show" else "settings"})
            elif args.action == "status":
                reply = request_json("GET", "/app")
            else:
                change = {"start": {"start": True}, "autostart-on": {"autostart": True},
                          "autostart-off": {"autostart": False}}[args.action]
                reply = request_json("POST", "/app", change)
        elif args.command == "mcp-serve":
            from .mcp_serve import serve

            return serve(request_json)
        elif args.command == "export":
            reply = request_json("GET", "/export", timeout=60.0)
            if reply.get("ok") is not False:
                descriptor = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(reply["data"], handle, ensure_ascii=False, indent=1)
                reply = {"ok": True, "file": os.path.abspath(args.file),
                         "conversations": len(reply["data"]["conversations"]), "secrets_included": False}
        elif args.command == "import":
            with open(args.file, encoding="utf-8") as handle:
                reply = request_json("POST", "/import", {"data": json.load(handle)}, timeout=60.0)
        elif args.command == "history":
            if args.id:
                reply = request_json("GET", f"/conversation?id={quote(args.id)}")
                if reply.get("ok") is not False:
                    for event in reply.get("events", []):
                        if event.get("type") == "user":
                            print(f"\n> {event.get('text', '')}")
                        elif event.get("type") == "text_delta":
                            print(event.get("text", ""), end="")
                    print()
                    return 0
            else:
                reply = request_json("GET", "/conversations")
                if reply.get("ok") is not False and not args.pretty:
                    for item in reply["conversations"]:
                        print(f"{item['id']}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(item['updated']))}  {item['title']}")
                    return 0
        elif args.command == "ask":
            return stream_ask(" ".join(args.message), args.conversation, args.dry_run, args.notify)
        elif args.command == "model":
            reply = run_model(args)
        elif args.command == "folders":
            settings = current_settings()
            if args.name and args.path:
                if args.path == "default":
                    settings["folders"].pop(args.name, None)
                else:
                    settings["folders"][args.name] = os.path.abspath(os.path.expanduser(args.path))
                reply = request_json("PUT", "/settings", {"settings": settings})
                if reply.get("ok") is not False:
                    reply = request_json("GET", "/settings")
            else:
                reply = request_json("GET", "/settings")
            if reply.get("ok") is not False:
                reply = {"ok": True, "folders": reply["effective_folders"], "overridden": sorted(reply["settings"]["folders"])}
        elif args.command == "policy":
            settings = current_settings()
            if args.value:
                settings["approval_policy"] = args.value
                reply = request_json("PUT", "/settings", {"settings": settings})
            else:
                reply = {"ok": True, "approval_policy": settings["approval_policy"]}
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

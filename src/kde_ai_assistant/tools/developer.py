"""Power-user tools: the system journal, user services, processes, Git, containers, network checks, the editor.

Each is a bounded, structured wrapper so a small model gets a short, readable
answer instead of composing a shell pipeline:

- ``read_journal``: ``journalctl`` for this boot or a time window, one unit
  (user or system), a minimum priority and a text filter, newest last.
- ``user_services`` / ``user_service_action``: ``systemctl --user`` units.
  System units are not changed here (they need root; see the broker rule).
- ``processes``: the top processes by CPU or memory (``ps``);
  ``stop_process`` ends one by pid or name and is ``danger``, because the
  program's unsaved work is lost.
- ``git_summary``: a repository's branch, changed files, and recent or
  today's commits (read only).
- ``containers``: Docker or Podman containers and the end of one's log.
- ``network_check``: ping, DNS lookup and a TCP port check for a host.
- ``open_in_editor``: open a file at a line in the user's editor (Kate when
  installed, else the default application), or a PDF, EPUB or DjVu document
  at a page in Okular.

All are ``read`` except the service actions and opening the editor
(``change``) and ``stop_process`` (``danger``). Output is cut to keep the
model's context small.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from typing import Any

from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

MAX_LINES = 120
_UNIT = re.compile(r"^[A-Za-z0-9@:._-]{1,120}$")


def read_journal(arguments: dict[str, Any]) -> str:
    command = ["journalctl", "--no-pager", "-o", "short-iso", "-n", str(min(int(arguments.get("lines") or 80), MAX_LINES))]
    since = str(arguments.get("since") or "").strip()
    command += ["--since", since] if since else ["-b"]
    if since and not re.fullmatch(r"[0-9: -]{4,19}|today|yesterday|-?\d+ ?(min|h|hours?|days?) ago", since):
        raise ToolFailure("'since' must be like 2026-11-23 14:00, today, yesterday or '2h ago'")
    unit = str(arguments.get("unit") or "").strip()
    if unit:
        if not _UNIT.match(unit):
            raise ToolFailure("'unit' must be a unit name")
        command += ["--user-unit" if arguments.get("user_unit") else "-u", unit]
    priority = arguments.get("priority")
    if priority:
        if priority not in ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"):
            raise ToolFailure("'priority' must be err, warning, notice, info, ...")
        command += ["-p", priority]
    grep = str(arguments.get("contains") or "").strip()
    if grep:
        command += ["--grep", grep, "--case-sensitive=false"]
    output = run_command(command, timeout=30)
    text = (output["stdout"] or output["stderr"]).strip()
    return text or "No matching journal entries."


def user_services(arguments: dict[str, Any]) -> str:
    output = run_checked(["systemctl", "--user", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"])
    failed = [line for line in output.splitlines() if " failed " in line]
    running = [line.split()[0] for line in output.splitlines() if " running " in line]
    return (f"Running: {', '.join(running) or 'none'}\nFailed: " + ("\n".join(failed) or "none"))


def user_service_action(arguments: dict[str, Any]) -> str:
    unit, action = str(arguments.get("unit") or "").strip(), arguments.get("action")
    if action not in ("start", "stop", "restart", "status"):
        raise ToolFailure("'action' must be start, stop, restart or status")
    if not _UNIT.match(unit):
        raise ToolFailure("'unit' must be a unit name")
    if action == "status":
        return run_command(["systemctl", "--user", "status", "--no-pager", "-n", "15", unit], timeout=15)["stdout"]
    run_checked(["systemctl", "--user", action, unit], timeout=60)
    return f"{action.capitalize()}ed {unit}." if action != "stop" else f"Stopped {unit}."


def processes(arguments: dict[str, Any]) -> str:
    sort = "-%mem" if arguments.get("sort") == "memory" else "-%cpu"
    output = run_checked(["ps", "-eo", "pid,user,%cpu,%mem,rss,comm", f"--sort={sort}"])
    lines = output.splitlines()
    return "\n".join(lines[:1 + min(int(arguments.get("limit") or 15), 40)])


def _matching_processes(target: str) -> list[tuple[int, str]]:
    if target.isdigit():
        output = run_command(["ps", "-o", "pid=,comm=", "-p", target], timeout=5)["stdout"]
    else:
        output = run_command(["ps", "-u", str(os.getuid()), "-o", "pid=,comm="], timeout=5)["stdout"]
    found = []
    for line in output.splitlines():
        pid, _, name = line.strip().partition(" ")
        if pid.isdigit() and (target.isdigit() or target.lower() in name.lower()):
            found.append((int(pid), name.strip()))
    return found


def stop_process(arguments: dict[str, Any]) -> str:
    target = str(arguments.get("process") or "").strip()
    if not target:
        raise ToolFailure("'process' is required: a pid or program name")
    found = [item for item in _matching_processes(target) if item[0] != os.getpid()]
    if not found:
        raise ToolFailure(f"no process of yours matches '{target}'")
    if len(found) > 5 and not target.isdigit():
        raise ToolFailure(f"{len(found)} processes match '{target}'; give a pid")
    for pid, _ in found:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise ToolFailure(f"process {pid} belongs to another user") from error
    return "Asked to stop: " + ", ".join(f"{name} ({pid})" for pid, name in found)


def git_summary(arguments: dict[str, Any]) -> str:
    repo = os.path.abspath(os.path.expanduser(str(arguments.get("repository") or "")))
    if not os.path.isdir(repo):
        raise ToolFailure(f"{repo} is not a folder")
    git = ["git", "-C", repo]
    branch = run_command(git + ["branch", "--show-current"], timeout=10)
    if not branch["ok"]:
        raise ToolFailure(f"{repo} is not a Git repository")
    status = run_command(git + ["status", "--short"], timeout=20)["stdout"].strip()
    since = ["--since=midnight"] if arguments.get("today") else ["-n", "10"]
    log = run_command(git + ["log", "--date=short", "--pretty=%h %ad %s", *since], timeout=20)["stdout"].strip()
    stat = run_command(git + ["diff", "--shortstat"], timeout=20)["stdout"].strip()
    return (f"Branch: {branch['stdout'].strip() or '(detached)'}\nUncommitted: {stat or 'none'}\n"
            f"{status[:3000] or ''}\nCommits{' today' if arguments.get('today') else ''}:\n{log or 'none'}")


def containers(arguments: dict[str, Any]) -> str:
    engine = "docker" if shutil.which("docker") else "podman" if shutil.which("podman") else ""
    if not engine:
        raise ToolFailure("neither Docker nor Podman is installed")
    name = str(arguments.get("logs_of") or "").strip()
    if name:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
            raise ToolFailure("'logs_of' must be a container name")
        result = run_command([engine, "logs", "--tail", "60", name], timeout=20)
        return ((result["stdout"] + result["stderr"]).strip() or "No log output.")[-8000:]
    return run_checked([engine, "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"]) or "No containers."


def network_check(arguments: dict[str, Any]) -> str:
    host = str(arguments.get("host") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
        raise ToolFailure("'host' must be a host name or address")
    lines = []
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, None)})
        lines.append(f"DNS: {host} is {', '.join(addresses[:4])}")
    except socket.gaierror as error:
        return f"DNS: {host} could not be resolved ({error})."
    ping = run_command(["ping", "-c", "3", "-W", "2", host], timeout=15)
    summary = [line for line in ping["stdout"].splitlines() if "packet loss" in line or "rtt" in line]
    lines.append("Ping: " + (" / ".join(summary) or "no reply"))
    port = arguments.get("port")
    if port is not None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ToolFailure("'port' must be a number from 1 to 65535")
        started = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=4):
                lines.append(f"Port {port}: open ({(time.monotonic() - started) * 1000:.0f} ms)")
        except OSError as error:
            lines.append(f"Port {port}: closed or unreachable ({error})")
    return "\n".join(lines)


def open_in_editor(arguments: dict[str, Any]) -> str:
    path = os.path.abspath(os.path.expanduser(str(arguments.get("path") or "")))
    if not os.path.exists(path):
        raise ToolFailure(f"{path} does not exist")
    line = arguments.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        raise ToolFailure("'line' must be a line number")
    if path.lower().endswith((".pdf", ".epub", ".djvu")) and shutil.which("okular"):
        command = ["okular", "--page", str(line), path] if line else ["okular", path]
    elif shutil.which("kate"):
        command = ["kate", "--line", str(line), path] if line else ["kate", path]
    else:
        command = ["xdg-open", path]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return f"Opened {path}" + (f" at line {line}." if line else ".")


def developer_tools() -> list[Tool]:
    text = {"type": "string"}
    return [
        Tool("read_journal", "Read the system log (journal): this boot or since a time, optionally one service, a "
             "minimum priority (err, warning) and text to look for. Use it to explain what went wrong.",
             object_schema({"since": text, "unit": text, "user_unit": {"type": "boolean"}, "priority": text,
                            "contains": text, "lines": {"type": "integer"}}), RISK_READ, read_journal,
             summarize=lambda a: "Read the system log"),
        Tool("user_services", "The user's background services: which run and which failed.", object_schema(),
             RISK_READ, user_services, summarize=lambda a: "List background services"),
        Tool("user_service_action", "Start, stop, restart or show the status of one of the user's services.",
             object_schema({"unit": text, "action": {"type": "string", "enum": ["start", "stop", "restart", "status"]}},
                           ["unit", "action"]), RISK_CHANGE, user_service_action,
             summarize=lambda a: f"{str(a.get('action', '?')).capitalize()} the service {a.get('unit', '?')}"),
        Tool("processes", "The programs using the most CPU or memory.",
             object_schema({"sort": {"type": "string", "enum": ["cpu", "memory"]}, "limit": {"type": "integer"}}),
             RISK_READ, processes, summarize=lambda a: "Check running programs"),
        Tool("stop_process", "Stop a program of the user's by pid or name. Its unsaved work is lost.",
             object_schema({"process": text}, ["process"]), RISK_DANGER, stop_process,
             classify=lambda a: (RISK_DANGER, "the program's unsaved work is lost"),
             summarize=lambda a: f"Stop {a.get('process', '?')}"),
        Tool("git_summary", "A Git repository's branch, uncommitted changes and recent (or today's) commits.",
             object_schema({"repository": text, "today": {"type": "boolean"}}, ["repository"]), RISK_READ,
             git_summary, summarize=lambda a: f"Check the repository {a.get('repository', '?')}"),
        Tool("containers", "Docker or Podman containers and their state, or the end of one container's log.",
             object_schema({"logs_of": text}), RISK_READ, containers, summarize=lambda a: "Check containers"),
        Tool("network_check", "Check a host: DNS lookup, ping, and optionally whether a TCP port answers.",
             object_schema({"host": text, "port": {"type": "integer"}}, ["host"]), RISK_READ, network_check,
             summarize=lambda a: f"Check the connection to {a.get('host', '?')}"),
        Tool("open_in_editor", "Open a file in the text editor at a line, or a PDF or e-book in the document "
             "viewer at a page (pass the page as 'line').",
             object_schema({"path": text, "line": {"type": "integer"}}, ["path"]), RISK_CHANGE, open_in_editor,
             summarize=lambda a: f"Open {a.get('path', '?')} in the editor"),
    ]

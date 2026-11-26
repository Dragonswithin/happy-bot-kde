"""The daemon's System info endpoints, kept apart from ``daemon_routes`` and merged into its ``ROUTES``.

The start screen's System info view (SystemInfoView.qml) polls these while it is open:

- ``GET /system/overview``: processor, memory, graphics, disks, network, battery and uptime, with the
  last minutes of history for the graphs (``system_monitor.overview``); about every second.
- ``GET /system/programs?sort=cpu|memory``: the busiest programs (``system_monitor.Programs.top``);
  every two seconds. Each look measures CPU use since the previous one, from any client.
- ``POST /system/stop`` (``{"pid"}``): ask one of the user's own programs to quit
  (``system_monitor.stop``). The view asks the user first; the daemon refuses other users' programs
  and the ones that keep the desktop running, and writes each stop to the action log.

Errors are ``{"ok": false, "error", "code": "invalid"}``.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Callable

from . import system_monitor
from .permissions import append_audit

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

Reply = tuple[int, dict[str, Any]]


def overview(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **system_monitor.overview(server.system_history)}


def programs(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    sort = (query.get("sort") or ["cpu"])[0]
    return 200, {"ok": True, "sort": sort, "programs": server.programs.top("memory" if sort == "memory" else "cpu")}


def stop(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    pid = body.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return 400, {"ok": False, "error": "pid must be a program's number", "code": "invalid"}
    try:
        message = system_monitor.stop(pid)
    except system_monitor.StopError as error:
        return 409, {"ok": False, "error": str(error), "code": "invalid"}
    append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": "stop_program",
                                      "risk": "change", "outcome": "chosen in System info",
                                      "arguments": json.dumps({"pid": pid})})
    return 200, {"ok": True, "message": message}


ROUTES: dict[tuple[str, str], Callable[["AssistantServer", dict[str, list[str]], dict[str, Any]], Reply]] = {
    ("GET", "/system/overview"): overview,
    ("GET", "/system/programs"): programs,
    ("POST", "/system/stop"): stop,
}

"""Plain-language descriptions of tool calls, as shown in the popup's step lines.

Tools that change things carry their own ``summarize`` because the same text
appears on approval cards. Read-only tools mostly do not, and their raw
names ("list_directory") read poorly as a record of what the assistant did.
``describe_read_call`` supplies a short past-tense line for them, and
``with_read_summaries`` attaches it to any tool that has no summary of its
own. ``describe_search`` phrases calls to the user's file-search and
web-search tools. Pure functions: no state, no I/O.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable

from .registry import Tool

QUOTE_CHARS = 60


def _short(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1] + "…"


def _path(value: Any) -> str:
    text = str(value or "")
    home = os.path.expanduser("~")
    return "~" + text[len(home):] if text == home or text.startswith(home + "/") else text


_READ_LINES: dict[str, Callable[[dict[str, Any]], str]] = {
    "current_time": lambda a: "Checked the time",
    "active_window": lambda a: "Looked at the current window",
    "list_windows": lambda a: "Looked at the open windows",
    "clipboard_text": lambda a: "Read the clipboard",
    "system_info": lambda a: "Checked system information",
    "list_directory": lambda a: f"Listed {_path(a.get('path'))}",
    "read_text_file": lambda a: f"Read {_path(a.get('path'))}",
    "disk_usage": lambda a: f"Measured disk use in {_path(a.get('path'))}",
    "read_kde_setting": lambda a: f"Read the setting {a.get('key', '')} in {a.get('file', '')}",
    "list_applications": lambda a: f"Looked up applications{' matching “' + _short(a['query']) + '”' if a.get('query') else ''}",
    "get_volume": lambda a: "Checked the volume",
    "list_wifi_networks": lambda a: "Looked for Wi-Fi networks",
    "list_displays": lambda a: "Looked at the displays",
    "list_color_schemes": lambda a: "Looked at the colour schemes",
    "ui_snapshot": lambda a: "Read the window's controls" + (f" matching “{_short(a['query'])}”" if a.get("query") else ""),
    "ui_get_text": lambda a: f"Read the text of “{_short(a.get('element'))}”",
}


def describe_read_call(name: str, arguments: dict[str, Any]) -> str | None:
    line = _READ_LINES.get(name)
    return line(arguments) if line else None


def describe_search(role: str | None, server: str, tool: str, query_argument: str | None) -> Callable[[dict[str, Any]], str]:
    """Summary for a bridged tool: what it searched for when it is a search role, else its name."""
    readable = tool.replace("_", " ")

    def summary(arguments: dict[str, Any]) -> str:
        query = _short(arguments.get(query_argument or "query", ""))
        if role == "file_search":
            return f"Searched your files for “{query}”" if query else "Searched your files"
        if role == "web_search":
            return f"Searched the web for “{query}”" if query else "Searched the web"
        return f"{readable} ({server})"

    return summary


def with_read_summaries(tools: list[Tool]) -> list[Tool]:
    """Attach a plain-language summary to every tool that lacks one."""
    attached = []
    for tool in tools:
        if tool.summarize is None and tool.name in _READ_LINES:
            tool = dataclasses.replace(tool, summarize=lambda arguments, name=tool.name: describe_read_call(name, arguments))
        attached.append(tool)
    return attached

"""Assembles the set of tools offered to the model for a turn.

The catalogue is every built-in tool followed by the tools of the user's MCP
servers. Built-in names win a clash. Which calls may run without asking is
not decided here: every offered tool is subject to the permission gate, which
judges each call.

Built-in tools come in groups (``GROUP_NAMES``). Reading the desktop
(``observe``: active window, clipboard, files, settings) is always offered,
together with the action history and undo (``tools/undo.py``), so the user
can always ask what was done and reverse it, and the clipboard history and
selected text (the read tools of ``tools/screen.py``; its screenshot,
recording and colour-picker tools belong to ``gui``).
The other groups are named in ``settings.TOOL_GROUPS`` and the user can
switch each off in the settings page (``agent.disabled_tool_groups``); a
switched-off group is never offered, so the model cannot call it however a
request is worded. ``GROUP_DESCRIPTIONS`` is how the model is told which
abilities are off, so it can say so instead of trying another route.

The shell tools are built with the user's ``command_timeout_seconds`` and
``terminal`` settings (see ``tools/shell.py``). The routine and layout tools
change the daemon's settings, so they are only offered when the daemon
passes ``read_settings`` and ``update_settings``.

Groups and their modules (all under ``tools/``):

- ``observe`` (always offered): ``observe.py``, ``undo.py``, the
  clipboard-history and selected-text tools of ``screen.py``,
  remember/forget (``memory.py``), and ``finding.py`` (recent files,
  bookmarks, reading a web page)

With ``agent.load_plugins`` on, the user's plugin files add tools after
the tool servers' (``tools/plugins.py``).

With the user's "local only" setting (``agent.local_only``) the web-search
role's tool and ``read_web_page`` are left out, so nothing is looked up on
the internet.
- ``windows``: ``windows.py``, ``workspace.py`` (desktops, activities, layouts)
- ``apps``: ``apps.py``, ``app_visibility.py``, ``defaults.py`` (default
  applications, autostart), ``software.py`` (sources, update history)
- ``gui``: ``gui.py`` and the screenshot, recording and colour tools of
  ``screen.py``
- ``system``: ``system.py``, ``media.py``, ``power.py``, ``appearance.py``,
  ``devices.py``
- ``files``: ``files.py``, ``documents.py``
- ``shell``: ``shell.py``, ``developer.py`` (journal, services, processes,
  Git, containers, network checks)
- ``phone``: ``phone.py`` (KDE Connect)
- ``schedule``: ``reminders.py``, ``routine_tools.py``, ``notes.py``
"""

from __future__ import annotations

from typing import Any, Callable

from ..mcp_client import McpManager
from .app_visibility import app_visibility_tools
from .appearance import appearance_tools
from .apps import app_tools
from .defaults import defaults_tools
from .developer import developer_tools
from .documents import document_tools
from .devices import device_tools
from .files import file_tools
from .finding import finding_tools
from .gui import gui_tools
from .media import media_tools
from .memory import memory_tools
from .mcp_bridge import bridged_name, mcp_tools
from .notes import note_tools
from .observe import observe_tools
from .phone import phone_tools
from .plugins import load_plugins
from .power import power_tools
from .registry import Tool, ToolRegistry
from .reminders import reminder_tools
from .screen import screen_tools
from .routine_tools import ReadSettings, UpdateSettings, routine_tools
from .shell import DEFAULT_TIMEOUT_SECONDS, shell_tools
from .software import software_tools
from .summaries import with_read_summaries
from .system import system_tools
from .undo import undo_tools
from .windows import window_tools
from .workspace import layout_tools, workspace_tools

# Model-facing wording for a switched-off group, used in the system prompt.
GROUP_DESCRIPTIONS = {
    "windows": "moving, arranging and closing windows",
    "apps": "starting and checking applications",
    "gui": "operating other applications' windows (pressing buttons, filling in fields, typing)",
    "system": "changing system settings (sound, network, Bluetooth, displays, appearance, power and session)",
    "files": "creating, moving, writing and trashing files and folders",
    "shell": "running shell commands and opening a terminal",
    "phone": "using the user's phone through KDE Connect (ringing it, sending to it, text messages)",
    "schedule": "setting reminders and timers, keeping notes and to-dos, and saving or deleting routines",
}


def _group_builders(
    agent: dict[str, Any],
    read_settings: ReadSettings | None = None,
    update_settings: UpdateSettings | None = None,
) -> dict[str, Callable[[], list[Tool]]]:
    timeout = int(agent.get("command_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    terminal = str(agent.get("terminal", ""))
    routines = (lambda: routine_tools(read_settings, update_settings)) if read_settings and update_settings else list
    layouts = (lambda: layout_tools(read_settings, update_settings)) if read_settings and update_settings else list
    memory = (lambda: memory_tools(read_settings, update_settings)) if read_settings and update_settings else list
    notes = (lambda: note_tools(read_settings)) if read_settings else list
    return {
        "observe": lambda: [*observe_tools(), *undo_tools(), *[tool for tool in screen_tools() if tool.risk == "read"],
                            *memory(), *finding_tools(bool(agent.get("local_only")))],
        "windows": lambda: [*window_tools(), *workspace_tools(), *layouts()],
        "gui": lambda: [*gui_tools(), *[tool for tool in screen_tools() if tool.risk != "read"]],
        "apps": lambda: [*app_tools(), *app_visibility_tools(), *defaults_tools(), *software_tools()],
        "system": lambda: [*system_tools(), *media_tools(), *power_tools(), *appearance_tools(), *device_tools()],
        "files": lambda: [*file_tools(), *document_tools()],
        "shell": lambda: [*shell_tools(timeout, terminal), *developer_tools()],
        "phone": phone_tools,
        "schedule": lambda: [*reminder_tools(), *routines(), *notes()],
    }


# Every group, in catalogue order; all but "observe" are in settings.TOOL_GROUPS.
GROUP_NAMES = tuple(_group_builders({}))


def builtin_tools(
    agent: dict[str, Any] | None = None,
    read_settings: ReadSettings | None = None,
    update_settings: UpdateSettings | None = None,
) -> list[Tool]:
    """Built-in tools of every group the user has not switched off, in catalogue order.

    The routine tools need ``read_settings`` and ``update_settings`` (from the
    daemon) and are left out without them.
    """
    agent = agent or {}
    disabled = set(agent.get("disabled_tool_groups", ()))
    tools: list[Tool] = []
    for group, build in _group_builders(agent, read_settings, update_settings).items():
        if group not in disabled:
            tools.extend(build())
    return with_read_summaries(tools)


def build_registry(
    manager: McpManager,
    settings: dict[str, Any],
    read_settings: ReadSettings | None = None,
    update_settings: UpdateSettings | None = None,
) -> tuple[ToolRegistry, list[str]]:
    """Return the registry for a turn and any warnings about tool servers that could not be reached."""
    bridged, warnings = mcp_tools(manager, settings)
    web = settings.get("roles", {}).get("web_search")
    if (settings.get("agent") or {}).get("local_only") and web:
        bridged = [tool for tool in bridged if tool.name != bridged_name(web["server"], web["tool"])]
    plugin_tools: list[Tool] = []
    if (settings.get("agent") or {}).get("load_plugins"):
        plugin_tools, plugin_warnings = load_plugins()
        warnings = [*warnings, *plugin_warnings]
    selected: list[Tool] = []
    seen: set[str] = set()
    for tool in [*builtin_tools(settings.get("agent"), read_settings, update_settings), *bridged, *plugin_tools]:
        if tool.name not in seen:
            seen.add(tool.name)
            selected.append(tool)
    return ToolRegistry(selected), warnings

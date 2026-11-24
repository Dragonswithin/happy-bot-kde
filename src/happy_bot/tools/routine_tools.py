"""Tools for the user's routines: list, save and delete them from the bar.

Routines live in the daemon's settings (``routines`` in ``settings.py``; what
they mean is in ``routines.py``), so these tools change settings. They are
built with ``read_settings`` and ``update_settings`` from the daemon
(``ask_stream`` passes them through ``tools/catalog.build_registry``);
``update_settings(mutate)`` validates and saves exactly like the settings
page does, and also brings the routine timers in step. A validation error
(a schedule systemd does not understand, for example) comes back to the
model as a tool failure with the reason.

Running a routine needs no tool: the system prompt lists every routine, and
the model carries out its request when the user names it.

Risk: listing is ``read``, saving is ``change``, deleting a saved routine is
``danger`` (it removes something the user made).
"""

from __future__ import annotations

from typing import Any, Callable

from ..settings import SettingsError
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

ReadSettings = Callable[[], dict[str, Any]]
UpdateSettings = Callable[[Callable[[dict[str, Any]], None]], dict[str, Any]]


def describe(name: str, entry: dict[str, Any]) -> str:
    when = []
    if entry.get("schedule"):
        when.append(f"on schedule '{entry['schedule']}'")
    if entry.get("watch_folder"):
        when.append(f"when {entry['watch_folder']} changes")
    if entry.get("drive_label"):
        when.append(f"when the drive {entry['drive_label']} is plugged in")
    if entry.get("on_network"):
        when.append(f"on joining the network {entry['on_network']}")
    if entry.get("battery_below"):
        when.append(f"when the battery drops below {entry['battery_below']}%")
    timing = (" and ".join(when) if when else "only when asked") + ("" if entry.get("enabled", True) else ", paused")
    return f"{name} ({timing}): {entry['request']}"


def routine_tools(read_settings: ReadSettings, update_settings: UpdateSettings) -> list[Tool]:
    def list_routines(arguments: dict[str, Any]) -> str:
        routines = read_settings().get("routines", {})
        return "\n".join(describe(name, entry) for name, entry in sorted(routines.items())) or "No routines are saved."

    def save_routine(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ToolFailure("'name' is required")
        existing = read_settings().get("routines", {}).get(name, {})
        entry = {
            "request": arguments.get("request", existing.get("request", "")),
            "schedule": arguments.get("schedule", existing.get("schedule", "")),
            "watch_folder": arguments.get("watch_folder", existing.get("watch_folder", "")),
            "drive_label": arguments.get("drive_label", existing.get("drive_label", "")),
            "on_network": arguments.get("on_network", existing.get("on_network", "")),
            "battery_below": arguments.get("battery_below", existing.get("battery_below", 0)),
            "enabled": arguments.get("enabled", existing.get("enabled", True)),
        }

        def mutate(settings: dict[str, Any]) -> None:
            settings.setdefault("routines", {})[name] = entry

        try:
            stored = update_settings(mutate)
        except SettingsError as error:
            raise ToolFailure(str(error)) from error
        return ("Updated" if existing else "Saved") + " the routine " + describe(name, stored["routines"][name])

    def delete_routine(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        if name not in read_settings().get("routines", {}):
            raise ToolFailure(f"there is no routine named '{name}'. Saved: "
                              f"{', '.join(sorted(read_settings().get('routines', {}))) or 'none'}")
        update_settings(lambda settings: settings["routines"].pop(name, None))
        return f"Deleted the routine '{name}'."

    return [
        Tool("list_routines", "The user's saved routines: name, when they run on their own, and the request.",
             object_schema(), RISK_READ, list_routines, summarize=lambda a: "List routines"),
        Tool("save_routine", "Save or change a named routine: a request the user can run by name, optionally on a "
             "schedule (systemd calendar syntax such as 'Mon..Fri 08:30', 'daily', '*-*-01 09:00'), whenever a "
             "folder changes, or when a drive is plugged in. Run on their own, routines cannot do anything that needs approval. Omitted fields "
             "keep their current value.",
             object_schema({"name": {"type": "string"}, "request": {"type": "string"},
                            "schedule": {"type": "string", "description": "'' for none"},
                            "watch_folder": {"type": "string", "description": "'' for none"},
                            "drive_label": {"type": "string", "description": "run when the drive with this label "
                                            "is plugged in; '' for none"},
                            "on_network": {"type": "string", "description": "run on joining this network; '' for none"},
                            "battery_below": {"type": "integer", "description": "run when the battery drops below "
                                              "this percent; 0 for none"},
                            "enabled": {"type": "boolean", "description": "false pauses it"}}, ["name"]),
             RISK_CHANGE, save_routine, summarize=lambda a: f"Save the routine '{a.get('name', '?')}'"),
        Tool("delete_routine", "Delete a saved routine.", object_schema({"name": {"type": "string"}}, ["name"]),
             RISK_DANGER, delete_routine, classify=lambda a: (RISK_DANGER, "deletes a routine you saved"),
             summarize=lambda a: f"Delete the routine '{a.get('name', '?')}'"),
    ]

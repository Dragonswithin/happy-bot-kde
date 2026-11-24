"""Default-application and autostart tools.

Default applications are the freedesktop MIME associations: ``xdg-mime query
default`` and ``xdg-mime default`` (which writes the user's
``mimeapps.list``, the file System Settings' Default Applications page also
writes). Common words map to their MIME types (``_KINDS``: "browser",
"email", "pdf", "images", ...); a raw MIME type such as ``text/markdown``
works too. The application is matched by name like ``launch_application``.

Autostart entries are ``.desktop`` files in ``$XDG_CONFIG_HOME/autostart``,
as System Settings' Autostart page manages them. Adding one copies the
application's own entry there; removing one moves it to the trash (``danger``,
it deletes a file) so it can be restored.
"""

from __future__ import annotations

import configparser
import os
import shutil
from pathlib import Path
from typing import Any

from .apps import installed_applications, match_applications
from .power import run_checked
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

_KINDS = {
    "browser": ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"],
    "email": ["x-scheme-handler/mailto"],
    "pdf": ["application/pdf"],
    "images": ["image/png", "image/jpeg", "image/webp", "image/gif"],
    "music": ["audio/mpeg", "audio/flac", "audio/ogg"],
    "video": ["video/mp4", "video/x-matroska", "video/webm"],
    "text": ["text/plain"],
    "folders": ["inode/directory"],
    "terminal": [],
}


def _autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart"


def _mime_types(kind: str) -> list[str]:
    kind = kind.strip().lower()
    if kind in _KINDS and _KINDS[kind]:
        return _KINDS[kind]
    if "/" in kind:
        return [kind]
    raise ToolFailure(f"'kind' must be one of {', '.join(k for k in _KINDS if _KINDS[k])}, or a MIME type like text/markdown")


def default_applications(arguments: dict[str, Any]) -> str:
    kinds = [str(arguments["kind"])] if arguments.get("kind") else [k for k in _KINDS if _KINDS[k]]
    lines = []
    for kind in kinds:
        first = _mime_types(kind)[0]
        lines.append(f"{kind}: {run_checked(['xdg-mime', 'query', 'default', first]) or '(none set)'}")
    return "\n".join(lines)


def set_default_application(arguments: dict[str, Any]) -> str:
    kind, name = str(arguments.get("kind") or ""), str(arguments.get("application") or "").strip()
    types = _mime_types(kind)
    matches = match_applications(name, installed_applications())
    if len(matches) != 1:
        options = ", ".join(app["name"] for app in matches[:8]) or "none"
        raise ToolFailure(f"'{name}' matches {len(matches)} applications ({options}); give the exact name")
    desktop_id = matches[0]["id"]
    run_checked(["xdg-mime", "default", desktop_id, *types])
    return f"{matches[0]['name']} now opens {kind}."


def list_autostart(arguments: dict[str, Any]) -> str:
    folder = _autostart_dir()
    entries = []
    for path in sorted(folder.glob("*.desktop")) if folder.is_dir() else []:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
            entry = parser["Desktop Entry"]
        except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
            continue
        off = entry.get("Hidden", "false").lower() == "true" or entry.get("X-KDE-autostart-enabled", "true") == "false"
        entries.append(f"{entry.get('Name', path.stem)} [{path.name}]{' (switched off)' if off else ''}")
    return "Starts at login:\n" + ("\n".join(entries) if entries else "nothing")


def add_autostart(arguments: dict[str, Any]) -> str:
    name = str(arguments.get("application") or "").strip()
    matches = match_applications(name, installed_applications())
    if len(matches) != 1:
        raise ToolFailure(f"'{name}' matches {len(matches)} applications; give the exact name")
    folder = _autostart_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / matches[0]["id"]
    if target.exists():
        return f"{matches[0]['name']} already starts at login."
    shutil.copyfile(matches[0]["path"], target)
    return f"{matches[0]['name']} will start at login."


def _autostart_entry(arguments: dict[str, Any]) -> Path:
    wanted = str(arguments.get("entry") or "").strip().lower()
    folder = _autostart_dir()
    found = [path for path in folder.glob("*.desktop") if wanted and wanted in path.name.lower()] if folder.is_dir() else []
    if len(found) != 1:
        raise ToolFailure(f"say which entry. {list_autostart({})}")
    return found[0]


def remove_autostart(arguments: dict[str, Any]) -> str:
    path = _autostart_entry(arguments)
    run_checked(["gio", "trash", "--", str(path)])
    return f"{path.stem} no longer starts at login (its entry is in the trash)."


def defaults_tools() -> list[Tool]:
    return [
        Tool("default_applications", "Which application opens each kind of thing (browser, email, PDF, images, ...).",
             object_schema({"kind": {"type": "string"}}), RISK_READ, default_applications,
             summarize=lambda a: "Check default applications"),
        Tool("set_default_application", "Make an application the default for a kind of thing, for example the "
             "default browser.", object_schema({"kind": {"type": "string", "description": "browser, email, pdf, "
                                                "images, music, video, text, folders, or a MIME type"},
                                                "application": {"type": "string"}}, ["kind", "application"]),
             RISK_CHANGE, set_default_application,
             summarize=lambda a: f"Make {a.get('application', '?')} the default for {a.get('kind', '?')}"),
        Tool("list_autostart", "Applications that start when the user logs in.", object_schema(), RISK_READ,
             list_autostart, summarize=lambda a: "List startup applications"),
        Tool("add_autostart", "Start an application automatically at login.",
             object_schema({"application": {"type": "string"}}, ["application"]), RISK_CHANGE, add_autostart,
             summarize=lambda a: f"Start {a.get('application', '?')} at login"),
        Tool("remove_autostart", "Stop an application from starting at login (its entry goes to the trash).",
             object_schema({"entry": {"type": "string", "description": "Name of the entry from list_autostart"}},
                           ["entry"]), RISK_DANGER, remove_autostart,
             classify=lambda a: (RISK_DANGER, "removes a startup entry"),
             summarize=lambda a: f"Stop {a.get('entry', '?')} starting at login"),
    ]

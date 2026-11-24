"""File tools that change the filesystem: write, create, move, copy and trash.

These are where the user's approval rule bites hardest, so each tool
classifies the specific call (docs/ROADMAP.md, Permission Gate):

- ``danger``: moving something to the trash; replacing the contents of an
  existing file; a move or copy that would land on an existing file; and any
  target under a system path (``shell_risk.SYSTEM_PATHS``).
- ``change``: creating a new file or folder, appending to a file, writing
  identical content, and moves or copies that overwrite nothing.

Replacing something is always explicit: a call must pass ``overwrite: true``
to replace an existing file, and that is what makes it ``danger``. Without
the flag the handler refuses when the target exists. This keeps the
classifier and the handler in agreement even if a file appears between the
two, because the handler never replaces anything the call did not ask to.

There is no permanent-delete tool: ``trash_path`` moves to the desktop trash
so a mistake can be undone. Paths may start with ``~``.

Every successful change is recorded in ``undo_journal`` with what is needed
to reverse it (``tools/undo.py``); a file about to be replaced is first
copied aside by ``undo_journal.back_up``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .. import undo_journal
from ..desktop_context import run_command
from ..shell_risk import SYSTEM_PATHS
from .registry import RISK_CHANGE, RISK_DANGER, Tool, ToolFailure, object_schema

MAX_WRITE_CHARS = 2_000_000


def _path(arguments: dict[str, Any], name: str) -> Path:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolFailure(f"'{name}' is required and must be a path")
    return Path(os.path.abspath(os.path.expanduser(value.strip())))


def _system_reason(path: Path) -> str:
    text = str(path)
    for root in SYSTEM_PATHS:
        if text == root or text.startswith(root + "/"):
            return f"{path} is a system location"
    return ""


def _landing_path(source: Path, destination: Path) -> Path:
    """Where ``source`` ends up: inside ``destination`` if that is an existing folder."""
    return destination / source.name if destination.is_dir() else destination


def classify_write(arguments: dict[str, Any]) -> tuple[str, str]:
    path = _path(arguments, "path")
    reason = _system_reason(path)
    if reason:
        return RISK_DANGER, reason
    if arguments.get("overwrite") and not arguments.get("append") and path.is_file():
        return RISK_DANGER, f"replaces the contents of the existing file {path}"
    return RISK_CHANGE, ""


def write_text_file(arguments: dict[str, Any]) -> str:
    path = _path(arguments, "path")
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ToolFailure("'content' is required and must be text")
    if len(content) > MAX_WRITE_CHARS:
        raise ToolFailure("the content is too large to write in one call")
    if path.is_dir():
        raise ToolFailure(f"{path} is a folder")
    append = bool(arguments.get("append"))
    existed = path.exists()
    if existed and not append and not arguments.get("overwrite"):
        raise ToolFailure(f"{path} already exists. Pass overwrite=true to replace it, or append=true to add to it.")
    previous_size = path.stat().st_size if existed else 0
    backup = undo_journal.back_up(path) if existed and not append else ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a" if append else "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as error:
        raise ToolFailure(f"could not write {path}: {error.strerror or error}") from error
    action = "Appended to" if append and existed else "Replaced" if existed else "Created"
    if append and existed:
        undo_journal.record("file_appended", f"Appended to {path}", {"path": str(path), "size": previous_size})
    elif existed:
        undo_journal.record("file_replaced", f"Replaced the contents of {path}", {"path": str(path), "backup": backup})
    else:
        undo_journal.record("file_created", f"Created {path}", {"path": str(path)})
    return f"{action} {path} ({len(content)} characters)."


def classify_make_directory(arguments: dict[str, Any]) -> tuple[str, str]:
    reason = _system_reason(_path(arguments, "path"))
    return (RISK_DANGER, reason) if reason else (RISK_CHANGE, "")


def make_directory(arguments: dict[str, Any]) -> str:
    path = _path(arguments, "path")
    if path.is_dir():
        return f"{path} already exists."
    topmost = path
    while not topmost.parent.exists():
        topmost = topmost.parent
    try:
        path.mkdir(parents=True)
    except OSError as error:
        raise ToolFailure(f"could not create {path}: {error.strerror or error}") from error
    undo_journal.record("folder_created", f"Created folder {path}", {"path": str(path), "topmost": str(topmost)})
    return f"Created folder {path}."


def classify_transfer(arguments: dict[str, Any]) -> tuple[str, str]:
    source = _path(arguments, "source")
    landing = _landing_path(source, _path(arguments, "destination"))
    for candidate in (landing, source) if arguments.get("_move") else (landing,):
        reason = _system_reason(candidate)
        if reason:
            return RISK_DANGER, reason
    if arguments.get("overwrite") and landing.exists() and landing != source:
        return RISK_DANGER, f"replaces the existing {'folder' if landing.is_dir() else 'file'} {landing}"
    return RISK_CHANGE, ""


def _transfer(arguments: dict[str, Any], move: bool) -> str:
    source = _path(arguments, "source")
    landing = _landing_path(source, _path(arguments, "destination"))
    if not source.exists() and not source.is_symlink():
        raise ToolFailure(f"{source} does not exist")
    if landing == source:
        raise ToolFailure("the source and destination are the same")
    if (landing.exists() or landing.is_symlink()) and not arguments.get("overwrite"):
        raise ToolFailure(f"{landing} already exists. Pass overwrite=true to replace it.")
    replaced = landing.exists() or landing.is_symlink()
    try:
        if landing.is_dir() and not landing.is_symlink():
            if any(landing.iterdir()):
                raise ToolFailure(f"{landing} is a folder that is not empty; it will not be replaced")
            landing.rmdir()
        elif landing.exists():
            landing.unlink()
        landing.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(source), str(landing))
        elif source.is_dir():
            shutil.copytree(source, landing, symlinks=True)
        else:
            shutil.copy2(source, landing)
    except OSError as error:
        raise ToolFailure(f"could not {'move' if move else 'copy'} {source}: {error.strerror or error}") from error
    if move:
        undo_journal.record("moved", f"Moved {source} to {landing}",
                            {"source": str(source), "landing": str(landing), "replaced": replaced})
    else:
        undo_journal.record("copied", f"Copied {source} to {landing}", {"copy": str(landing), "replaced": replaced})
    return f"{'Moved' if move else 'Copied'} {source} to {landing}."


def move_path(arguments: dict[str, Any]) -> str:
    return _transfer(arguments, move=True)


def copy_path(arguments: dict[str, Any]) -> str:
    return _transfer(arguments, move=False)


def trash_path(arguments: dict[str, Any]) -> str:
    path = _path(arguments, "path")
    if not path.exists() and not path.is_symlink():
        raise ToolFailure(f"{path} does not exist")
    if not shutil.which("gio"):
        raise ToolFailure("the 'gio' command is not installed, so the trash cannot be used")
    result = run_command(["gio", "trash", "--", str(path)], timeout=60.0)
    if not result["ok"]:
        raise ToolFailure(result["stderr"].strip() or f"could not move {path} to the trash")
    undo_journal.record("trashed", f"Moved {path} to the trash", {"path": str(path)})
    return f"Moved {path} to the trash. It can be restored from there."


def _require_exists(name: str):
    def check(arguments: dict[str, Any]) -> None:
        path = _path(arguments, name)
        if not path.exists() and not path.is_symlink():
            raise ToolFailure(f"{path} does not exist. Check the folder with list_directory or search for the file.")

    return check


def file_tools() -> list[Tool]:
    path = {"type": "string", "description": "Absolute path, or one starting with ~"}
    overwrite = {"type": "boolean", "description": "Replace an existing file. Needs the user's approval."}
    transfer = object_schema({"source": path, "destination": {
        "type": "string", "description": "New path, or an existing folder to put it in"}, "overwrite": overwrite},
        ["source", "destination"])
    return [
        Tool("write_text_file", "Create a text file, replace a file's contents, or append to it. Parent folders "
             "are created as needed.",
             object_schema({"path": path, "content": {"type": "string"},
                            "append": {"type": "boolean", "description": "Add to the end instead of replacing"},
                            "overwrite": overwrite},
                           ["path", "content"]), RISK_CHANGE, write_text_file, classify=classify_write,
             summarize=lambda a: f"{'Append to' if a.get('append') else 'Write'} {a.get('path', '')}"),
        Tool("make_directory", "Create a folder, with any missing parent folders.",
             object_schema({"path": path}, ["path"]), RISK_CHANGE, make_directory, classify=classify_make_directory,
             summarize=lambda a: f"Create folder {a.get('path', '')}"),
        Tool("move_path", "Move or rename a file or folder.", transfer, RISK_CHANGE, move_path,
             classify=lambda a: classify_transfer({**a, "_move": True}), precheck=_require_exists("source"),
             summarize=lambda a: f"Move {a.get('source', '')} to {a.get('destination', '')}"),
        Tool("copy_path", "Copy a file or folder.", transfer, RISK_CHANGE, copy_path, classify=classify_transfer,
             precheck=_require_exists("source"),
             summarize=lambda a: f"Copy {a.get('source', '')} to {a.get('destination', '')}"),
        Tool("trash_path", "Move a file or folder to the trash. This is how to delete something; it can be restored.",
             object_schema({"path": path}, ["path"]), RISK_DANGER, trash_path,
             classify=lambda a: (RISK_DANGER, "moves it to the trash"), precheck=_require_exists("path"),
             summarize=lambda a: f"Move to trash: {a.get('path', '')}"),
    ]

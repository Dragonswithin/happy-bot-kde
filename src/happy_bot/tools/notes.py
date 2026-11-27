"""Notes and to-do tools: quick notes and a to-do list kept in two plain Markdown files.

The files are the user's own documents, readable and editable in any editor
and found by their file index like everything else: by default
``Notes.md`` and ``To-do.md`` in the Documents folder, or the paths set on
the settings page (``personal.notes_file`` / ``personal.todo_file`` in
``settings.py``). ``note_tools(read_settings)`` builds the tools with the
current settings.

- A note is appended as ``- YYYY-MM-DD HH:MM text``.
- A to-do is a Markdown task line, ``- [ ] text`` with an optional
  `` (due YYYY-MM-DD)``; completing one turns it into ``- [x]``. Hidden
  Markdown comments carry stable IDs and structured task details.

Adding records ``file_appended`` (or ``file_created``) in ``undo_journal``;
completing a to-do copies the file aside first and records
``file_replaced``, so every change can be undone. All writes are ``change``.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any, Callable

from .. import undo_journal
from ..tasks import TaskError, TaskStore
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

MAX_TEXT = 2000


def _file(read_settings: Callable[[], dict[str, Any]], key: str, default_name: str) -> Path:
    from ..agent_loop import user_folders

    settings = read_settings()
    configured = (settings.get("personal") or {}).get(key, "")
    if configured:
        return Path(os.path.expanduser(configured))
    return Path(user_folders(settings.get("folders"))["Documents"]) / default_name


def _append(path: Path, line: str, what: str) -> None:
    existed = path.exists()
    size = path.stat().st_size if existed else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        if existed and size and not path.read_text(encoding="utf-8").endswith("\n"):
            handle.write("\n")
        handle.write(line + "\n")
    if existed:
        undo_journal.record("file_appended", f"Added {what} to {path}", {"path": str(path), "size": size})
    else:
        undo_journal.record("file_created", f"Created {path}", {"path": str(path)})


def _text(arguments: dict[str, Any], name: str = "text") -> str:
    text = " ".join(str(arguments.get(name) or "").split())
    if not text:
        raise ToolFailure(f"'{name}' is required")
    if len(text) > MAX_TEXT:
        raise ToolFailure(f"'{name}' may be at most {MAX_TEXT} characters")
    return text


def task_store(read_settings: Callable[[], dict[str, Any]]) -> TaskStore:
    return TaskStore(lambda: _file(read_settings, "todo_file", "To-do.md"))


def note_tools(read_settings: Callable[[], dict[str, Any]]) -> list[Tool]:
    def notes_path() -> Path:
        return _file(read_settings, "notes_file", "Notes.md")

    store = task_store(read_settings)

    def add_note(arguments: dict[str, Any]) -> str:
        text = _text(arguments)
        path = notes_path()
        _append(path, f"- {datetime.datetime.now():%Y-%m-%d %H:%M} {text}", "a note")
        return f"Noted in {path}."

    def find_notes(arguments: dict[str, Any]) -> str:
        path = notes_path()
        if not path.exists():
            return f"There are no notes yet ({path})."
        wanted = str(arguments.get("contains") or "").lower()
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and wanted in line.lower()]
        return "\n".join(lines[-60:]) or f"No note mentions '{wanted}'."

    def list_todos(arguments: dict[str, Any]) -> str:
        items = [item for item in store.list() if arguments.get("include_done") or not item["done"]]
        today = datetime.date.today().isoformat()
        lines = []
        for number, item in enumerate(items, 1):
            due = f" (due {item['due']})" if item["due"] else ""
            late = " [overdue]" if item["due"] and item["due"] < today and not item["done"] else ""
            lines.append(f"{number}. {'[done] ' if item['done'] else ''}{item['text']}{due}{late} "
                         f"[id: {item['id']}, group: {item['group'] or '—'}, priority: {item['priority']}, "
                         f"repeat: {item['repeat']}, parent: {item['parent'] or '—'}, reminder: {item['reminder'] or '—'}]")
        return "\n".join(lines) or "The to-do list is empty."

    def change(action: str, arguments: dict[str, Any]) -> str:
        fields = dict(arguments)
        ident = fields.pop("id", "")
        if action == "complete" and not ident:
            wanted = str(fields.pop("item", "")).strip().casefold()
            open_items = [item for item in store.list() if not item["done"]]
            found = [item for number, item in enumerate(open_items, 1)
                     if wanted == str(number) or (not wanted.isdigit() and wanted and wanted in item["text"].casefold())]
            if len(found) != 1:
                raise ToolFailure(f"Say which to-do:\n{list_todos({})}")
            ident = found[0]["id"]
        try:
            item = store.change(action, ident, **fields)
        except (TaskError, OSError) as error:
            raise ToolFailure(str(error)) from error
        warning = store.sync_reminders()
        result = f"{action.capitalize()} task: {item['text']} (id: {item['id']})"
        return f"{result}\n{warning}" if warning else result

    text = {"type": "string"}
    fields = {
        "text": text, "due": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "group": text, "priority": {"type": "string", "enum": ["none", "low", "normal", "high"]},
        "repeat": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
        "parent": {"type": "string", "description": "Parent task ID or empty"},
        "reminder": {"type": "string", "description": "Due-date local time HH:MM or empty"},
    }
    return [
        Tool("add_note", "Write down a quick note for the user (kept in their notes file with the time).",
             object_schema({"text": text}, ["text"]), RISK_CHANGE, add_note, summarize=lambda a: "Write a note"),
        Tool("find_notes", "Read the user's quick notes, optionally only those mentioning some words.",
             object_schema({"contains": text}), RISK_READ, find_notes, summarize=lambda a: "Look through notes"),
        Tool("add_todo", "Create a task or subtask with optional scheduling details.",
             object_schema(fields, ["text"]), RISK_CHANGE, lambda a: change("create", a)),
        Tool("list_todos", "List tasks with stable task IDs and scheduling details.",
             object_schema({"include_done": {"type": "boolean"}}), RISK_READ, list_todos),
        Tool("edit_todo", "Edit the supplied fields of a task by ID.",
             object_schema({"id": text, **fields}, ["id"]), RISK_CHANGE, lambda a: change("edit", a)),
        Tool("complete_todo", "Complete a task by ID, list number, or words from its title.",
             object_schema({"id": text, "item": text}), RISK_CHANGE, lambda a: change("complete", a)),
        Tool("reopen_todo", "Reopen a completed task by ID.",
             object_schema({"id": text}, ["id"]), RISK_CHANGE, lambda a: change("reopen", a)),
        Tool("delete_todo", "Delete a task and its subtasks by ID.",
             object_schema({"id": text}, ["id"]), RISK_DANGER, lambda a: change("delete", a)),
    ]

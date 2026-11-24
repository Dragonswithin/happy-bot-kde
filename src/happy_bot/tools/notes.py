"""Notes and to-do tools: quick notes and a to-do list kept in two plain Markdown files.

The files are the user's own documents, readable and editable in any editor
and found by their file index like everything else: by default
``Notes.md`` and ``To-do.md`` in the Documents folder, or the paths set on
the settings page (``personal.notes_file`` / ``personal.todo_file`` in
``settings.py``). ``note_tools(read_settings)`` builds the tools with the
current settings.

- A note is appended as ``- YYYY-MM-DD HH:MM text``.
- A to-do is a Markdown task line, ``- [ ] text`` with an optional
  `` (due YYYY-MM-DD)``; completing one turns it into ``- [x]``.

Adding records ``file_appended`` (or ``file_created``) in ``undo_journal``;
completing a to-do copies the file aside first and records
``file_replaced``, so every change can be undone. All writes are ``change``.
"""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any, Callable

from .. import undo_journal
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

MAX_TEXT = 2000
_TASK = re.compile(r"^- \[( |x)\] (.*)$")


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


def note_tools(read_settings: Callable[[], dict[str, Any]]) -> list[Tool]:
    def notes_path() -> Path:
        return _file(read_settings, "notes_file", "Notes.md")

    def todo_path() -> Path:
        return _file(read_settings, "todo_file", "To-do.md")

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

    def add_todo(arguments: dict[str, Any]) -> str:
        text = _text(arguments)
        due = str(arguments.get("due") or "").strip()
        if due:
            try:
                due = datetime.date.fromisoformat(due).isoformat()
            except ValueError as error:
                raise ToolFailure("'due' must be a date like 2026-11-30") from error
        path = todo_path()
        _append(path, f"- [ ] {text}" + (f" (due {due})" if due else ""), "a to-do")
        return f"Added to the to-do list ({path})."

    def _tasks() -> list[tuple[int, bool, str]]:
        path = todo_path()
        if not path.exists():
            return []
        tasks = []
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            match = _TASK.match(line)
            if match:
                tasks.append((index, match.group(1) == "x", match.group(2)))
        return tasks

    def list_todos(arguments: dict[str, Any]) -> str:
        tasks = [task for task in _tasks() if arguments.get("include_done") or not task[1]]
        if not tasks:
            return "The to-do list is empty."
        today = datetime.date.today().isoformat()
        lines = []
        for number, (_, done, text) in enumerate(tasks, 1):
            due = re.search(r"\(due (\d{4}-\d{2}-\d{2})\)", text)
            late = " [overdue]" if due and due.group(1) < today and not done else ""
            lines.append(f"{number}. {'[done] ' if done else ''}{text}{late}")
        return "\n".join(lines)

    def complete_todo(arguments: dict[str, Any]) -> str:
        wanted = str(arguments.get("item") or "").strip().lower()
        open_tasks = [task for task in _tasks() if not task[1]]
        found = [task for number, task in enumerate(open_tasks, 1)
                 if wanted == str(number) or (not wanted.isdigit() and wanted and wanted in task[2].lower())]
        if len(found) != 1:
            raise ToolFailure(f"say which to-do (its number or words from it). Open ones:\n{list_todos({})}")
        path = todo_path()
        backup = undo_journal.back_up(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[found[0][0]] = f"- [x] {found[0][2]}"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        undo_journal.record("file_replaced", f"Ticked off '{found[0][2]}'", {"path": str(path), "backup": backup})
        return f"Done: {found[0][2]}"

    text = {"type": "string"}
    return [
        Tool("add_note", "Write down a quick note for the user (kept in their notes file with the time).",
             object_schema({"text": text}, ["text"]), RISK_CHANGE, add_note, summarize=lambda a: "Write a note"),
        Tool("find_notes", "Read the user's quick notes, optionally only those mentioning some words.",
             object_schema({"contains": text}), RISK_READ, find_notes, summarize=lambda a: "Look through notes"),
        Tool("add_todo", "Add an item to the user's to-do list, optionally with a due date.",
             object_schema({"text": text, "due": {"type": "string", "description": "YYYY-MM-DD"}}, ["text"]),
             RISK_CHANGE, add_todo, summarize=lambda a: f"Add to-do: {str(a.get('text', ''))[:80]}"),
        Tool("list_todos", "The user's to-do list, numbered, with overdue items marked.",
             object_schema({"include_done": {"type": "boolean"}}), RISK_READ, list_todos,
             summarize=lambda a: "Read the to-do list"),
        Tool("complete_todo", "Tick off a to-do item by its number or some of its words.",
             object_schema({"item": text}, ["item"]), RISK_CHANGE, complete_todo,
             summarize=lambda a: f"Tick off to-do {a.get('item', '?')}"),
    ]

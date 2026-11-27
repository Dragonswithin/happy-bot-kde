"""Shared task storage. Existing Markdown checklists remain the source of truth."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from . import task_reminders, undo_journal

_TASK = re.compile(r"^(\s*[-*+] \[)([ xX])(\]\s+)(.*)$")
_META = re.compile(r"\s+<!-- happy-bot-task (.*?) -->$")
_DUE = re.compile(r" \(due (\d{4}-\d{2}-\d{2})\)$")
_LOCK = threading.RLock()
PRIORITIES = ("none", "low", "normal", "high")
REPEATS = ("none", "daily", "weekly", "monthly")


class TaskError(ValueError):
    pass


def _date(value: Any) -> str:
    if not value:
        return ""
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise TaskError("The 'due' date must be YYYY-MM-DD.") from error


def _next_date(value: str, repeat: str) -> str:
    import calendar

    day = dt.date.fromisoformat(value)
    if repeat == "monthly":
        year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
        return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])).isoformat()
    return (day + dt.timedelta(days=7 if repeat == "weekly" else 1)).isoformat()


def _parse(lines: list[str]) -> list[dict[str, Any]]:
    tasks = []
    seen = set()
    for index, line in enumerate(lines):
        match = _TASK.match(line)
        if not match:
            continue
        title = match[4]
        metadata = {}
        marker = _META.search(title)
        if marker:
            try:
                value = json.loads(marker[1])
                if isinstance(value, dict):
                    metadata = value
                    title = title[:marker.start()]
            except ValueError:
                pass
        due = _DUE.search(title)
        if due:
            try:
                deadline = _date(due[1])
                title = title[:due.start()]
            except TaskError:
                deadline = ""
        else:
            deadline = ""
        ident = metadata.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident) or ident in seen:
            ident = uuid.uuid4().hex
        seen.add(ident)
        tasks.append(dict(id=ident, text=title, done=match[2].lower() == "x", due=deadline,
                          group=metadata.get("group", ""), priority=metadata.get("priority", "none"),
                          repeat=metadata.get("repeat", "none"), parent=metadata.get("parent", ""),
                          reminder=metadata.get("reminder", ""), successor=metadata.get("successor", ""), index=index))
    return tasks


def _line(task: dict[str, Any], prefix: str = "- [", spacing: str = "] ") -> str:
    meta = {key: task[key] for key in ("id", "group", "priority", "repeat", "parent", "reminder", "successor")}
    encoded = json.dumps(meta, ensure_ascii=True, separators=(",", ":")).replace("-", r"\u002d")
    due = f" (due {task['due']})" if task["due"] else ""
    return f"{prefix}{'x' if task['done'] else ' '}{spacing}{task['text']}{due} <!-- happy-bot-task {encoded} -->"


class TaskStore:
    def __init__(self, path: Callable[[], Path]) -> None:
        self.path = path

    def _read(self) -> tuple[Path, list[str], list[dict[str, Any]]]:
        path = self.path().resolve()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        tasks = _parse(lines)
        for task in tasks:
            index = task["index"]
            line = lines[index]
            match = _TASK.match(line)
            if not _META.search(match[4]) or task["id"] not in line:
                lines[index] = _line(task, match[1], match[3])
        return path, lines, tasks

    @staticmethod
    def _write(path: Path, lines: list[str], *, undo: str = "") -> None:
        existed = path.exists()
        backup = undo_journal.back_up(path) if undo and existed else None
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            try:
                if existed:
                    os.fchmod(out.fileno(), path.stat().st_mode & 0o777)
                out.write("\n".join(lines) + ("\n" if lines else ""))
                out.flush()
                os.fsync(out.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        if undo:
            if backup is not None:
                undo_journal.record("file_replaced", undo, {"path": str(path), "backup": backup})
            else:
                undo_journal.record("file_created", undo, {"path": str(path)})

    def list(self, *, migrate: bool = True) -> list[dict[str, Any]]:
        with _LOCK:
            path, lines, tasks = self._read()
            if migrate and tasks and lines != path.read_text(encoding="utf-8").splitlines():
                self._write(path, lines)
            return [{key: value for key, value in task.items() if key != "index"} for task in tasks]

    def sync_reminders(self) -> str:
        with _LOCK:
            try:
                task_reminders.reconcile(self.list())
            except OSError as error:
                return f"Task reminder scheduling: {error}"
        return ""

    def change(self, action: str, ident: str = "", **fields: Any) -> dict[str, Any]:
        with _LOCK:
            path, lines, tasks = self._read()
            existing = {task["id"]: task for task in tasks}
            if action == "create":
                task = dict(id=uuid.uuid4().hex, text="", done=False, due="", group="", priority="none",
                            repeat="none", parent="", reminder="", successor="", index=len(lines))
            else:
                if ident not in existing:
                    raise TaskError("That task no longer exists.")
                task = dict(existing[ident])
            if action in {"create", "edit"}:
                self._edit(task, fields, existing)
            elif action in {"complete", "reopen"}:
                task["done"] = action == "complete"
            elif action != "delete":
                raise TaskError("Unknown task action.")

            if action == "delete":
                removed = {ident}
                for _ in tasks:
                    removed.update(item["id"] for item in tasks if item["parent"] in removed)
                for index in sorted((existing[key]["index"] for key in removed), reverse=True):
                    del lines[index]
            elif action == "create":
                lines.append(_line(task))
            else:
                original = _TASK.match(lines[task["index"]])
                if (action == "complete" and not existing[ident]["done"] and task["repeat"] in REPEATS[1:]
                        and task["due"] and task["successor"] not in existing):
                    self._repeat_task(tasks, task, lines)
                lines[task["index"]] = _line(task, original[1], original[3])
            self._write(path, lines, undo=f"{action.capitalize()} task: {task['text']}")
            return {key: value for key, value in task.items() if key != "index"}

    @staticmethod
    def _edit(task: dict[str, Any], fields: dict[str, Any], existing: dict[str, dict[str, Any]]) -> None:
        for key in ("text", "group", "priority", "repeat", "parent", "reminder", "due"):
            if key in fields:
                task[key] = " ".join(str(fields[key] or "").split())
        if not 1 <= len(task["text"]) <= 2000 or len(task["group"]) > 120:
            raise TaskError("Enter a task name up to 2,000 characters and a group up to 120 characters.")
        task["due"] = _date(task["due"])
        if task["priority"] not in PRIORITIES or task["repeat"] not in REPEATS:
            raise TaskError("Choose a supported priority and recurrence.")
        parent = task["parent"]
        if parent and (parent not in existing or parent == task["id"] or existing[parent]["parent"]
                       or any(child["parent"] == task["id"] for child in existing.values())):
            raise TaskError("Select a top-level task as the parent.")
        if task["repeat"] != "none" and (not task["due"] or parent):
            raise TaskError("Recurring tasks need a due date and must be top-level tasks.")
        if task["reminder"] and (not task["due"] or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", task["reminder"])):
            raise TaskError("A reminder needs a due date and a local time in HH:MM format.")

    @staticmethod
    def _repeat_task(tasks: list[dict[str, Any]], task: dict[str, Any], lines: list[str]) -> None:
        next_due = _next_date(task["due"], task["repeat"])
        today = dt.date.today().isoformat()
        while next_due < today:
            next_due = _next_date(next_due, task["repeat"])
        task["successor"] = uuid.uuid4().hex
        replacement = dict(task, id=task["successor"], done=False, due=next_due, successor="")
        lines.append(_line(replacement))
        for child in tasks:
            if child["parent"] == task["id"]:
                due = ""
                if child["due"]:
                    delta = dt.date.fromisoformat(child["due"]) - dt.date.fromisoformat(task["due"])
                    due = (dt.date.fromisoformat(next_due) + delta).isoformat()
                lines.append(_line(dict(child, id=uuid.uuid4().hex, parent=replacement["id"], done=False, due=due)))

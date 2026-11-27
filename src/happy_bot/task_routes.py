"""Task screen endpoints backed by the same Markdown store as assistant tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .tasks import TaskError
from .tools.notes import task_store

if TYPE_CHECKING:
    from .daemon_http import AssistantServer


def list_tasks(server: AssistantServer, query: dict, body: dict) -> tuple[int, dict]:
    try:
        store = task_store(lambda: server.settings)
        return 200, {"ok": True, "tasks": store.list(), "warning": store.sync_reminders()}
    except (OSError, ValueError) as error:
        return 400, {"ok": False, "error": str(error), "code": "invalid"}


def change_task(server: AssistantServer, query: dict, body: dict[str, Any]) -> tuple[int, dict]:
    action = body.get("action", "")
    ident = body.get("id", "")
    fields = {key: body[key] for key in ("text", "group", "priority", "repeat", "parent", "reminder", "due") if key in body}
    if not isinstance(action, str) or not isinstance(ident, str):
        return 400, {"ok": False, "error": "Invalid task action or ID.", "code": "invalid"}
    try:
        store = task_store(lambda: server.settings)
        task = store.change(action, ident, **fields)
        return 200, {"ok": True, "task": task, "tasks": store.list(), "warning": store.sync_reminders()}
    except (TaskError, OSError) as error:
        return 400, {"ok": False, "error": str(error), "code": "invalid"}

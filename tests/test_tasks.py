"""Task UI and chat share the migrated Markdown file and deterministic timers."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401

from happy_bot import task_reminders, task_routes
from happy_bot.tools.notes import note_tools, task_store


class TaskFlow(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "To-do.md"
        self.unit_dir = Path(folder.name) / "systemd"
        self.server = SimpleNamespace(settings={"personal": {"todo_file": str(self.path)}})
        self.tools = {tool.name: tool.handler for tool in note_tools(lambda: self.server.settings)}
        self.addCleanup(patch.stopall)
        patch("happy_bot.user_timers.default_unit_dir", return_value=self.unit_dir).start()
        self.calls = []
        patch("happy_bot.user_timers.systemctl", side_effect=self.systemctl).start()

    def systemctl(self, *args):
        self.calls.append(args)
        if args[0] in {"enable", "disable"}:
            folder = self.unit_dir / "timers.target.wants"
            folder.mkdir(exist_ok=True)
            link = folder / args[-1]
            if args[0] == "enable" and not link.exists():
                link.symlink_to(self.unit_dir / args[-1])
            if args[0] == "disable":
                link.unlink(missing_ok=True)
        return True, ""

    def read(self):
        code, data = task_routes.list_tasks(self.server, {}, {})
        self.assertEqual(code, 200, data)
        return data["tasks"]

    def update(self, action, **fields):
        code, data = task_routes.change_task(self.server, {}, dict(action=action, **fields))
        self.assertEqual(code, 200, data)
        self.assertEqual(data["warning"], "")
        return data["task"]

    def test_migrate_edit_and_recur_across_reopened_store(self):
        self.path.write_text("# My list\n- [ ] Legacy (due 2024-03-01)\n- [x] Finished\n")
        legacy, finished = self.read()
        self.assertEqual((legacy["due"], finished["done"]), ("2024-03-01", True))
        self.assertEqual(self.read()[0]["id"], legacy["id"])
        self.assertIn("# My list", self.path.read_text())

        due = (dt.date.today() + dt.timedelta(days=7)).isoformat()
        self.tools["add_todo"](dict(text="Water plants", due=due, repeat="weekly", reminder="08:00"))
        parent = self.read()[-1]
        child = self.update("create", text="Fill the can", parent=parent["id"])
        self.update("edit", id=parent["id"], text="Water balcony plants", group="Home", priority="high", reminder="09:00")
        name = f"happy-bot-task-reminder-{parent['id']}"
        timer = self.unit_dir / f"{name}.timer"
        self.assertIn("09:00:00", timer.read_text())
        self.assertEqual(len(list(self.unit_dir.glob("*.timer"))), 1)
        call_count = len(self.calls)
        items = task_store(lambda: self.server.settings).list()
        self.read()
        self.assertEqual(len(self.calls), call_count)
        self.assertEqual(task_reminders.due_text(items, parent["id"], f"{due} 08:00:00"), "")
        self.assertEqual(task_reminders.due_text(items, parent["id"], f"{due} 09:00:00"), "Water balcony plants")

        self.tools["complete_todo"]({"id": child["id"]})
        self.tools["complete_todo"]({"id": parent["id"]})
        tasks = self.read()
        self.assertFalse(timer.exists())
        self.assertEqual(len(list(self.unit_dir.glob("*.timer"))), 1)
        next_parent = next(item for item in tasks if item["text"] == "Water balcony plants" and not item["done"])
        self.assertEqual(next_parent["due"], (dt.date.fromisoformat(due) + dt.timedelta(days=7)).isoformat())
        self.assertTrue(any(item["parent"] == next_parent["id"] and not item["done"] for item in tasks))
        self.tools["reopen_todo"]({"id": parent["id"]})
        self.update("complete", id=parent["id"])
        self.assertEqual(len(self.read()), len(tasks))
        self.tools["delete_todo"]({"id": next_parent["id"]})
        self.assertFalse(list(self.unit_dir.glob("*.timer")))
        self.assertFalse(any(item["parent"] == next_parent["id"] for item in self.read()))

    def test_failed_timer_activation_leaves_task_saved_and_can_retry(self):
        due = (dt.date.today() + dt.timedelta(days=7)).isoformat()
        with patch("happy_bot.user_timers.systemctl", return_value=(False, "temporary failure")):
            status, data = task_routes.change_task(
                self.server, {}, {"action": "create", "text": "Retry alert", "due": due, "reminder": "08:00"}
            )
        self.assertEqual(status, 200, data)
        self.assertIn("temporary failure", data["warning"])
        self.assertEqual(self.read()[0]["id"], data["task"]["id"])
        self.assertEqual(len(list(self.unit_dir.glob("*.timer"))), 1)

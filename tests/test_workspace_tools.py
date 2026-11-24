"""Tests for the workspace tools: virtual desktops, activities, other windows, saved layouts.

KWin and the Activity Manager are replaced by fakes, so the tests check what
the tools ask for and how they read the answers; the layout tools run
against an in-memory settings store validated by the real ``settings.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tools import workspace  # noqa: E402
from happy_bot.tools.registry import RISK_DANGER, ToolFailure  # noqa: E402


class DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        self.state = {"desktops": [(0, "id-1", "Main"), (1, "id-2", "Mail")], "current": "id-1"}
        patches = [
            mock.patch.object(workspace.session_dbus, "properties", side_effect=lambda *a: self.state),
            mock.patch.object(workspace.session_dbus, "set_property", side_effect=lambda *a: self.calls.append(("set",) + a[3:])),
            mock.patch.object(workspace.session_dbus, "call", side_effect=self.fake_call),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_call(self, service, path, interface, method, signature="", arguments=()):
        self.calls.append((method, arguments))
        if method == "ListActivitiesWithInformation":
            return ([("act-1", "Default", "", "", 2, 0), ("act-2", "Work", "", "", 2, 0)],)
        if method == "CurrentActivity":
            return ("act-1",)
        return ()

    def test_listing_and_switching_by_number_or_name(self) -> None:
        text = workspace.list_workspaces({})
        self.assertIn("1. Main (current), 2. Mail", text)
        self.assertIn("Default (current), Work", text)
        workspace.desktop_action({"action": "switch", "desktop": "mail"})
        workspace.desktop_action({"action": "switch", "desktop": "1"})
        self.assertEqual([call for call in self.calls if call[0] == "set"], [("set", "current", "s", "id-2"), ("set", "current", "s", "id-1")])
        with self.assertRaisesRegex(ToolFailure, "no virtual desktop"):
            workspace.desktop_action({"action": "switch", "desktop": "9"})

    def test_create_rename_remove_and_activities(self) -> None:
        workspace.desktop_action({"action": "create", "name": "Games"})
        workspace.desktop_action({"action": "rename", "desktop": "2", "name": "Post"})
        workspace.desktop_action({"action": "remove", "desktop": "Mail"})
        workspace.activity_action({"action": "switch", "name": "work"})
        self.assertIn(("createDesktop", (2, "Games")), self.calls)
        self.assertIn(("setDesktopName", ("id-2", "Post")), self.calls)
        self.assertIn(("removeDesktop", ("id-2",)), self.calls)
        self.assertIn(("SetCurrentActivity", ("act-2",)), self.calls)
        self.state["desktops"] = [(0, "id-1", "Main")]
        with self.assertRaisesRegex(ToolFailure, "last virtual desktop"):
            workspace.desktop_action({"action": "remove", "desktop": "1"})


class LayoutTests(unittest.TestCase):
    WINDOWS = [{"id": "{a}", "app": "kate", "title": "x", "x": 0, "y": 0, "width": 960, "height": 1080},
               {"id": "{b}", "app": "konsole", "title": "y", "x": 960, "y": 0, "width": 960, "height": 1080}]

    def setUp(self) -> None:
        self.store = {"settings": validate_settings({})}
        self.placed = []

        def update(mutate):
            changed = {**self.store["settings"], "layouts": dict(self.store["settings"]["layouts"])}
            mutate(changed)
            self.store["settings"] = validate_settings(changed)
            return self.store["settings"]

        self.tools = {tool.name: tool for tool in workspace.layout_tools(lambda: self.store["settings"], update)}
        patcher = mock.patch.object(workspace, "_kwin", return_value=self.WINDOWS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_restore_and_delete(self) -> None:
        self.assertIn("2 windows", self.tools["save_layout"].handler({"name": "coding"}))
        with mock.patch("happy_bot.tools.windows._run", side_effect=lambda args, js: self.placed.append(args)):
            with mock.patch.object(workspace, "_kwin", return_value=self.WINDOWS[:1]):
                text = self.tools["restore_layout"].handler({"name": "coding"})
        self.assertIn("Not running, so not placed: konsole", text)
        self.assertEqual(self.placed, [{"window": "{a}", "x": 0, "y": 0, "width": 960, "height": 1080}])
        self.assertEqual(self.tools["delete_layout"].risk, RISK_DANGER)
        self.tools["delete_layout"].handler({"name": "coding"})
        self.assertEqual(self.tools["list_layouts"].handler({}), "No layouts are saved.")

    def test_layouts_are_validated(self) -> None:
        with self.assertRaisesRegex(SettingsError, "whole number of pixels"):
            validate_settings({"layouts": {"x": [{"app": "kate", "x": "left", "y": 0, "width": 1, "height": 1}]}})
        with self.assertRaisesRegex(ToolFailure, "names use letters"):
            self.tools["save_layout"].handler({"name": "bad/name"})


class OtherWindowsTests(unittest.TestCase):
    def test_close_others_sends_the_keep_list_to_kwin(self) -> None:
        with mock.patch.object(workspace, "_kwin", return_value=["dolphin: Home"]) as kwin:
            self.assertIn("Asked 1 windows to close", workspace.close_other_windows({"keep": ["Firefox"]}))
        self.assertIn('["firefox"]', kwin.call_args[0][0])


if __name__ == "__main__":
    unittest.main()

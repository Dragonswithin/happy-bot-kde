"""Tests for panel_widget: reading and changing the Happy Bot panel widgets' look.

The Plasma shell is replaced by a fake that keeps the widgets' settings and
answers the read script, so these check the scripts' contract (what is read,
what is written), the read-back that turns a change that did not take into a
failure, and the /panel route's validation; nothing on the desktop changes.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import daemon_routes, panel_widget  # noqa: E402


class FakeShell:
    """Stands in for ``_evaluate``: widgets with settings; applies writes unless ``ignore_writes``."""

    def __init__(self, widgets: list[dict], ignore_writes: bool = False) -> None:
        self.widgets = widgets
        self.ignore_writes = ignore_writes
        self.scripts: list[str] = []

    def __call__(self, script: str) -> str:
        self.scripts.append(script)
        if "print(JSON.stringify(out))" in script:
            return json.dumps(self.widgets)
        if not self.ignore_writes:
            for widget in self.widgets:
                if "writeConfig('inputInPanel', true)" in script:
                    widget["search_bar"] = True
                if "writeConfig('inputInPanel', false)" in script:
                    widget["search_bar"] = False
                if "writeConfig('barWidth', 30)" in script:
                    widget["bar_width"] = 30
        return ""


class PanelWidgetTests(unittest.TestCase):
    def test_the_search_bar_is_switched_on_and_checked(self) -> None:
        shell = FakeShell([{"id": 189, "search_bar": False, "bar_width": 18, "vertical": False}])
        with mock.patch.object(panel_widget, "_evaluate", side_effect=shell):
            widgets = panel_widget.change(search_bar=True, bar_width=30)
        self.assertEqual(widgets, [{"id": 189, "search_bar": True, "bar_width": 30, "vertical": False}])
        write = shell.scripts[1]
        self.assertIn(json.dumps(panel_widget.APPLET_ID), write)
        self.assertIn("w.reloadConfig();", write)

    def test_a_change_that_did_not_take_is_a_failure(self) -> None:
        shell = FakeShell([{"id": 189, "search_bar": False, "bar_width": 18, "vertical": False}], ignore_writes=True)
        with mock.patch.object(panel_widget, "_evaluate", side_effect=shell):
            with self.assertRaisesRegex(panel_widget.PanelWidgetError, "did not take"):
                panel_widget.change(search_bar=True)

    def test_no_panel_widget_and_bad_values_are_refused(self) -> None:
        with mock.patch.object(panel_widget, "_evaluate", side_effect=FakeShell([])):
            with self.assertRaisesRegex(panel_widget.PanelWidgetError, "not on a panel"):
                panel_widget.change(search_bar=True)
        with self.assertRaisesRegex(panel_widget.PanelWidgetError, "8 to 60"):
            panel_widget.change(bar_width=99)
        for body in ({}, {"search_bar": "yes"}, {"bar_width": 99}, {"bar_width": True}):
            with self.subTest(body=body):
                status, reply = daemon_routes.panel_change(None, {}, body)
                self.assertEqual(status, 400)
                self.assertEqual(reply["code"], "invalid")


if __name__ == "__main__":
    unittest.main()

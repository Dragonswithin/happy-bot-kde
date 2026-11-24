"""Tests for Happy Bot's shared look and feel (``ui_settings``) and changing it with ``POST /ui``.

The schema is checked directly: defaults fill in, ranges and unknown keys are refused. The route
is checked against a stand-in daemon whose ``replace_settings`` validates with the real settings
schema, so a refused change leaves the stored settings as they were.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import daemon_routes  # noqa: E402
from happy_bot.settings import validate_settings  # noqa: E402
from happy_bot.ui_settings import UI_DEFAULTS, UiSettingsError, validate_ui  # noqa: E402


class UiSchemaTests(unittest.TestCase):
    def test_defaults_fill_in_and_bad_values_are_refused(self) -> None:
        self.assertEqual(validate_ui({}), UI_DEFAULTS)
        self.assertEqual(validate_ui({"robot_mascot": True, "imported": ["app", "app"]})["imported"], ["app"])
        for bad, message in (({"popup_width": 5}, "'popup_width'"), ({"robot_mascot": "yes"}, "'robot_mascot'"),
                             ({"colour": "red"}, "unknown setting 'colour'"), ({"imported": ["phone"]}, "'imported'"),
                             ({"floating_x": True}, "'floating_x'")):
            with self.subTest(bad=bad), self.assertRaisesRegex(UiSettingsError, message):
                validate_ui(bad)
        self.assertEqual(validate_settings({})["ui"], UI_DEFAULTS)


class FakeDaemon:
    def __init__(self) -> None:
        self.settings = validate_settings({})

    def replace_settings(self, new_settings: Any) -> dict[str, Any]:
        self.settings = validate_settings(new_settings)
        return self.settings


class ChangeUiRouteTests(unittest.TestCase):
    def test_changes_merge_and_a_refused_one_changes_nothing(self) -> None:
        daemon = FakeDaemon()
        status, reply = daemon_routes.change_ui(daemon, {}, {"changes": {"robot_mascot": True, "floating_x": 300}})
        self.assertEqual((status, reply["ui"]["robot_mascot"], reply["ui"]["floating_x"]), (200, True, 300))
        status, reply = daemon_routes.change_ui(daemon, {}, {"changes": {"popup_height": 999}})
        self.assertEqual((status, reply["code"]), (400, "invalid"))
        self.assertEqual(daemon.settings["ui"]["popup_height"], 26)
        self.assertTrue(daemon.settings["ui"]["robot_mascot"])


if __name__ == "__main__":
    unittest.main()

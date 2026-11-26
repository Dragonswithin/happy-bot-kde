"""Tests for Happy Bot's shared look and feel (``ui_settings``) and changing it with ``POST /ui``.

The schema is checked directly: defaults fill in, ranges and unknown keys are refused. The route
is checked against a stand-in daemon whose ``replace_settings`` validates with the real settings
schema, so a refused change leaves the stored settings as they were. ``assistant_icon`` and the
finished-request notification (``ask_stream.notify_finished``, with ``notify-send`` stubbed out)
are checked to show the mascot only when it is chosen.
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import daemon_routes  # noqa: E402
from happy_bot.settings import validate_settings  # noqa: E402
from happy_bot import ask_stream  # noqa: E402
from happy_bot.ui_settings import MASCOT_ICON, UI_DEFAULTS, WAND_ICON, UiSettingsError, assistant_icon, validate_ui  # noqa: E402


class NotificationIconTests(unittest.TestCase):
    def test_the_mascot_setting_picks_the_notification_icon(self) -> None:
        self.assertEqual(assistant_icon(UI_DEFAULTS), MASCOT_ICON)
        for ui in ({"robot_mascot": False}, None, {"robot_mascot": "yes"}):
            self.assertEqual(assistant_icon(ui), WAND_ICON)

    def test_the_finished_notification_shows_the_chosen_icon(self) -> None:
        sent: list[list[str]] = []
        with mock.patch.object(ask_stream.shutil, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(ask_stream, "run_command", side_effect=lambda command, timeout: sent.append(command) or {}), \
                mock.patch.object(ask_stream.threading, "Thread", side_effect=lambda target, **_: mock.Mock(start=target)):
            ask_stream.notify_finished("Wallpaper", MASCOT_ICON)
        self.assertIn(f"--icon={MASCOT_ICON}", sent[0])


class UiSchemaTests(unittest.TestCase):
    def test_existing_picture_choice_gets_quiet_feedback_defaults(self) -> None:
        older_ui = validate_ui({"robot_mascot": False})
        self.assertFalse(older_ui["robot_mascot"])
        self.assertFalse(older_ui["robot_sounds"])
        self.assertTrue(older_ui["mascot_animations"])

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
    def test_retired_typing_settings_are_dropped_not_refused(self) -> None:
        # Settings saved before files stopped being searched while typing still load.
        ui = validate_ui({"instant_search": False, "instant_min_chars": 3, "instant_delay_ms": 0,
                          "instant_results": 5, "robot_mascot": True})
        self.assertEqual(ui, {**UI_DEFAULTS, "robot_mascot": True})

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

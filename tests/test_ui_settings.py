"""Tests for Happy Bot's shared look and feel (``ui_settings``) and changing it with ``POST /ui``.

The schema is checked directly: defaults fill in, ranges and unknown keys are refused. The route
is checked against a stand-in daemon whose ``replace_settings`` validates with the real settings
schema, so a refused change leaves the stored settings as they were. ``assistant_icon`` and the
finished-request notification (``ask_stream.notify_finished``, with ``notify-send`` stubbed out)
are checked to show the mascot only when it is chosen.
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from unittest import mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import daemon_routes  # noqa: E402
from happy_bot.daemon_http import AssistantServer  # noqa: E402
from happy_bot.settings import load_settings, save_settings, validate_settings  # noqa: E402
from happy_bot import ask_stream  # noqa: E402
from happy_bot.ui_settings import (MASCOT_ICON, ROBOT_STYLES, UI_DEFAULTS, WAND_ICON, UiSettingsError,
                                   assistant_icon, validate_ui)  # noqa: E402


class NotificationIconTests(unittest.TestCase):
    def test_the_mascot_setting_picks_the_notification_icon(self) -> None:
        self.assertEqual(assistant_icon(UI_DEFAULTS), MASCOT_ICON)
        for style in ROBOT_STYLES:
            expected = MASCOT_ICON if style == "pip" else f"{MASCOT_ICON}-{style}"
            self.assertEqual(assistant_icon({"robot_mascot": True, "robot_style": style}), expected)
            self.assertEqual(assistant_icon({"robot_mascot": False, "robot_style": style}), WAND_ICON)
        for ui in ({"robot_mascot": False}, None, {"robot_mascot": "yes"}):
            self.assertEqual(assistant_icon(ui), WAND_ICON)

    def test_the_finished_notification_shows_the_chosen_icon(self) -> None:
        sent: list[list[str]] = []
        with mock.patch.object(ask_stream.shutil, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(ask_stream, "run_command", side_effect=lambda command, timeout: sent.append(command) or {}), \
                mock.patch.object(ask_stream.threading, "Thread", side_effect=lambda target, **_: mock.Mock(start=target)):
            ask_stream.notify_finished("Wallpaper", assistant_icon({"robot_mascot": True, "robot_style": "orbit"}))
        self.assertIn(f"--icon={MASCOT_ICON}-orbit", sent[0])

    def test_robot_tray_icons_install_with_their_own_art_and_remove_independently_of_app_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        images = root / "plasmoid" / MASCOT_ICON / "contents/images"
        reactions = ("busy", "memory", "nudge", "hot", "download", "upload", "transfer", "recording")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            app_icon = directory / f"{MASCOT_ICON}.svg"
            app_icon.write_bytes((images / "happy-bot.svg").read_bytes())
            generator = [sys.executable, str(root / "scripts/mascot_tray_icons.py"), tmp]
            subprocess.run(generator, check=True)
            for style in ROBOT_STYLES:
                base = images / "happy-bot.svg" if style == "pip" else images / "robots" / f"{style}.svg"
                prefix = assistant_icon({"robot_mascot": True, "robot_style": style})
                self.assertEqual((directory / f"{prefix}.svg").read_bytes(), base.read_bytes())
                body = list(ET.parse(base).getroot())
                for state in reactions:
                    with self.subTest(style=style, state=state):
                        pose = list(ET.parse(directory / f"{prefix}-{state}.svg").getroot())
                        self.assertGreater(len(pose), len(body))
                        self.assertEqual([ET.tostring(part) for part in pose[:len(body)]],
                                         [ET.tostring(part) for part in body])
            self.assertTrue((directory / f"{MASCOT_ICON}-microphone-active.svg").exists())
            subprocess.run([*generator, "--remove"], check=True)
            self.assertEqual(list(directory.iterdir()), [app_icon])


class UiSchemaTests(unittest.TestCase):
    def test_popup_positions_survive_a_settings_reload(self) -> None:
        ui = validate_ui({"panel_popup_x": 120, "panel_popup_y": 85,
                          "floating_popup_x": 40, "floating_popup_y": 0,
                          "floating_x": 900, "floating_y": 300})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings({"ui": ui}, path)
            self.assertEqual(load_settings(path)["ui"], ui)

    def test_greeting_migrates_to_the_configured_robot(self) -> None:
        old = validate_ui({"robot_style": "orbit", "robot_sounds": True})
        self.assertTrue(old["sounds_follow_mascot"])
        sounds = old["event_sounds"]
        self.assertEqual([event for event, fields in sounds.items() if fields["enabled"]], ["open"])
        self.assertEqual({row["theme"] for row in sounds.values()}, {"orbit"})
        self.assertEqual(validate_ui(old), old)

    def test_existing_picture_choice_gets_quiet_feedback_defaults(self) -> None:
        older_ui = validate_ui({"robot_mascot": False})
        self.assertFalse(older_ui["robot_mascot"])
        self.assertEqual(older_ui["robot_style"], "pip")
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

    def test_chosen_style_persists_even_with_the_wand_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_settings({"ui": {"robot_mascot": False, "robot_style": "sprig"}}, path)
            ui = load_settings(path)["ui"]
            self.assertEqual(ui["robot_style"], "sprig")
            self.assertFalse(ui["robot_mascot"])


class FakeDaemon:
    update_ui = AssistantServer.update_ui

    def __init__(self) -> None:
        self.settings = validate_settings({})
        self._settings_lock = threading.RLock()

    def replace_settings(self, new_settings: Any) -> dict[str, Any]:
        self.settings = validate_settings(new_settings)
        return self.settings


class ChangeUiRouteTests(unittest.TestCase):
    def test_wand_sound_theme_follows_appearance_and_keeps_mutes(self) -> None:
        daemon = FakeDaemon()

        def save(**changes):
            status, data = daemon_routes.change_ui(daemon, {}, {"changes": changes})
            self.assertEqual(status, 200, data)
            return data["ui"]["event_sounds"]

        save(event_sounds={"reminder": {"enabled": True}})
        wand = save(robot_mascot=False)
        self.assertEqual({row["theme"] for row in wand.values()}, {"wand"})
        self.assertEqual([event for event, row in wand.items() if row["enabled"]], ["reminder"])
        self.assertEqual({row["theme"] for row in save(robot_mascot=True).values()}, {"pip"})
        self.assertEqual(save(event_sounds={"open": {"theme": "wand"}})["open"]["theme"], "wand")
        self.assertEqual(save(sounds_follow_mascot=False, robot_mascot=False)["reminder"]["theme"], "pip")

    def test_sound_choices_follow_the_robot_only_when_requested(self) -> None:
        daemon = FakeDaemon()

        def save(**changes):
            status, data = daemon_routes.change_ui(daemon, {}, {"changes": changes})
            self.assertEqual(status, 200, data)
            return data["ui"]

        save(event_sounds={"reminder": {"theme": "sprig", "enabled": True}, "error": {"theme": "rivet"}})
        save(sounds_follow_mascot=False)
        sounds = save(robot_style="nixie")["event_sounds"]
        self.assertEqual(sounds["reminder"], {"theme": "sprig", "enabled": True})
        self.assertEqual(sounds["error"], {"theme": "rivet", "enabled": False})
        save(sounds_follow_mascot=True)
        sounds = save(robot_style="sonar")["event_sounds"]
        self.assertEqual({row["theme"] for row in sounds.values()}, {"sonar"})
        self.assertEqual([event for event, row in sounds.items() if row["enabled"]], ["reminder"])
        save(event_sounds={"error": {"enabled": True}})
        sounds = save(event_sounds={"error": {"theme": "dotty"}})["event_sounds"]
        self.assertEqual(sounds["error"], {"theme": "dotty", "enabled": True})
        self.assertEqual(sounds["reminder"], {"theme": "sonar", "enabled": True})
        self.assertTrue(save(robot_sounds=True)["event_sounds"]["open"]["enabled"])
        self.assertFalse(save(event_sounds={"open": {"enabled": False}})["robot_sounds"])

    def test_invalid_event_edits_are_atomic(self) -> None:
        daemon = FakeDaemon()
        for patch in (None, [], {"bad": {}}, {"error": {"theme": "../test"}}, {"open": {"enabled": "no"}},
                      {"alarm": {"source": "elsewhere"}}, {"error": 3}):
            with self.subTest(patch=patch):
                status, _ = daemon_routes.change_ui(daemon, {}, {"changes": {"robot_style": "pixel", "event_sounds": patch}})
                self.assertEqual(status, 400)
                self.assertEqual(daemon.settings["ui"], UI_DEFAULTS)

    def test_style_changes_are_checked_before_replacing_a_saved_robot(self) -> None:
        daemon = FakeDaemon()
        for style in ROBOT_STYLES:
            status, reply = daemon_routes.change_ui(daemon, {}, {"changes": {"robot_style": style}})
            self.assertEqual((status, reply["ui"]["robot_style"]), (200, style))
        for invalid in ("", "../other.svg", False, ["sonar"]):
            with self.subTest(invalid=invalid):
                status, _ = daemon_routes.change_ui(daemon, {}, {"changes": {"robot_style": invalid}})
                self.assertEqual(status, 400)
                self.assertEqual(daemon.settings["ui"]["robot_style"], "dotty")

    def test_retired_typing_settings_are_dropped_not_refused(self) -> None:
        # Settings saved before files stopped being searched while typing still load.
        ui = validate_ui({"instant_search": False, "instant_min_chars": 3, "instant_delay_ms": 0,
                          "instant_results": 5, "robot_mascot": True})
        self.assertEqual(ui, {**UI_DEFAULTS, "robot_mascot": True})

    def test_floating_shortcut_size_defaults_and_limits(self) -> None:
        daemon = FakeDaemon()
        self.assertEqual(validate_ui({"floating_x": 420})["floating_size"], 100)
        for size in (50, 200):
            status, reply = daemon_routes.change_ui(daemon, {}, {"changes": {"floating_size": size}})
            self.assertEqual((status, reply["ui"]["floating_size"]), (200, size))
        for invalid in (49, 201, True):
            status, _ = daemon_routes.change_ui(daemon, {}, {"changes": {"floating_size": invalid}})
            self.assertEqual(status, 400)
            self.assertEqual(daemon.settings["ui"]["floating_size"], 200)

    def test_docking_an_existing_shortcut_persists_its_mode_and_position(self) -> None:
        position = {"floating_x": 420, "floating_y": 160}
        daemon = FakeDaemon()
        daemon.replace_settings({"ui": position})
        self.assertFalse(daemon.settings["ui"]["floating_docked"])
        status, _ = daemon_routes.change_ui(daemon, {}, {"changes": {"floating_docked": True}})
        self.assertEqual(status, 200)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_settings(daemon.settings, path)
            self.assertEqual(load_settings(path)["ui"], {**UI_DEFAULTS, **position, "floating_docked": True})
        status, _ = daemon_routes.change_ui(daemon, {}, {"changes": {"floating_docked": "false"}})
        self.assertEqual(status, 400)
        self.assertTrue(daemon.settings["ui"]["floating_docked"])

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

"""Tests for the media, phone, reminder and routine features.

Media and phone tools run against fakes of the session DBus
(``session_dbus``) and of the programs they call, so the tests need no
player or paired phone. Reminders and routines write their systemd units
into a temporary directory with ``systemctl`` switched off, and the unit
text is checked directly; ``systemd-analyze`` is used for real when it is
installed, to validate schedules.
"""

from __future__ import annotations

import datetime
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import routines, user_timers  # noqa: E402
from kde_ai_assistant.agent_loop import system_prompt  # noqa: E402
from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tools import media, phone, reminders  # noqa: E402
from kde_ai_assistant.tools.registry import RISK_DANGER, RISK_READ, Tool, ToolFailure, ToolRegistry, object_schema  # noqa: E402
from kde_ai_assistant.tools.routine_tools import routine_tools  # noqa: E402

PLAYER = "org.mpris.MediaPlayer2.elisa"


class MediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        state = {"PlaybackStatus": "Playing", "Position": 65_000_000, "Metadata": {
            "xesam:title": "Song", "xesam:artist": ["Band"], "xesam:album": "Record", "mpris:length": 200_000_000}}
        patches = [
            mock.patch.object(media.session_dbus, "names", return_value=[PLAYER]),
            mock.patch.object(media.session_dbus, "properties", return_value=state),
            mock.patch.object(media.session_dbus, "call", side_effect=lambda *a: self.calls.append(a)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_now_playing_describes_the_track(self) -> None:
        self.assertEqual(media.now_playing({}), 'elisa: Playing "Song" by Band from Record at 1:05 of 3:20')

    def test_seek_moves_by_the_difference_from_the_current_position(self) -> None:
        self.assertIn("1:30", media.seek_media({"position_seconds": 90}))
        self.assertEqual(self.calls[0][3:], ("Seek", "x", (25_000_000,)))
        with self.assertRaisesRegex(ToolFailure, "no running player matches"):
            media.seek_media({"position_seconds": 1, "player": "vlc"})


class AudioTests(unittest.TestCase):
    SINKS = '[{"index": 1, "name": "hdmi", "description": "HDMI Out", "mute": false, "volume": {"fl": {"value_percent": "50%"}}},' \
            ' {"index": 2, "name": "usb-headset", "description": "USB Headset", "mute": true, "volume": {"fl": {"value_percent": "30%"}}}]'

    def setUp(self) -> None:
        self.commands = []

        def fake(command, timeout=5.0):
            self.commands.append(command)
            outputs = {"sinks": self.SINKS, "sources": "[]",
                       "sink-inputs": '[{"index": 9, "properties": {"application.name": "Firefox"}, "volume": {}, "mute": false}]'}
            if command[:3] == ["pactl", "--format=json", "list"]:
                return {"ok": True, "stdout": outputs[command[3]], "stderr": ""}
            if command[:2] == ["pactl", "get-default-sink"]:
                return {"ok": True, "stdout": "hdmi\n", "stderr": ""}
            return {"ok": True, "stdout": "", "stderr": ""}

        patcher = mock.patch.object(media, "run_command", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self._tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_devices_and_streams_are_listed_with_the_default_marked(self) -> None:
        text = media.list_audio_devices({})
        self.assertIn(" * HDMI Out  [hdmi]  50%", text)
        self.assertIn("USB Headset  [usb-headset]  30%, muted", text)
        self.assertIn("Firefox  (stream 9)", text)

    def test_default_output_is_matched_by_name_and_can_be_undone(self) -> None:
        self.assertIn("USB Headset", media.set_default_device({"kind": "output", "device": "headset"}))
        self.assertIn(["pactl", "set-default-sink", "usb-headset"], self.commands)
        from kde_ai_assistant import undo_journal
        self.assertEqual(undo_journal.pending()[0]["data"], {"kind": "sink", "name": "hdmi"})
        with self.assertRaisesRegex(ToolFailure, "no device matches"):
            media.set_default_device({"kind": "output", "device": "bluetooth"})

    def test_one_application_volume(self) -> None:
        self.assertEqual(media.set_app_volume({"application": "firefox", "percent": 40}), "Set Firefox to 40%.")
        self.assertIn(["pactl", "set-sink-input-volume", "9", "40%"], self.commands)
        with self.assertRaisesRegex(ToolFailure, "is playing sound"):
            media.set_app_volume({"application": "spotify", "mute": True})


class PhoneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cli_calls = []
        devices = {"aaaaaaaa11": {"name": "Pixel", "type": "phone"}, "bbbbbbbb22": {"name": "Laptop", "type": "laptop"}}

        def cli(arguments, timeout=30.0):
            self.cli_calls.append(arguments)
            if arguments[0] == "--list-available":
                return "aaaaaaaa11 Pixel\nbbbbbbbb22 Laptop\n"
            return ""

        def properties(service, path, interface):
            device_id = path.split("/")[4]
            if path.endswith("/battery"):
                return {"hasBattery": device_id == "aaaaaaaa11", "charge": 40, "isCharging": True}
            return devices[device_id]

        for patcher in (mock.patch.object(phone, "_cli", side_effect=cli),
                        mock.patch.object(phone.session_dbus, "properties", side_effect=properties)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_one_phone_is_chosen_and_battery_shown(self) -> None:
        self.assertIn("Pixel (phone, battery 40%, charging)", phone.list_devices({}))
        self.assertEqual(phone.ring_phone({}), "Ringing Pixel.")
        self.assertEqual(self.cli_calls[-1], ["--device", "aaaaaaaa11", "--ring"])
        phone.send_to_device({"device": "laptop", "text": "hi"})
        self.assertEqual(self.cli_calls[-1], ["--device", "bbbbbbbb22", "--share-text", "hi"])

    def test_sms_is_danger_and_checked(self) -> None:
        tool = next(tool for tool in phone.phone_tools() if tool.name == "send_sms")
        self.assertEqual(ToolRegistry([tool]).assess("send_sms", {"phone_number": "123", "message": "x"})[0], RISK_DANGER)
        with self.assertRaisesRegex(ToolFailure, "phone number"):
            phone.send_sms({"phone_number": "call me", "message": "hi"})
        phone.send_sms({"phone_number": "+1 555 0100", "message": "On my way"})
        self.assertEqual(self.cli_calls[-1][-4:], ["--send-sms", "On my way", "--destination", "+1 555 0100"])

    def test_sending_needs_exactly_one_thing_and_an_existing_file(self) -> None:
        with self.assertRaisesRegex(ToolFailure, "exactly one"):
            phone.send_to_device({})
        with self.assertRaisesRegex(ToolFailure, "does not exist"):
            phone.send_to_device({"file_or_url": "/nonexistent/file.pdf"})


class TimerDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.unit_dir = Path(self._tmp.name) / "units"
        patcher = mock.patch.object(reminders, "_location", return_value=(self.unit_dir, False))
        patcher.start()
        self.addCleanup(patcher.stop)


class ReminderTests(TimerDirTest):
    NOW = datetime.datetime(2026, 11, 23, 15, 0)

    def test_times_are_parsed_and_past_ones_refused(self) -> None:
        self.assertEqual(reminders.parse_when({"in_minutes": 10}, self.NOW), datetime.datetime(2026, 11, 23, 15, 10))
        self.assertEqual(reminders.parse_when({"at": "16:30"}, self.NOW), datetime.datetime(2026, 11, 23, 16, 30))
        self.assertEqual(reminders.parse_when({"at": "09:00"}, self.NOW), datetime.datetime(2026, 11, 24, 9, 0))
        with self.assertRaisesRegex(ToolFailure, "already passed"):
            reminders.parse_when({"at": "2026-11-01 10:00"}, self.NOW)
        with self.assertRaisesRegex(ToolFailure, "exactly one"):
            reminders.parse_when({}, self.NOW)

    def test_reminder_units_are_written_listed_and_cancelled(self) -> None:
        text = reminders.set_reminder({"text": 'Call the vet, 100% "today"', "in_minutes": 30})
        ident = text.split()[1]
        service = (self.unit_dir / f"kde-ai-assistant-reminder-{ident}.service").read_text()
        self.assertIn('"Call the vet, 100%% \\"today\\""', service)
        timer = (self.unit_dir / f"kde-ai-assistant-reminder-{ident}.timer").read_text()
        self.assertIn("Persistent=true", timer)
        self.assertIn(f"{ident}  ", reminders.list_reminders({}))
        self.assertIn('Call the vet, 100% "today"', reminders.list_reminders({}))
        self.assertIn("Cancelled", reminders.cancel_reminder({"id": ident}))
        self.assertEqual(list(self.unit_dir.iterdir()), [])
        self.assertEqual(reminders.list_reminders({}), "No reminders are set.")

    def test_passed_reminders_are_cleaned_up_and_other_units_left_alone(self) -> None:
        user_timers.write_units(self.unit_dir, "kde-ai-assistant-reminder-old", "old", ["true"], "timer", "2020-01-01 10:00:00")
        (self.unit_dir / "someone-else.timer").write_text("[Timer]\nOnCalendar=daily\n")
        self.assertEqual(reminders.list_reminders({}), "No reminders are set.")
        self.assertEqual(sorted(path.name for path in self.unit_dir.iterdir()), ["someone-else.timer"])


class RoutineTests(TimerDirTest):
    def test_routines_are_validated(self) -> None:
        good = validate_settings({"routines": {"start work": {"request": "Open Kate", "watch_folder": "~/Inbox"}}})
        entry = good["routines"]["start work"]
        self.assertEqual((entry["schedule"], entry["enabled"]), ("", True))
        self.assertTrue(entry["watch_folder"].endswith("/Inbox"))
        cases = {"names use letters": {"bad/name": {"request": "x"}}, "'request' must be text": {"a": {"request": ""}},
                 "unknown setting 'when'": {"a": {"request": "x", "when": "now"}},
                 "'watch_folder' must be empty": {"a": {"request": "x", "watch_folder": "relative"}}}
        if shutil.which("systemd-analyze"):
            cases["is not understood"] = {"a": {"request": "x", "schedule": "every blue moon"}}
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(SettingsError, message):
                validate_settings({"routines": raw})

    def test_sync_writes_one_unit_pair_per_trigger_and_removes_stale_ones(self) -> None:
        settings = validate_settings({"routines": {
            "Morning": {"request": "Summarise my calendar", "schedule": "Mon..Fri 08:00"},
            "Inbox": {"request": "Sort new files in ~/Inbox", "watch_folder": "/tmp/inbox"},
            "Manual": {"request": "Only when asked"},
            "Paused": {"request": "x", "schedule": "daily", "enabled": False},
        }})
        self.assertEqual(routines.sync(settings["routines"], self.unit_dir, manage=False), [])
        names = sorted(path.name for path in self.unit_dir.iterdir())
        self.assertEqual(len(names), 4)
        timer = next(self.unit_dir.glob("*schedule.timer")).read_text()
        self.assertIn("OnCalendar=Mon..Fri 08:00", timer)
        service = next(self.unit_dir.glob("*schedule.service")).read_text()
        self.assertIn('"ask" "--notify" "--" "Summarise my calendar"', service)
        self.assertIn("PathChanged=/tmp/inbox", next(self.unit_dir.glob("*watch.path")).read_text())
        routines.sync({}, self.unit_dir, manage=False)
        self.assertEqual(list(self.unit_dir.iterdir()), [])

    def test_prompt_lists_routines(self) -> None:
        prompt = system_prompt(None, "", [], routines={"start work": {"request": "Open Kate"}})
        self.assertIn("- start work: Open Kate", prompt)

    def test_routine_tools_change_settings_through_the_daemon_path(self) -> None:
        store = {"settings": validate_settings({})}

        def update(mutate):
            changed = dict(store["settings"], routines=dict(store["settings"]["routines"]))
            mutate(changed)
            store["settings"] = validate_settings(changed)
            return store["settings"]

        tools = {tool.name: tool for tool in routine_tools(lambda: store["settings"], update)}
        self.assertIn("Saved the routine tidy (only when asked)", tools["save_routine"].handler(
            {"name": "tidy", "request": "Sort Downloads"}))
        self.assertIn("paused", tools["save_routine"].handler({"name": "tidy", "enabled": False}))
        self.assertEqual(store["settings"]["routines"]["tidy"]["request"], "Sort Downloads")
        with self.assertRaisesRegex(ToolFailure, "'request' must be text"):
            tools["save_routine"].handler({"name": "empty"})
        self.assertEqual(tools["delete_routine"].risk, RISK_DANGER)
        tools["delete_routine"].handler({"name": "tidy"})
        self.assertEqual(tools["list_routines"].handler({}), "No routines are saved.")


class DryRunTests(unittest.TestCase):
    def test_only_tools_that_cannot_change_anything_remain(self) -> None:
        registry = ToolRegistry([
            Tool("look", "", object_schema(), RISK_READ, lambda a: ""),
            Tool("act", "", object_schema(), "change", lambda a: ""),
            Tool("maybe", "", object_schema(), RISK_READ, lambda a: "", classify=lambda a: ("danger", "")),
        ])
        self.assertEqual(registry.reads_only().names(), ["look"])


if __name__ == "__main__":
    unittest.main()

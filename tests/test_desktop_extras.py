"""Tests for weather (and its popup card), mice and touchpads, key repeat, reopening the popup, pinning,
drive-, network- and battery-triggered routines, finding windows by their content, and
opening folders and terminals.

Network, DBus, KWin, accessibility, ``nmcli``/``upower`` output and program starts are replaced by fakes,
so nothing on the desktop changes; pinned conversations and routine units
are written into temporary folders.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import desktop_actions, routine_conditions, routines, user_timers  # noqa: E402
from happy_bot.accessibility import Element, Snapshot  # noqa: E402
from happy_bot.conversation_archive import ConversationArchive  # noqa: E402
from happy_bot.conversations import Conversation, ConversationStore  # noqa: E402
from happy_bot.settings import validate_settings  # noqa: E402
from happy_bot.tools import appearance, apps, media, weather, workspace  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


class WeatherTests(unittest.TestCase):
    def test_place_is_geocoded_then_forecast_read(self) -> None:
        replies = [
            {"results": [{"name": "Paris", "country": "United States", "admin1": "Texas", "latitude": 33.6, "longitude": -95.5},
                         {"name": "Paris", "country": "France", "admin1": "Île-de-France", "latitude": 48.85, "longitude": 2.35}]},
            {"current": {"temperature_2m": 11.2, "apparent_temperature": 9.0, "weather_code": 61, "wind_speed_10m": 14.0},
             "daily": {"time": ["2026-11-24"], "temperature_2m_min": [6.0], "temperature_2m_max": [12.0],
                       "precipitation_probability_max": [70], "weather_code": [63],
                       "sunrise": ["2026-11-24T08:21"], "sunset": ["2026-11-24T17:00"]}},
        ]
        asked = []
        with mock.patch.object(weather, "_get", side_effect=lambda url, parameters: asked.append(parameters) or replies.pop(0)):
            text = weather.weather({"place": "Paris, France", "days": 1})
        self.assertEqual(asked[1]["latitude"], 48.85)
        self.assertIn("Paris, Île-de-France, France: now 11.2°C (feels 9.0°C), light rain", text)
        self.assertIn("2026-11-24: 6.0–12.0°C, rain, rain 70%, sunrise 08:21, sunset 17:00", text)
        with self.assertRaisesRegex(ToolFailure, "'days'"):
            weather.weather({"place": "Paris", "days": 30})
        card = weather.weather_card(text)
        self.assertEqual((card["place"], card["now"]["temperature"], card["now"]["conditions"]),
                         ("Paris, Île-de-France, France", "11.2", "light rain"))
        self.assertEqual(card["days"], [{"date": "2026-11-24", "low": "6.0", "high": "12.0", "conditions": "rain",
                                         "rain": "70", "sunrise": "08:21", "sunset": "17:00"}])
        self.assertIsNone(weather.weather_card("the weather service could not be reached"))

    def test_the_card_travels_with_a_successful_weather_result(self) -> None:
        from happy_bot.tools.registry import ToolRegistry

        registry = ToolRegistry(weather.weather_tools())
        text = "Oslo, Norway: now -3.0°C (feels -8.0°C), light snow, wind 20.0 km/h\n(Open-Meteo)"
        self.assertEqual(registry.card("weather", text)["now"]["feels"], "-8.0")
        self.assertIsNone(registry.card("weather", "garbled"))
        self.assertIsNone(registry.card("no_such_tool", text))


class InputTests(unittest.TestCase):
    DEVICES = {"event5": {"name": "Logitech Mouse", "pointer": True, "touchpad": False, "pointerAcceleration": 0.0,
                          "naturalScroll": False},
               "event9": {"name": "ELAN Touchpad", "pointer": True, "touchpad": True, "pointerAcceleration": 0.2,
                          "naturalScroll": True, "tapToClick": False}}

    def setUp(self) -> None:
        self.sets = []

        def properties(service, path, interface):
            if path.endswith("InputDevice"):
                return {"devicesSysNames": list(self.DEVICES)}
            return self.DEVICES[path.rsplit("/", 1)[1]]

        for patcher in (mock.patch.object(appearance.session_dbus, "properties", side_effect=properties),
                        mock.patch.object(appearance.session_dbus, "set_property",
                                          side_effect=lambda *a: self.sets.append(a[1:]))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_devices_are_listed_and_the_touchpad_changed(self) -> None:
        self.assertIn("ELAN Touchpad (touchpad): speed +0.2, natural scrolling on, tap to click off",
                      appearance.input_devices({}))
        appearance.set_input_device({"device": "touchpad", "tap_to_click": True, "pointer_speed": -0.5})
        self.assertEqual(self.sets, [("/org/kde/KWin/InputDevice/event9", "org.kde.KWin.InputDevice", "tapToClick", "b", True),
                                     ("/org/kde/KWin/InputDevice/event9", "org.kde.KWin.InputDevice", "pointerAcceleration", "d", -0.5)])
        with self.assertRaisesRegex(ToolFailure, "'pointer_speed'"):
            appearance.set_input_device({"device": "mouse", "pointer_speed": 3})

    def test_key_repeat_writes_kcminputrc_and_reloads_kwin(self) -> None:
        commands = []
        with mock.patch.object(appearance, "run_checked", side_effect=lambda command, timeout=20: commands.append(command) or ""):
            appearance.set_key_repeat({"delay_ms": 300, "rate": 30})
        self.assertEqual(commands[0][-2:], ["RepeatDelay", "300"])
        self.assertEqual(commands[1][-2:], ["RepeatRate", "30"])
        self.assertEqual(commands[2], ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])


class PopupTests(unittest.TestCase):
    def test_popup_is_opened_through_the_applets_shortcut_action(self) -> None:
        calls = []
        with mock.patch.object(desktop_actions, "_run", side_effect=lambda command: calls.append(command) or "192 "):
            desktop_actions.open_assistant_popup()
        self.assertEqual(calls[1][-1], "activate widget 192")
        with mock.patch.object(desktop_actions, "_run", return_value=""), \
                self.assertRaisesRegex(desktop_actions.DesktopActionError, "not on any panel"):
            desktop_actions.open_assistant_popup()


class PinTests(unittest.TestCase):
    def test_pinned_conversations_come_first_and_never_expire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = ConversationArchive(Path(tmp), days=30)
            store = ConversationStore(archive)
            for ident, title, updated in (("aaaaaaaaaa", "Precious", time.time() - 60), ("bbbbbbbbbb", "Recent", time.time())):
                archive.save(Conversation(id=ident, title=title, updated=updated).to_record())
            self.assertTrue(store.set_pinned("aaaaaaaaaa", True))
            self.assertEqual([item["id"] for item in store.list()], ["aaaaaaaaaa", "bbbbbbbbbb"])
            self.assertTrue(store.list()[0]["pinned"])
            forty_days_later = time.time() + 40 * 86400
            archive.prune(now=forty_days_later)
            self.assertEqual([item["id"] for item in archive.list()], ["aaaaaaaaaa"])
            store.set_pinned("aaaaaaaaaa", False)
            archive.prune(now=forty_days_later)
            self.assertEqual(archive.list(), [])
            self.assertFalse(store.set_pinned("cccccccccc", True))


class DriveRoutineTests(unittest.TestCase):
    def test_drive_label_routine_is_a_service_wanted_by_the_device(self) -> None:
        self.assertEqual(user_timers.device_unit("/dev/disk/by-label/Back-up 2"), "dev-disk-by\\x2dlabel-Back\\x2dup\\x202.device")
        settings = validate_settings({"routines": {"Backup": {"request": "Copy Documents to the backup drive",
                                                              "drive_label": "BACKUP"}}})
        with tempfile.TemporaryDirectory() as tmp:
            routines.sync(settings["routines"], Path(tmp), manage=False)
            files = list(Path(tmp).iterdir())
            self.assertEqual([path.suffix for path in files], [".service"])
            text = files[0].read_text()
            self.assertIn("WantedBy=dev-disk-by\\x2dlabel-BACKUP.device", text)
            self.assertIn("After=dev-disk-by\\x2dlabel-BACKUP.device", text)


class WindowContentTests(unittest.TestCase):
    def test_windows_are_found_by_title_or_by_what_they_show(self) -> None:
        windows = [{"id": "{a}", "app": "okular", "title": "scan.pdf", "pid": 10},
                   {"id": "{b}", "app": "kate", "title": "Invoice notes", "pid": 11}]
        snapshot = Snapshot(10, "scan.pdf", "okular", [Element("e1", "label", "Invoice #42 total", 1, True, (), (), False, "")], False)
        with mock.patch.object(workspace, "_kwin", return_value=windows), \
                mock.patch("happy_bot.accessibility.take_snapshot", return_value=snapshot):
            text = workspace.find_window_with_text({"text": "invoice"})
        self.assertIn('id {a}  okular  "scan.pdf"  (shows: Invoice #42 total)', text)
        self.assertIn('id {b}  kate  "Invoice notes"  (in its title)', text)


class FolderAndTerminalTests(unittest.TestCase):
    def test_folders_and_files_go_to_the_file_manager_and_terminals_open_in_a_folder(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("happy_bot.session_dbus.call", side_effect=lambda *a: calls.append(a)):
            Path(tmp, "a.txt").write_text("x")
            apps.open_folder({"path": tmp})
            apps.open_folder({"path": str(Path(tmp, "a.txt"))})
            self.assertEqual([call[3] for call in calls], ["ShowFolders", "ShowItems"])
            with mock.patch("happy_bot.tools.shell.terminal_program", return_value="/usr/bin/konsole"), \
                    mock.patch.object(apps.subprocess, "Popen") as popen:
                apps.open_terminal({"folder": tmp})
            self.assertEqual(popen.call_args[0][0], ["/usr/bin/konsole", "--workdir", tmp])
            kwi = "/home/u/.local/share/flatpak/exports/bin/org.kde.kwi"
            with mock.patch("happy_bot.tools.shell.terminal_program", return_value=kwi) as chosen, \
                    mock.patch.object(apps.subprocess, "Popen") as popen:
                apps.open_terminal({"folder": tmp}, "kwi")
            self.assertEqual(popen.call_args[0][0], [kwi, "--workdir", tmp])
            chosen.assert_called_once_with("kwi")             # the Behaviour setting is followed
            from happy_bot.tools import gui
            for app, terminal in (("org.kde.kwi", True), ("kwin_wayland", False), ("org.kde.kwin.killer", False),
                                  ("gnome-terminal-server", True)):
                self.assertIs(gui._is_terminal({"app": app}), terminal, app)



class DownloadTests(unittest.TestCase):
    def test_saved_files_are_reported_and_recorded_and_failures_explained(self) -> None:
        from happy_bot import undo_journal

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "yt-dlp"
            downloads = Path(tmp) / "Downloads"
            downloads.mkdir()
            fake.write_text("#!/bin/sh\nif [ \"$NO_LUCK\" = 1 ]; then echo 'ERROR: unavailable'; exit 1; fi\n"
                            f"echo '[download] 50%'\ntouch '{downloads}/Song.mp3'\necho '{downloads}/Song.mp3'\n")
            fake.chmod(0o755)
            with mock.patch.object(media.shutil, "which", return_value=str(fake)), \
                    mock.patch("happy_bot.agent_loop.user_folders", return_value={"Downloads": str(downloads)}):
                self.assertEqual(media.download_media({"url": "https://example.com/v", "audio_only": True}),
                                 f"Saved {downloads}/Song.mp3.")
                self.assertEqual(undo_journal.pending()[0]["data"], {"path": f"{downloads}/Song.mp3"})
                with mock.patch.dict("os.environ", {"NO_LUCK": "1"}), self.assertRaisesRegex(ToolFailure, "unavailable"):
                    media.download_media({"url": "https://example.com/gone"})
            with self.assertRaisesRegex(ToolFailure, "'url'"):
                media.download_media({"url": "file:///etc/passwd"})


class ConditionRoutineTests(unittest.TestCase):
    def test_a_condition_runs_the_routine_only_when_it_becomes_true(self) -> None:
        ran = []
        results = []
        with tempfile.TemporaryDirectory() as tmp:
            for value in (False, True, True, False, True):
                with mock.patch.object(routine_conditions, "holds", return_value=value):
                    results.append(routine_conditions.check("Home", "network", "Home", lambda: ran.append(1), Path(tmp)))
        self.assertEqual(results, ["not true", "ran", "still true", "not true", "ran"])
        self.assertEqual(len(ran), 2)

    def test_battery_and_network_are_read_from_upower_and_nmcli(self) -> None:
        outputs = {"nmcli": "Wired connection 1\nHome\\:Net\n", "upower -e": "/org/x/battery_BAT0\n",
                   "upower -i": "  state: discharging\n  percentage: 14%\n"}
        with mock.patch.object(routine_conditions, "_output",
                               side_effect=lambda command: next(v for k, v in outputs.items() if " ".join(command).startswith(k))):
            self.assertTrue(routine_conditions.on_network("home:net"))
            self.assertFalse(routine_conditions.on_network("Cafe"))
            self.assertTrue(routine_conditions.battery_below(20))
            self.assertFalse(routine_conditions.battery_below(10))

    def test_condition_routines_get_a_checking_timer(self) -> None:
        settings = validate_settings({"routines": {"Low": {"request": "Save my work", "battery_below": 15},
                                                   "Home": {"request": "Mount the NAS", "on_network": "Home"}}})
        with tempfile.TemporaryDirectory() as tmp:
            routines.sync(settings["routines"], Path(tmp), manage=False)
            timers = sorted(path.read_text() for path in Path(tmp).glob("*.timer"))
            services = " ".join(path.read_text() for path in Path(tmp).glob("*.service"))
        self.assertEqual(len(timers), 2)
        self.assertTrue(all("OnCalendar=*:0/2" in timer for timer in timers))
        self.assertIn('"routine-check" "--kind" "battery" "--value" "15" "--" "Low"', services)
        self.assertIn('"routine-check" "--kind" "network" "--value" "Home" "--" "Home"', services)
        from happy_bot.settings import SettingsError
        with self.assertRaisesRegex(SettingsError, "'battery_below'"):
            validate_settings({"routines": {"x": {"request": "y", "battery_below": 150}}})


if __name__ == "__main__":
    unittest.main()

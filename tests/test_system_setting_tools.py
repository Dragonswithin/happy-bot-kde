"""Tests for the power, appearance, device and default-application tools.

Every program and DBus call is replaced by a recorder, so nothing on the
machine changes: the tests check argument validation, how each tool reads
the programs' output, what it would run, and the undo entries it records.
The drive tests check the safety rule that a drive mounted by the system
(outside the desktop's media folders) is never unmounted or ejected.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import undo_journal  # noqa: E402
from happy_bot.tools import appearance, defaults, devices, power, undo  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


class Recorder:
    """Stands in for ``run_checked``: records commands and answers from a table of outputs."""

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.outputs = outputs or {}

    def __call__(self, command, timeout=20.0):
        self.commands.append(command)
        for prefix, output in self.outputs.items():
            if " ".join(command).startswith(prefix):
                return output
        return ""


def clear_journal() -> None:
    path = Path(os.environ["XDG_RUNTIME_DIR"]) / "happy-bot" / "undo.jsonl"
    if path.exists():
        path.unlink()


class PowerTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_journal()
        self.dbus_calls = []
        self.brightness = 40

        def call(service, path, interface, method, signature="", arguments=()):
            self.dbus_calls.append((method, arguments))
            if method == "brightnessMax":
                return (200,)
            if method == "brightness":
                return (self.brightness,)
            if method == "Inhibit":
                return (7,)
            return ()

        patcher = mock.patch.object(power.session_dbus, "call", side_effect=call)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_brightness_is_in_percent_and_undoable(self) -> None:
        self.assertEqual(power.get_brightness({}), "Screen brightness 20%.")
        power.set_brightness({"percent": 75})
        self.assertIn(("setBrightness", (150,)), self.dbus_calls)
        self.assertEqual(undo_journal.pending()[0]["data"], {"percent": 20})
        with self.assertRaisesRegex(ToolFailure, "from 1 to 100"):
            power.set_brightness({"percent": 0})

    def test_do_not_disturb_holds_and_releases_the_inhibition(self) -> None:
        self.assertIn("30 minutes", power.do_not_disturb({"minutes": 30}))
        self.assertEqual(power._dnd["cookie"], 7)
        self.assertIn("off", power.do_not_disturb({"minutes": 0}))
        self.assertIn(("UnInhibit", (7,)), self.dbus_calls)
        self.assertIsNone(power._dnd["timer"])
        with self.assertRaisesRegex(ToolFailure, "'minutes'"):
            power.do_not_disturb({"minutes": 5000})

    def test_power_profile_and_battery(self) -> None:
        recorder = Recorder({"powerprofilesctl get": "balanced", "powerprofilesctl list": "  performance:\n* balanced:\n  power-saver:\n",
                             "upower -e": "/org/freedesktop/UPower/devices/battery_BAT0",
                             "upower -i": "  model: 5B10\n  state: discharging\n  percentage: 64%\n  capacity: 91%\n  time to empty: 3.2 hours"})
        with mock.patch.object(power, "run_checked", recorder):
            self.assertIn("Available: performance, balanced, power-saver", power.get_power_profile({}))
            power.set_power_profile({"profile": "power-saver"})
            self.assertEqual(undo_journal.pending()[0]["data"], {"profile": "balanced"})
            self.assertEqual(power.battery_status({}), "5B10: 64%, discharging, health 91%, 3.2 hours left")
        with self.assertRaisesRegex(ToolFailure, "'profile'"):
            power.set_power_profile({"profile": "turbo"})


class AppearanceTests(unittest.TestCase):
    CURSORS = (" * Breeze Dark [breeze_cursors] (Current theme for this Plasma session)\n"
               " * Capitaine Cursors [capitaine-cursors]\n")

    def setUp(self) -> None:
        clear_journal()

    def test_theme_lists_are_read_and_switching_is_undoable(self) -> None:
        recorder = Recorder({"plasma-apply-cursortheme --list-themes": self.CURSORS,
                             "plasma-apply-desktoptheme --list-themes": " * default (current theme for this Plasma session)\n * breeze-dark\n"})
        with mock.patch.object(appearance, "run_checked", recorder):
            self.assertIn("Breeze Dark (current), Capitaine Cursors", appearance.list_themes({}))
            appearance.set_theme({"kind": "cursor", "name": "capitaine cursors"})
            self.assertEqual(recorder.commands[-1], ["plasma-apply-cursortheme", "capitaine-cursors"])
            with self.assertRaisesRegex(ToolFailure, "no plasma theme"):
                appearance.set_theme({"kind": "plasma", "name": "neon"})
        undo_commands = []
        with mock.patch.object(undo, "_run", side_effect=lambda command, timeout=30.0: undo_commands.append(command)):
            undo.undo_change({})
        self.assertEqual(undo_commands, [["plasma-apply-cursortheme", "breeze_cursors"]])

    def test_wallpaper_needs_an_existing_image(self) -> None:
        with self.assertRaisesRegex(ToolFailure, "not an image file"):
            appearance.set_wallpaper({"image": "/nonexistent.png"})
        with self.assertRaisesRegex(ToolFailure, "'color'"):
            appearance.set_accent_color({"color": "rgb(1,2,3); rm"})

    def test_keyboard_layout_is_chosen_from_the_configured_ones(self) -> None:
        calls = []

        def call(service, path, interface, method, signature="", arguments=()):
            calls.append((method, arguments))
            return ([("us", "", "English (US)"), ("de", "", "German")],) if method == "getLayoutsList" else (0,)

        with mock.patch.object(appearance.session_dbus, "call", side_effect=call):
            self.assertIn("German [de]", appearance.keyboard_layouts({}))
            self.assertEqual(appearance.set_keyboard_layout({"layout": "german"}), "Keyboard layout switched to German.")
            self.assertIn(("setLayout", (1,)), calls)
            with self.assertRaisesRegex(ToolFailure, "not one of the configured layouts"):
                appearance.set_keyboard_layout({"layout": "fr"})


class DriveTests(unittest.TestCase):
    LSBLK = json.dumps({"blockdevices": [
        {"name": "sda", "path": "/dev/sda", "tran": "usb", "rm": False, "hotplug": True, "type": "disk", "size": "7T",
         "mountpoints": [None], "children": [
             {"name": "sda1", "path": "/dev/sda1", "label": "data", "rm": False, "hotplug": True, "type": "part",
              "fstype": "btrfs", "size": "7T", "mountpoints": ["/srv/data"]}]},
        {"name": "sdb", "path": "/dev/sdb", "tran": "usb", "rm": True, "hotplug": True, "type": "disk", "size": "32G",
         "mountpoints": [None], "children": [
             {"name": "sdb1", "path": "/dev/sdb1", "label": "STICK", "rm": True, "hotplug": True, "type": "part",
              "fstype": "vfat", "size": "32G", "mountpoints": ["/run/media/alice/STICK"]}]},
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "tran": "nvme", "rm": False, "hotplug": False, "type": "disk",
         "size": "2T", "mountpoints": [None], "children": [
             {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "type": "part", "fstype": "btrfs", "size": "2T",
              "mountpoints": ["/"]}]},
    ]})

    def test_system_mounted_and_internal_drives_are_refused_and_media_ejected(self) -> None:
        recorder = Recorder({"lsblk": self.LSBLK})
        with mock.patch.object(devices, "run_checked", recorder):
            with self.assertRaisesRegex(ToolFailure, "part of the system's setup .*/srv/data"):
                devices.drive_action({"action": "eject", "drive": "/dev/sda1"})
            with self.assertRaisesRegex(ToolFailure, "internal drive"):
                devices.drive_action({"action": "unmount", "drive": "/dev/nvme0n1p2"})
            self.assertEqual({command[0] for command in recorder.commands}, {"lsblk"})  # nothing was run
            self.assertIn("can be unplugged", devices.drive_action({"action": "eject", "drive": "STICK"}))
        self.assertEqual(recorder.commands[-2:], [["udisksctl", "unmount", "-b", "/dev/sdb1"],
                                                   ["udisksctl", "power-off", "-b", "/dev/sdb"]])

    def test_temperatures_are_summarised(self) -> None:
        sensors = json.dumps({"k10temp-pci-00c3": {"Adapter": "PCI", "Tctl": {"temp1_input": 61.5}},
                              "nvme-pci-0100": {"Composite": {"temp1_input": 40.0, "temp1_max": 80.0}}})
        with mock.patch.object(devices, "run_checked", Recorder({"sensors": sensors})):
            self.assertEqual(devices.temperatures({}), "k10temp: Tctl 62°C\nnvme: Composite 40°C")


class DefaultsTests(unittest.TestCase):
    APPS = [{"id": "firefox.desktop", "name": "Firefox", "generic": "Web Browser", "keywords": "", "comment": "",
             "path": "/usr/share/applications/firefox.desktop"}]

    def test_default_application_uses_mime_types(self) -> None:
        recorder = Recorder()
        with mock.patch.object(defaults, "run_checked", recorder), \
                mock.patch.object(defaults, "installed_applications", return_value=self.APPS):
            self.assertEqual(defaults.set_default_application({"kind": "browser", "application": "firefox"}),
                             "Firefox now opens browser.")
        self.assertEqual(recorder.commands[0][:3], ["xdg-mime", "default", "firefox.desktop"])
        self.assertIn("x-scheme-handler/https", recorder.commands[0])
        with self.assertRaisesRegex(ToolFailure, "'kind'"):
            defaults.set_default_application({"kind": "spaceships", "application": "firefox"})

    def test_autostart_entries_are_added_listed_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            source = Path(tmp) / "firefox.desktop"
            source.write_text("[Desktop Entry]\nName=Firefox\nExec=firefox\n")
            apps = [dict(self.APPS[0], path=str(source))]
            with mock.patch.object(defaults, "installed_applications", return_value=apps):
                self.assertIn("will start at login", defaults.add_autostart({"application": "Firefox"}))
            self.assertIn("Firefox [firefox.desktop]", defaults.list_autostart({}))
            recorder = Recorder()
            with mock.patch.object(defaults, "run_checked", recorder):
                defaults.remove_autostart({"entry": "firefox"})
            self.assertEqual(recorder.commands[0][:3], ["gio", "trash", "--"])


if __name__ == "__main__":
    unittest.main()

"""Exercise nudge conditions and shared dismissal without changing the desktop."""
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from happy_bot import mascot_nudges as nudges
from happy_bot.icon_activity import IconActivity
from happy_bot.system_monitor import batteries


class NudgeTests(unittest.TestCase):
    def test_dismissal_survives_other_activity_and_unknown_readings_until_recovery(self):
        state = IconActivity()
        state.observe_nudges(updates=True, disk=True, battery=True, restart=True)
        self.assertEqual(state.wait("")["nudges"], ["battery", "disk", "restart", "updates"])
        self.assertTrue(state.dismiss_nudge("battery"))
        dismissed = state.wait("")
        self.assertEqual(dismissed["nudges"], ["disk", "restart", "updates"])
        self.assertTrue(state.dismiss_nudge("battery"))
        self.assertFalse(state.dismiss_nudge("other"))
        self.assertEqual(state.wait("")["revision"], dismissed["revision"])
        state.set_recording(True)
        state.observe_nudges(battery=None, disk=False, restart=True, updates=True)
        state.observe_nudges(battery=True)
        self.assertEqual(state.wait("")["nudges"], [])
        state.observe_nudges(battery=False)
        state.observe_nudges(battery=True)
        self.assertEqual(state.wait("")["nudges"], ["battery"])

    def test_battery_excludes_charging_removed_and_peripheral_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            supplies = root / "class/power_supply"
            laptop = supplies / "CMB0"
            laptop.mkdir(parents=True)
            (laptop / "type").write_text("Battery")
            (laptop / "capacity").write_text("20")
            (laptop / "status").write_text("Discharging")
            with patch.object(nudges, "batteries", lambda: batteries(root)):
                self.assertIs(nudges.low_battery(), True)
                (laptop / "capacity").write_text("unknown")
                self.assertIsNone(nudges.low_battery())
                (laptop / "capacity").write_text("18")
                (laptop / "status").write_text("Charging")
                self.assertIs(nudges.low_battery(), False)
                (laptop / "status").write_text("Discharging")
                (laptop / "present").write_text("0")
                self.assertIs(nudges.low_battery(), False)
                (laptop / "present").write_text("1")
                (laptop / "scope").write_text("Device")
                self.assertIs(nudges.low_battery(), False)

    def test_fullness_requires_low_percent_and_little_space_on_either_volume(self):
        large = SimpleNamespace(total=1000 * 1024**3, free=25 * 1024**3)
        small = SimpleNamespace(total=4 * 1024**3, free=1 * 1024**3)
        near_full = SimpleNamespace(total=50 * 1024**3, free=2 * 1024**3)
        with patch.object(nudges.shutil, "disk_usage", side_effect=[large, small]):
            self.assertIs(nudges.low_disk(), False)
        with patch.object(nudges.shutil, "disk_usage", side_effect=[OSError(), near_full]):
            self.assertIs(nudges.low_disk(), True)
        with patch.object(nudges.shutil, "disk_usage", side_effect=[large, OSError()]):
            self.assertIsNone(nudges.low_disk())

    def test_only_cached_package_metadata_is_queried(self):
        cases = (
            ("pacman", ["pacman", "-Quq"], 1, "", False),
            ("pacman", ["pacman", "-Quq"], 1, "error", None),
            ("pacman", ["pacman", "-Quq"], 0, "kernel", True),
            ("apt", ["apt", "list", "--upgradable"], 0, "Listing...", False),
            ("apt", ["apt", "list", "--upgradable"], 0, "Listing...\nbash/stable 5.2 [upgradable from: 5]", True),
            ("dnf", ["dnf", "--cacheonly", "--noplugins", "check-update"], 100, "", True),
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CHECKUPDATES_DB": tmp}):
            for mgr, query, code, output, expected in cases:
                with self.subTest(mgr=mgr, output=output), \
                        patch.object(nudges.shutil, "which", side_effect=lambda cmd: cmd if cmd == mgr else None), \
                        patch.object(nudges.subprocess, "run", return_value=subprocess.CompletedProcess(
                            query, code, "" if output == "error" else output, "failed" if output == "error" else "")) as run:
                    self.assertIs(nudges.cached_updates(), expected)
                    self.assertEqual(run.call_args.args[0], query)

    def test_package_check_cadence_and_disabled_sampler(self):
        enabled = False
        source = nudges.NudgeReadings(lambda: enabled)
        with patch.object(nudges, "cached_updates", side_effect=[True, None, False]) as packages, \
                patch.object(nudges, "low_battery", return_value=False) as battery, \
                patch.object(nudges, "low_disk", return_value=False), patch.object(nudges, "pending_reboot", return_value=""), \
                patch.object(nudges.time, "monotonic", side_effect=[10, 70, 10 + nudges.UPDATE_SECONDS, 1000]):
            self.assertEqual(source.snapshot(), {})
            packages.assert_not_called()
            battery.assert_not_called()
            enabled = True
            self.assertIs(source.snapshot()["updates"], True)
            self.assertIs(source.snapshot()["updates"], True)
            self.assertIsNone(source.snapshot()["updates"])
            enabled = False
            self.assertEqual(source.snapshot(), {})
            enabled = True
            self.assertIs(source.snapshot()["updates"], False)
            self.assertEqual(packages.call_count, 3)

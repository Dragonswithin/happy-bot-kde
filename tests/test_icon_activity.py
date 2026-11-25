"""Sensor dwell times and delivery of short microphone captures to both views."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from happy_bot.icon_activity import IconActivity


class IconActivityTests(unittest.TestCase):
    def setUp(self):
        self.activity = IconActivity()

    def sample(self, at, cpu=95, high=90, down=300000, up=0):
        with patch("happy_bot.icon_activity.time.monotonic", return_value=at):
            self.activity.observe_sensors(cpu_c=cpu, high_c=high, receive_bytes_per_second=down,
                                          send_bytes_per_second=up)
        return self.activity.wait("")

    def test_heat_dwell_and_recovery(self):
        self.sample(0)
        self.assertFalse(self.sample(9)["hot"])
        self.sample(10, cpu=89)
        self.sample(11)
        self.assertTrue(self.sample(21)["hot"])
        self.sample(22, cpu=85)
        self.assertTrue(self.sample(41, cpu=85)["hot"])
        self.assertFalse(self.sample(42, cpu=85)["hot"])

    def test_transfer_directions_and_missing_sensor(self):
        self.sample(0, up=300000)
        self.assertFalse(self.sample(2, up=300000)["downloading"])
        both = self.sample(3, up=300000)
        self.assertTrue(both["downloading"] and both["uploading"])
        self.sample(4)
        self.assertFalse(self.sample(9)["uploading"])
        self.assertTrue(self.sample(10)["hot"])
        missing = self.sample(11, high=None, down=None)
        self.assertFalse(missing["hot"] or missing["downloading"])

    def test_both_views_wake_on_record_and_stop(self):
        state = self.activity.wait("")
        with ThreadPoolExecutor(max_workers=2) as workers:
            for recording in (True, False):
                waits = [workers.submit(self.activity.wait, state["revision"], 1) for _ in range(2)]
                self.activity.set_recording(recording)
                state, other = (wait.result() for wait in waits)
                self.assertEqual(state, other)
                self.assertIs(state["recording"], recording)

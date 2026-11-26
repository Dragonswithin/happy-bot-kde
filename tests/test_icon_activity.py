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

    def sample(self, at, cpu=95, high=90, down=300000, up=0, **memory_and_load):
        with patch("happy_bot.icon_activity.time.monotonic", return_value=at):
            self.activity.observe_sensors(cpu_c=cpu, high_c=high, receive_bytes_per_second=down,
                                          send_bytes_per_second=up, **memory_and_load)
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

    def test_memory_requires_pressure_and_cpu_load_recovers_separately(self):
        low = dict(available_memory_percent=8, memory_pressure=False, cpu_percent=90)
        self.sample(0, **low)
        state = self.sample(20, **low)
        self.assertFalse(state["low_memory"])
        self.assertTrue(state["busy"])
        low.update(memory_pressure=True, cpu_percent=60)
        self.sample(21, **low)
        self.assertFalse(self.sample(29, **low)["busy"])
        self.assertTrue(self.sample(36, **low)["low_memory"])
        low.update(memory_pressure=False)
        self.assertTrue(self.sample(37, **low)["low_memory"])
        self.assertFalse(self.sample(57, **low)["low_memory"])

    def test_both_views_wake_on_record_and_stop(self):
        state = self.activity.wait("")
        with ThreadPoolExecutor(max_workers=2) as workers:
            for recording in (True, False):
                waits = [workers.submit(self.activity.wait, state["revision"], 1) for _ in range(2)]
                self.activity.set_recording(recording)
                state, other = (wait.result() for wait in waits)
                self.assertEqual(state, other)
                self.assertIs(state["recording"], recording)

    def test_nudge_sound_requires_a_new_known_condition(self):
        observe = self.activity.observe_nudges
        self.assertFalse(observe(battery=True, disk=False))  # first sample sets the baseline
        self.assertTrue(observe(battery=True, disk=True))
        self.activity.dismiss_nudge("disk")
        self.assertFalse(observe(disk=None))
        self.assertFalse(observe(disk=True))  # unknown readings and reconnected views cannot rearm it
        self.assertNotIn("disk", self.activity.wait("")["nudges"])
        self.assertFalse(observe(battery=False, disk=False))
        self.assertTrue(observe(battery=True, disk=True))  # one callback covers both
        self.assertFalse(observe(battery=True, disk=True))
        self.assertFalse(observe(disk=False))
        self.assertFalse(observe())  # nudges disabled
        self.assertFalse(observe(disk=True))

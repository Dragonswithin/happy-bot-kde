"""Tests for the mascot's live readings (``system_sensors``) and, through them, its poses.

A synthetic machine (``FakeMachine``) is a temporary ``/proc`` and ``/sys`` tree with two clocks
(monotonic and boot time) that the tests advance by hand; it is rewritten before each tick.
Unit tests cover each reading and its edge cases (sensor discovery, PSI, counter resets,
interface changes, suspend). The acceptance tests feed ``SystemReadings.snapshot`` into a real
``IconActivity`` once per synthetic second, its clock patched to the same time, and check that
heat, sustained CPU load, memory pressure, download and upload each raise their pose and clear
again. Nothing on the real machine is read.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from happy_bot import system_sensors  # noqa: E402
from happy_bot.icon_activity import IconActivity  # noqa: E402
from happy_bot.system_sensors import SensorSampler, SystemReadings  # noqa: E402

ROUTE = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n{lines}"


class FakeMachine:
    """A /proc and /sys tree and two clocks; ``tick`` writes one second's state."""

    def __init__(self, root: Path) -> None:
        self.proc, self.sys = root / "proc", root / "sys"
        self.mono = self.boot = 1000.0
        self.idle = self.busy = 0
        self.rx = self.tx = 0
        self.interface = "wlan0"
        self.temperature, self.high = 60.0, 100.0
        self.write("proc/pressure/memory", "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
        self.meminfo(available=50)
        hwmon = "sys/class/hwmon/hwmon3"
        self.write(f"{hwmon}/name", "k10temp\n")
        self.write(f"{hwmon}/temp1_label", "Tctl\n")
        self.write(f"{hwmon}/temp1_max", f"{int(self.high * 1000)}\n")
        self.readings = SystemReadings(self.proc, self.sys, lambda: self.mono, lambda: self.boot)

    def write(self, relative: str, text: str) -> None:
        path = self.proc.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def meminfo(self, available: float) -> None:
        self.write("proc/meminfo", f"MemTotal:       1000000 kB\nMemFree: 1 kB\nMemAvailable:   {int(available * 10000)} kB\n")

    def pressure(self, avg10: float) -> None:
        self.write("proc/pressure/memory", f"some avg10={avg10:.2f} avg60=0.00 avg300=0.00 total=1\n"
                                           "full avg10=0.00 avg60=0.00 avg300=0.00 total=1\n")

    def tick(self, seconds: float = 1.0, busy_percent: float = 5, down: int = 0, up: int = 0,
             suspended: float = 0.0) -> dict:
        self.mono += seconds
        self.boot += seconds + suspended
        busy = int(100 * busy_percent * seconds)          # jiffies, running totals like /proc/stat
        self.busy += busy
        self.idle += int(10000 * seconds) - busy
        self.write("proc/stat", f"cpu  {self.busy} 0 0 {self.idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")
        self.rx += int(down * seconds)
        self.tx += int(up * seconds)
        self.write("proc/net/route", ROUTE.format(lines=f"{self.interface}\t00000000\t0102A8C0\t0003\t0\t0\t600\t00000000\n"))
        self.write(f"sys/class/net/{self.interface}/statistics/rx_bytes", f"{self.rx}\n")
        self.write(f"sys/class/net/{self.interface}/statistics/tx_bytes", f"{self.tx}\n")
        self.write("sys/class/hwmon/hwmon3/temp1_input", f"{int(self.temperature * 1000)}\n")
        return self.readings.snapshot()


class ReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.machine = FakeMachine(self.root)

    def test_a_complete_snapshot_with_no_baseline_first(self) -> None:
        first = self.machine.tick()
        self.assertEqual(set(first), {"cpu_c", "high_c", "cpu_percent", "available_memory_percent", "memory_pressure",
                                      "receive_bytes_per_second", "send_bytes_per_second"})
        self.assertEqual((first["cpu_c"], first["high_c"]), (60.0, 100.0))
        self.assertIsNone(first["cpu_percent"])
        self.assertIsNone(first["receive_bytes_per_second"])
        second = self.machine.tick(seconds=2, busy_percent=40, down=1000, up=500)
        self.assertAlmostEqual(second["cpu_percent"], 40.0)
        self.assertEqual((second["receive_bytes_per_second"], second["send_bytes_per_second"]), (1000, 500))
        self.assertEqual((second["available_memory_percent"], second["memory_pressure"]), (50.0, False))

    def test_rate_baselines_restart_on_interface_change_counter_reset_and_resume(self) -> None:
        self.machine.tick()
        self.assertEqual(self.machine.tick(down=2000)["receive_bytes_per_second"], 2000)
        self.machine.interface = "enp1s0"
        self.assertIsNone(self.machine.tick(down=2000)["receive_bytes_per_second"])      # new interface
        self.assertEqual(self.machine.tick(down=2000)["receive_bytes_per_second"], 2000)
        self.machine.rx = 0
        self.assertIsNone(self.machine.tick(down=2000)["receive_bytes_per_second"])      # counter went back
        self.assertIsNone(self.machine.tick(down=2000, suspended=600)["receive_bytes_per_second"])  # resumed
        self.assertEqual(self.machine.tick(down=2000)["send_bytes_per_second"], 0)
        self.machine.write("proc/net/route", ROUTE.format(lines=""))
        self.assertIsNone(self.machine.readings.snapshot()["receive_bytes_per_second"])  # no default route

    def test_memory_pressure_threshold_and_missing_psi(self) -> None:
        self.assertIs(system_sensors.memory_pressure("some avg10=12.50 avg60=1 avg300=0 total=9"), True)
        self.assertIs(system_sensors.memory_pressure("some avg10=9.99 avg60=1 avg300=0 total=9"), False)
        self.assertIsNone(system_sensors.memory_pressure(None))
        self.assertIsNone(system_sensors.memory_pressure("garbage"))
        (self.machine.proc / "pressure" / "memory").unlink()
        self.assertIsNone(self.machine.tick()["memory_pressure"])

    def test_cpu_sensor_discovery_prefers_one_with_its_own_threshold(self) -> None:
        sys_root = self.root / "other"
        def device(index: int, driver: str, channels: dict[str, dict[str, str]]) -> None:
            folder = sys_root / "class" / "hwmon" / f"hwmon{index}"
            folder.mkdir(parents=True)
            (folder / "name").write_text(driver)
            for prefix, files in channels.items():
                for suffix, value in files.items():
                    (folder / f"{prefix}_{suffix}").write_text(value)
        device(1, "nvme", {"temp1": {"input": "40000", "label": "Composite", "max": "80000"}})
        device(2, "k10temp", {"temp1": {"input": "59000", "label": "Tctl"}})
        device(3, "cros_ec", {"temp4": {"input": "61000", "label": "cpu@4c", "max": "108000", "crit": "110000"},
                              "temp1": {"input": "30000", "label": "mainboard_power", "max": "90000"}})
        found = system_sensors.find_cpu_temperature(sys_root)
        self.assertEqual((found.reading.name, found.threshold.name, found.name), ("temp4_input", "temp4_max", "cros_ec cpu@4c"))
        (sys_root / "class" / "hwmon" / "hwmon3").rename(sys_root / "gone")
        alone = system_sensors.find_cpu_temperature(sys_root)
        self.assertEqual((alone.name, alone.threshold), ("k10temp Tctl", None))            # never borrows a threshold
        readings = SystemReadings(self.machine.proc, sys_root)
        self.assertEqual((readings.snapshot()["cpu_c"], readings.snapshot()["high_c"]), (59.0, None))

    def test_thermal_zone_fallback_and_no_sensor(self) -> None:
        empty = self.root / "empty"
        self.assertIsNone(system_sensors.find_cpu_temperature(empty))
        zone = empty / "class" / "thermal" / "thermal_zone0"
        zone.mkdir(parents=True)
        for name, value in (("type", "x86_pkg_temp"), ("temp", "55000"), ("trip_point_0_type", "passive"),
                            ("trip_point_0_temp", "95000"), ("trip_point_1_type", "critical"), ("trip_point_1_temp", "105000")):
            (zone / name).write_text(value)
        found = system_sensors.find_cpu_temperature(empty)
        self.assertEqual((found.reading.name, found.threshold.name), ("temp", "trip_point_0_temp"))

    def test_ipv6_default_route_when_there_is_no_ipv4_one(self) -> None:
        ipv6 = "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe80000000000000 00000400 00000001 00000000 00000003 wlp2s0\n"
        self.assertEqual(system_sensors.default_interface(ROUTE.format(lines=""), ipv6), "wlp2s0")


class SamplerTests(unittest.TestCase):
    def test_one_complete_snapshot_per_tick_until_stopped(self) -> None:
        seen: list[dict] = []
        ticked = threading.Event()

        class Readings:
            def snapshot(self):
                return {"cpu_c": None, "high_c": None, "cpu_percent": None, "available_memory_percent": None,
                        "memory_pressure": None, "receive_bytes_per_second": None, "send_bytes_per_second": None}

        def observe(**snapshot):
            seen.append(snapshot)
            if len(seen) >= 3:
                ticked.set()

        sampler = SensorSampler(observe, Readings(), interval=0.02)
        sampler.start()
        self.assertTrue(ticked.wait(2))
        sampler.stop()
        count = len(seen)
        threading.Event().wait(0.1)
        self.assertEqual(len(seen), count)                     # stopped
        self.assertEqual(len(seen[0]), 7)


class PoseAcceptanceTests(unittest.TestCase):
    """Synthetic readings through the real IconActivity: each pose comes and goes."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.machine = FakeMachine(Path(folder.name))
        self.activity = IconActivity()

    def run_for(self, seconds: int, **tick) -> dict:
        for _ in range(seconds):
            snapshot = self.machine.tick(**tick)
            with mock.patch("happy_bot.icon_activity.time.monotonic", return_value=self.machine.mono):
                self.activity.observe_sensors(**snapshot)
        return self.activity.wait("", timeout=0)

    def test_heat(self) -> None:
        self.machine.temperature = 101
        self.assertFalse(self.run_for(5)["hot"])
        self.assertTrue(self.run_for(10)["hot"])
        self.machine.temperature = 90
        self.assertTrue(self.run_for(15)["hot"])
        self.assertFalse(self.run_for(10)["hot"])

    def test_sustained_cpu_load(self) -> None:
        self.assertFalse(self.run_for(5, busy_percent=95)["busy"])
        self.assertTrue(self.run_for(10, busy_percent=95)["busy"])
        self.assertFalse(self.run_for(12, busy_percent=20)["busy"])

    def test_memory_pressure(self) -> None:
        self.machine.meminfo(available=5)
        self.assertFalse(self.run_for(20)["low_memory"])           # little free memory, but nothing stalls
        self.machine.pressure(35.0)
        self.assertTrue(self.run_for(20)["low_memory"])
        self.machine.pressure(0.0)
        self.assertFalse(self.run_for(25)["low_memory"])

    def test_download_upload_and_recovery(self) -> None:
        state = self.run_for(6, down=2_000_000)
        self.assertTrue(state["downloading"] and not state["uploading"])
        state = self.run_for(6, up=1_000_000)
        self.assertTrue(state["uploading"])
        state = self.run_for(8)
        self.assertFalse(state["downloading"] or state["uploading"])


if __name__ == "__main__":
    unittest.main()

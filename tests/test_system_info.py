"""Tests for System info (``system_monitor``, ``system_routes``) and the start screen's buttons setting.

Programs are read from a fake ``/proc`` tree built here, so the CPU shares are exact and nothing is
stopped for real (``os.kill`` is recorded). The overview runs against this computer's own ``/proc``
and ``/sys``, checking only its shape, since the numbers change.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import system_monitor, system_routes, ui_settings  # noqa: E402

ME = os.getuid()


def fake_process(proc: Path, pid: int, name: str, ticks: int, pages: int, uid: int = ME, cmdline: str = "") -> None:
    entry = proc / str(pid)
    entry.mkdir(parents=True, exist_ok=True)
    fields = ["S"] + ["0"] * 10 + [str(ticks), "0"] + ["0"] * 10  # utime is the 12th after the state
    (entry / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
    (entry / "statm").write_text(f"100 {pages} 0 0 0 0 0")
    (entry / "status").write_text(f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    (entry / "cmdline").write_text(cmdline.replace(" ", "\0"))


class ProgramTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proc = Path(tmp.name)
        fake_process(self.proc, 100, "firefox", 1000, 50_000, cmdline="/usr/lib/firefox/firefox -contentproc")
        fake_process(self.proc, 200, "java", 500, 900_000, uid=ME + 1)
        fake_process(self.proc, 300, "plasmashell", 10, 40_000)

    def test_cpu_share_is_measured_between_looks_and_memory_sorts_too(self) -> None:
        programs = system_monitor.Programs(self.proc)
        first = programs.top()
        self.assertTrue(all(item["cpu_percent"] == 0.0 for item in first))  # no earlier look yet
        fake_process(self.proc, 100, "firefox", 1000 + programs._ticks, 50_000,
                     cmdline="/usr/lib/firefox/firefox -contentproc")  # one second of one core
        with mock.patch.object(system_monitor.os, "cpu_count", return_value=4), \
                mock.patch.object(system_monitor.time, "monotonic", side_effect=[programs._previous_time + 1.0]):
            top = programs.top()
        self.assertEqual((top[0]["name"], top[0]["cpu_percent"], top[0]["mine"]), ("firefox", 25.0, True))
        by_memory = programs.top("memory")
        self.assertEqual(by_memory[0]["name"], "java")
        self.assertFalse(by_memory[0]["mine"])
        self.assertTrue(next(item for item in by_memory if item["name"] == "plasmashell")["protected"])

    def test_only_the_users_own_ordinary_programs_are_stopped(self) -> None:
        with mock.patch.object(system_monitor.os, "kill") as kill:
            self.assertEqual(system_monitor.stop(100, self.proc), "Asked firefox to quit.")
            kill.assert_called_once_with(100, signal.SIGTERM)
            for pid, reason in ((200, "another user"), (300, "keeps the desktop"), (999, "no longer running")):
                with self.subTest(pid=pid), self.assertRaisesRegex(system_monitor.StopError, reason):
                    system_monitor.stop(pid, self.proc)
            self.assertEqual(kill.call_count, 1)


class OverviewTests(unittest.TestCase):
    def test_hardware_history_measures_disk_bytes_per_second(self) -> None:
        history = system_monitor.History(size=3)
        with mock.patch.object(system_monitor.time, "monotonic", side_effect=[10, 12, 13]):
            history.hardware([{"id": "gpu", "busy_percent": 20}], {"/dev/sda": 1024})
            sample = history.hardware([{"id": "gpu", "busy_percent": 45}], {"/dev/sda": 3072})
            self.assertEqual(sample["gpu"], {"gpu": [20, 45]})
            self.assertEqual(sample["disk"], [None, 1024])
            self.assertEqual(sample["disk_by_device"]["/dev/sda"], [None, 1024])
            history.clear()
            self.assertEqual(history.hardware([], {"/dev/sda": 4096})["disk"], [None])

    def test_history_keeps_the_last_samples_and_the_overview_has_every_part(self) -> None:
        history = system_monitor.History(size=3)
        for load in (10, 20, 30, 40):
            history.add({"cpu_percent": load, "available_memory_percent": 75, "receive_bytes_per_second": 5})
        self.assertEqual([sample["cpu_percent"] for sample in history.samples()], [20, 30, 40])
        overview = system_monitor.overview(history)
        self.assertEqual(set(overview), {"cpu", "memory", "os", "gpus", "disks", "network", "battery", "uptime_seconds", "history"})
        self.assertEqual((overview["cpu"]["percent"], overview["history"]["memory"]), (40, [25, 25, 25]))
        history.clear()
        self.assertEqual(history.samples(), [])
        history.add({"cpu_percent": 11})
        self.assertEqual([sample["cpu_percent"] for sample in history.samples()], [11])
        self.assertGreater(overview["memory"]["total"], 0)
        self.assertTrue(overview["os"]["name"])
        self.assertTrue(overview["os"]["kernel"])


class RouteTests(unittest.TestCase):
    def test_stop_route_checks_the_pid_reports_refusals_and_logs_stops(self) -> None:
        with tempfile.TemporaryDirectory() as runtime:
            class Server:
                runtime_dir = Path(runtime)

            self.assertEqual(system_routes.stop(Server(), {}, {"pid": "12"})[0], 400)
            self.assertEqual(system_routes.stop(Server(), {}, {"pid": 1})[0], 400)
            with mock.patch.object(system_monitor, "stop", side_effect=system_monitor.StopError("another user")):
                self.assertEqual(system_routes.stop(Server(), {}, {"pid": 4321})[0], 409)
            with mock.patch.object(system_monitor, "stop", return_value="Asked kate to quit."):
                self.assertEqual(system_routes.stop(Server(), {}, {"pid": 4321})[1]["message"], "Asked kate to quit.")
            logged = json.loads((Path(runtime) / "actions.jsonl").read_text().splitlines()[0])
            self.assertEqual((logged["tool"], json.loads(logged["arguments"])), ("stop_program", {"pid": 4321}))


class StartScreenSettingTests(unittest.TestCase):
    def test_buttons_default_to_the_three_and_system_info_is_opt_in(self) -> None:
        self.assertEqual(ui_settings.validate_ui({})["start_screen"], ["files", "web", "help"])
        self.assertEqual(ui_settings.validate_ui({"start_screen": ["system", "files"]})["start_screen"], ["system", "files"])
        self.assertEqual(ui_settings.validate_ui({"start_screen": []})["start_screen"], [])
        for bad in (["weather"], ["files", "files"], "files", None):
            with self.subTest(bad=bad), self.assertRaises(ui_settings.UiSettingsError):
                ui_settings.validate_ui({"start_screen": bad})


if __name__ == "__main__":
    unittest.main()

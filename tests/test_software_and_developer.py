"""Tests for the software, power-user and screen tools.

Programs are replaced by recorders or fed canned output, so nothing is
searched, started or stopped for real; the pacman log is a temporary file.
The checks cover how each tool reads its program's output, the arguments it
refuses, and that stopping a program is classed as needing approval.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.tools import developer, screen, software  # noqa: E402
from happy_bot.tools.registry import RISK_DANGER, ToolFailure, ToolRegistry  # noqa: E402


def result(stdout: str = "", ok: bool = True) -> dict:
    return {"ok": ok, "stdout": stdout, "stderr": "", "returncode": 0 if ok else 1}


class UpdateCheckTests(unittest.TestCase):
    def check(self, replies: dict[str, dict], reboot: str = "", programs=("checkupdates", "yay", "flatpak")) -> str:
        def fake_run(command, timeout=5.0):
            return replies[command[0]]
        with mock.patch.object(software.shutil, "which", side_effect=lambda name: name if name in programs else None), \
                mock.patch.object(software, "run_command", side_effect=fake_run), \
                mock.patch("happy_bot.tools.shell.pending_reboot", return_value=reboot):
            return software.check_updates({})

    @staticmethod
    def reply(code: int, stdout: str = "") -> dict:
        return {"ok": code == 0, "returncode": code, "stdout": stdout, "stderr": ""}

    def test_waiting_updates_are_listed_with_one_command_and_a_kernel_restart_note(self) -> None:
        text = self.check({"checkupdates": self.reply(0, "linux 6.1-1 -> 6.2-1\nfirefox 1 -> 2\n"),
                           "yay": self.reply(1), "flatpak": self.reply(0, "org.kde.kate\t24.1\n")})
        self.assertTrue(text.startswith("3 updates waiting: 2 from distribution, 1 from Flatpak"))
        self.assertIn("a restart will be needed afterwards", text)
        self.assertIn("yay -Syu && flatpak update -y", text)

    def test_a_source_that_could_not_be_checked_is_not_counted_as_up_to_date(self) -> None:
        text = self.check({"checkupdates": self.reply(1), "yay": self.reply(1), "flatpak": self.reply(0)},
                          reboot="the running kernel (6.1) was replaced by an update")
        self.assertIn("0 updates waiting.", text)
        self.assertIn("Could not check: distribution", text)
        self.assertIn("A restart is already needed", text)
        self.assertNotIn("To update everything", text)

    def test_without_the_programs_it_points_to_discover(self) -> None:
        self.assertIn("plasma-discover --mode update", self.check({}, programs=()))


class SoftwareTests(unittest.TestCase):
    def test_search_labels_every_source(self) -> None:
        outputs = {
            "pacman": "extra/firefox 140.0-1\n    Fast browser\n",
            "yay": "aur/firefox-bin 141.0-1 (+10 1.2)\n    Binary build\n",
            "flatpak": "Firefox\torg.mozilla.firefox\tflathub\n",
        }
        with mock.patch.object(software.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(software, "run_command", side_effect=lambda command, timeout=60: result(outputs[command[0]])):
            text = software.search_software({"query": "firefox"})
        self.assertIn("firefox 140.0-1 [extra] - Fast browser", text)
        self.assertIn("firefox-bin 141.0-1 - Binary build", text)
        self.assertIn("Firefox [org.mozilla.firefox] from flathub", text)
        with self.assertRaisesRegex(ToolFailure, "'query'"):
            software.search_software({"query": "x; rm -rf ~"})

    def test_update_history_and_kernel_reboot_note(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as log:
            log.write("[2026-11-20T10:00:00-0800] [ALPM] upgraded vim (9.0-1 -> 9.1-1)\n"
                      "[2026-11-23T09:00:00-0800] [ALPM] upgraded linux (6.1-1 -> 6.2-1)\n"
                      "[2026-11-23T09:00:01-0800] [ALPM] installed zip (3.0-1)\n")
        self.addCleanup(os.unlink, log.name)
        with mock.patch.object(software, "PACMAN_LOG", Path(log.name)):
            text = software.recent_updates({})
            self.assertIn("1 upgraded, 1 installed", text)
            self.assertNotIn("vim", text)
            self.assertIn("reboot is needed", text)
            self.assertIn("vim", software.recent_updates({"package": "vim"}))

    def test_flatpak_permission_options_are_limited(self) -> None:
        recorder = []
        with mock.patch.object(software, "run_checked", side_effect=lambda command, timeout=20: recorder.append(command) or ""):
            software.set_flatpak_permission({"app": "org.mozilla.firefox", "permission": "--filesystem=~/Music"})
        self.assertEqual(recorder[0], ["flatpak", "override", "--user", "--filesystem=~/Music", "org.mozilla.firefox"])
        with self.assertRaisesRegex(ToolFailure, "'permission'"):
            software.set_flatpak_permission({"app": "org.mozilla.firefox", "permission": "--filesystem=/ --talk-name=x"})


class DeveloperTests(unittest.TestCase):
    def test_journal_command_is_built_from_safe_parts(self) -> None:
        seen = []
        with mock.patch.object(developer, "run_command", side_effect=lambda command, timeout=30: seen.append(command) or result("a log line")):
            developer.read_journal({"unit": "NetworkManager", "priority": "err", "since": "2h ago", "contains": "dhcp"})
        self.assertEqual(seen[0][-9:], ["--since", "2h ago", "-u", "NetworkManager", "-p", "err", "--grep", "dhcp",
                                        "--case-sensitive=false"])
        for bad in ({"since": "$(reboot)"}, {"unit": "a b"}, {"priority": "loud"}):
            with self.subTest(bad=bad), self.assertRaises(ToolFailure):
                developer.read_journal(bad)

    def test_stopping_a_program_needs_approval_and_spares_the_daemon(self) -> None:
        tool = next(tool for tool in developer.developer_tools() if tool.name == "stop_process")
        self.assertEqual(ToolRegistry([tool]).assess("stop_process", {"process": "firefox"})[0], RISK_DANGER)
        killed = []
        listing = result(f"{os.getpid()} python3\n4242 firefox\n")
        with mock.patch.object(developer, "run_command", return_value=listing), \
                mock.patch.object(developer.os, "kill", side_effect=lambda pid, signal: killed.append(pid)):
            self.assertIn("firefox (4242)", developer.stop_process({"process": "firefox"}))
            with self.assertRaisesRegex(ToolFailure, "no process"):
                developer.stop_process({"process": "python3"})
        self.assertEqual(killed, [4242])

    def test_git_summary_on_this_repository(self) -> None:
        text = developer.git_summary({"repository": str(Path(__file__).resolve().parent.parent)})
        self.assertTrue(text.startswith("Branch: "))
        with self.assertRaisesRegex(ToolFailure, "not a Git repository"):
            developer.git_summary({"repository": tempfile.gettempdir()})

    def test_network_check_resolves_and_checks_a_port(self) -> None:
        with mock.patch.object(developer, "run_command", return_value=result("3 packets transmitted, 3 received, 0% packet loss")):
            text = developer.network_check({"host": "localhost", "port": 1})
        self.assertIn("DNS: localhost is", text)
        self.assertIn("Port 1: closed", text)
        with self.assertRaisesRegex(ToolFailure, "'host'"):
            developer.network_check({"host": "a;b"})


class ScreenTests(unittest.TestCase):
    def test_clipboard_history_stops_at_the_first_empty_item(self) -> None:
        items = ["newest", "older", ""]
        with mock.patch.object(screen.session_dbus, "call", side_effect=lambda *a: (items[a[5][0]],)):
            self.assertEqual(screen.clipboard_history({"limit": 5}), "1. newest\n2. older")

    def test_picked_colour_is_hex(self) -> None:
        with mock.patch.object(screen.session_dbus, "call", return_value=((0xFF3DAEE9,),)):
            self.assertEqual(screen.pick_color({}), "#3daee9")
        with self.assertRaisesRegex(ToolFailure, "'area'"):
            screen.take_screenshot({"area": "everything"})


if __name__ == "__main__":
    unittest.main()

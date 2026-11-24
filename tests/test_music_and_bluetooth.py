"""Tests for music by name, playlists, Bluetooth and opening documents at a page.

Music runs against a temporary Music folder with empty files named like
tracks; opening the player and every Bluetooth or viewer command is replaced
by a recorder, so nothing plays, pairs or opens.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.tools import developer, devices, media  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


class MusicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name)
        for name in ("Radiohead/OK Computer/01 Airbag.flac", "Radiohead/OK Computer/02 Paranoid Android.flac",
                     "Bjork/Homogenic/01 Hunter.mp3", "Bjork/cover.jpg"):
            (self.music / name).parent.mkdir(parents=True, exist_ok=True)
            (self.music / name).write_text("")
        patcher = mock.patch.object(media, "_music_folder", return_value=self.music)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_play_matches_words_in_paths_and_opens_a_playlist(self) -> None:
        opened = []
        with mock.patch("happy_bot.desktop_actions.open_location", side_effect=opened.append):
            self.assertIn("Playing 2 track(s)", media.play_music({"query": "ok computer"}))
        self.assertTrue(opened[0].endswith(".m3u"))
        self.assertIn("Paranoid Android.flac", Path(opened[0]).read_text())
        self.assertIn("Nothing in", media.play_music({"query": "beatles"}))

    def test_playlist_collects_several_queries_without_duplicates(self) -> None:
        text = media.make_playlist({"name": "Mix: 90s!", "include": ["radiohead", "airbag", "hunter"]})
        self.assertIn("3 tracks", text)
        playlist = self.music / "Playlists" / "Mix 90s.m3u"
        self.assertEqual(playlist.read_text().count("\n"), 4)
        with self.assertRaisesRegex(ToolFailure, "nothing in"):
            media.make_playlist({"name": "x", "include": ["nobody"]})


class BluetoothTests(unittest.TestCase):
    def test_connect_by_name_and_report_failure(self) -> None:
        commands = []

        def fake(command, timeout=20.0):
            commands.append(command)
            if command[:3] == ["bluetoothctl", "devices", "Connected"]:
                return ""
            if command[:2] == ["bluetoothctl", "devices"]:
                return "Device E8:EE:CC:75:A5:6E soundcore Liberty 4\nDevice D6:5A:4A:1A:23:7D MX Master 3S"
            if command[1] == "connect":
                return "Connection successful" if command[2].startswith("E8") else "Failed to connect"
            return ""

        with mock.patch.object(devices, "run_checked", side_effect=fake):
            self.assertEqual(devices.bluetooth_action({"action": "connect", "device": "liberty"}),
                             "Connected soundcore Liberty 4.")
            with self.assertRaisesRegex(ToolFailure, "did not connect"):
                devices.bluetooth_action({"action": "connect", "device": "mx master"})
            with self.assertRaisesRegex(ToolFailure, "say which device"):
                devices.bluetooth_action({"action": "connect", "device": "sony"})


class DocumentPageTests(unittest.TestCase):
    def test_pdf_opens_in_okular_at_a_page(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as document, \
                mock.patch.object(developer.shutil, "which", return_value="/usr/bin/okular"), \
                mock.patch.object(developer.subprocess, "Popen") as popen:
            developer.open_in_editor({"path": document.name, "line": 12})
        self.assertEqual(popen.call_args[0][0], ["okular", "--page", "12", document.name])


if __name__ == "__main__":
    unittest.main()

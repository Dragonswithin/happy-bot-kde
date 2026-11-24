"""Tests for the search bar's own results: computed answers and quick results.

``quick_answers`` is pure apart from ``qalc`` (used for real when installed,
else those cases are skipped). ``quick_results`` runs against fake window,
application and settings-page sources, and its activation against a recorded
fake of process start-up, so nothing is launched.
"""

from __future__ import annotations

import datetime
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import krunner_bridge, quick_answers, quick_results  # noqa: E402


class AnswerTests(unittest.TestCase):
    def test_arithmetic_and_percentages(self) -> None:
        cases = {"2+2*3": "= 8", "2^10": "= 1024", "sqrt(16)/2": "= 2", "(1+2)*3.5": "= 10.5",
                 "15% of 80": "12", "80 + 15%": "92", "100 - 10%": "90", "123456*2": "= 246 912"}
        for text, title in cases.items():
            with self.subTest(text=text):
                self.assertEqual(quick_answers.answer(text)["title"], title)

    def test_text_that_is_not_a_question_gets_no_answer(self) -> None:
        for text in ("tax return 2025 pdf", "2025", "firefox", "1/0", "9**9999999", '__import__("os")',
                     "open(1)", "a.b", "hello world"):
            with self.subTest(text=text):
                self.assertIsNone(quick_answers.answer(text))

    def test_dates(self) -> None:
        monday = datetime.date(2026, 11, 23)
        self.assertEqual(quick_answers.date_answer("3 weeks from friday", monday)[0], "Friday 18 December 2026")
        self.assertEqual(quick_answers.date_answer("10 days ago", monday)[0], "Friday 13 November 2026")
        self.assertEqual(quick_answers.date_answer("2 days from tomorrow", monday)[0], "Thursday 26 November 2026")
        self.assertEqual(quick_answers.date_answer("days until 2026-12-25", monday)[0], "32 days")
        self.assertIsNone(quick_answers.date_answer("days until someday", monday))

    def test_world_time(self) -> None:
        noon = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(quick_answers.world_time("time in Tokyo", noon), ("21:00, Monday", "Asia/Tokyo"))
        self.assertEqual(quick_answers.world_time("time in new york", noon)[1], "America/New York")
        self.assertIsNone(quick_answers.world_time("time in Atlantis", noon))

    @unittest.skipUnless(shutil.which("qalc"), "qalc is not installed")
    def test_conversions_through_qalc_give_one_unit(self) -> None:
        self.assertEqual(quick_answers.convert("5 km to miles"), "3.106855961 miles")
        self.assertEqual(quick_answers.convert("100 F in C"), "37.77777778 °C")
        self.assertEqual(quick_answers.convert("3 GB to MB"), "3000 MB")
        self.assertIsNone(quick_answers.convert("5 km to kg"))
        self.assertIsNone(quick_answers.convert("5 apples to pears"))


class QuickResultTests(unittest.TestCase):
    def setUp(self) -> None:
        windows = [{"id": "{w1}", "title": "notes.txt — Kate", "app": "kate"}]
        applications = [{"id": "org.kde.kate.desktop", "name": "Kate", "generic": "Text Editor", "keywords": "",
                         "comment": "", "path": "/usr/share/applications/org.kde.kate.desktop"}]
        pages = [{"module": "kcm_pulseaudio", "name": "Sound", "comment": "Audio devices", "keywords": "volume;speaker",
                  "icon": "audio-speakers"}]

        class FakeBridge:
            def run(self, script):
                return windows

        patches = [
            mock.patch.object(quick_results.kwin_bridge, "shared", return_value=FakeBridge()),
            mock.patch.object(quick_results.apps, "installed_applications", return_value=applications),
            mock.patch.object(quick_results, "settings_pages", return_value=pages),
            mock.patch.object(quick_results, "_desktop_icon", return_value="kate"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        quick_results._cache.clear()

    def test_windows_then_applications_then_settings_then_conversations(self) -> None:
        results = quick_results.gather("kate", [{"id": "c1", "title": "Kate plugin question"}])
        self.assertEqual([item["action"]["type"] for item in results], ["window", "launch", "conversation"])
        sound = quick_results.gather("volume")
        self.assertEqual((sound[0]["title"], sound[0]["action"]), ("Sound", {"type": "settings", "target": "kcm_pulseaudio"}))

    def test_an_answer_comes_alone_and_one_letter_finds_nothing_else(self) -> None:
        self.assertEqual([item["action"]["type"] for item in quick_results.gather("6*7")], ["copy"])
        self.assertEqual(quick_results.gather("k"), [])

    def test_activation_starts_the_right_program_and_refuses_odd_targets(self) -> None:
        started = []
        with mock.patch.object(quick_results, "_start", side_effect=started.append), \
                tempfile.NamedTemporaryFile(suffix=".desktop") as entry:
            quick_results.activate({"type": "launch", "target": entry.name})
            quick_results.activate({"type": "settings", "target": "kcm_pulseaudio"})
            quick_results.activate({"type": "copy", "target": "42"})
        self.assertEqual(started[0], ["gio", "launch", entry.name])
        self.assertEqual(started[1], ["systemsettings", "kcm_pulseaudio"])
        self.assertEqual(started[2][-1], "42")
        for action in ({"type": "settings", "target": "; rm -rf ~"}, {"type": "launch", "target": "/etc/passwd"},
                       {"type": "explode", "target": "x"}, {"type": "copy"}):
            with self.subTest(action=action), self.assertRaises(quick_results.ActivationError):
                quick_results.activate(action)

    def test_reveal_asks_the_file_manager_for_existing_files_only(self) -> None:
        calls = []
        with mock.patch("kde_ai_assistant.session_dbus.call", side_effect=lambda *a: calls.append(a)), \
                tempfile.NamedTemporaryFile() as entry:
            quick_results.activate({"type": "reveal", "target": entry.name})
            self.assertEqual(calls[0][3:5], ("ShowItems", "ass"))
            self.assertEqual(calls[0][5][0], [Path(entry.name).as_uri()])
        with self.assertRaises(quick_results.ActivationError):
            quick_results.activate({"type": "reveal", "target": "/nonexistent/file"})

    def test_settings_pages_are_read_from_kcm_entries(self) -> None:
        mock.patch.stopall()
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "kcm_mouse.desktop").write_text(
                "[Desktop Entry]\nName=Mouse\nComment=Pointer\nKeywords=cursor;\nIcon=input-mouse\nNoDisplay=true\n")
            Path(tmp, "org.kde.kate.desktop").write_text("[Desktop Entry]\nName=Kate\n")
            self.assertEqual(quick_results.settings_pages((Path(tmp),)), [
                {"module": "kcm_mouse", "name": "Mouse", "comment": "Pointer", "keywords": "cursor;", "icon": "input-mouse"}])



class KRunnerTests(unittest.TestCase):
    class Server:
        class Conversations:
            def list(self):
                return []

        conversations = Conversations()
        mcp = None
        settings = {"roles": {}}

    def test_matches_offer_quick_results_files_and_asking_then_run_the_chosen_one(self) -> None:
        bridge = krunner_bridge.KRunnerBridge(self.Server())
        quick = [{"kind": "quick", "title": "Konsole", "subtitle": "Application", "icon": "konsole",
                  "action": {"type": "launch", "target": "/usr/share/applications/org.kde.konsole.desktop"}}]
        files = [{"title": "konsole-notes.txt", "location": "/home/u/konsole-notes.txt", "kind": "file"}]
        with mock.patch.object(krunner_bridge.quick_results, "gather", return_value=quick), \
                mock.patch.object(krunner_bridge.instant_search, "search_files", return_value=files):
            found = bridge.matches("konsole")
        self.assertEqual([item[0] for item in found], ["quick-0", "file-0", "ask"])
        self.assertEqual(found[0][3], krunner_bridge.EXACT)
        self.assertEqual(found[2][1], "Ask the assistant: konsole")
        self.assertEqual(bridge.matches("ko"), [])
        with mock.patch.object(krunner_bridge.quick_results, "activate") as activate:
            bridge.run("quick-0")
        activate.assert_called_once_with(quick[0]["action"])
        with mock.patch.object(krunner_bridge.shutil, "which", return_value="/usr/bin/kde-ai-assistant"), \
                mock.patch.object(krunner_bridge.subprocess, "Popen") as popen:
            bridge.run("ask")
        self.assertEqual(popen.call_args[0][0], ["/usr/bin/kde-ai-assistant", "ask", "--notify", "--", "konsole"])


if __name__ == "__main__":
    unittest.main()

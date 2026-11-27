"""Tests for GUI control: element matching, key parsing and risk classification.

The accessibility tree and the portal belong to a live desktop session, so
these tests cover the logic around them with stand-ins: ``Snapshot`` objects
built by hand for matching and formatting, the key-combination parser, and
the GUI tools' classifiers with the window and element lookups patched.
Operating real Qt and GTK applications is verified by hand and recorded in
docs/ROADMAP.md.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import accessibility, input_portal  # noqa: E402
from happy_bot.accessibility import Element, Snapshot  # noqa: E402
from happy_bot.input_portal import InputUnavailable, keysym_for_character, parse_combination  # noqa: E402
from happy_bot.tools import gui  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


def element(ref: str, role: str, name: str, showing: bool = True, actions: tuple = ("Press",), editable: bool = False,
            states: tuple = (), value: str = "", depth: int = 1) -> Element:
    return Element(ref, role, name, depth, showing, states, actions, editable, value)


def snapshot(*elements: Element) -> Snapshot:
    return Snapshot(pid=42, title="Doc — Editor", application="editor", elements=list(elements), truncated=False)


class ElementTests(unittest.TestCase):
    def test_lines_show_ref_role_label_value_and_flags(self) -> None:
        self.assertEqual(element("e1", "button", "Save", depth=0).line(), 'e1 button "Save"')
        field = element("e2", "text", "", editable=True, states=("focused",), value="hello", depth=2)
        self.assertEqual(field.line(), "    e2 text = 'hello' [focused, editable]")
        self.assertEqual(element("e3", "menu item", "Quit", showing=False, depth=9).line(),
                         "            e3 menu item \"Quit\" [hidden]")

    def test_matching_prefers_exact_then_prefix_then_substring_and_visible_controls(self) -> None:
        snap = snapshot(
            element("e1", "button", "Save"), element("e2", "menu item", "Save", showing=False),
            element("e3", "menu item", "Save As...", showing=False), element("e4", "button", "Don't Save"),
            element("e5", "label", "Unsaved changes", actions=()), element("e6", "text", "File name", actions=(), editable=True),
        )
        find = lambda text, actionable=False: [e.ref for e in accessibility.find_elements(snap, text, actionable)]  # noqa: E731
        self.assertEqual(find("save"), ["e1"])                       # exact, visible wins over hidden twin
        self.assertEqual(find("Save As"), ["e3"])                    # trailing dots ignored
        self.assertEqual(find("don't"), ["e4"])
        self.assertEqual(find("changes"), ["e5"])
        self.assertEqual(find("changes", True), [])                  # a label cannot be pressed
        self.assertEqual(find("file name", True), ["e6"])            # editable counts as actionable
        self.assertEqual(find("nothing like this"), [])
        self.assertEqual(snap.by_ref("e3").name, "Save As...")
        self.assertIsNone(snap.by_ref("e99"))

    def test_ref_pattern(self) -> None:
        self.assertTrue(accessibility.REF_PATTERN.match("e12"))
        for text in ("e", "12", "Edit", "e12b", "save"):
            self.assertFalse(accessibility.REF_PATTERN.match(text), text)


class AccessibilityWorkerTests(unittest.TestCase):
    def test_worker_loss_invalidates_cached_refs_and_next_request_starts_a_new_worker(self):
        self.assertIsNone(accessibility.last_snapshot(0))
        accessibility._process.kill()
        accessibility._process.join()
        self.assertIsNone(accessibility.last_snapshot(0))
        self.assertIsNone(accessibility.last_snapshot(0))

    def test_failed_init_never_calls_native_methods(self):
        from happy_bot import _atspi
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
        except (ImportError, ValueError):
            self.skipTest("AT-SPI bindings unavailable")
        with mock.patch.object(_atspi, "_atspi", None), mock.patch.object(Atspi, "init", return_value=2), \
                mock.patch.object(Atspi, "get_desktop") as desktop:
            with self.assertRaisesRegex(_atspi.WorkerStale, "code 2"):
                _atspi.take_snapshot(1, "")
            desktop.assert_not_called()

    def test_reconnect_retries_snapshot_restarting_only_a_confirmed_broken_bus(self):
        a = accessibility
        down = a._atspi.BusUnavailable("refused")
        for probe_failed in (True, False):
            sequence = [down] + ([down] if probe_failed else []) + [None, snapshot()]
            with mock.patch.object(a, "_exchange", side_effect=sequence) as exchange, \
                    mock.patch.object(a, "_reset_worker"), mock.patch.object(a, "_last_restart", float("-inf")), \
                    mock.patch.object(a.subprocess, "run") as systemctl:
                self.assertEqual(a.take_snapshot(42, "test").pid, 42)
                self.assertEqual(exchange.call_args_list[-1], mock.call("snapshot", 42, "test"))
                self.assertEqual(systemctl.call_count, int(probe_failed))
                if probe_failed:
                    self.assertEqual(systemctl.call_args.args[0], ["systemctl", "--user", "restart", "at-spi-dbus-bus.service"])

    def test_persistent_failure_is_rate_limited_and_app_errors_do_not_restart_bus(self):
        a = accessibility
        with mock.patch.object(a, "_exchange", side_effect=a._atspi.BusUnavailable("refused")), \
                mock.patch.object(a, "_reset_worker"), mock.patch.object(a, "_last_restart", a.time.monotonic()), \
                mock.patch.object(a.subprocess, "run") as systemctl:
            with self.assertRaisesRegex(a.AccessibilityUnavailable, "recent restart"):
                a.take_snapshot(1, "test")
            systemctl.assert_not_called()
        with mock.patch.object(a, "_exchange", side_effect=a._atspi.WindowUnavailable("no window")), \
                mock.patch.object(a, "_recover") as recover:
            with self.assertRaisesRegex(a.AccessibilityUnavailable, "no window"):
                a.take_snapshot(1, "test")
            recover.assert_not_called()

    def test_lost_action_reply_recovers_connection_without_repeating_action(self):
        a = accessibility
        with mock.patch.object(a, "_exchange", side_effect=[a._atspi.WorkerStale("EOF"), None]) as exchange, \
                mock.patch.object(a, "_reset_worker"), mock.patch.object(a.subprocess, "run") as systemctl:
            with self.assertRaisesRegex(a.AccessibilityUnavailable, "fresh snapshot"):
                a.press(element("e1", "button", "OK"))
            self.assertEqual([c.args[0] for c in exchange.call_args_list], ["press", "probe"])
            systemctl.assert_not_called()


class KeyParsingTests(unittest.TestCase):
    def test_combinations(self) -> None:
        ctrl, shift, alt = 0xFFE3, 0xFFE1, 0xFFE9
        cases = {
            "ctrl+s": ([ctrl], ord("s")), "Ctrl+S": ([ctrl], ord("s")), "ctrl + shift + s": ([ctrl, shift], ord("s")),
            "Return": ([], 0xFF0D), "enter": ([], 0xFF0D), "alt+F4": ([alt], 0xFFC1), "F1": ([], 0xFFBE),
            "shift+Tab": ([shift], 0xFF09), "Escape": ([], 0xFF1B), "ctrl++": ([ctrl], ord("+")), "+": ([], ord("+")),
            "a": ([], ord("a")), "A": ([], ord("A")), "ctrl+Delete": ([ctrl], 0xFFFF), "space": ([], 0x20),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_combination(text), expected)

    def test_bad_combinations(self) -> None:
        for text in ("", "hyper+s", "ctrl+nosuchkey", "   "):
            with self.subTest(text=text), self.assertRaises(InputUnavailable):
                parse_combination(text)

    def test_characters_map_to_keysyms(self) -> None:
        self.assertEqual([keysym_for_character(c) for c in "aZ ~é"], [0x61, 0x5A, 0x20, 0x7E, 0xE9])
        self.assertEqual(keysym_for_character("€"), 0x010020AC)
        self.assertEqual(keysym_for_character("\n"), 0xFF0D)
        self.assertEqual(keysym_for_character("\t"), 0xFF09)

    def test_declined_consent_is_reported(self) -> None:
        portal = input_portal.KeyboardPortal(Path("/nonexistent/token"))
        with mock.patch.object(portal, "start", side_effect=InputUnavailable("you declined")):
            with self.assertRaisesRegex(InputUnavailable, "declined"):
                portal.press_keys("Return")


class GuiRiskTests(unittest.TestCase):
    def classify_press(self, label: str) -> str:
        with mock.patch.object(gui, "_resolve", return_value=({"id": "w"}, element("e1", "button", label))):
            return gui.classify_press({"element": "e1"})[0]

    def test_destructive_labels_need_approval(self) -> None:
        for label in ("Delete", "Delete Permanently", "Remove Account", "Empty Trash", "Empty the Wastebin",
                      "Discard", "Don't Save", "Dont Save", "Close Without Saving", "Format Disk", "Uninstall",
                      "Overwrite", "Replace", "Shut Down", "Shutdown", "Restart", "Log Out", "Reset", "Clear History",
                      "Move to Trash", "Erase"):
            with self.subTest(label=label):
                self.assertEqual(self.classify_press(label), "danger")

    def test_ordinary_labels_do_not(self) -> None:
        for label in ("Save", "OK", "Cancel", "Open", "New File", "Apply", "Next", "Close", "Print", "Copy",
                      "Undelete", "Information", "Clear Search", "Back"):
            with self.subTest(label=label):
                self.assertEqual(self.classify_press(label), "change")

    def test_an_unresolvable_press_is_not_classified_as_danger(self) -> None:
        with mock.patch.object(gui, "_resolve", side_effect=ToolFailure("no such control")):
            self.assertEqual(gui.classify_press({"element": "Delete"}), ("change", ""))

    def test_keys_and_typing_depend_on_the_target_window(self) -> None:
        editor, terminal = {"app": "org.kde.kwrite", "title": "x"}, {"app": "org.kde.konsole", "title": "y"}
        with mock.patch.object(gui, "_target", return_value=editor):
            self.assertEqual(gui.classify_keys({"keys": ["ctrl+s", "Return"]})[0], "change")
            self.assertEqual(gui.classify_keys({"keys": "Delete"})[0], "change")
            self.assertEqual(gui.classify_keys({"keys": ["shift+Delete"]})[0], "danger")
            self.assertEqual(gui.classify_type({"text": "rm -rf everything\n"})[0], "change")
        with mock.patch.object(gui, "_target", return_value=terminal):
            self.assertEqual(gui.classify_keys({"keys": ["Return"]})[0], "danger")
            self.assertEqual(gui.classify_keys({"keys": ["ctrl+shift+t"]})[0], "change")
            self.assertEqual(gui.classify_type({"text": "ls -la"})[0], "change")
            self.assertEqual(gui.classify_type({"text": "rm notes.txt"})[0], "danger")
            self.assertEqual(gui.classify_type({"text": "ls\n"})[0], "danger")

    def test_window_change_notes(self) -> None:
        before = [{"id": "{a}", "title": "Untitled — KWrite"}]
        after = [{"id": "{a}", "title": "Untitled * — KWrite"}, {"id": "{b}", "title": "Save File — KWrite"}]
        with mock.patch.object(gui.windows, "windows_of_process", return_value=after):
            note = gui._window_changes(1, before)
        self.assertIn('Opened window "Save File — KWrite", id {b}.', note)
        self.assertIn('Window id {a} is now titled "Untitled * — KWrite".', note)
        with mock.patch.object(gui.windows, "windows_of_process", return_value=[]):
            self.assertEqual(gui._window_changes(1, before), 'Closed window "Untitled — KWrite".')
        with mock.patch.object(gui.windows, "windows_of_process", return_value=before):
            self.assertEqual(gui._window_changes(1, before), "")

    def test_argument_validation(self) -> None:
        with mock.patch.object(gui, "_target", return_value={"pid": 1, "id": "w", "title": "t"}):
            with self.assertRaisesRegex(ToolFailure, "'element' is required"):
                gui.ui_press({})
            with mock.patch.object(accessibility, "last_snapshot", return_value=None):
                with self.assertRaisesRegex(ToolFailure, "not from a current snapshot"):
                    gui.ui_press({"element": "e5"})
            with self.assertRaisesRegex(ToolFailure, "'text' is required"):
                gui.ui_set_text({"element": "e1"})
            with self.assertRaisesRegex(ToolFailure, "'keys' is required"):
                gui.press_keys({})
            with self.assertRaisesRegex(ToolFailure, "too much to type"):
                gui.type_text({"text": "x" * 6000})


if __name__ == "__main__":
    unittest.main()

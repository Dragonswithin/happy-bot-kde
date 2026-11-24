"""Tests for the Happy Bot app's daemon side (``app_control``): start at login, and "show yourself".

The login entry is written into a temporary config folder from a menu entry in a temporary data
folder, so the user's own autostart folder is never touched. The waker is checked with threads: a
waiting app wakes when a show request arrives, and gives up after its timeout otherwise.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import app_control  # noqa: E402


class AutostartTests(unittest.TestCase):
    def test_the_login_entry_is_a_copy_of_the_menu_entry_and_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as config, tempfile.TemporaryDirectory() as data:
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": config, "XDG_DATA_HOME": data}):
                menu = app_control.menu_entry_path()
                menu.parent.mkdir(parents=True)
                menu.write_text("[Desktop Entry]\nName=Happy Bot\nExec=happy-bot-app\n")
                self.assertFalse(app_control.autostart_enabled())
                app_control.set_autostart(True)
                self.assertEqual(app_control.autostart_path().read_text(), menu.read_text())
                self.assertEqual(app_control.autostart_path().parent, Path(config) / "autostart")
                app_control.set_autostart(False)
                self.assertFalse(app_control.autostart_enabled())
                app_control.set_autostart(False)  # removing twice is fine

    def test_without_an_installed_menu_entry_turning_it_on_fails_plainly(self) -> None:
        with tempfile.TemporaryDirectory() as config, tempfile.TemporaryDirectory() as data:
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": config, "XDG_DATA_HOME": data}):
                with self.assertRaises(OSError):
                    app_control.set_autostart(True)


class WakerTests(unittest.TestCase):
    def test_a_waiting_app_wakes_on_a_show_request(self) -> None:
        waker = app_control.Waker()
        seen = waker.wait(-1)  # the first call answers at once with the current count
        woke: list[int] = []
        waiter = threading.Thread(target=lambda: woke.append(waker.wait(seen, timeout=5)))
        waiter.start()
        time.sleep(0.1)
        waker.notify()
        waiter.join(2)
        self.assertEqual(woke, [seen + 1])

    def test_without_a_request_the_wait_ends_after_its_timeout(self) -> None:
        waker = app_control.Waker()
        started = time.monotonic()
        self.assertEqual(waker.wait(0, timeout=0.2), 0)
        self.assertGreaterEqual(time.monotonic() - started, 0.15)


if __name__ == "__main__":
    unittest.main()

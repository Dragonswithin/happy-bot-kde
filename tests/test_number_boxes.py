"""Checks that no number box in Happy Bot's widget changes when the page is scrolled over it.

KDE's desktop style (org/kde/desktop/SpinBox.qml) turns the mouse wheel on for every SpinBox, and
the settings pages save a number as soon as it changes, so scrolling down a page with the pointer
passing over one changed the setting unnoticed (the maintainer's popup width went from 30 to 22
this way). Every SpinBox in the widget's QML must say ``wheelEnabled: false``; it is then changed
only by typing or its arrows. The QML files are read as text; nothing is run.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "plasmoid" / "io.github.dragonswithin.happybot" / "contents" / "ui"


class NumberBoxTests(unittest.TestCase):
    def test_every_number_box_ignores_the_mouse_wheel(self) -> None:
        found = []
        for path in sorted(UI.glob("*.qml")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"SpinBox \{\n((?:.*\n){0,3})", text):
                found.append(path.name)
                self.assertIn("wheelEnabled: false", match.group(1),
                              f"{path.name}:{text[:match.start()].count(chr(10)) + 1}: SpinBox reacts to the wheel")
        self.assertGreaterEqual(len(found), 9)


if __name__ == "__main__":
    unittest.main()

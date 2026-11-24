"""Tests for answerParts.js, which splits an answer into text, code blocks and file lists for the popup.

The module is plain JavaScript with a QML ``.pragma library`` line; the test strips that line and
runs it in Node, so it checks the same file the applet loads. Skipped when Node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

MODULE = (Path(__file__).resolve().parent.parent
          / "plasmoid/io.github.dragonswithin.happybot/contents/ui/answerParts.js")


def split(markdown: str, home: str = "/home/u") -> list[dict]:
    source = MODULE.read_text(encoding="utf-8").replace(".pragma library", "")
    script = source + f"\nprocess.stdout.write(JSON.stringify(split({json.dumps(markdown)}, {json.dumps(home)})));"
    completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20, check=True)
    return json.loads(completed.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AnswerPartsTests(unittest.TestCase):
    def test_code_blocks_are_separate_parts_with_their_language(self) -> None:
        parts = split("Run this:\n\n```bash\nsudo pacman -Syu\n```\nThen reboot.")
        self.assertEqual([part["kind"] for part in parts], ["text", "code", "text"])
        self.assertEqual((parts[1]["language"], parts[1]["code"]), ("bash", "sudo pacman -Syu"))

    def test_an_unclosed_fence_while_streaming_runs_to_the_end(self) -> None:
        parts = split("~~~\nline one\nline two")
        self.assertEqual(parts, [{"kind": "code", "language": "", "code": "line one\nline two"}])

    def test_two_or_more_path_lines_become_a_file_list(self) -> None:
        parts = split("I found:\n- `~/Documents/tax.pdf`\n- /home/u/Pictures/cat.png\n\nWant more?")
        self.assertEqual(parts[1], {"kind": "files", "paths": ["/home/u/Documents/tax.pdf", "/home/u/Pictures/cat.png"]})
        self.assertEqual(parts[2]["kind"], "text")

    def test_a_single_path_or_a_url_stays_in_the_text(self) -> None:
        self.assertEqual([part["kind"] for part in split("It is at /etc/hosts.\nSee https://example.org/a")], ["text"])
        self.assertEqual([part["kind"] for part in split("/etc/hosts\nhttps://example.org/a")], ["text"])


if __name__ == "__main__":
    unittest.main()

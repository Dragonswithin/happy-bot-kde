"""Exercise the manually selected attachment and project-result paths without a desktop or provider."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from happy_bot import attachments
from happy_bot.conversation import Message
from happy_bot.tools import project_search
from happy_bot.tools.mcp_bridge import web_card


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_preview_and_one_turn_payload(self):
        note = self.root / "report.txt"
        note.write_text("A paragraph.\n" * 40)
        image = self.root / "photo.jpg"
        image.write_bytes(b"\xff\xd8\xff" + bytes(range(8)))
        files = attachments.load(list(map(str, [note, image])))
        self.assertEqual([x.kind for x in files], ["text", "image"])
        self.assertLess(len(files[0].preview()["preview"]), len(note.read_text()))
        history = [Message("system", "Help."), Message("user", "Compare these.")]
        prepared = attachments.include(history.copy(), files)
        self.assertIn("report.txt", prepared[-1].text)
        self.assertTrue(prepared[-1].images[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(history[-1], Message("user", "Compare these."))

    def test_failed_inputs(self):
        path = self.root / "empty.txt"
        path.touch()
        with self.assertRaisesRegex(ValueError, "no extractable text"):
            attachments.load([str(path)])
        path.write_bytes(bytes(range(128)))
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            attachments.load([str(path)])

    @unittest.skipUnless(shutil.which("rg"), "ripgrep needed")
    def test_literal_search_and_line_open(self):
        file = self.root / "a project [v2].py"
        file.write_text("line one\nneedle[42]\n")
        result = project_search.search({"folder": str(self.root), "text": "needle[42]"})
        hit, = project_search.card(result)["matches"]
        self.assertEqual((hit["path"], hit["line"]), (str(file), 2))
        with patch.object(shutil, "which", return_value="/usr/bin/kate"), patch("subprocess.Popen") as launch:
            project_search.open_line(hit["path"], hit["line"])
        self.assertEqual(launch.call_args.args[0], ["/usr/bin/kate", "--line", "2", "--", str(file)])

    def test_source_links_from_configured_web_search(self):
        result = json.dumps({"results": [{"title": "Kate", "url": "https://kate-editor.org"},
                                         {"title": "Local", "path": "/tmp/local"}]})
        self.assertEqual(web_card(result)["links"], [{"title": "Kate", "url": "https://kate-editor.org"}])

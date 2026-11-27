"""Tests for the document tools, run for real in a temporary folder.

Archives, duplicates, file finding, comparison and permissions need only the
standard library. Conversion, image edits, PDF pages and OCR call the real
``magick``, ``pdfunite``/``pdfseparate`` and ``tesseract``, and are skipped
when those programs are not installed. Every output must be a new file, and
inputs must stay untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import undo_journal  # noqa: E402
from happy_bot.tools import documents  # noqa: E402
from happy_bot.tools.registry import RISK_DANGER, ToolFailure  # noqa: E402


class DocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "a.txt").write_text("alpha\nbeta\n")
        (self.root / "docs" / "b.txt").write_text("alpha\nbeta\n")
        (self.root / "docs" / "c.txt").write_text("alpha\ngamma\n")

    def test_scoped_trash_and_gio_fallback(self):
        data = self.root / "home"
        mount = self.root / "Storage"
        home_info = data / "Trash/info"
        info = mount / f".Trash-{os.getuid()}/info"
        for folder, path in ((home_info, "/home/example"), (info, "my%20file")):
            folder.mkdir(parents=True)
            (folder / "one.trashinfo").write_text("[Trash Info]\nPath=" + path + "\n")
        with mock.patch.dict(os.environ, XDG_DATA_HOME=str(data)), \
                mock.patch.object(documents, "_mounted_volumes", return_value={mount}), \
                mock.patch.object(documents, "_trash_items", side_effect=ToolFailure("unsupported")):
            scoped = documents.list_trash({"mount_point": str(mount)})
            self.assertIn(str(mount / "my file"), scoped)
            self.assertNotIn("/home/example", scoped)
            files = info.parent / "files"
            files.mkdir()
            (files / "unindexed").touch()
            self.assertIn("original location unknown", documents.list_trash({"mount_point": str(mount)}))
            self.assertIn("/home/example", documents.list_trash({}))
            with self.assertRaisesRegex(ToolFailure, "exact mounted drive"):
                documents.list_trash({"mount_point": "/unknown"})

    def test_archives_round_trip_and_never_replace(self) -> None:
        for name in ("pack.zip", "pack.tar.gz"):
            with self.subTest(name=name):
                archive = self.root / name
                documents.create_archive({"paths": [str(self.root / "docs")], "archive": str(archive)})
                self.assertIn("docs/a.txt", documents.list_archive({"archive": str(archive), "contains": "a.txt"}))
                out = self.root / ("out-" + name.split(".")[1])
                documents.extract_archive({"archive": str(archive), "destination": str(out)})
                self.assertEqual((out / "docs" / "c.txt").read_text(), "alpha\ngamma\n")
                with self.assertRaisesRegex(ToolFailure, "already exists"):
                    documents.create_archive({"paths": [str(self.root / "docs")], "archive": str(archive)})
        self.assertEqual(undo_journal.pending()[0]["kind"], "file_created")

    def test_unsafe_zip_members_are_refused_and_nothing_left_behind(self) -> None:
        bad = self.root / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../escape.txt", "x")
        with self.assertRaisesRegex(ToolFailure, "unsafe path"):
            documents.extract_archive({"archive": str(bad), "destination": str(self.root / "bad")})
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((self.root / "bad").exists())

    def test_duplicates_files_and_comparisons(self) -> None:
        text = documents.find_duplicates({"folder": str(self.root / "docs")})
        self.assertIn("1 sets of identical files", text)
        self.assertIn("a.txt", text)
        self.assertNotIn("c.txt", text)
        self.assertIn("3 files match", documents.find_files({"folder": str(self.root), "extensions": ["txt"]}))
        self.assertEqual(documents.find_files({"folder": str(self.root), "older_than_days": 5}), "No files match.")
        self.assertEqual(documents.compare({"first": str(self.root / "docs/a.txt"), "second": str(self.root / "docs/b.txt")}),
                         "The files are identical.")
        self.assertIn("+gamma", documents.compare({"first": str(self.root / "docs/a.txt"),
                                                    "second": str(self.root / "docs/c.txt")}))

    def test_permissions_by_name_and_system_paths_are_danger(self) -> None:
        target = self.root / "docs" / "a.txt"
        self.assertIn("to 600", documents.set_permissions({"path": str(target), "mode": "private"}))
        self.assertEqual(oct(target.stat().st_mode & 0o777), "0o600")
        self.assertEqual(documents.classify_permissions({"path": "/etc/hosts", "mode": "644"})[0], RISK_DANGER)
        with self.assertRaisesRegex(ToolFailure, "'mode'"):
            documents.set_permissions({"path": str(target), "mode": "rwx"})

    @unittest.skipUnless(shutil.which("magick"), "ImageMagick is not installed")
    def test_conversion_and_image_edits_make_new_files(self) -> None:
        picture = self.root / "pic.png"
        subprocess.run(["magick", "-size", "40x20", "xc:red", str(picture)], check=True)
        documents.convert_file({"path": str(picture), "to": "jpg"})
        self.assertTrue((self.root / "pic.jpg").exists())
        result = documents.edit_images({"paths": [str(picture)], "resize": "50%", "rotate": 90, "strip_metadata": True})
        self.assertIn("pic-edited.png", result)
        size = subprocess.run(["magick", "identify", "-format", "%wx%h", str(self.root / "pic-edited.png")],
                              capture_output=True, text=True).stdout
        self.assertEqual(size, "10x20")
        with self.assertRaisesRegex(ToolFailure, "'rotate'"):
            documents.edit_images({"paths": [str(picture)], "rotate": 45})

    @unittest.skipUnless(shutil.which("magick") and shutil.which("pdfunite") and shutil.which("pdfseparate"),
                         "ImageMagick or poppler is not installed")
    def test_pdf_merge_and_page_extraction(self) -> None:
        for name in ("one.pdf", "two.pdf"):
            subprocess.run(["magick", "-size", "50x50", "xc:white", "xc:gray", str(self.root / name)], check=True)
        documents.pdf_pages({"action": "merge", "paths": [str(self.root / "one.pdf"), str(self.root / "two.pdf")],
                             "output": str(self.root / "all.pdf")})
        documents.pdf_pages({"action": "extract", "path": str(self.root / "all.pdf"), "pages": "2-3",
                             "output": str(self.root / "middle.pdf")})
        pages = subprocess.run(["pdfinfo", str(self.root / "middle.pdf")], capture_output=True, text=True).stdout
        self.assertRegex(pages, r"Pages:\s+2")
        with self.assertRaisesRegex(ToolFailure, "'pages'"):
            documents.pdf_pages({"action": "extract", "path": str(self.root / "all.pdf"), "pages": "two",
                                 "output": str(self.root / "x.pdf")})

    @unittest.skipUnless(shutil.which("magick") and shutil.which("tesseract"), "ImageMagick or tesseract missing")
    def test_text_is_read_from_a_picture(self) -> None:
        picture = self.root / "words.png"
        made = subprocess.run(["magick", "-size", "400x100", "xc:white", "-fill", "black", "-pointsize", "48",
                               "-annotate", "+20+70", "HELLO 42", str(picture)], capture_output=True)
        if made.returncode != 0:
            self.skipTest("no font available to draw text")
        self.assertIn("HELLO", documents.text_from_image({"path": str(picture)}))


if __name__ == "__main__":
    unittest.main()

"""Exercise speech completion, request-scoped Stop and backend errors without audio."""

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from happy_bot import read_aloud
from happy_bot.voice import VOICE_DEFAULTS


class ReadAloudTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.reader = read_aloud.Reader(directory.name)
        self.addCleanup(self.reader.stop)

    def finished(self, job):
        deadline = time.monotonic() + 2
        while self.reader.status(job)["playing"] and time.monotonic() < deadline:
            time.sleep(.01)
        result = self.reader.status(job)
        self.assertFalse(result["playing"])
        return result

    @patch.object(read_aloud, "dispatcher")
    def test_stops_only_own_request(self, dispatcher):
        spoke = threading.Event()
        client = dispatcher.return_value
        client.speak.side_effect = lambda *args, **kwargs: spoke.set()
        job = self.reader.start("A reply.", {**VOICE_DEFAULTS, "dispatcher_voice": "English"})
        self.assertTrue(spoke.wait(2))
        self.reader.stop("older-job")
        self.assertTrue(self.reader.status(job)["playing"])
        with self.assertRaises(ValueError):
            self.reader.start("Another.", VOICE_DEFAULTS)
        self.reader.stop(job)
        self.assertNotIn("error", self.finished(job))
        client.set_synthesis_voice.assert_called_once_with("English")
        client.cancel.assert_called_once_with()
        client.close.assert_called_once_with()

    @patch.object(read_aloud, "dispatcher")
    def test_completion_and_silent_output_configuration(self, dispatcher):
        client = dispatcher.return_value
        client.speak.side_effect = lambda text, callback, event_types: callback("end")
        self.assertNotIn("error", self.finished(self.reader.start("One", VOICE_DEFAULTS)))
        client.get_output_module.return_value = "dummy"
        self.assertIn("synthesizer", self.finished(self.reader.start("Two", VOICE_DEFAULTS))["error"])
        client.speak.assert_called_once()

    def test_missing_piper_voice_can_retry(self):
        settings = {**VOICE_DEFAULTS, "speech_engine": "piper"}
        for _ in range(2):
            self.assertIn(".onnx", self.finished(self.reader.start("Hello", settings))["error"])

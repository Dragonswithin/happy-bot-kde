"""Tests for talking to Happy Bot (``voice``): the settings group, listening until a pause, and speech to text.

The microphone is replaced by a small Python program that writes synthetic 16 kHz sound to stdout
(quiet, then loud "speech", then quiet), standing in for ``pw-record``; the speech service by a
loopback HTTP server that records the multipart upload and answers with text, so the WAV sent
(16 kHz mono, loudness-normalized) can be read back. Nothing is
recorded from a real microphone and no real service is asked.
"""

from __future__ import annotations

import array
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import voice  # noqa: E402
from happy_bot.settings import SettingsError, validate_settings  # noqa: E402

# Writes `quiet` tenths of a second of near-silence, `loud` of a loud tone (paced, as a real microphone
# delivers sound over time), then quiet until killed.
FAKE_MICROPHONE = r"""
import math, sys, time
quiet, loud, level = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
def chunk(level):
    return b"".join(int(level * math.sin(i / 3)).to_bytes(2, "little", signed=True) for i in range(1600))
for _ in range(quiet): sys.stdout.buffer.write(chunk(30))
for _ in range(loud):
    sys.stdout.buffer.write(chunk(level)); sys.stdout.buffer.flush(); time.sleep(0.02)
while True:
    sys.stdout.buffer.write(chunk(30)); sys.stdout.buffer.flush(); time.sleep(0.01)
"""


class Speech(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (http.server's name)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.uploads.append((self.path, self.headers.get("Content-Type", ""), body))
        reply = json.dumps({"text": " turn on night light "}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args) -> None:
        pass


class VoiceSettingsTests(unittest.TestCase):
    def test_defaults_and_refusals(self) -> None:
        self.assertEqual(validate_settings({})["voice"], voice.VOICE_DEFAULTS)
        cleaned = voice.validate_voice({"enabled": True, "base_url": " http://127.0.0.1:52625/v1/ ", "language": "de"})
        self.assertEqual((cleaned["base_url"], cleaned["language"]), ("http://127.0.0.1:52625/v1", "de"))
        for bad, message in (({"enabled": "yes"}, "'enabled'"), ({"base_url": "ftp://x"}, "'base_url'"),
                             ({"language": "English"}, "'language'"), ({"loud": 1}, "unknown")):
            with self.assertRaisesRegex(SettingsError, message):
                validate_settings({"voice": bad})


class ListeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Speech)
        self.server.uploads = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.voice = {**voice.VOICE_DEFAULTS, "enabled": True,
                      "base_url": f"http://127.0.0.1:{self.server.server_address[1]}/v1"}
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.runtime = Path(folder.name)
        self.listener = voice.Listener(self.runtime)

    def microphone(self, quiet: int, loud: int, level: int = 8000):
        return mock.patch.object(voice, "_recorder", return_value=[sys.executable, "-c", FAKE_MICROPHONE, str(quiet),
                                                                   str(loud), str(level)])

    def test_speech_then_a_pause_is_sent_from_memory(self) -> None:
        with self.microphone(quiet=5, loud=8):
            heard = self.listener.listen(self.voice, local_only=True)
        self.assertEqual(heard, {"text": "turn on night light"})
        path, content_type, body = self.server.uploads[0]
        self.assertEqual(path, "/v1/audio/transcriptions")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="language"\r\n\r\nen', body)
        self.assertIn(b"RIFF", body)                       # a WAV file
        self.assertNotIn(b'name="model"', body)            # none set, none sent
        self.assertFalse((self.runtime / "voice").exists())
        self.assertFalse(self.listener.active)

    def test_clear_cache_removes_only_abandoned_recordings(self) -> None:
        folder = self.runtime / "voice"
        folder.mkdir()
        (folder / ("b" * 32 + ".wav")).touch()
        keep = folder / "song.wav"
        keep.touch()
        self.listener.clear_cache()
        self.assertEqual(list(folder.iterdir()), [keep])

    def test_capture_indicator_clears_before_transcription(self) -> None:
        changes = []
        listener = voice.Listener(self.runtime, changes.append)

        def transcribe(settings, audio):
            self.assertEqual(changes, [True, False])
            self.assertTrue(listener.active)
            return "hello"

        with self.microphone(quiet=5, loud=8), mock.patch.object(voice, "transcribe", transcribe):
            self.assertEqual(listener.listen(self.voice, local_only=True), {"text": "hello"})
        self.assertEqual(changes, [True, False])

    def test_tones_bracket_capture_and_finish_before_transcription(self) -> None:
        events = []
        ui = {"robot_style": "orbit"}
        listener = voice.Listener(self.runtime, lambda active: events.append("capture" if active else "closed"))

        def cue(settings, event, *, wait=False):
            self.assertIs(settings, ui)
            self.assertEqual(wait, event == "mic_ready")
            events.append(event)

        def transcribe(settings, audio):
            events.append("transcribe")
            return "hello"

        with self.microphone(quiet=4, loud=8), mock.patch.object(voice.sounds, "play", cue), \
                mock.patch.object(voice, "transcribe", transcribe):
            listener.listen(self.voice, local_only=True, ui=ui)
        self.assertEqual(events, ["mic_ready", "capture", "closed", "mic_done", "transcribe"])

    def test_discard_during_ready_tone_skips_microphone_and_completion(self) -> None:
        def cue(settings, event, *, wait=False):
            self.assertEqual((event, wait), ("mic_ready", True))
            self.listener.stop(discard=True)

        with self.microphone(quiet=4, loud=8), mock.patch.object(voice.sounds, "play", cue), \
                mock.patch.object(voice.subprocess, "Popen") as recorder:
            self.assertEqual(self.listener.listen(self.voice, local_only=True), {"text": "", "discarded": True})
        recorder.assert_not_called()

    def test_device_that_never_opens_does_not_show_recording(self) -> None:
        changes = []
        listener = voice.Listener(self.runtime, changes.append)
        with mock.patch.object(voice, "_recorder", return_value=[sys.executable, "-c", "pass"]):
            with self.assertRaises(voice.VoiceError):
                listener.listen(self.voice, local_only=True)
        self.assertEqual(changes, [])

    def test_quiet_speech_is_loudness_normalized_before_it_is_sent(self) -> None:
        with self.microphone(quiet=5, loud=8, level=1500):
            self.listener.listen(self.voice, local_only=False)
        body = self.server.uploads[0][2]
        wav = body[body.index(b"RIFF"):]
        samples = array.array("h", wav[44:wav.index(b"\r\n--")])
        speech = samples[5 * 1600: 13 * 1600]
        level = (sum(sample * sample for sample in speech) / len(speech)) ** 0.5
        self.assertAlmostEqual(level, voice.TARGET_SPEECH_RMS, delta=voice.TARGET_SPEECH_RMS * 0.05)
        self.assertLessEqual(max(abs(sample) for sample in samples), voice.PEAK_LIMIT)
        self.assertEqual(int.from_bytes(wav[24:28], "little"), 16000)   # 16 kHz
        self.assertEqual(int.from_bytes(wav[22:24], "little"), 1)       # mono

    def test_silence_is_never_sent(self) -> None:
        with self.microphone(quiet=5, loud=0), mock.patch.object(voice, "WAIT_FOR_SPEECH_SECONDS", 0.8):
            with self.assertRaises(voice.VoiceError) as caught:
                self.listener.listen(self.voice, local_only=False)
        self.assertEqual(caught.exception.code, "no_speech")
        self.assertEqual(self.server.uploads, [])

    def test_stop_with_discard_sends_nothing(self) -> None:
        threading.Timer(0.6, lambda: self.listener.stop(discard=True)).start()
        with self.microphone(quiet=2, loud=200):
            self.assertEqual(self.listener.listen(self.voice, local_only=False), {"text": "", "discarded": True})
        self.assertEqual(self.server.uploads, [])

    def test_an_online_service_is_refused_while_local_only(self) -> None:
        online = {**self.voice, "base_url": "https://speech.example.com/v1"}
        with self.assertRaises(voice.VoiceError) as caught:
            self.listener.listen(online, local_only=True)
        self.assertEqual(caught.exception.code, "local_only")
        with self.assertRaises(voice.VoiceError) as unset:
            self.listener.listen(voice.VOICE_DEFAULTS, local_only=False)
        self.assertEqual(unset.exception.code, "not_set_up")

    def test_find_skips_services_that_do_not_answer_and_online_ones(self) -> None:
        dead = "http://127.0.0.1:9/v1"
        self.assertEqual(voice.find_service(["https://speech.example.com/v1", dead, self.voice["base_url"] + "/"]),
                         self.voice["base_url"])
        self.assertEqual(voice.find_service([dead]), "")

    def test_a_silent_or_missing_microphone_is_unavailable_not_a_bad_gateway(self) -> None:
        from happy_bot import daemon_routes
        status, reply = daemon_routes._voice_error(voice.VoiceError("no_microphone", "No sound came from the microphone."))
        self.assertEqual((status, reply["code"]), (503, "no_microphone"))
        self.assertEqual(daemon_routes._voice_error(voice.VoiceError("service", "down"))[0], 502)

    def test_final_listening_errors_sound_once_and_busy_capture_stays_quiet(self) -> None:
        from happy_bot import daemon_routes
        server = mock.Mock(settings={"ui": {}, "voice": self.voice})
        with mock.patch.object(voice.sounds, "play") as play:
            server.voice.listen.side_effect = voice.VoiceError("service", "Service unavailable")
            self.assertEqual(daemon_routes.voice_listen(server, {}, {})[0], 502)
            server.voice.listen.side_effect = voice.VoiceError("busy", "Already listening")
            self.assertEqual(daemon_routes.voice_listen(server, {}, {})[0], 409)
        play.assert_called_once_with({}, "error")

    def test_check_sends_silence_and_accepts_text(self) -> None:
        self.assertEqual(voice.check_service({**self.voice, "model": "whisper-v3:turbo"}), {"ok": True})
        self.assertIn(b'name="model"\r\n\r\nwhisper-v3:turbo', self.server.uploads[0][2])


if __name__ == "__main__":
    unittest.main()

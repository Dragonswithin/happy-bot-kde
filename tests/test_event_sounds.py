"""Check the bundled repertoire and event rules without playing on the desktop."""

import hashlib
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from happy_bot import ask_stream, daemon_routes, sounds, ui_settings


class EventSoundTests(unittest.TestCase):
    def test_each_robot_has_a_distinct_recording_for_each_event(self):
        signatures = set()
        for robot in ui_settings.ROBOT_STYLES:
            for event in ui_settings.SOUND_EVENTS:
                with self.subTest(robot=robot, event=event):
                    with wave.open(str(sounds._asset(robot, event)), "rb") as audio:
                        duration = audio.getnframes() / audio.getframerate()
                        self.assertGreater(duration, .05)
                        self.assertLess(duration, 3)
                        frames = audio.readframes(audio.getnframes())
                    self.assertTrue(any(frames))
                    signature = hashlib.sha256(frames).digest()
                    self.assertNotIn(signature, signatures)
                    signatures.add(signature)

    def test_preview_respects_selection_and_explicit_mute_survives_preview(self):
        ui = ui_settings.validate_ui({"robot_style": "sprig", "event_sounds": {
            "alarm": {"enabled": True, "theme": "rivet"}}})
        server = mock.Mock(settings={"ui": ui})
        server.voice.active = False
        with mock.patch.object(sounds, "preview", return_value=True) as player:
            self.assertFalse(sounds.play(ui, "open", wait=True))
            self.assertTrue(sounds.play(ui, "alarm", wait=True))
            player.assert_called_once_with("rivet", "alarm")
            self.assertEqual(200, daemon_routes.preview_sound(server, {}, {"event": "open", "theme": "sonar"})[0])
            player.assert_called_with("sonar", "open")
            self.assertFalse(ui["event_sounds"]["open"]["enabled"])
            self.assertEqual(400, daemon_routes.preview_sound(server, {}, {"event": "../file", "theme": "pip"})[0])

    def test_long_turn_plays_one_sound_for_its_final_outcome(self):
        def cue(stop="answered", outcomes=(), background=False, long=True):
            actions = [{"summary": "action", "outcome": outcome} for outcome in outcomes]
            return ask_stream._completion_sound({"stop": stop, "actions": actions}, background, long)

        self.assertEqual(cue(), "complete")
        self.assertEqual(cue(long=False), "")
        self.assertEqual(cue(background=True), "background")
        self.assertEqual(cue(outcomes=["failed"], background=True), "error")
        self.assertEqual(cue(outcomes=["failed", "done"]), "complete")
        self.assertEqual(cue(outcomes=["declined"]), "")
        self.assertEqual(cue(outcomes=["declined"], background=True), "error")
        self.assertEqual(cue("cancelled", ["failed"]), "")
        self.assertEqual(cue("step_limit"), "error")

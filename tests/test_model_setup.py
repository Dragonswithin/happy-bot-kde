"""Tests for adding an AI model with one press and placing it in the order (``model_setup.use``), and the presets.

``use`` runs against a stand-in daemon whose ``replace_settings`` validates with the real settings
schema. The model check and the service's model list are faked, so no model is asked anything and
nothing goes online. The presets are checked for the fields the settings page relies on.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import model_presets, model_setup  # noqa: E402
from happy_bot.settings import validate_settings  # noqa: E402

NPU = "http://127.0.0.1:52625/v1"
GPU = "http://127.0.0.1:52626/v1"


class FakeDaemon:
    """Just what ``model_setup.use`` needs from ``AssistantServer``."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = validate_settings(settings or {})

    def replace_settings(self, new_settings: Any) -> dict[str, Any]:
        self.settings = validate_settings(new_settings)
        return self.settings


class UseModelTests(unittest.TestCase):
    def use(self, daemon: FakeDaemon, body: dict[str, Any], check: Any = None) -> dict[str, Any]:
        passing = [{"check": "answers", "status": "pass", "detail": "ready"},
                   {"check": "tool_call", "status": "pass", "detail": "get_weather"}]
        with mock.patch.object(model_setup, "list_models", return_value=[{"id": body.get("model"), "context_window": 65536}]), \
                mock.patch.object(model_setup.model_check, "run", return_value=check or passing):
            return model_setup.use(daemon, body)

    def test_npu_first_and_gpu_if_it_fails(self) -> None:
        daemon = FakeDaemon()
        first = self.use(daemon, {"base_url": NPU, "model": "qwen3.6-moe:35b-a3b", "job": "main"})
        backup = self.use(daemon, {"base_url": GPU, "model": "qwen3.6-35b-a3b", "job": "backup"})
        self.assertTrue(first["ok"] and backup["ok"], (first, backup))
        self.assertEqual(daemon.settings["model_order"], [first["name"], backup["name"]])
        self.assertEqual(daemon.settings["active_model"], first["name"])
        self.assertEqual(daemon.settings["models"][first["name"]]["context_window"], 65536)

    def test_an_online_model_may_come_after_a_local_one(self) -> None:
        daemon = FakeDaemon()
        self.use(daemon, {"base_url": NPU, "model": "a", "job": "main"})
        online = self.use(daemon, {"base_url": "https://api.example.com/v1", "model": "m", "job": "backup"})
        self.assertTrue(online["ok"], online)
        self.assertEqual(daemon.settings["model_order"][1], online["name"])

    def test_a_preset_needs_its_key_and_fills_the_address(self) -> None:
        preset = model_presets.PRESETS[0]
        daemon = FakeDaemon()
        refused = self.use(daemon, {"preset": preset["id"], "model": preset["models"][0]["id"]})
        self.assertIn("API key", refused["error"])
        added = self.use(daemon, {"preset": preset["id"], "model": preset["models"][0]["id"], "api_key": "k", "job": "none"})
        self.assertTrue(added["ok"], added)
        self.assertEqual(daemon.settings["models"][added["name"]]["base_url"], preset["base_url"].rstrip("/"))

    def test_a_model_that_does_not_answer_is_not_kept(self) -> None:
        daemon = FakeDaemon()
        result = self.use(daemon, {"base_url": NPU, "model": "x", "job": "main"},
                          check=[{"check": "answers", "status": "fail", "detail": "refused"}])
        self.assertFalse(result["ok"])
        self.assertIn("refused", result["error"])
        self.assertEqual((daemon.settings["models"], daemon.settings["model_order"]), ({}, []))

    def test_a_problem_found_by_the_check_is_named_when_adding(self) -> None:
        daemon = FakeDaemon()
        result = self.use(daemon, {"base_url": NPU, "model": "x", "job": "main"}, check=[
            {"check": "answers", "status": "pass", "detail": "ready"},
            {"check": "parallel_calls", "status": "fail", "detail": "calls arrived broken"}])
        self.assertTrue(result["ok"])  # kept: it answers
        self.assertFalse(result["passed"])
        self.assertIn("using two tools at once: calls arrived broken", result["message"])

    def test_asking_the_second_first_reorders_without_duplicates(self) -> None:
        daemon = FakeDaemon()
        a = self.use(daemon, {"base_url": NPU, "model": "a", "job": "main"})
        b = self.use(daemon, {"base_url": GPU, "model": "b", "job": "none"})
        self.use(daemon, {"base_url": GPU, "model": "b", "job": "main"})
        self.assertEqual(daemon.settings["model_order"], [b["name"], a["name"]])


class PresetTests(unittest.TestCase):
    def test_every_preset_has_what_the_page_shows(self) -> None:
        for preset in model_presets.listing():
            with self.subTest(preset=preset["id"]):
                self.assertTrue(preset["base_url"].startswith("https://"))
                self.assertTrue(preset["key_url"].startswith("https://"))
                for key in ("title", "description", "privacy", "key_steps"):
                    self.assertTrue(preset[key].strip())
                self.assertTrue(preset["models"])
        self.assertEqual(len({preset["id"] for preset in model_presets.PRESETS}), len(model_presets.PRESETS))


if __name__ == "__main__":
    unittest.main()

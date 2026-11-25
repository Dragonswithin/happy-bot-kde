"""Tests for "Fix selected text": choosing the AI, rewriting, noting the selection and pasting it back.

``text_rewrite`` runs against fake providers, so no AI is asked; the privacy, "local only" and
spending rules are checked on the models it chooses, and the provider's "no thinking" option on
the requests it would send. ``selection_fix`` runs with the selection,
the window list, the clipboard and the typing portal faked, so nothing on the desktop changes.
The daemon routes are called directly with a stand-in server.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import app_control, daemon_routes, input_portal, selection_fix, text_rewrite  # noqa: E402
from happy_bot.conversation import TextDelta, TurnEnd  # noqa: E402
from happy_bot.providers import ProviderError  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402

LOCAL = {"provider": "openai_compatible", "base_url": "http://127.0.0.1:52626/v1", "model": "gpu"}
ONLINE = {"provider": "openai_compatible", "base_url": "https://api.example.com/v1", "model": "big"}


def settings(policy: str = "local", local_only: bool = False, order=("online", "local")) -> dict:
    return {"model_order": list(order), "models": {"online": dict(ONLINE), "local": dict(LOCAL)},
            "agent": {"app_context": policy, "local_only": local_only}}


class FakeProvider:
    def __init__(self, reply: str = "", error: str = "") -> None:
        self.reply, self.error, self.seen = reply, error, []

    def stream(self, messages, tools, cancel):
        self.seen.append((messages, tools))
        if self.error:
            raise ProviderError(self.error)
        yield TextDelta(self.reply)
        yield TurnEnd(input_tokens=10, output_tokens=5)


class RewriteTests(unittest.TestCase):
    def test_privacy_setting_decides_which_ais_may_see_the_text(self) -> None:
        self.assertEqual([name for name, _ in text_rewrite.allowed_models(settings("local"))], ["local"])
        self.assertEqual([name for name, _ in text_rewrite.allowed_models(settings("any"))], ["online", "local"])
        self.assertEqual([name for name, _ in text_rewrite.allowed_models(settings("off"))], ["local"])
        self.assertEqual([name for name, _ in text_rewrite.allowed_models(settings("any", local_only=True))], ["local"])
        with mock.patch.object(text_rewrite.spend, "over_cap", return_value=True):
            self.assertEqual(text_rewrite.allowed_models(settings("any")), [])

    def test_tasks_name_the_users_language_and_say_what_replaces(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}):
            wording, replaces = text_rewrite.task("translate")
            self.assertIn("into German", wording)
            self.assertTrue(replaces)
            self.assertFalse(text_rewrite.task("explain")[1])
        self.assertEqual(text_rewrite.task("fix", "  make it   formal "), ("Do this with the text: make it formal", True))
        with self.assertRaises(text_rewrite.RewriteError):
            text_rewrite.task("shout")

    def test_replies_are_cleaned_of_what_models_add(self) -> None:
        cases = {"<think>hmm</think>\nHello there.": "Hello there.", "```\nfixed text\n```": "fixed text",
                 '"Quoted answer."': "Quoted answer.", "“Curly.”": "Curly.", 'He said "hi".': 'He said "hi".'}
        for reply, cleaned in cases.items():
            with self.subTest(reply=reply):
                self.assertEqual(text_rewrite.clean(reply), cleaned)

    def test_translations_name_their_language_first_and_same_language_text_is_refused(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}):
            with mock.patch.object(text_rewrite, "create_provider",
                                   return_value=FakeProvider(reply="Spanish\nWhere is the library?")):
                self.assertEqual(text_rewrite.rewrite(settings(), "¿Dónde está la biblioteca?", "translate")["text"],
                                 "Where is the library?")
            with mock.patch.object(text_rewrite, "create_provider", return_value=FakeProvider(reply="**English**\n")), \
                    self.assertRaisesRegex(text_rewrite.RewriteError, "already in English"):
                text_rewrite.rewrite(settings(), "The meeting is at 3pm.", "translate")
            with mock.patch.object(text_rewrite, "create_provider", return_value=FakeProvider(reply="Bonjour.")):
                self.assertEqual(text_rewrite.rewrite(settings(), "Hello.", "", "translate into French")["text"],
                                 "Bonjour.")

    def test_explaining_has_its_own_instructions(self) -> None:
        provider = FakeProvider(reply="It says hello.")
        with mock.patch.object(text_rewrite, "create_provider", return_value=provider):
            self.assertFalse(text_rewrite.rewrite(settings(), "Hello.", "explain")["replaces"])
        self.assertEqual(provider.seen[0][0][0].text, text_rewrite.EXPLAIN_SYSTEM)

    def test_the_first_allowed_ai_answers_and_a_failing_one_hands_over(self) -> None:
        broken, working = FakeProvider(error="refused"), FakeProvider(reply="Their fixed.")
        order = settings("any", order=("online", "local"))
        with mock.patch.object(text_rewrite, "create_provider", side_effect=[broken, working]), \
                mock.patch.object(text_rewrite.spend, "record") as recorded:
            result = text_rewrite.rewrite(order, "there fixed", "fix")
        self.assertEqual(result, {"text": "Their fixed.", "model": "local", "replaces": True})
        recorded.assert_called_once_with("local", order["models"]["local"], 10, 5)
        messages, tools = working.seen[0]
        self.assertEqual(tools, [])
        self.assertIn("Correct the spelling", messages[1].text)
        self.assertTrue(messages[1].text.endswith("there fixed"))

    def test_nothing_selected_too_much_no_ai_or_all_failing_is_said_plainly(self) -> None:
        with self.assertRaisesRegex(text_rewrite.RewriteError, "Nothing is selected"):
            text_rewrite.rewrite(settings(), "   ", "fix")
        with self.assertRaisesRegex(text_rewrite.RewriteError, "too much"):
            text_rewrite.rewrite(settings(), "x" * (text_rewrite.MAX_TEXT_CHARS + 1), "fix")
        with self.assertRaisesRegex(text_rewrite.RewriteError, "No AI may see"):
            text_rewrite.rewrite(settings("local", order=("online",)), "text", "fix")
        with mock.patch.object(text_rewrite, "create_provider", return_value=FakeProvider(reply="  ")), \
                self.assertRaisesRegex(text_rewrite.RewriteError, "empty"):
            text_rewrite.rewrite(settings(), "text", "fix")


class NoThinkingTests(unittest.TestCase):
    STREAM = (b'data: {"choices":[{"delta":{"content":"Fixed."}}]}\n\n'
              b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\ndata: [DONE]\n\n')

    def run_request(self, base_url: str, refuse: bool) -> list[dict]:
        from happy_bot.providers import openai_compatible
        sent = []

        def fake_urlopen(request, timeout):
            body = json.loads(request.data)
            sent.append(body)
            if refuse and "chat_template_kwargs" in body:
                raise openai_compatible.HTTPError(request.full_url, 400, "unknown field", {}, io.BytesIO(b"{}"))
            return io.BytesIO(self.STREAM)

        provider = text_rewrite.create_provider({**LOCAL, "base_url": base_url}, no_thinking=True)
        with mock.patch.object(openai_compatible, "urlopen", side_effect=fake_urlopen):
            events = list(provider.stream([], [], threading.Event()))
        self.assertEqual("".join(event.text for event in events if isinstance(event, TextDelta)), "Fixed.")
        return sent

    def test_local_services_are_asked_to_skip_thinking_and_a_refusal_is_retried_without_it(self) -> None:
        sent = self.run_request("http://127.0.0.1:52626/v1", refuse=False)
        self.assertEqual(sent[0]["chat_template_kwargs"], {"enable_thinking": False})
        sent = self.run_request("http://127.0.0.1:52625/v1", refuse=True)
        self.assertEqual(["chat_template_kwargs" in body for body in sent], [True, False])
        self.assertIn("stream_options", sent[1])
        sent = self.run_request("https://api.example.com/v1", refuse=False)
        self.assertNotIn("chat_template_kwargs", sent[0])


class SelectionTests(unittest.TestCase):
    WINDOW = {"id": "{w1}", "title": "notes.txt — Kate", "app": "org.kde.kate"}

    def test_the_note_holds_the_selection_and_its_window_until_the_next_capture(self) -> None:
        note = selection_fix.SelectionNote()
        found = {"app": "Kwi", "class": "org.kde.kwi", "title": "~", "icon": "", "window": "{t}"}
        with mock.patch.object(selection_fix.screen, "selected_text", return_value="ls -la"), \
                mock.patch.object(selection_fix.desktop_context, "current_application", return_value=found):
            captured = note.capture()
        self.assertEqual(captured, {"text": "ls -la", "window": "{t}", "app": "Kwi", "title": "~", "terminal": True})
        self.assertEqual(note.current(), captured)
        with mock.patch.object(selection_fix.screen, "selected_text", return_value=selection_fix.NOTHING_SELECTED), \
                mock.patch.object(selection_fix.desktop_context, "current_application",
                                  return_value={**found, "class": "org.kde.kate", "app": "Kate"}):
            self.assertEqual(note.capture()["text"], "")
            self.assertFalse(note.current()["terminal"])

    def test_replace_pastes_over_the_selection_and_gives_the_clipboard_back(self) -> None:
        copied, pressed, focused, timers = [], [], [], []
        portal = mock.Mock()
        portal.press_keys.side_effect = pressed.append

        class Timer:
            def __init__(self, delay, function):
                timers.append(function)

            def start(self):
                pass

        with mock.patch.object(selection_fix.windows, "describe_window", return_value=self.WINDOW), \
                mock.patch.object(selection_fix.windows, "focus_window", side_effect=focused.append), \
                mock.patch.object(selection_fix, "_clipboard_text", return_value="my own clipboard"), \
                mock.patch.object(selection_fix, "_set_clipboard", side_effect=copied.append), \
                mock.patch.object(selection_fix.input_portal, "shared", return_value=portal), \
                mock.patch.object(selection_fix.threading, "Timer", Timer), \
                mock.patch.object(selection_fix.time, "sleep"):
            message = selection_fix.replace("{w1}", "Fixed text.")
            timers[0]()
        self.assertIn("notes.txt", message)
        self.assertEqual(focused, [{"window": "{w1}"}])
        self.assertEqual(pressed, ["ctrl+v"])
        self.assertEqual(copied, ["Fixed text.", "my own clipboard"])

    def test_replace_refuses_terminals_closed_windows_and_says_when_typing_is_not_allowed(self) -> None:
        with mock.patch.object(selection_fix.windows, "describe_window",
                               return_value={**self.WINDOW, "app": "org.kde.kwi"}), \
                self.assertRaisesRegex(selection_fix.ReplaceError, "terminals"):
            selection_fix.replace("{w1}", "text")
        with mock.patch.object(selection_fix.windows, "describe_window", side_effect=ToolFailure("no window")), \
                self.assertRaisesRegex(selection_fix.ReplaceError, "closed"):
            selection_fix.replace("{gone}", "text")
        for window, text in (("", "text"), ("{w1}", "")):
            with self.subTest(window=window, text=text), self.assertRaises(selection_fix.ReplaceError):
                selection_fix.replace(window, text)
        portal = mock.Mock()
        portal.press_keys.side_effect = input_portal.InputUnavailable("the user declined")
        with mock.patch.object(selection_fix.windows, "describe_window", return_value=self.WINDOW), \
                mock.patch.object(selection_fix.windows, "focus_window"), \
                mock.patch.object(selection_fix, "_clipboard_text", return_value=None), \
                mock.patch.object(selection_fix, "_set_clipboard") as copied, \
                mock.patch.object(selection_fix.input_portal, "shared", return_value=portal), \
                mock.patch.object(selection_fix.time, "sleep"), \
                self.assertRaisesRegex(selection_fix.ReplaceError, "Allow typing"):
            selection_fix.replace("{w1}", "Fixed.")
        copied.assert_called_once_with("Fixed.")  # left on the clipboard to paste by hand


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        class Server:
            runtime_dir = Path(folder.name)
            selection = selection_fix.SelectionNote()

        Server.settings = settings()
        self.server = Server()

    def test_the_fix_shortcut_notes_the_selection_before_the_app_opens(self) -> None:
        self.assertIn("fix", app_control.ACTIONS)
        with mock.patch.object(self.server.selection, "capture") as capture, \
                mock.patch.object(app_control, "running", return_value=True):
            daemon_routes.app_show(self.server, {}, {"action": "fix"})
            capture.assert_called_once_with()
            daemon_routes.app_show(self.server, {}, {"action": "open"})
            capture.assert_called_once_with()

    def test_rewrite_and_replace_routes_report_problems_and_log_the_paste(self) -> None:
        status, reply = daemon_routes.selection_rewrite(self.server, {}, {"text": "", "style": "fix"})
        self.assertEqual((status, reply["code"]), (400, "invalid"))
        with mock.patch.object(selection_fix, "replace", return_value="Replaced."):
            status, reply = daemon_routes.selection_replace(self.server, {}, {"window": "{w1}", "text": "Hi."})
        self.assertEqual((status, reply["message"]), (200, "Replaced."))
        logged = json.loads((self.server.runtime_dir / "actions.jsonl").read_text().splitlines()[0])
        self.assertEqual((logged["tool"], json.loads(logged["arguments"])), ("replace_selection", {"window": "{w1}", "characters": 3}))
        with mock.patch.object(selection_fix, "replace", side_effect=selection_fix.ReplaceError("no terminals")):
            self.assertEqual(daemon_routes.selection_replace(self.server, {}, {"window": "{w1}", "text": "x"})[0], 409)


if __name__ == "__main__":
    unittest.main()

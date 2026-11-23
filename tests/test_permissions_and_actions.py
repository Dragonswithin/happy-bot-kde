"""Tests for the permission gate and the tools that change things.

Gate tests drive ``PermissionGate`` and ``ApprovalBroker`` directly and
through the agent loop with a scripted provider. File and shell tools run
for real inside a temporary directory. Application matching uses desktop
files written to a temporary directory. System tools are tested only for
their classifiers and argument validation, so nothing on the desktop changes.
The end-to-end test sends an approval over HTTP while a turn is waiting.
"""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model_service import FakeModelService, chunks_for  # noqa: E402

from kde_ai_assistant.agent_loop import run_turn  # noqa: E402
from kde_ai_assistant.conversation import Message, TextDelta, ToolCall, ToolCallReady, TurnEnd  # noqa: E402
from kde_ai_assistant.daemon_http import AssistantServer  # noqa: E402
from kde_ai_assistant.permissions import ApprovalBroker, PermissionGate, needs_approval  # noqa: E402
from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tools import apps, files, shell, system  # noqa: E402
from kde_ai_assistant.tools.catalog import builtin_tools  # noqa: E402
from kde_ai_assistant.tools.registry import (  # noqa: E402
    RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, ToolRegistry, object_schema)


class PolicyTests(unittest.TestCase):
    def test_policy_table(self) -> None:
        expected = {
            "danger": {RISK_READ: False, RISK_CHANGE: False, RISK_DANGER: True},
            "changes": {RISK_READ: False, RISK_CHANGE: True, RISK_DANGER: True},
            "everything": {RISK_READ: True, RISK_CHANGE: True, RISK_DANGER: True},
        }
        for policy, row in expected.items():
            for risk, asks in row.items():
                with self.subTest(policy=policy, risk=risk):
                    self.assertEqual(needs_approval(policy, risk), asks)

    def test_policy_setting_is_validated(self) -> None:
        self.assertEqual(validate_settings({})["approval_policy"], "danger")
        self.assertEqual(validate_settings({"approval_policy": "changes"})["approval_policy"], "changes")
        with self.assertRaisesRegex(SettingsError, "approval_policy"):
            validate_settings({"approval_policy": "never"})


class FolderTests(unittest.TestCase):
    def test_folders_come_from_overrides_then_the_system_then_defaults(self) -> None:
        import os
        from unittest import mock

        from kde_ai_assistant.agent_loop import system_prompt, user_folders

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "user-dirs.dirs").write_text(
                '# comment\nXDG_DOCUMENTS_DIR="$HOME/Papers"\nXDG_DOWNLOAD_DIR="/mnt/big/Downloads"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                home = os.path.expanduser("~")
                found = user_folders({"Downloads": "/data/dl"})
                self.assertEqual(found["Documents"], f"{home}/Papers")      # system setting
                self.assertEqual(found["Downloads"], "/data/dl")             # override wins
                self.assertEqual(found["Desktop"], f"{home}/Desktop")        # default
                self.assertIn("Downloads is /data/dl", system_prompt({"Downloads": "/data/dl"}))
                self.assertIn("Downloads is /mnt/big/Downloads", system_prompt())

    def test_folder_setting_is_validated(self) -> None:
        self.assertEqual(validate_settings({})["folders"], {})
        self.assertEqual(validate_settings({"folders": {"Documents": "/srv/docs"}})["folders"], {"Documents": "/srv/docs"})
        self.assertTrue(validate_settings({"folders": {"Desktop": "~/Work"}})["folders"]["Desktop"].endswith("/Work"))
        for bad in ({"Cellar": "/x"}, {"Desktop": "relative/path"}, {"Desktop": 5}):
            with self.subTest(bad=bad), self.assertRaisesRegex(SettingsError, "'folders'"):
                validate_settings({"folders": bad})


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runtime = Path(self._tmp.name)
        self.broker = ApprovalBroker()
        self.events: list[dict] = []
        self.cancel = threading.Event()

    def gate(self, policy: str = "danger", timeout: float = 5.0) -> PermissionGate:
        return PermissionGate(policy, self.broker, self.events.append, self.cancel, self.runtime, timeout)

    def answer_when_asked(self, decision: str, remember: bool = False) -> threading.Thread:
        def worker() -> None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                asked = [event for event in self.events if event["type"] == "approval_required"]
                if asked:
                    self.broker.resolve(asked[-1]["id"], decision, remember)
                    return
                time.sleep(0.01)
        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(thread.join)
        return thread

    def audit(self) -> list[dict]:
        path = self.runtime / "actions.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_reads_and_changes_run_without_asking_under_the_default_policy(self) -> None:
        self.assertEqual(self.gate().check("c1", "t", {}, RISK_READ, "s", ""), (True, ""))
        self.assertEqual(self.gate().check("c2", "t", {"a": 1}, RISK_CHANGE, "s", ""), (True, ""))
        self.assertEqual(self.events, [])
        self.assertEqual([(r["tool"], r["risk"], r["outcome"]) for r in self.audit()],
                         [("t", "change", "ran without asking")])

    def test_danger_asks_and_allow_runs_it(self) -> None:
        self.answer_when_asked("allow")
        allowed, message = self.gate().check("c1", "trash_path", {"path": "/x"}, RISK_DANGER, "Move to trash: /x", "why")
        self.assertEqual((allowed, message), (True, ""))
        asked, resolved = self.events
        self.assertEqual((asked["tool"], asked["risk"], asked["summary"], asked["detail"], asked["can_remember"]),
                         ("trash_path", "danger", "Move to trash: /x", "why", False))
        self.assertEqual((resolved["type"], resolved["decision"], resolved["id"]),
                         ("approval_resolved", "allow", asked["id"]))
        self.assertEqual(self.audit()[0]["outcome"], "allow")

    def test_deny_timeout_and_cancel_all_refuse(self) -> None:
        self.answer_when_asked("deny")
        allowed, message = self.gate().check("c1", "t", {}, RISK_DANGER, "s", "")
        self.assertFalse(allowed)
        self.assertIn("declined", message)

        self.events.clear()
        allowed, message = self.gate(timeout=0.3).check("c2", "t", {}, RISK_DANGER, "s", "")
        self.assertFalse(allowed)
        self.assertIn("did not answer", message)
        self.assertEqual(self.events[-1]["decision"], "timeout")

        self.events.clear()
        threading.Timer(0.1, self.cancel.set).start()
        allowed, message = self.gate().check("c3", "t", {}, RISK_DANGER, "s", "")
        self.assertFalse(allowed)
        self.assertEqual(self.events[-1]["decision"], "cancelled")
        self.assertEqual([r["outcome"] for r in self.audit()], ["deny", "timeout", "cancelled"])

    def test_session_grants_apply_to_changes_but_never_to_danger(self) -> None:
        self.answer_when_asked("allow", remember=True)
        self.assertTrue(self.gate("changes").check("c1", "set_volume", {}, RISK_CHANGE, "s", "")[0])
        self.assertTrue(self.events[0]["can_remember"])
        self.events.clear()
        self.assertTrue(self.gate("changes").check("c2", "set_volume", {}, RISK_CHANGE, "s", "")[0])
        self.assertEqual(self.events, [])

        self.answer_when_asked("allow", remember=True)
        self.assertTrue(self.gate().check("c3", "trash_path", {}, RISK_DANGER, "s", "")[0])
        self.events.clear()
        self.answer_when_asked("deny")
        self.assertFalse(self.gate().check("c4", "trash_path", {}, RISK_DANGER, "s", "")[0])

    def test_broker_rejects_bad_or_repeated_answers(self) -> None:
        approval_id = self.broker.open()
        self.assertFalse(self.broker.resolve("unknown", "allow"))
        self.assertFalse(self.broker.resolve(approval_id, "maybe"))
        self.assertTrue(self.broker.resolve(approval_id, "deny"))
        self.assertFalse(self.broker.resolve(approval_id, "allow"))
        self.assertEqual(self.broker.wait(approval_id, self.cancel, 1)[0], "deny")

    def test_agent_loop_does_not_run_a_refused_call_and_tells_the_model(self) -> None:
        ran: list[str] = []
        registry = ToolRegistry([
            Tool("wipe", "x", object_schema(), RISK_DANGER, lambda a: ran.append("wipe") or "wiped",
                 summarize=lambda a: "Wipe everything"),
            Tool("look", "x", object_schema(), RISK_READ, lambda a: ran.append("look") or "seen"),
        ])

        class Provider:
            def __init__(self) -> None:
                self.replies = [[ToolCallReady(ToolCall("1", "wipe", {})), ToolCallReady(ToolCall("2", "look", {}))],
                                [TextDelta("Understood.")]]
                self.seen: list[list[Message]] = []

            def stream(self, messages, tools, cancel):
                self.seen.append(list(messages))
                yield from self.replies.pop(0)
                yield TurnEnd("stop")

        provider = Provider()
        self.answer_when_asked("deny")
        history = [Message("user", "clean up")]
        run_turn(provider, history, registry, self.events.append, self.cancel, gate=self.gate())
        self.assertEqual(ran, ["look"])
        kinds = [event["type"] for event in self.events]
        self.assertEqual(kinds, ["tool_call", "approval_required", "approval_resolved", "tool_result",
                                 "tool_call", "tool_result", "text_delta", "done"])
        self.assertEqual(self.events[0]["summary"], "Wipe everything")
        self.assertFalse(self.events[3]["ok"])
        self.assertIn("declined", provider.seen[1][-2].text)

    def test_a_call_that_cannot_succeed_fails_before_the_user_is_asked(self) -> None:
        from kde_ai_assistant.tools.files import file_tools
        registry = ToolRegistry(file_tools())

        class Provider:
            replies = [[ToolCallReady(ToolCall("1", "trash_path", {"path": "/nonexistent/ghost.txt"}))], [TextDelta("ok")]]

            def stream(self, messages, tools, cancel):
                yield from self.replies.pop(0)
                yield TurnEnd("stop")

        run_turn(Provider(), [Message("user", "x")], registry, self.events.append, self.cancel, gate=self.gate())
        self.assertNotIn("approval_required", [event["type"] for event in self.events])
        result = next(event for event in self.events if event["type"] == "tool_result")
        self.assertFalse(result["ok"])
        self.assertIn("does not exist", result["text"])
        self.assertEqual(self.audit(), [])

    def test_a_failing_classifier_is_treated_as_danger(self) -> None:
        registry = ToolRegistry([Tool("odd", "x", object_schema(), RISK_READ, str, classify=lambda a: 1 / 0)])
        risk, _summary, detail = registry.assess("odd", {})
        self.assertEqual(risk, RISK_DANGER)
        self.assertIn("could not be checked", detail)


class FileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "old.txt").write_text("old", encoding="utf-8")
        (self.root / "folder").mkdir()

    def p(self, name: str) -> str:
        return str(self.root / name)

    def test_creating_and_appending_are_changes_and_work(self) -> None:
        new = {"path": self.p("deep/new.txt"), "content": "hello"}
        self.assertEqual(files.classify_write(new), (RISK_CHANGE, ""))
        self.assertIn("Created", files.write_text_file(new))
        append = {"path": self.p("old.txt"), "content": "+more", "append": True}
        self.assertEqual(files.classify_write(append)[0], RISK_CHANGE)
        files.write_text_file(append)
        self.assertEqual((self.root / "old.txt").read_text(), "old+more")

    def test_replacing_needs_the_overwrite_flag_and_is_danger(self) -> None:
        plain = {"path": self.p("old.txt"), "content": "new"}
        self.assertEqual(files.classify_write(plain)[0], RISK_CHANGE)
        with self.assertRaisesRegex(ToolFailure, "already exists"):
            files.write_text_file(plain)
        self.assertEqual((self.root / "old.txt").read_text(), "old")
        forced = {**plain, "overwrite": True}
        risk, reason = files.classify_write(forced)
        self.assertEqual(risk, RISK_DANGER)
        self.assertIn("replaces the contents", reason)
        self.assertIn("Replaced", files.write_text_file(forced))
        self.assertEqual(files.classify_write({"path": self.p("brand-new.txt"), "content": "x", "overwrite": True})[0],
                         RISK_CHANGE)

    def test_system_paths_are_danger_for_every_file_tool(self) -> None:
        self.assertEqual(files.classify_write({"path": "/etc/fstab", "content": "x"})[0], RISK_DANGER)
        self.assertEqual(files.classify_make_directory({"path": "/boot/new"})[0], RISK_DANGER)
        self.assertEqual(files.classify_transfer({"source": self.p("old.txt"), "destination": "/usr/bin/x"})[0],
                         RISK_DANGER)
        self.assertEqual(files.classify_transfer({"source": "/etc/hosts", "destination": self.p("h"), "_move": True})[0],
                         RISK_DANGER)
        self.assertEqual(files.classify_transfer({"source": "/etc/hosts", "destination": self.p("h")})[0], RISK_CHANGE)

    def test_move_and_copy_never_replace_without_the_flag(self) -> None:
        (self.root / "other.txt").write_text("other", encoding="utf-8")
        into_folder = {"source": self.p("old.txt"), "destination": self.p("folder")}
        self.assertEqual(files.classify_transfer(into_folder)[0], RISK_CHANGE)
        self.assertIn("folder/old.txt", files.copy_path(into_folder))
        clash = {"source": self.p("other.txt"), "destination": self.p("old.txt")}
        self.assertEqual(files.classify_transfer(clash)[0], RISK_CHANGE)
        with self.assertRaisesRegex(ToolFailure, "already exists"):
            files.move_path(clash)
        self.assertEqual(files.classify_transfer({**clash, "overwrite": True})[0], RISK_DANGER)
        files.move_path({**clash, "overwrite": True})
        self.assertEqual((self.root / "old.txt").read_text(), "other")
        self.assertFalse((self.root / "other.txt").exists())
        self.assertIn("Moved", files.move_path({"source": self.p("old.txt"), "destination": self.p("renamed.txt")}))
        with self.assertRaisesRegex(ToolFailure, "does not exist"):
            files.copy_path({"source": self.p("ghost"), "destination": self.p("x")})
        with self.assertRaisesRegex(ToolFailure, "are the same"):
            files.move_path({"source": self.p("renamed.txt"), "destination": self.p("renamed.txt")})

    def test_folders_copy_whole_and_non_empty_folders_are_not_replaced(self) -> None:
        (self.root / "folder" / "a.txt").write_text("a", encoding="utf-8")
        files.copy_path({"source": self.p("folder"), "destination": self.p("copy")})
        self.assertEqual((self.root / "copy" / "a.txt").read_text(), "a")
        (self.root / "f2").mkdir()
        (self.root / "copy" / "f2").mkdir()
        (self.root / "copy" / "f2" / "keep.txt").write_text("k", encoding="utf-8")
        with self.assertRaisesRegex(ToolFailure, "not empty"):
            files.move_path({"source": self.p("f2"), "destination": self.p("copy"), "overwrite": True})
        self.assertIn("already exists", files.make_directory({"path": self.p("folder")}))

    def test_trash_is_always_danger(self) -> None:
        tool = next(tool for tool in files.file_tools() if tool.name == "trash_path")
        self.assertEqual(tool.classify({"path": self.p("old.txt")})[0], RISK_DANGER)
        with self.assertRaisesRegex(ToolFailure, "does not exist"):
            files.trash_path({"path": self.p("ghost")})


class ShellToolTests(unittest.TestCase):
    def test_output_status_working_directory_and_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "note.txt").write_text("x", encoding="utf-8")
            result = shell.run_command({"command": "pwd; ls; echo err >&2; exit 3", "working_directory": tmp})
            self.assertTrue(result.startswith("[exit status 3]"))
            self.assertIn(tmp, result)
            self.assertIn("note.txt", result)
            self.assertIn("err", result)
            self.assertEqual(shell.classify({"command": "ls", "working_directory": tmp}), (RISK_CHANGE, ""))
            self.assertEqual(shell.classify({"command": "rm note.txt", "working_directory": tmp})[0], RISK_DANGER)
            self.assertEqual(shell.classify({"command": "echo y > note.txt", "working_directory": tmp})[0], RISK_DANGER)

    def test_timeout_kills_the_command_and_long_output_is_cut(self) -> None:
        started = time.monotonic()
        result = shell.run_command({"command": "echo start; sleep 30", "timeout_seconds": 1})
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn("timed out after 1 s", result)
        self.assertIn("start", result)
        long = shell.run_command({"command": "seq 1 20000"})
        self.assertIn("characters cut", long)
        self.assertTrue(long.rstrip().endswith("20000"))
        self.assertLess(len(long), 8000)

    def test_bad_arguments(self) -> None:
        for arguments, message in (({}, "'command' is required"), ({"command": "ls", "working_directory": "/nope/x"}, "does not exist"),
                                   ({"command": "ls", "timeout_seconds": "soon"}, "must be a number")):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ToolFailure, message):
                shell.run_command(arguments)
        self.assertEqual(shell.run_command({"command": "cat"}), "[exit status 0]\n(no output)")


class ApplicationTests(unittest.TestCase):
    def test_discovery_and_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            user, system_dir = Path(tmp, "user"), Path(tmp, "system")
            user.mkdir()
            system_dir.mkdir()
            def entry(directory: Path, name: str, body: str) -> None:
                (directory / name).write_text("[Desktop Entry]\nType=Application\n" + body, encoding="utf-8")
            entry(system_dir, "org.kde.konsole.desktop", "Name=Konsole\nGenericName=Terminal\nExec=konsole\nKeywords=shell;prompt;\n")
            entry(system_dir, "firefox.desktop", "Name=Firefox\nGenericName=Web Browser\nExec=firefox %u\n")
            entry(system_dir, "firefox-dev.desktop", "Name=Firefox Developer Edition\nExec=firefox-dev\n")
            entry(system_dir, "hidden.desktop", "Name=Hidden Tool\nExec=x\nNoDisplay=true\n")
            entry(system_dir, "link.desktop", "Name=A Link\nType=Link\nURL=http://x\n")
            entry(user, "firefox.desktop", "Name=Firefox\nGenericName=My Browser\nExec=firefox --mine\n")
            (system_dir / "broken.desktop").write_text("not a desktop file", encoding="utf-8")
            found = apps.installed_applications([user, system_dir])
            self.assertEqual([app["name"] for app in found], ["Firefox", "Firefox Developer Edition", "Konsole"])
            self.assertEqual(found[0]["generic"], "My Browser")
            match = lambda text: [app["name"] for app in apps.match_applications(text, found)]  # noqa: E731
            self.assertEqual(match("firefox"), ["Firefox"])
            self.assertEqual(match("fire"), ["Firefox", "Firefox Developer Edition"])
            self.assertEqual(match("terminal"), ["Konsole"])
            self.assertEqual(match("org.kde.konsole"), ["Konsole"])
            self.assertEqual(match("web browser"), [])
            self.assertEqual(match("my browser"), ["Firefox"])
            self.assertEqual(match("nonexistent"), [])
            self.assertEqual(match("  "), [])


class SystemToolClassifierTests(unittest.TestCase):
    def test_session_dbus_and_setting_classification(self) -> None:
        self.assertEqual(system.classify_session({"action": "lock"})[0], RISK_CHANGE)
        self.assertEqual(system.classify_session({"action": "suspend"})[0], RISK_CHANGE)
        for action in ("logout", "restart", "shutdown"):
            self.assertEqual(system.classify_session({"action": action})[0], RISK_DANGER)
        self.assertEqual(system.classify_dbus({"bus": "session", "method": "org.kde.KWin.showDesktop"})[0], RISK_CHANGE)
        self.assertEqual(system.classify_dbus({"bus": "system", "method": "org.freedesktop.login1.Manager.PowerOff"})[0],
                         RISK_DANGER)
        self.assertEqual(system.classify_dbus({"bus": "system", "method": "org.freedesktop.login1.Manager.ListSessions"})[0],
                         RISK_CHANGE)
        self.assertEqual(system.classify_kde_setting({"file": "kdeglobals"})[0], RISK_CHANGE)
        self.assertEqual(system.classify_kde_setting({"file": "/etc/xdg/kdeglobals"})[0], RISK_DANGER)

    def test_argument_validation_happens_before_anything_runs(self) -> None:
        cases = [
            (system.set_volume, {}, "give 'percent'"), (system.set_volume, {"percent": 400}, "0 to 150"),
            (system.media_control, {"action": "rewind"}, "must be one of"),
            (system.set_radio, {"radio": "nfc", "enabled": True}, "'radio' must be"),
            (system.configure_displays, {}, "give 'enable'"), (system.session_action, {"action": "explode"}, "must be one of"),
            (system.dbus_call, {"bus": "other", "service": "a", "path": "/", "method": "m"}, "'bus' must be"),
            (system.write_kde_setting, {"file": "f", "group": "g", "key": "k"}, "'value' is required"),
            (system.set_clipboard, {}, "'text' is required"), (system.connect_wifi, {}, "'ssid' is required"),
        ]
        for handler, arguments, message in cases:
            with self.subTest(handler=handler.__name__, arguments=arguments), self.assertRaisesRegex(ToolFailure, message):
                handler(arguments)

    def test_catalogue_names_are_unique_valid_and_every_changing_tool_has_a_summary(self) -> None:
        tools = builtin_tools()
        ToolRegistry(tools)
        self.assertGreater(len(tools), 30)
        for tool in tools:
            self.assertIn(tool.risk, (RISK_READ, RISK_CHANGE, RISK_DANGER), tool.name)
            self.assertEqual(tool.parameters.get("type"), "object", tool.name)
            if tool.risk != RISK_READ:
                self.assertIsNotNone(tool.summarize, f"{tool.name} needs a summary for approval cards")


class ApprovalOverHttpTests(unittest.TestCase):
    def test_a_waiting_turn_resumes_when_the_user_approves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "victim.txt"
            target.write_text("precious", encoding="utf-8")
            model = FakeModelService()
            server = AssistantServer("127.0.0.1", 0, root / "runtime", root / "config.json")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                server.replace_settings({"models": {"m": {
                    "provider": "openai_compatible", "base_url": model.base_url, "model": "fake-model"}},
                    "active_model": "m"})
                command = json.dumps({"command": f"rm {target}"})
                model.replies += [chunks_for(tool_calls=[("c1", "run_command", command)]), chunks_for("Kept it."),
                                  chunks_for(tool_calls=[("c2", "run_command", command)]), chunks_for("Removed.")]
                headers = {"Authorization": f"Bearer {server.auth_token}", "Content-Type": "application/json"}

                def turn(decision: str) -> list[dict]:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
                    connection.request("POST", "/ask", body=json.dumps({"message": "delete it"}), headers=headers)
                    response = connection.getresponse()
                    events = []
                    while True:
                        line = response.fp.readline().decode()
                        if not line:
                            break
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:])
                        events.append(event)
                        if event["type"] == "approval_required":
                            self.assertEqual((event["risk"], event["detail"]), ("danger", "deletes files"))
                            self.assertTrue(event["summary"].startswith("Run: rm "))
                            answer = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                            answer.request("POST", "/approve", headers=headers,
                                           body=json.dumps({"id": event["id"], "decision": decision}))
                            self.assertEqual(answer.getresponse().status, 200)
                            answer.close()
                    connection.close()
                    return events

                denied = turn("deny")
                self.assertTrue(target.exists())
                self.assertFalse(next(e for e in denied if e["type"] == "tool_result")["ok"])
                allowed = turn("allow")
                self.assertFalse(target.exists())
                self.assertTrue(next(e for e in allowed if e["type"] == "tool_result")["ok"])
                log = [json.loads(line) for line in (root / "runtime" / "actions.jsonl").read_text().splitlines()]
                self.assertEqual([(r["tool"], r["outcome"]) for r in log],
                                 [("run_command", "deny"), ("run_command", "allow")])
                stale = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                stale.request("POST", "/approve", headers=headers, body=json.dumps({"id": "gone", "decision": "allow"}))
                self.assertEqual(stale.getresponse().status, 404)
                stale.close()
            finally:
                server.shutdown()
                server.server_close()
                server.shutdown_tools()
                thread.join(timeout=5)
                model.close()


if __name__ == "__main__":
    unittest.main()

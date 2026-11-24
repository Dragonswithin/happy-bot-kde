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
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model_service import FakeModelService, chunks_for  # noqa: E402

from happy_bot.agent_loop import run_turn  # noqa: E402
from happy_bot.conversation import Message, TextDelta, ToolCall, ToolCallReady, TurnEnd  # noqa: E402
from happy_bot.daemon_http import AssistantServer  # noqa: E402
from happy_bot.permissions import ApprovalBroker, PermissionGate, needs_approval  # noqa: E402
from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tools import apps, files, shell, system  # noqa: E402
from happy_bot.tools.catalog import builtin_tools  # noqa: E402
from happy_bot.tools.registry import (  # noqa: E402
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

        from happy_bot.agent_loop import system_prompt, user_folders

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
        from happy_bot.tools.files import file_tools
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
            with self.assertRaises(ToolFailure) as failed:
                shell.run_command({"command": "pwd; ls; echo err >&2; exit 3", "working_directory": tmp})
            result = str(failed.exception)
            self.assertTrue(result.startswith("[exit status 3]"))
            self.assertIn(tmp, result)
            self.assertIn("note.txt", result)
            self.assertIn("err", result)
            self.assertEqual(shell.classify({"command": "ls", "working_directory": tmp}), (RISK_CHANGE, ""))
            self.assertEqual(shell.classify({"command": "rm note.txt", "working_directory": tmp})[0], RISK_DANGER)
            self.assertEqual(shell.classify({"command": "echo y > note.txt", "working_directory": tmp})[0], RISK_DANGER)

    def test_timeout_kills_the_command_and_long_output_is_cut(self) -> None:
        started = time.monotonic()
        with self.assertRaises(ToolFailure) as failed:
            shell.run_command({"command": "echo start; sleep 30", "timeout_seconds": 1})
        result = str(failed.exception)
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn("timed out after 1 s", result)
        self.assertIn("start", result)
        long = shell.run_command({"command": "seq 1 20000"})
        self.assertIn("characters cut", long)
        self.assertTrue(long.rstrip().endswith("20000"))
        self.assertLess(len(long), 8000)

    def test_progress_redraws_are_collapsed(self) -> None:
        result = shell.run_command({"command": "printf 'get 10%%\\rget 50%%\\rget 100%%\\nok\\n'"})
        self.assertEqual(result, "[exit status 0]\nget 100%\nok")

    def test_bad_arguments(self) -> None:
        for arguments, message in (({}, "'command' is required"), ({"command": "ls", "working_directory": "/nope/x"}, "does not exist"),
                                   ({"command": "ls", "timeout_seconds": "soon"}, "must be a number")):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ToolFailure, message):
                shell.run_command(arguments)
        self.assertEqual(shell.run_command({"command": "cat"}), "[exit status 0]\n(no output)")


class ShellProgressAndTerminalTests(unittest.TestCase):
    def run_with_context(self, arguments: dict, cancel_after: float | None = None) -> tuple[str, list[str], float]:
        from happy_bot.tools.registry import CallContext, call_context

        lines: list[str] = []
        cancel = threading.Event()
        if cancel_after is not None:
            threading.Timer(cancel_after, cancel.set).start()
        token = call_context.set(CallContext(lines.append, cancel))
        started = time.monotonic()
        try:
            result, self.last_ok = shell.run_command(arguments), True
        except ToolFailure as failure:
            result, self.last_ok = str(failure), False
        finally:
            call_context.reset(token)
        return result, lines, time.monotonic() - started

    def test_output_is_reported_while_the_command_runs(self) -> None:
        result, lines, _elapsed = self.run_with_context(
            {"command": "for i in 1 2 3; do echo step $i; sleep 0.4; done"})
        self.assertTrue(result.startswith("[exit status 0]"))
        self.assertIn("step 3", result)
        self.assertTrue(any(line.startswith("step") for line in lines), lines)
        silent, quiet_lines, _ = self.run_with_context({"command": "sleep 0.5"})
        self.assertTrue(any("no output yet" in line for line in quiet_lines), quiet_lines)

    def test_stop_kills_the_command_and_its_children_at_once(self) -> None:
        result, _lines, elapsed = self.run_with_context(
            {"command": "echo begun; sleep 30 & sleep 30; wait", "timeout_seconds": 60}, cancel_after=0.5)
        self.assertLess(elapsed, 5)
        self.assertTrue(result.startswith("[stopped by the user]"), result)
        self.assertIn("begun", result)

    def test_password_commands_are_refused_with_a_pointer_to_the_terminal(self) -> None:
        tool = next(tool for tool in shell.shell_tools() if tool.name == "run_command")
        for command in ("yay -S ladybird --noconfirm", "sudo pacman -Syu"):
            with self.subTest(command=command), self.assertRaisesRegex(ToolFailure, "run_in_terminal"):
                tool.precheck({"command": command})
        tool.precheck({"command": "yay -Ss ladybird"})
        registry = ToolRegistry(shell.shell_tools())
        self.assertEqual(registry.assess("run_in_terminal", {"command": "yay -S ladybird"})[0], RISK_DANGER)
        self.assertEqual(registry.assess("run_in_terminal", {"command": "make -j8"})[0], RISK_CHANGE)

    def fake_terminal(self, folder: Path) -> str:
        """A stand-in terminal program: runs what follows '-e' with no window."""
        program = folder / "xterm"
        program.write_text("#!/bin/sh\nshift\nexec \"$@\" < /dev/null\n", encoding="utf-8")
        program.chmod(0o755)
        return str(program)

    def run_terminal(self, command: str, cancel_after: float | None = None, reboot: str = "") -> tuple[str, list[str]]:
        """Run ``command`` through ``run_in_terminal``; the result text either way, and ``self.last_ok``."""
        from unittest import mock

        from happy_bot.tools.registry import CallContext, call_context

        lines: list[str] = []
        cancel = threading.Event()
        if cancel_after is not None:
            threading.Timer(cancel_after, cancel.set).start()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shell, "terminal_program", return_value=self.fake_terminal(Path(tmp))), \
                mock.patch.object(shell, "ensure_runtime_root", return_value=Path(tmp)), \
                mock.patch.object(shell, "pending_reboot", return_value=reboot):
            token = call_context.set(CallContext(lines.append, cancel))
            try:
                result, self.last_ok = shell.run_in_terminal({"command": command, "working_directory": tmp}), True
            except ToolFailure as failure:
                result, self.last_ok = str(failure), False
            finally:
                call_context.reset(token)
            leftovers = [name for name in os.listdir(tmp) if name.startswith("terminal-")]
        self.assertEqual(leftovers, [], "log and status files are removed")
        return result, lines

    def test_terminal_waits_for_the_command_and_reports_status_and_output(self) -> None:
        result, lines = self.run_terminal("echo building; sleep 1; echo installed ok; exit 3")
        self.assertTrue(result.startswith("[finished with exit status 3]"), result)
        self.assertFalse(self.last_ok, "a non-zero exit status is a failed step")
        self.assertIn("installed ok", result)
        self.assertTrue(any(line.startswith("Waiting for you in the terminal window") for line in lines), lines)
        ok, _ = self.run_terminal("true")
        self.assertTrue(ok.startswith("[finished with exit status 0]"), ok)
        self.assertTrue(self.last_ok)
        self.assertNotIn("reboot", ok)

    def test_terminal_output_is_cleaned_and_a_needed_reboot_is_reported(self) -> None:
        bars = "".join(f"\\r(1/2) upgrading kernel [{'#' * n}{'-' * (20 - n)}] {n * 5}%%" for n in range(21))
        command = ("printf 'Packages (2) linux-7.3.6 kwin-6.8.3\\n'; "
                   "printf '\\033]3008;start=abc;hostname=secret-host;machineid=123\\033\\\\:: Starting\\n'; "
                   f"printf '{bars}\\n'; printf '\\033[1;32mdone\\033[0m\\n'")
        result, _ = self.run_terminal(command, reboot="the running kernel (7.3.5) was replaced by an update")
        self.assertTrue(self.last_ok, result)
        self.assertIn("Packages (2) linux-7.3.6 kwin-6.8.3", result)
        self.assertIn("(1/2) upgrading kernel [####################] 100%", result)
        self.assertNotIn("0%\n", result.replace("100%", ""))
        self.assertEqual(result.count("upgrading kernel"), 1, result)
        self.assertNotIn("secret-host", result)
        self.assertNotIn("\x1b", result)
        self.assertIn("\ndone", result)
        self.assertTrue(result.rstrip().endswith(
            "[A reboot is needed: the running kernel (7.3.5) was replaced by an update. Tell the user.]"), result)

    def test_closing_the_window_early_and_stop_are_reported_without_killing(self) -> None:
        # The command's parent is `script`; its parent is the window's shell.
        closed, _ = self.run_terminal("kill -9 $(ps -o ppid= -p $PPID | tr -d ' '); sleep 5")
        self.assertIn("closed before the command finished", closed)
        self.assertFalse(self.last_ok)
        stopped, _ = self.run_terminal("sleep 3", cancel_after=0.5)
        self.assertIn("stopped waiting at the user's request", stopped)
        self.assertFalse(self.last_ok)

    def test_terminal_command_keeps_the_window_open_and_reports_the_status(self) -> None:
        konsole = shell.terminal_command("/usr/bin/konsole", "yay -S ladybird", "/home/x")
        self.assertEqual(konsole[:5], ["/usr/bin/konsole", "--separate", "-e", "bash", "-c"])
        script = konsole[5]
        self.assertIn("cd /home/x", script)
        self.assertIn("yay -S ladybird", script)
        self.assertIn("Finished with exit status", script)
        self.assertIn("read -r -n 1", script)
        self.assertEqual(shell.terminal_command("/usr/bin/gnome-terminal", "ls", "/")[1], "--")
        self.assertEqual(shell.terminal_command("/usr/bin/xterm", "ls", "/")[1], "-e")


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
            self.assertIsNotNone(tool.summarize, f"{tool.name} needs a plain-language summary for the popup")
            self.assertTrue(tool.summarize({}).strip(), tool.name)

    def test_read_and_search_summaries_read_naturally(self) -> None:
        import os

        from happy_bot.tools.summaries import describe_read_call, describe_search

        home = os.path.expanduser("~")
        self.assertEqual(describe_read_call("list_directory", {"path": f"{home}/Desktop"}), "Listed ~/Desktop")
        self.assertEqual(describe_read_call("clipboard_text", {}), "Read the clipboard")
        self.assertIsNone(describe_read_call("no_such_tool", {}))
        files = describe_search("file_search", "index", "machine_search", "query")
        self.assertEqual(files({"query": "tax return"}), "Searched your files for “tax return”")
        web = describe_search("web_search", "searx", "web_search", "q")
        self.assertEqual(web({"q": "x" * 100})[-2:], "…”")
        self.assertEqual(describe_search(None, "gitlab", "list_issues", None)({}), "list issues (gitlab)")


class ApprovalOverHttpTests(unittest.TestCase):
    def test_a_waiting_turn_resumes_when_the_user_approves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "victim.txt"
            target.write_text("precious", encoding="utf-8")
            model = FakeModelService()
            server = AssistantServer("127.0.0.1", 0, root / "runtime", root / "config.json", root / "history")
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


class AppVisibilityTests(unittest.TestCase):
    """verify_app_install and refresh_app_menu with the shell, cache and restart stubbed out."""

    def setUp(self) -> None:
        from unittest import mock

        from happy_bot.tools import app_visibility

        self.v = app_visibility
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "flatpak" / "exports" / "share"
        (root / "applications").mkdir(parents=True)
        self.root = str(root)
        self.entry = root / "applications" / "org.example.Browser.desktop"
        self.entry.write_text("[Desktop Entry]\nType=Application\nName=Browser\nExec=browser\n", encoding="utf-8")
        self.app = {"id": "org.example.Browser.desktop", "name": "Browser", "generic": "", "keywords": "",
                    "comment": "", "path": str(self.entry)}
        self.restarts: list[list[str]] = []
        patches = [
            mock.patch.object(app_visibility, "installed_applications", return_value=[self.app]),
            mock.patch.object(app_visibility, "session_data_dirs", return_value=[self.root, "/usr/share"]),
            mock.patch.object(app_visibility, "rebuild_menu_cache", return_value=True),
            mock.patch.object(app_visibility, "RESTART_DELAY_SECONDS", 0),
            mock.patch.object(app_visibility, "run_command",
                              side_effect=lambda command, timeout=0: self.restarts.append(command) or {"stdout": ""}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        app_visibility._restart_pending = False

    def shell_sees(self, dirs: list[str]):
        from unittest import mock

        return mock.patch.object(self.v, "shell_data_dirs", return_value=(123, dirs))

    def cached(self, value: bool):
        from unittest import mock

        return mock.patch.object(self.v, "menu_cache_contains", return_value=value)

    def test_visible_when_the_shell_searches_the_folder_and_the_cache_has_it(self) -> None:
        with self.shell_sees([self.root, "/usr/share"]), self.cached(True):
            self.assertIn("visible in the launcher", self.v.verify_app_install({"name": "browser"}))

    def test_not_visible_when_the_shell_does_not_search_the_folder(self) -> None:
        with self.shell_sees(["/usr/local/share", "/usr/share"]), self.cached(False):
            result = self.v.verify_app_install({"name": "Browser"})
        self.assertIn("NOT visible yet", result)
        self.assertIn(self.root, result)
        with self.shell_sees([self.root]), self.cached(False):
            self.assertIn("menu cache has not picked it up", self.v.verify_app_install({"name": "Browser"}))

    def test_missing_app_is_a_clear_failure(self) -> None:
        from unittest import mock

        with mock.patch.object(self.v, "installed_applications", return_value=[]), \
                self.assertRaisesRegex(ToolFailure, "No launcher entry"):
            self.v.verify_app_install({"name": "Nothing"})

    def test_refresh_schedules_a_shell_restart_only_when_the_shell_lacks_the_folder(self) -> None:
        with self.shell_sees([self.root, "/usr/share"]), self.cached(True):
            result = self.v.refresh_app_menu({"name": "Browser"})
        self.assertNotIn("restart", result)
        self.assertFalse(self.v.run_after_turn())

        with self.shell_sees(["/usr/share"]), self.cached(True):
            result = self.v.refresh_app_menu({"name": "Browser"})
        self.assertIn("panel will restart", result)
        self.assertIn(["systemctl", "--user", "set-environment", f"XDG_DATA_DIRS={self.root}:/usr/share"], self.restarts)
        self.assertNotIn(["systemctl", "--user", "restart", "plasma-plasmashell.service"], self.restarts)
        self.assertTrue(self.v.run_after_turn())
        deadline = time.monotonic() + 3
        while ["systemctl", "--user", "restart", "plasma-plasmashell.service"] not in self.restarts and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIn(["systemctl", "--user", "restart", "plasma-plasmashell.service"], self.restarts)
        self.assertFalse(self.v.run_after_turn(), "a scheduled restart runs once")

    def test_refresh_fails_loudly_when_the_cache_still_lacks_the_app(self) -> None:
        with self.shell_sees([self.root]), self.cached(False), self.assertRaisesRegex(ToolFailure, "still does not list"):
            self.v.refresh_app_menu({"name": "Browser"})


class TerminalTextTests(unittest.TestCase):
    def test_clean_keeps_what_the_screen_finally_showed(self) -> None:
        from happy_bot.tools.terminal_text import clean

        self.assertEqual(clean("a\r\nb\r\n"), "a\nb\n")
        self.assertEqual(clean("10%\r50%\r100%\rdone   \n"), "done\n")
        self.assertEqual(clean("\x1b]0;title\x07\x1b]3008;host=h\x1b\\\x1b[1mbold\x1b[0m\x1b(B"), "bold")
        self.assertEqual(clean("bell\x07 back\x08"), "bell back")

    def test_head_and_tail(self) -> None:
        from happy_bot.tools.terminal_text import keep_head_and_tail

        self.assertEqual(keep_head_and_tail("short", 3, 3), "short")
        self.assertEqual(keep_head_and_tail("abcdefghij", 3, 2), "abc\n[... 5 characters cut ...]\nij")

    def test_pending_reboot(self) -> None:
        from unittest import mock

        release = os.uname().release
        with mock.patch.object(shell.os.path, "isdir", side_effect=lambda path: path == "/usr/lib/modules"):
            self.assertIn(f"running kernel ({release}) was replaced", shell.pending_reboot())
        with mock.patch.object(shell.os.path, "isdir", return_value=True), \
                mock.patch.object(shell.os.path, "exists", side_effect=lambda path: path == shell.REBOOT_REQUIRED_FLAG):
            self.assertEqual(shell.pending_reboot(), "the system reports that a reboot is required")
        with mock.patch.object(shell.os.path, "isdir", return_value=True), \
                mock.patch.object(shell.os.path, "exists", return_value=False):
            self.assertEqual(shell.pending_reboot(), "")

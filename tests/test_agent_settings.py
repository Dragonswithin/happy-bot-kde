"""Tests for the ``agent`` settings and the code that applies them.

Covers validation of the ``agent`` section in ``settings.py``; switching off
built-in tool groups in ``tools/catalog.py`` (and that its group names stay
in step with ``settings.TOOL_GROUPS``); the user's instructions and the
switched-off abilities in ``agent_loop.system_prompt``; the shell tools'
configurable time limit and terminal in ``tools/shell.py``; and the tool
argument listing the settings page's role editor uses
(``tool_roles.tool_arguments``). Pure logic: no daemon, model or desktop.
"""

from __future__ import annotations

import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import settings as settings_store  # noqa: E402
from happy_bot.agent_loop import system_prompt  # noqa: E402
from happy_bot.mcp_client import McpManager  # noqa: E402
from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tool_roles import tool_arguments  # noqa: E402
from happy_bot.tools import catalog, shell  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


class AgentSettingsTests(unittest.TestCase):
    def test_missing_section_gets_defaults_and_partial_section_is_completed(self) -> None:
        self.assertEqual(validate_settings({})["agent"], settings_store.default_agent())
        self.assertEqual(validate_settings({})["agent"]["instructions"], settings_store.SUGGESTED_INSTRUCTIONS)
        self.assertEqual(validate_settings({"agent": {"instructions": ""}})["agent"]["instructions"], "")
        agent = validate_settings({"agent": {"max_steps": 12, "instructions": "  Reply in German.  "}})["agent"]
        self.assertEqual((agent["max_steps"], agent["instructions"]), (12, "Reply in German."))
        self.assertEqual(agent["command_timeout_seconds"], shell.DEFAULT_TIMEOUT_SECONDS)

    def test_invalid_values_name_the_problem(self) -> None:
        cases = {
            "'max_steps' must be a whole number from 5 to 200": {"max_steps": 2},
            "'notify_after_seconds' must be": {"notify_after_seconds": -1},
            "'command_timeout_seconds' must be": {"command_timeout_seconds": True},
            "'terminal' must be empty": {"terminal": "/usr/bin/sh"},
            "unknown tool group 'observe'": {"disabled_tool_groups": ["observe"]},
            "'instructions' may be at most": {"instructions": "x" * (settings_store.MAX_INSTRUCTIONS_CHARS + 1)},
            "unknown setting 'steps'": {"steps": 3},
        }
        for message, agent in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(SettingsError, message):
                validate_settings({"agent": agent})

    def test_disabled_groups_are_deduplicated_and_sorted(self) -> None:
        agent = validate_settings({"agent": {"disabled_tool_groups": ["shell", "gui", "shell"]}})["agent"]
        self.assertEqual(agent["disabled_tool_groups"], ["gui", "shell"])


class ToolGroupTests(unittest.TestCase):
    def test_group_names_match_the_settings_and_the_model_wording(self) -> None:
        self.assertEqual(catalog.GROUP_NAMES[0], "observe")
        self.assertEqual(set(catalog.GROUP_NAMES) - {"observe"}, set(settings_store.TOOL_GROUPS))
        self.assertEqual(set(catalog.GROUP_DESCRIPTIONS), set(settings_store.TOOL_GROUPS))

    def test_switched_off_groups_are_not_offered(self) -> None:
        everything = {tool.name for tool in catalog.builtin_tools()}
        fewer = {tool.name for tool in catalog.builtin_tools({"disabled_tool_groups": ["shell", "gui"]})}
        self.assertTrue({"run_command", "run_in_terminal", "ui_press", "type_text"} <= everything - fewer)
        self.assertIn("clipboard_text", fewer)  # reading the desktop is always offered

    def test_registry_follows_the_settings(self) -> None:
        settings = validate_settings({"agent": {"disabled_tool_groups": ["files"]}})
        registry, _ = catalog.build_registry(McpManager(), settings)
        self.assertNotIn("trash_path", registry.names())
        self.assertIn("list_directory", registry.names())


class PromptTests(unittest.TestCase):
    def test_instructions_come_last_and_switched_off_abilities_are_named(self) -> None:
        prompt = system_prompt(None, "Always answer in German.", [catalog.GROUP_DESCRIPTIONS["shell"]])
        self.assertTrue(prompt.endswith("Always answer in German."))
        self.assertIn("switched off these abilities in the assistant's settings: running shell commands", prompt)

    def test_preferences_are_not_hidden_in_the_built_in_prompt(self) -> None:
        prompt = system_prompt(None, "", [])
        for phrase in ("third-party", "kill", "pre-built", "pacman"):
            self.assertNotIn(phrase, prompt)
        self.assertLess(len(settings_store.SUGGESTED_INSTRUCTIONS), settings_store.MAX_INSTRUCTIONS_CHARS)

    def test_plan_confirmation_is_asked_for_only_when_chosen(self) -> None:
        self.assertIn("short numbered plan", system_prompt(None, "", [], confirm_plans=True))
        self.assertNotIn("numbered plan", system_prompt(None, "", []))
        with self.assertRaisesRegex(SettingsError, "'confirm_plans' must be true or false"):
            validate_settings({"agent": {"confirm_plans": "yes"}})

    def test_nothing_is_added_without_instructions_or_switched_off_groups(self) -> None:
        prompt = system_prompt(None, "   ", [])
        self.assertNotIn("own instructions", prompt)
        self.assertNotIn("switched off", prompt)


class ShellSettingTests(unittest.TestCase):
    def test_default_time_limit_comes_from_the_settings(self) -> None:
        tool = next(tool for tool in shell.shell_tools(default_timeout=1) if tool.name == "run_command")
        self.assertIn("Default 1,", tool.parameters["properties"]["timeout_seconds"]["description"])
        with self.assertRaisesRegex(ToolFailure, "timed out|exit status|stopped"):
            tool.handler({"command": "sleep 5"})

    def test_chosen_terminal_is_used_or_reported_missing(self) -> None:
        with mock.patch.object(shell.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}" if name == "foot" else None), \
                mock.patch.object(shell, "FLATPAK_EXPORTS", ()):
            self.assertEqual(shell.terminal_program("foot"), "/usr/bin/foot")
            with self.assertRaisesRegex(ToolFailure, "choose another under Behaviour"):
                shell.terminal_program("kitty")
            self.assertEqual(shell.installed_terminals(), ["foot"])

    def test_kde_choice_is_used_only_when_supported(self) -> None:
        installed = {"konsole", "xterm"}
        which = mock.patch.object(shell.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}" if name in installed else None)
        for configured, expected in (("xterm -fa Mono", "/usr/bin/xterm"), ("cool-retro-term", "/usr/bin/konsole")):
            reply = {"stdout": configured + "\n", "stderr": "", "returncode": 0}
            with self.subTest(configured=configured), which, mock.patch.object(shell, "run_program", return_value=reply):
                self.assertEqual(shell.terminal_program(), expected)

    def test_a_flatpak_terminal_is_found_and_kdes_choice_of_it_followed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            launcher = Path(folder, "org.kde.kwi")
            launcher.write_text("#!/bin/sh\n")
            installed = {"konsole"}
            which = mock.patch.object(shell.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}" if name in installed else None)
            with which, mock.patch.object(shell, "FLATPAK_EXPORTS", (Path(folder),)):
                self.assertEqual(shell.installed_terminals(), ["konsole", "kwi"])
                self.assertEqual(shell.terminal_program("kwi"), str(launcher))
                self.assertEqual(shell.terminal_name(str(launcher)), "kwi")
                # Plasma names it by its launcher entry, or by the Flatpak command line.
                for service, application in (("org.kde.kwi.desktop", ""),
                                             ("", "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=kwi org.kde.kwi")):
                    replies = iter([{"stdout": service, "stderr": "", "returncode": 0},
                                    {"stdout": application, "stderr": "", "returncode": 0}])
                    with self.subTest(service=service), mock.patch.object(shell, "run_program", side_effect=lambda *a, **k: next(replies)):
                        self.assertEqual(shell.terminal_program(), str(launcher))
        command = shell.terminal_command("/home/u/.local/share/flatpak/exports/bin/org.kde.kwi", "true", "/tmp")
        self.assertEqual(command[1:4], ["-e", "bash", "-c"])

    def test_every_supported_terminal_has_a_command_line(self) -> None:
        for name in shell.SUPPORTED_TERMINALS:
            with self.subTest(name=name):
                command = shell.terminal_command(f"/usr/bin/{name}", "true", "/tmp")
                self.assertEqual(command[0], f"/usr/bin/{name}")
                self.assertEqual(command[-3:-1], ["bash", "-c"])
        self.assertEqual(shell.terminal_command("/usr/bin/wezterm", "true", "/tmp")[1:3], ["start", "--"])


class ToolArgumentTests(unittest.TestCase):
    def test_arguments_are_listed_with_type_and_required(self) -> None:
        tool = {"name": "find", "inputSchema": {"type": "object", "required": ["q"], "properties": {
            "q": {"type": "string"}, "limit": {"type": "integer"}, "odd": "not a schema"}}}
        self.assertEqual(tool_arguments(tool), [
            {"name": "q", "type": "string", "required": True},
            {"name": "limit", "type": "integer", "required": False},
            {"name": "odd", "type": "", "required": False},
        ])
        self.assertEqual(tool_arguments({"name": "bare"}), [])


if __name__ == "__main__":
    unittest.main()

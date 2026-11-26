"""Tests for the search speed-ups: instant commands, characters, recent items, application actions, web finder.

``quick_commands`` runs against a fake tool catalogue, so nothing on the
desktop changes, and Plasma's on-screen display is a recorded fake.
``characters`` parses a small dictionary built here in Plasma's format and
searches Python's own Unicode names. ``usage_history`` and
``quick_results.recent`` read a throwaway database in the activity manager's
layout. ``app_actions`` runs with ``pacman`` answers and the terminal faked,
and with private autostart folders, so no package or login entry is touched.
The web finder's search reads a recorded SearXNG answer; no search is sent.
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import (app_actions, characters, daemon_routes, instant_search, quick_commands,  # noqa: E402
                       quick_results, usage_history)
from happy_bot.tools.registry import RISK_CHANGE, RISK_DANGER, Tool, ToolFailure, object_schema  # noqa: E402


class CommandTests(unittest.TestCase):
    def test_commands_are_recognised_with_their_tool_and_arguments(self) -> None:
        cases = {
            "volume 30": ("set_volume", {"percent": 30}), "Set volume to 45%": ("set_volume", {"percent": 45}),
            "mute": ("set_volume", {"mute": True}), "unmute": ("set_volume", {"mute": False}),
            "brightness 60": ("set_brightness", {"percent": 60}),
            "dark mode": ("set_color_scheme", {"scheme": "BreezeDark"}),
            "light theme": ("set_color_scheme", {"scheme": "BreezeLight"}),
            "night light off": ("set_night_light", {"enabled": False}),
            "turn off wifi": ("set_radio", {"radio": "wifi", "enabled": False}),
            "bluetooth on": ("set_radio", {"radio": "bluetooth", "enabled": True}),
            "timer 1h30m": ("set_reminder", {"text": "Time is up: your timer for 1 hour 30 minutes", "in_minutes": 90}),
            "10 minute timer": ("set_reminder", {"text": "Time is up: your timer for 10 minutes", "in_minutes": 10}),
            "lock": ("session_action", {"action": "lock"}),
            "dnd": ("do_not_disturb", {"minutes": 60}), "dnd 30m": ("do_not_disturb", {"minutes": 30}),
            "do not disturb off": ("do_not_disturb", {"off": True}),
        }
        for text, (tool, arguments) in cases.items():
            with self.subTest(text=text):
                command = quick_commands.parse(text)
                self.assertEqual((command.tool, command.arguments), (tool, arguments))

    def test_loose_or_out_of_range_text_is_not_a_command(self) -> None:
        for text in ("play", "sleep", "volume 200", "brightness 0", "timer 0m", "timer", "lock screen app",
                     "dark", "firefox", "volume"):
            with self.subTest(text=text):
                self.assertIsNone(quick_commands.parse(text))
                self.assertEqual(quick_commands.match(text), [])

    def test_a_result_carries_only_the_typed_words(self) -> None:
        result = quick_commands.match("  Volume   30 ")
        self.assertEqual(result[0]["action"], {"type": "command", "target": "Volume 30"})
        self.assertEqual(result[0]["title"], "Set the volume to 30%")

    def _tools(self, calls: list) -> list[Tool]:
        def record(name):
            return lambda arguments: calls.append((name, arguments)) or f"{name} done"

        def classify_session(arguments):
            return (RISK_DANGER, "closes everything") if arguments.get("action") != "lock" else (RISK_CHANGE, "")

        def failing(arguments):
            raise ToolFailure("the radio is blocked")

        return [Tool("set_volume", "", object_schema(), RISK_CHANGE, record("set_volume")),
                Tool("session_action", "", object_schema(), RISK_CHANGE, record("session_action"), classify=classify_session),
                Tool("set_radio", "", object_schema(), RISK_CHANGE, failing)]

    def test_run_uses_the_tool_logs_it_and_shows_it_on_screen(self) -> None:
        calls, shown = [], []
        with tempfile.TemporaryDirectory() as runtime, \
                mock.patch("happy_bot.tools.catalog.builtin_tools", return_value=self._tools(calls)), \
                mock.patch.object(quick_commands, "show_on_screen", side_effect=lambda *a: shown.append(a)):
            self.assertEqual(quick_commands.run("volume 30", {}, Path(runtime)), "set_volume done")
            log = [json.loads(line) for line in Path(runtime, "actions.jsonl").read_text().splitlines()]
        self.assertEqual(calls, [("set_volume", {"percent": 30})])
        self.assertEqual(shown, [("audio-volume-medium", "Set the volume to 30%")])
        self.assertEqual((log[0]["tool"], log[0]["outcome"]), ("set_volume", "ran from the search bar"))

    def test_failures_switched_off_tools_and_dangerous_calls_are_refused(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as runtime, \
                mock.patch("happy_bot.tools.catalog.builtin_tools", return_value=self._tools(calls)), \
                mock.patch.object(quick_commands, "show_on_screen") as shown:
            with self.assertRaisesRegex(quick_commands.CommandError, "blocked"):
                quick_commands.run("wifi off", {}, Path(runtime))
            with self.assertRaisesRegex(quick_commands.CommandError, "switched off"):
                quick_commands.run("dark mode", {}, Path(runtime))
            with self.assertRaisesRegex(quick_commands.CommandError, "not a command"):
                quick_commands.run("play", {}, Path(runtime))
            with mock.patch.object(quick_commands, "parse", return_value=quick_commands.Command(
                    "Log out", "", "session_action", {"action": "logout"})), \
                    self.assertRaisesRegex(quick_commands.CommandError, "needs your approval"):
                quick_commands.run("log out", {}, Path(runtime))
        self.assertEqual(calls, [])
        shown.assert_not_called()

    def test_commands_come_first_and_need_the_daemon(self) -> None:
        with mock.patch.object(quick_results.apps, "installed_applications", return_value=[]), \
                mock.patch.object(quick_results, "settings_pages", return_value=[]):
            quick_results._cache.clear()
            self.assertEqual(quick_results.gather("lock")[0]["action"]["type"], "command")
        with self.assertRaisesRegex(quick_results.ActivationError, "daemon"):
            quick_results.activate({"type": "command", "target": "lock"})


def _plasma_dict(entries: list[tuple[str, str, list[str]]]) -> bytes:
    """Bytes in the layout of /usr/share/plasma/emoji/*.dict (see characters.parse_dict)."""
    def text(value: str) -> bytes:
        data = value.encode("utf-8")
        return struct.pack("<I", len(data)) + data

    raw = struct.pack("<I", len(entries))
    for emoji, name, keywords in entries:
        raw += text(emoji) + text(name) + struct.pack("<I", 1) + struct.pack("<I", len(keywords))
        raw += b"".join(text(word) for word in keywords)
    return struct.pack(">I", len(raw)) + zlib.compress(raw)


class CharacterTests(unittest.TestCase):
    ENTRIES = [("❤️", "red heart", ["love"]), ("💔", "broken heart", ["break"]), ("🐈", "cat", ["pet"]),
               ("🍕", "pizza", ["cheese"])]

    def setUp(self) -> None:
        characters._emoji = characters.parse_dict(_plasma_dict(self.ENTRIES))
        characters._symbols = None
        self.addCleanup(setattr, characters, "_emoji", None)
        self.addCleanup(setattr, characters, "_symbols", None)

    def glyphs(self, text: str) -> list[str]:
        return [result["glyph"] for result in characters.find(text)]

    def test_plasma_dictionaries_parse_and_broken_ones_are_refused(self) -> None:
        self.assertEqual(characters._emoji[0], characters.Character("❤️", "red heart", ("love",), True))
        for broken in (b"", b"\x00\x00\x00\x04nope", _plasma_dict(self.ENTRIES)[:-3]):
            with self.subTest(broken=broken[:8]), self.assertRaises(ValueError):
                characters.parse_dict(broken)

    def test_emoji_words_search_names_and_keywords(self) -> None:
        self.assertEqual(self.glyphs("emoji heart"), ["❤️", "💔"])
        self.assertEqual(self.glyphs("heart emoji"), ["❤️", "💔"])
        self.assertEqual(self.glyphs("emoji love"), ["❤️"])
        self.assertEqual(self.glyphs("emoji dragon"), [])

    def test_symbol_words_search_unicode_names_whole_words_first(self) -> None:
        self.assertEqual(self.glyphs("euro sign")[0], "€")
        self.assertEqual(self.glyphs("pi character")[0], "π")
        self.assertEqual(self.glyphs("arrow right symbol")[0], "→")
        result = characters.find("euro sign")[0]
        self.assertEqual((result["action"], result["subtitle"]),
                         ({"type": "character", "target": "€"}, "Character · U+20AC · Enter copies it"))

    def test_without_a_trigger_word_only_exact_names_of_two_words_show(self) -> None:
        self.assertEqual(self.glyphs("em dash"), ["—"])
        self.assertEqual(self.glyphs("red heart"), ["❤️"])
        self.assertEqual(self.glyphs("pizza"), [])
        self.assertEqual(self.glyphs("firefox"), [])

    def test_the_users_language_is_used_with_english_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "en.dict").write_bytes(_plasma_dict([("🐈", "cat", [])]))
            Path(folder, "de.dict").write_bytes(_plasma_dict([("🐈", "katze", [])]))
            with mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}):
                self.assertEqual(characters._load_emoji(Path(folder))[0].name, "katze")
            with mock.patch.dict(os.environ, {"LANG": "fr_FR.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""}):
                self.assertEqual(characters._load_emoji(Path(folder))[0].name, "cat")
            self.assertEqual(characters._load_emoji(Path(folder, "missing")), [])

    def test_characters_are_copied(self) -> None:
        started = []
        with mock.patch.object(quick_results, "_start", side_effect=started.append), \
                mock.patch.object(quick_results.shutil, "which", return_value="/usr/bin/wl-copy"):
            quick_results.activate({"type": "character", "target": "€"})
        self.assertEqual(started, [["wl-copy", "--", "€"]])


def _activity_database(path: Path, rows: list[tuple[str, int]], titles: dict[str, str] | None = None) -> None:
    """A database in kactivitymanagerd's layout holding ``(resource, last used)`` rows."""
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE ResourceScoreCache (usedActivity TEXT, initiatingAgent TEXT, targettedResource "
                       "TEXT, scoreType INTEGER, cachedScore FLOAT, firstUpdate INTEGER, lastUpdate INTEGER, "
                       "PRIMARY KEY(usedActivity, initiatingAgent, targettedResource))")
    connection.execute("CREATE TABLE ResourceInfo (targettedResource TEXT, title TEXT, mimetype TEXT, autoTitle "
                       "INTEGER, autoMimetype INTEGER, PRIMARY KEY(targettedResource))")
    for target, used in rows:
        connection.execute("INSERT INTO ResourceScoreCache VALUES ('a', 'agent', ?, 0, 1.0, ?, ?)", (target, used, used))
    for target, title in (titles or {}).items():
        connection.execute("INSERT INTO ResourceInfo VALUES (?, ?, '', 0, 0)", (target, title))
    connection.commit()
    connection.close()


class RecentTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.database = self.folder / "database"
        applications = [
            {"id": "org.kde.kate.desktop", "name": "Kate", "generic": "Text Editor", "keywords": "", "comment": "",
             "path": "/usr/share/applications/org.kde.kate.desktop"},
            {"id": "io.github.dragonswithin.happybot.desktop", "name": "Happy Bot", "generic": "", "keywords": "",
             "comment": "", "path": "/usr/share/applications/io.github.dragonswithin.happybot.desktop"}]
        pages = [{"module": "kcm_pulseaudio", "name": "Sound", "comment": "", "keywords": "", "icon": "audio-speakers"}]
        for patcher in (mock.patch.object(quick_results.apps, "installed_applications", return_value=applications),
                        mock.patch.object(quick_results, "settings_pages", return_value=pages),
                        mock.patch.object(quick_results, "_desktop_icon", return_value="kate"),
                        mock.patch.object(quick_results, "TRANSIENT_FOLDERS", ("/proc/",)),
                        mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/4242"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        quick_results._cache.clear()

    def test_missing_or_foreign_databases_give_nothing(self) -> None:
        self.assertEqual(usage_history.recent_resources(self.folder / "absent"), [])
        (self.folder / "junk").write_text("not a database")
        self.assertEqual(usage_history.recent_resources(self.folder / "junk"), [])

    def test_recent_items_newest_first_by_kind_without_transient_files_or_happy_bot(self) -> None:
        note = self.folder / "note.txt"
        note.write_text("x")
        _activity_database(self.database, [
            ("applications:org.kde.kate.desktop", 50), ("applications:io.github.dragonswithin.happybot.desktop", 90),
            ("applications:gone.desktop", 80), ("kcm:kcm_pulseaudio", 40), (str(note), 70),
            (f"file://{self.folder}", 60), ("/proc/self/status", 85), (str(self.folder / "deleted.txt"), 95),
            ("https://kde.org/", 30)], {"https://kde.org/": "KDE"})
        found = quick_results.recent([{"id": "c1", "title": "Old", "updated": 1}, {"id": "c2", "title": "New", "updated": 9}],
                                     False, self.database)
        self.assertEqual([item["title"] for item in found], ["Kate", "note.txt", self.folder.name, "Sound", "New", "Old"])
        self.assertEqual(found[1]["location"], str(note))
        self.assertEqual(found[2]["kind"], "folder")
        with_websites = quick_results.recent([], True, self.database)
        self.assertEqual(with_websites[-1]["action"], {"type": "visited", "target": "https://kde.org/"})
        self.assertEqual(with_websites[-1]["title"], "KDE")
        original_database = self.database.read_bytes()
        chats = [{"id": "old", "title": "Earlier", "updated": 40}, {"id": "new", "title": "Later", "updated": 51}]
        cleared = quick_results.recent(chats, True, self.database, since=50)
        self.assertEqual([item["title"] for item in cleared], ["note.txt", self.folder.name, "Later"])
        self.assertEqual(self.database.read_bytes(), original_database)


class AppActionTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.entry = self.folder / "org.kde.kate.desktop"
        self.entry.write_text("[Desktop Entry]\nName=Kate\nExec=kate\n")
        for patcher in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.folder / "config")}),
                        mock.patch.object(app_actions, "SYSTEM_AUTOSTART", self.folder / "xdg-autostart")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def pacman(self, owner: str, foreign: bool):
        def run(command):
            if command[:2] == ["pacman", "-Qqo"]:
                return (0, owner) if owner else (1, "")
            return (0, owner) if foreign else (1, "")
        return mock.patch.object(app_actions, "_run", side_effect=run)

    def test_packages_and_commands_for_each_source(self) -> None:
        flatpak = "/home/u/.local/share/flatpak/exports/share/applications/org.kde.kwi.desktop"
        self.assertEqual(app_actions.package_of(flatpak), {"source": "flatpak", "name": "org.kde.kwi"})
        with self.pacman("kate", False):
            self.assertEqual(app_actions.package_of(str(self.entry)), {"source": "standard", "name": "kate"})
        with self.pacman("bitwarden-bin", True):
            self.assertEqual(app_actions.package_of(str(self.entry)), {"source": "aur", "name": "bitwarden-bin"})
        with self.pacman("", False):
            self.assertEqual(app_actions.package_of(str(self.entry))["source"], "")
        with mock.patch.object(app_actions.shutil, "which", side_effect=lambda name: "/usr/bin/shelly" if name == "shelly" else None):
            self.assertEqual(app_actions._commands({"source": "aur", "name": "x"}), ("shelly update aur x", "shelly remove aur x"))
        with mock.patch.object(app_actions.shutil, "which", return_value=None):
            self.assertEqual(app_actions._commands({"source": "standard", "name": "kate"}),
                             ("sudo pacman -Syu", "sudo pacman -Rs kate"))
            self.assertEqual(app_actions._commands({"source": "flatpak", "name": "org.kde.kwi"}),
                             ("flatpak update org.kde.kwi", "flatpak uninstall org.kde.kwi"))
            self.assertEqual(app_actions._commands({"source": "aur", "name": "x"}), ("", "sudo pacman -Rs x"))
            self.assertEqual(app_actions._commands({"source": "", "name": ""}), ("", ""))

    def test_start_at_login_for_user_and_system_entries(self) -> None:
        path = str(self.entry)
        app_actions.set_starts_at_login(path, True)
        self.assertTrue(app_actions.starts_at_login(path))
        self.assertIn("Exec=kate", (self.folder / "config" / "autostart" / self.entry.name).read_text())
        app_actions.set_starts_at_login(path, False)
        self.assertFalse(app_actions.starts_at_login(path))
        system = self.folder / "xdg-autostart"
        system.mkdir()
        (system / self.entry.name).write_text("[Desktop Entry]\nExec=kate\n")
        self.assertTrue(app_actions.starts_at_login(path))
        app_actions.set_starts_at_login(path, False)
        self.assertFalse(app_actions.starts_at_login(path))
        self.assertIn("Hidden=true", (self.folder / "config" / "autostart" / self.entry.name).read_text())
        app_actions.set_starts_at_login(path, True)
        self.assertTrue(app_actions.starts_at_login(path))
        self.assertFalse((self.folder / "config" / "autostart" / self.entry.name).exists())

    def test_update_and_uninstall_open_a_terminal_and_odd_requests_are_refused(self) -> None:
        with self.pacman("kate", False), mock.patch.object(app_actions.shutil, "which", return_value=None), \
                mock.patch.object(app_actions, "open_terminal") as terminal:
            self.assertEqual(app_actions.carry_out(str(self.entry), "uninstall", "kwi"), "Opened a terminal: sudo pacman -Rs kate")
            terminal.assert_called_once_with("sudo pacman -Rs kate", "kwi")
            with self.assertRaises(app_actions.AppActionError):
                app_actions.carry_out(str(self.entry), "explode")
            with self.assertRaises(app_actions.AppActionError):
                app_actions.carry_out("/etc/passwd", "update")
        with self.pacman("", False), self.assertRaisesRegex(app_actions.AppActionError, "does not know"):
            app_actions.carry_out(str(self.entry), "update")

    def test_the_route_does_it_and_writes_the_action_log(self) -> None:
        class Server:
            settings = {"agent": {"terminal": "kwi"}}
            runtime_dir = self.folder

        with self.pacman("kate", False), mock.patch.object(app_actions, "open_terminal"):
            status, reply = daemon_routes.quick_app_action(Server(), {}, {"path": str(self.entry), "action": "uninstall"})
            self.assertEqual(status, 200)
            status, info = daemon_routes.quick_app(Server(), {"path": [str(self.entry)]}, {})
        self.assertEqual((status, info["package"], info["autostart"]), (200, "kate", False))
        logged = json.loads((self.folder / "actions.jsonl").read_text().splitlines()[0])
        self.assertEqual((logged["tool"], logged["risk"]), ("app_uninstall", "danger"))
        self.assertEqual(daemon_routes.quick_app(Server(), {"path": ["/nowhere.desktop"]}, {})[0], 404)


class WebFinderTests(unittest.TestCase):
    SEARXNG = ("Title: Introducing Kwi - KDE Blogs\nDescription: A new terminal.\nURL: https://blogs.kde.org/kwi/\n"
               "Relevance Score: 1.3\n\nTitle: kwi - Arch Linux\nDescription: Modern terminal. Upstream URL: x\n"
               "URL: https://archlinux.org/packages/extra/x86_64/kwi/\n")

    def test_key_value_records_become_hits_with_titles_and_snippets(self) -> None:
        from happy_bot.mcp_client import ToolResult
        hits = instant_search.extract_hits(ToolResult(self.SEARXNG))
        self.assertEqual([(hit["title"], hit["location"], hit["snippet"], hit["kind"]) for hit in hits], [
            ("Introducing Kwi - KDE Blogs", "https://blogs.kde.org/kwi/", "A new terminal.", "link"),
            ("kwi - Arch Linux", "https://archlinux.org/packages/extra/x86_64/kwi/", "Modern terminal. Upstream URL: x", "link")])

    def test_web_search_keeps_pages_only_and_marks_them(self) -> None:
        from happy_bot.mcp_client import ToolResult
        result = ToolResult(self.SEARXNG + "\nPath: /home/u/notes.txt\n")
        with mock.patch.object(instant_search, "call_role", return_value=result) as call:
            hits = instant_search.search_web(None, {}, "kwi")
        self.assertEqual(call.call_args[0][2], "web_search")
        self.assertEqual([hit["source"] for hit in hits], ["web", "web"])

    def test_the_route_says_when_web_search_is_not_set_up(self) -> None:
        from happy_bot.tool_roles import RoleNotConfigured

        class Server:
            mcp, settings = None, {}

        with mock.patch.object(instant_search, "call_role", side_effect=RoleNotConfigured("web_search")):
            status, reply = daemon_routes.search_web(Server(), {"q": ["kwi"]}, {})
        self.assertEqual((status, reply["code"]), (409, "not_configured"))
        self.assertEqual(daemon_routes.search_web(Server(), {"q": [""]}, {})[1]["hits"], [])


if __name__ == "__main__":
    unittest.main()

"""End-to-end tests of the daemon's settings, tool and search endpoints.

A real ``AssistantServer`` runs on an ephemeral port with its settings file
and runtime directory in a temporary directory, and uses
``tests/fake_mcp_server.py`` as its tool server. Requests go over HTTP with
the server's token, so routing, validation, persistence and tool-server
supervision are covered together. ``/open`` is tested only for refusals so no
application is launched.
"""

from __future__ import annotations

import json
import time
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.daemon_http import AssistantServer  # noqa: E402

FAKE_SERVER = str(Path(__file__).resolve().parent / "fake_mcp_server.py")
FAKE_ENTRY = {"command": sys.executable, "args": [FAKE_SERVER], "env": {"TOKEN": "abc"}}


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.config_file = root / "config" / "config.json"
        self.server = AssistantServer("127.0.0.1", 0, root / "runtime", self.config_file, root / "history")
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.shutdown_tools()
        self._thread.join(timeout=5)
        self._tmp.cleanup()

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        request = Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.server.auth_token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def configure(self, with_role: bool = True, mode: str = "structured") -> None:
        settings = {"tool_servers": {"fake": dict(FAKE_ENTRY)}, "roles": {}}
        if with_role:
            settings["roles"]["file_search"] = {
                "server": "fake", "tool": "find_files", "arguments": {"limit": 3, "mode": mode}}
        status, reply = self.call("PUT", "/settings", {"settings": settings})
        self.assertEqual(status, 200, reply)

    def test_search_without_setup_says_so(self) -> None:
        status, reply = self.call("GET", "/search?q=tax")
        self.assertEqual((status, reply["code"]), (409, "not_configured"))

    def test_web_start_shows_saved_pins_without_reading_browser_history(self) -> None:
        index = self.server.search_history.index
        with mock.patch.object(index, "frequent_sites", side_effect=AssertionError("browser history disabled")):
            self.assertEqual(self.call("GET", "/web/start"), (200, {"ok": True, "sites": [], "searches": [],
                "history_enabled": False, "search_clear_revision": 0}))
            status, start = self.call("POST", "/web/site", {"action": "pin", "url": "https://kde.org/discuss?ref=1"})
            self.assertEqual(status, 200)
            self.assertEqual(start["sites"], [{"host": "kde.org", "location": "https://kde.org/",
                                               "title": "kde.org", "pinned": True}])
            self.assertEqual(self.call("POST", "/web/site", {"action": "pin", "url": "file:///tmp/test"})[0], 400)
            self.assertEqual(self.call("POST", "/web/site", {"action": "delete", "url": "https://kde.org"})[0], 400)

        frequent = [{"host": "planet.kde.org", "title": "KDE Planet", "location": "https://planet.kde.org/"}]
        self.call("POST", "/ui", {"changes": {"search_history": True}})
        with mock.patch.object(index, "frequent_sites", return_value=frequent):
            start = self.call("GET", "/web/start")[1]
            self.assertEqual([site["host"] for site in start["sites"]], ["kde.org", "planet.kde.org"])
            self.assertTrue(start["history_enabled"])
            hidden = self.call("POST", "/web/site", {"action": "hide", "url": "https://planet.kde.org/"})[1]
            self.assertEqual([site["host"] for site in hidden["sites"]], ["kde.org"])
            restored = self.call("POST", "/web/site", {"action": "unhide", "url": "https://planet.kde.org/"})[1]
            self.assertEqual(restored["sites"], start["sites"])

    def test_web_start_keeps_only_deliberate_searches_and_observes_clear(self) -> None:
        self.call("GET", "/search/web?q=unfini")
        self.assertEqual(self.call("GET", "/web/start")[1]["searches"], [])
        query = {"query": "KDE shortcuts", "revision": 0}
        self.assertEqual(self.call("POST", "/web/search/remember", query)[0], 200)
        self.assertEqual(self.call("GET", "/web/start")[1]["searches"], ["KDE shortcuts"])
        self.call("POST", "/history/clear", {"kind": "search"})
        self.call("POST", "/web/search/remember", query)
        cleared = self.call("GET", "/web/start")[1]
        self.assertEqual(cleared["searches"], [])
        self.assertGreater(cleared["search_clear_revision"], 0)
        self.assertEqual(self.call("POST", "/web/search/remember", {"query": []})[0], 400)
        self.assertFalse(self.call("GET", "/health")[1]["setup"]["file_search"])

    def test_clear_search_keeps_archived_chats_and_survives_restart(self) -> None:
        store = self.server.conversations
        chat = store.get_or_create()
        store.begin_turn(chat, "Yesterday's chat")
        store.save(chat)
        before = self.call("GET", "/icon/activity")[1]
        self.assertEqual(before["search_clear_revision"], "")
        for invalid in ({}, {"kind": "all"}, {"kind": ["search"]}, {"kind": "search", "all": True}):
            self.assertEqual(self.call("POST", "/history/clear", invalid)[0], 400)
        self.assertEqual(self.call("POST", "/history/clear", {"kind": "search"}), (200, {"ok": True}))
        after = self.call("GET", "/icon/activity")[1]
        self.assertNotEqual(after["search_clear_revision"], before["search_clear_revision"])
        self.assertEqual(after["conversation_clear_revision"], "")
        self.assertTrue(self.call("GET", f"/conversation?id={chat.id}")[1]["ok"])
        self.assertFalse(any(r.get("action", {}).get("target") == chat.id
                             for r in self.call("GET", "/quick/recent")[1]["results"]))
        self.assertTrue(any(r.get("action", {}).get("target") == chat.id
                            for r in self.call("GET", "/quick?q=Yesterday")[1]["results"]))
        self.assertEqual(self.server.search_history.marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(float(after["search_clear_revision"]), self.server.search_history.index.history_since)
        self.call("POST", "/history/clear", {"kind": "conversations"})
        cleared = self.call("GET", "/icon/activity")[1]
        restarted = AssistantServer("127.0.0.1", 0, self.server.runtime_dir, self.config_file, store.archive.directory)
        try:
            saved = restarted.activity.wait("")
            for key in ("search_clear_revision", "conversation_clear_revision"):
                self.assertEqual(saved[key], cleared[key])
        finally:
            restarted.server_close()
            restarted.shutdown_tools()

    def test_clear_chats_including_pinned_and_active_never_resaves_them(self) -> None:
        store = self.server.conversations
        pinned = store.get_or_create()
        store.begin_turn(pinned, "Pinned")
        self.assertTrue(store.set_pinned(pinned.id, True))
        active = store.acquire_turn("")
        store.begin_turn(active, "Still working")
        try:
            self.assertEqual(self.call("POST", "/history/clear", {"kind": "conversations"}),
                             (200, {"ok": True, "deleted": 2}))
            self.assertTrue(active.cancel.is_set())
            store.save(active)  # stream_ask's finally runs even for a cancelled turn.
        finally:
            active.turn_lock.release()
        self.assertEqual(self.call("GET", "/conversations")[1]["conversations"], [])
        self.assertIsNone(store.archive.load(active.id))
        revision = self.call("GET", "/icon/activity")[1]["conversation_clear_revision"]
        self.assertTrue(revision)
        self.assertEqual(self.call("POST", "/conversations/delete", {"all": True})[1]["deleted"], 0)
        self.assertNotEqual(self.call("GET", "/icon/activity")[1]["conversation_clear_revision"], revision)

    def test_failed_search_clear_preserves_suggestions_and_reports_failure(self) -> None:
        revision = self.call("GET", "/icon/activity")[1]["search_clear_revision"]
        with mock.patch("happy_bot.quick_results.write_private_file", side_effect=PermissionError("read-only")):
            status, error = self.call("POST", "/history/clear", {"kind": "search"})
        self.assertEqual((status, error["code"]), (500, "clear_failed"))
        self.assertEqual(self.server.search_history.index.history_since, 0)
        self.assertEqual(self.call("GET", "/icon/activity")[1]["search_clear_revision"], revision)

    def test_clearing_a_runtime_category_only_removes_its_own_data(self) -> None:
        runtime = self.server.runtime_dir
        log, journal = runtime / "actions.jsonl", runtime / "undo.jsonl"
        shot = runtime / "screenshots" / "desktop-context-123.png"
        shot.parent.mkdir()
        for path in (log, journal, shot):
            path.write_bytes(b"fixture")
        for kind, path in (("activity", log), ("undo", journal), ("cache", shot)):
            self.assertTrue(path.exists())
            self.assertEqual(self.call("POST", "/history/clear", {"kind": kind}), (200, {"ok": True}))
            self.assertFalse(path.exists())
            self.assertEqual((runtime / "token").read_text().strip(), self.server.auth_token)

    def test_clearing_conversations_refuses_a_redirected_archive(self) -> None:
        archive = self.server.conversations.archive.directory
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        fixture = outside / "record.json"
        fixture.write_text("unrelated")
        archive.symlink_to(outside, target_is_directory=True)
        status, error = self.call("POST", "/history/clear", {"kind": "conversations"})
        self.assertEqual((status, error["code"]), (500, "clear_failed"))
        self.assertEqual(fixture.read_text(), "unrelated")

    def test_search_returns_hits_and_respects_limit(self) -> None:
        self.configure()
        status, reply = self.call("GET", f"/search?q={quote('tax return')}&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual([hit["location"] for hit in reply["hits"]],
                         ["/tmp/fake/tax return-0.txt", "/tmp/fake/tax return-1.txt"])
        self.assertTrue(self.call("GET", "/health")[1]["setup"]["file_search"])
        self.assertEqual(self.call("GET", "/search?q=")[1]["hits"], [])
        self.assertEqual(self.call("GET", "/search?q=x&limit=many")[0], 400)

    def test_search_tool_failure_is_recoverable(self) -> None:
        self.configure(mode="error")
        status, reply = self.call("GET", "/search?q=tax")
        self.assertEqual((status, reply["code"]), (502, "tool_failed"))
        self.configure(mode="structured")
        self.assertEqual(self.call("GET", "/search?q=tax")[0], 200)

    def test_settings_are_saved_validated_and_never_leak_secrets(self) -> None:
        self.configure()
        self.assertEqual(json.loads(self.config_file.read_text())["tool_servers"]["fake"]["env"], {"TOKEN": "abc"})
        status, reply = self.call("GET", "/settings")
        self.assertEqual(reply["settings"]["tool_servers"]["fake"]["env"], {"TOKEN": None})
        self.assertNotIn("abc", json.dumps(reply))
        self.assertEqual(self.call("PUT", "/settings", {"settings": reply["settings"]})[0], 200)
        self.assertEqual(json.loads(self.config_file.read_text())["tool_servers"]["fake"]["env"], {"TOKEN": "abc"})
        status, reply = self.call("PUT", "/settings", {"settings": {"roles": {"file_search": {"server": "x", "tool": "y"}}}})
        self.assertEqual((status, reply["code"]), (400, "invalid"))
        self.assertIn("fake", json.loads(self.config_file.read_text())["tool_servers"])

    def test_settings_survive_a_restart_of_the_daemon(self) -> None:
        self.configure()
        other = AssistantServer("127.0.0.1", 0, Path(self._tmp.name) / "runtime2", self.config_file, Path(self._tmp.name) / "history")
        try:
            self.assertIn("file_search", other.settings["roles"])
            self.assertEqual(other.settings_error, "")
        finally:
            other.server_close()
            other.shutdown_tools()

    def test_unreadable_settings_are_reported_not_fatal(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text("{broken", encoding="utf-8")
        other = AssistantServer("127.0.0.1", 0, Path(self._tmp.name) / "runtime3", self.config_file, Path(self._tmp.name) / "history")
        try:
            self.assertIn("could not read", other.settings_error)
            self.assertEqual(other.settings["tool_servers"], {})
        finally:
            other.server_close()

    def test_tool_listing_includes_role_proposals_and_errors(self) -> None:
        self.configure(with_role=False)
        settings = self.call("GET", "/settings")[1]["settings"]
        settings["tool_servers"]["broken"] = {"command": "/nonexistent/server"}
        self.call("PUT", "/settings", {"settings": settings})
        servers = {item["name"]: item for item in self.call("GET", "/tools/servers")[1]["servers"]}
        self.assertEqual(len(servers["fake"]["tools"]), 5)
        self.assertEqual({(p["role"], p["config"]["tool"]) for p in servers["fake"]["proposals"]},
                         {("file_search", "find_files"), ("web_search", "web_lookup")})
        self.assertIn("could not start", servers["broken"]["error"])
        only = self.call("GET", "/tools/servers?name=fake")[1]["servers"]
        self.assertEqual([item["name"] for item in only], ["fake"])
        find_files = next(tool for tool in only[0]["tools"] if tool["name"] == "find_files")
        self.assertIn({"name": "query", "type": "string", "required": True}, find_files["arguments"])
        self.assertEqual((find_files["query_argument"], find_files["limit_argument"]), ("query", "limit"))

    def test_dismissing_one_nudge_updates_the_shared_activity_snapshot(self) -> None:
        self.server.activity.observe_nudges(battery=True, disk=True)
        self.assertEqual(self.call("GET", "/icon/activity")[1]["nudges"], ["battery", "disk"])
        self.assertEqual(self.call("POST", "/icon/nudge/dismiss", {"kind": "battery"}), (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/icon/activity")[1]["nudges"], ["disk"])
        self.assertEqual(self.call("POST", "/icon/nudge/dismiss", {"kind": []})[0], 400)
        self.assertEqual(self.call("POST", "/icon/nudge/dismiss", {"kind": "other"})[0], 400)

    def test_quick_results_reminders_and_routine_units_go_through_the_daemon(self) -> None:
        from unittest import mock

        from happy_bot.tools import reminders

        reply = self.call("GET", "/quick?q=6*7")[1]
        self.assertEqual(reply["results"][0]["action"], {"type": "copy", "target": "42"})
        self.assertEqual(self.call("POST", "/quick/activate", {"action": {"type": "settings", "target": "x;y"}})[0], 400)
        units = Path(self._tmp.name) / "units"
        with mock.patch.object(reminders, "_location", return_value=(units, False)):
            ident = reminders.set_reminder({"text": "Stretch", "in_minutes": 5}).split()[1]
            listed = self.call("GET", "/reminders")[1]["reminders"]
            self.assertEqual([(item["id"], item["text"]) for item in listed], [(ident, "Stretch")])
            self.assertEqual(self.call("POST", "/reminders/cancel", {"id": ident})[0], 200)
            self.assertEqual(self.call("POST", "/reminders/cancel", {"id": ident})[0], 404)
        settings = self.call("GET", "/settings")[1]["settings"]
        settings["routines"] = {"Morning": {"request": "Say hello", "schedule": "daily"}}
        self.assertEqual(self.call("PUT", "/settings", {"settings": settings})[0], 200)
        written = sorted(path.suffix for path in self.server.unit_dir.iterdir())
        self.assertEqual(written, [".service", ".timer"])
        self.assertFalse(self.server.manage_units)

    def test_export_has_no_secrets_and_import_restores_conversations(self) -> None:
        self.configure()
        self.server.conversations.archive.days = 30
        self.server.conversations.archive.save({"id": "abcdefghij", "title": "Fence quote", "created": time.time(),
                                                 "updated": time.time(), "events": [], "history": []})
        data = self.call("GET", "/export")[1]["data"]
        self.assertNotIn("abc", json.dumps(data["settings"]))  # the tool server's TOKEN value
        self.assertEqual([record["id"] for record in data["conversations"]], ["abcdefghij"])
        self.server.conversations.archive.delete("abcdefghij")
        reply = self.call("POST", "/import", {"data": data})[1]
        self.assertEqual(reply["conversations_added"], 1)
        self.assertEqual(json.loads(self.config_file.read_text())["tool_servers"]["fake"]["env"], {"TOKEN": "abc"})
        self.assertEqual(self.call("POST", "/import", {"data": {"format": "other"}})[0], 400)

    def test_self_check_names_problems_with_fixes(self) -> None:
        import json as json_module

        from happy_bot import __version__

        metadata = Path(__file__).resolve().parent.parent / "plasmoid/io.github.dragonswithin.happybot/metadata.json"
        self.assertEqual(json_module.loads(metadata.read_text())["KPlugin"]["Version"], __version__)
        self.configure()
        reply = self.call("GET", "/check")[1]
        checks = {item["name"]: item for item in reply["checks"]}
        self.assertFalse(reply["healthy"])
        self.assertEqual((checks["AI model"]["ok"], checks["AI model"]["fix"]),
                         (False, "Choose or add one on the AI Model page."))
        self.assertTrue(checks["Tool server fake"]["ok"])
        self.assertTrue(checks["File search"]["ok"])
        self.assertIn("press Set up next to Web", checks["Web search"]["fix"])
        self.assertTrue(all(item["ok"] or item["fix"] for item in reply["checks"]))

    def test_settings_read_offers_choices_and_agent_settings_round_trip(self) -> None:
        reply = self.call("GET", "/settings")[1]
        self.assertIsInstance(reply["terminals"], list)
        self.assertEqual(reply["suggested_instructions"], reply["settings"]["agent"]["instructions"])
        self.assertEqual(reply["settings"]["agent"]["max_steps"], 40)
        reply["settings"]["agent"].update(max_steps=12, disabled_tool_groups=["shell"], instructions="Be brief.")
        status, stored = self.call("PUT", "/settings", {"settings": reply["settings"]})
        self.assertEqual((status, stored["settings"]["agent"]["max_steps"]), (200, 12))
        self.assertEqual(json.loads(self.config_file.read_text())["agent"]["disabled_tool_groups"], ["shell"])
        reply["settings"]["agent"]["terminal"] = "not-a-terminal"
        status, refused = self.call("PUT", "/settings", {"settings": reply["settings"]})
        self.assertEqual((status, refused["code"]), (400, "invalid"))

    def test_removing_a_server_stops_its_process(self) -> None:
        self.configure()
        self.call("GET", "/search?q=tax")
        session = self.server.mcp.session("fake")
        self.call("PUT", "/settings", {"settings": {"tool_servers": {}, "roles": {}}})
        self.assertFalse(session.alive)

    def test_open_refuses_unsafe_or_missing_locations(self) -> None:
        for location in ("", "relative/file.txt", "ftp://example.org/x", "--help", "/nonexistent/file.txt"):
            with self.subTest(location=location):
                status, reply = self.call("POST", "/open", {"location": location})
                self.assertEqual((status, reply["ok"]), (400, False))

    def test_import_of_unknown_server_is_refused(self) -> None:
        status, reply = self.call("POST", "/tools/import", {"name": "definitely-not-configured-anywhere-xyz"})
        self.assertEqual(status, 404)


class CurrentApplicationTests(unittest.TestCase):
    def test_the_window_in_use_is_named_after_its_desktop_entry(self) -> None:
        import tempfile
        from happy_bot import desktop_context

        with tempfile.TemporaryDirectory() as data:
            apps = Path(data) / "applications"
            apps.mkdir()
            (apps / "org.example.notes.desktop").write_text("[Desktop Entry]\nName=Notes Pro\nIcon=notes-pro\nExec=notes\n"
                                                              "[Desktop Action new]\nName=New Note\nIcon=list-add\n")
            window = {"available": True, "window": {"app": "org.example.notes", "title": "todo.md — Notes Pro"}}
            with mock.patch.dict("os.environ", {"XDG_DATA_HOME": data, "XDG_DATA_DIRS": data}), \
                    mock.patch.object(desktop_context, "active_window_context", return_value=window):
                self.assertEqual(desktop_context.current_application(),
                                 {"app": "Notes Pro", "class": "org.example.notes", "title": "todo.md — Notes Pro",
                                  "icon": "notes-pro", "window": ""})
            self.assertEqual(desktop_context.application_name("org.example.unknown-app"), "Unknown app")
            with mock.patch.object(desktop_context, "active_window_context", return_value={"available": False}):
                self.assertEqual(desktop_context.current_application(), {"app": "", "class": "", "title": "", "icon": "", "window": ""})


if __name__ == "__main__":
    unittest.main()

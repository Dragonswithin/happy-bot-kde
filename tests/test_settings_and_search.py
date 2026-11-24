"""Tests for settings storage, role mapping, hit extraction and discovery.

Pure-logic tests need no process. The search tests run the real
``file_search`` path against ``tests/fake_mcp_server.py``. Discovery tests
build other programs' configuration files inside a temporary home directory.
"""

from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import settings as settings_store  # noqa: E402
from kde_ai_assistant.instant_search import extract_hits, search_files  # noqa: E402
from kde_ai_assistant.mcp_client import McpError, McpManager, ToolResult  # noqa: E402
from kde_ai_assistant.mcp_discovery import discover_servers  # noqa: E402
from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tool_roles import RoleNotConfigured, propose_role  # noqa: E402

FAKE_SERVER = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


def fake_settings(mode: str = "structured") -> dict:
    return validate_settings({
        "tool_servers": {"fake": {"command": sys.executable, "args": [FAKE_SERVER], "env": {"TOKEN": "abc"}}},
        "roles": {"file_search": {"server": "fake", "tool": "find_files", "arguments": {"limit": 3, "mode": mode}}},
    })


class SettingsTests(unittest.TestCase):
    def test_defaults_are_filled_in(self) -> None:
        server = fake_settings()["tool_servers"]["fake"]
        self.assertEqual((server["enabled"], server["read_only"], server["tools"]), (True, False, None))
        self.assertEqual(fake_settings()["roles"]["file_search"]["query_argument"], "query")

    def test_invalid_settings_name_the_problem(self) -> None:
        cases = {
            "unknown setting 'modle'": {"modle": {}},
            "'command' is required": {"tool_servers": {"a": {}}},
            "names use letters": {"tool_servers": {"bad name": {"command": "x"}}},
            "unknown setting 'cmd'": {"tool_servers": {"a": {"command": "x", "cmd": "y"}}},
            "'env' must map": {"tool_servers": {"a": {"command": "x", "env": {"K": 1}}}},
            "'enabled' must be true or false": {"tool_servers": {"a": {"command": "x", "enabled": "yes"}}},
            "unknown role": {"roles": {"image_search": {"server": "a", "tool": "t"}}},
            "is not set up": {"roles": {"file_search": {"server": "ghost", "tool": "t"}}},
            "unsupported settings version": {"version": 99},
        }
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(SettingsError, message):
                validate_settings(raw)

    def test_save_is_private_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            stored = settings_store.save_settings(fake_settings(), path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(settings_store.load_settings(path), stored)
            self.assertEqual(settings_store.load_settings(Path(tmp) / "absent.json"), settings_store.default_settings())
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(SettingsError):
                settings_store.load_settings(path)

    def test_redaction_hides_values_and_merge_restores_them(self) -> None:
        stored = fake_settings()
        view = settings_store.redacted(stored)
        self.assertEqual(view["tool_servers"]["fake"]["env"], {"TOKEN": None})
        self.assertNotIn("abc", json.dumps(view))
        view["tool_servers"]["fake"]["env"]["NEW"] = "fresh"
        merged = settings_store.merge_redacted(view, stored)
        self.assertEqual(merged["tool_servers"]["fake"]["env"], {"TOKEN": "abc", "NEW": "fresh"})
        del view["tool_servers"]["fake"]["env"]["TOKEN"]
        self.assertEqual(settings_store.merge_redacted(view, stored)["tool_servers"]["fake"]["env"], {"NEW": "fresh"})

    def test_disabled_servers_are_not_launched(self) -> None:
        raw = fake_settings()
        raw["roles"] = {}
        raw["tool_servers"]["fake"]["enabled"] = False
        self.assertEqual(settings_store.server_specs(validate_settings(raw)), [])


class RoleProposalTests(unittest.TestCase):
    def tool(self, name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {"name": name, "description": description,
                "inputSchema": {"type": "object", "properties": properties, "required": required}}

    def test_file_and_web_search_tools_are_recognised(self) -> None:
        files = self.tool("machine_search", "Search paths and text across local files.",
                          {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"])
        web = self.tool("lookup", "Search the web through a metasearch engine.",
                        {"q": {"type": "string"}, "max_results": {"type": "integer"}}, ["q"])
        self.assertEqual(propose_role("s", files), {"role": "file_search", "config": {
            "server": "s", "tool": "machine_search", "query_argument": "query", "arguments": {"limit": 8}}})
        proposal = propose_role("s", web)
        self.assertEqual((proposal["role"], proposal["config"]["query_argument"]), ("web_search", "q"))
        self.assertEqual(proposal["config"]["arguments"], {"max_results": 8})

    def test_tools_that_cannot_be_called_with_just_a_query_are_not_proposed(self) -> None:
        needs_repo = self.tool("pack", "Search local files in a repository.",
                               {"repo_path": {"type": "string"}, "query": {"type": "string"}}, ["repo_path", "query"])
        not_search = self.tool("refresh", "Refresh the local file index.", {"query": {"type": "string"}}, [])
        ambiguous = self.tool("search", "Search files on the web.", {"query": {"type": "string"}}, ["query"])
        no_query = self.tool("status", "Search status of local files.", {}, [])
        for tool in (needs_repo, not_search, ambiguous, no_query):
            with self.subTest(tool=tool["name"]):
                self.assertIsNone(propose_role("s", tool))


class HitExtractionTests(unittest.TestCase):
    def test_structured_content_wins_and_non_hit_paths_are_ignored(self) -> None:
        result = ToolResult(text="ignored /etc/passwd", structured={
            "hits": [{"path": "/home/u/a.pdf", "excerpt": "  first\n  line "}, {"path": "/home/u/a.pdf"},
                     {"url": "https://example.org/x", "title": "Example"}, {"path": "relative/skip.txt"}],
            "coverage": {"database_path": "/var/lib/index.sqlite"},
        })
        hits = extract_hits(result)
        self.assertEqual([hit["location"] for hit in hits],
                         ["/home/u/a.pdf", "https://example.org/x"])
        self.assertEqual(hits[0], {"title": "a.pdf", "location": "/home/u/a.pdf", "snippet": "first line", "kind": "file"})
        self.assertEqual((hits[1]["title"], hits[1]["kind"]), ("Example", "link"))

    def test_json_text_file_urls_folders_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = [{"uri": f"file://{tmp}"}, {"file_path": "/x/My%20Doc.txt"}, {"uri": "file:///x/My%20Doc.txt"}]
            hits = extract_hits(ToolResult(text=json.dumps(payload)))
            self.assertEqual(hits[0]["kind"], "folder")
            self.assertEqual(hits[2]["location"], "/x/My Doc.txt")
            self.assertEqual(len(extract_hits(ToolResult(text=json.dumps(payload)), limit=1)), 1)

    def test_plain_text_fallback_and_empty_output(self) -> None:
        text = "Found:\n- /home/u/notes.md: fence quote\n- see https://example.org/help.\nratio 3/4 is not a path"
        self.assertEqual([hit["location"] for hit in extract_hits(ToolResult(text=text))],
                         ["/home/u/notes.md", "https://example.org/help"])
        self.assertEqual(extract_hits(ToolResult(text="")), [])
        self.assertEqual(extract_hits(ToolResult(text="nothing matched")), [])

    def test_long_snippets_are_shortened(self) -> None:
        hit = extract_hits(ToolResult(text="", structured=[{"path": "/a", "snippet": "word " * 100}]))[0]
        self.assertLessEqual(len(hit["snippet"]), 200)
        self.assertTrue(hit["snippet"].endswith("…"))


class FileSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = McpManager()
        self.addCleanup(self.manager.close_all)

    def search(self, mode: str) -> list[dict]:
        settings = fake_settings(mode)
        self.manager.configure(settings_store.server_specs(settings))
        return search_files(self.manager, settings, "tax return")

    def test_every_output_shape_yields_the_same_files(self) -> None:
        expected = [f"/tmp/fake/tax return-{index}.txt" for index in range(3)]
        for mode in ("structured", "json_text"):
            with self.subTest(mode=mode):
                self.assertEqual([hit["location"] for hit in self.search(mode)][:3], expected)

    def test_tool_error_and_missing_role(self) -> None:
        with self.assertRaisesRegex(McpError, "index is offline"):
            self.search("error")
        with self.assertRaises(RoleNotConfigured):
            search_files(self.manager, settings_store.default_settings(), "x")


class DiscoveryTests(unittest.TestCase):
    def test_reads_known_formats_and_skips_unusable_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text(json.dumps({
                "mcpServers": {
                    "index": {"type": "stdio", "command": "/opt/index", "args": ["serve"], "env": {"KEY": "v"}},
                    "remote": {"type": "http", "url": "https://example.org/mcp"},
                    "off": {"command": "/opt/off", "disabled": True},
                },
                "projects": {"/p": {"mcpServers": {"scoped": {"command": "/opt/scoped"}}}},
            }), encoding="utf-8")
            (home / ".config/opencode").mkdir(parents=True)
            (home / ".config/opencode/opencode.json").write_text(json.dumps({
                "mcp": {"web": {"type": "local", "command": ["/opt/web", "--stdio"], "environment": {"A": "b"}},
                        "index": {"command": ["/opt/index", "serve"]}},
            }), encoding="utf-8")
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").write_text('[mcp_servers.tom]\ncommand = "/opt/tom"\nargs = ["x"]\n', encoding="utf-8")
            (home / ".cursor").mkdir()
            (home / ".cursor/mcp.json").write_text("{not json", encoding="utf-8")

            found = {server.name: server for server in discover_servers(home)}
            self.assertEqual(sorted(found), ["index", "scoped", "tom", "web"])
            self.assertEqual(found["index"].source, "Claude Code")
            self.assertEqual((found["web"].command, found["web"].args), ("/opt/web", ("--stdio",)))
            self.assertEqual(found["web"].env, (("A", "b"),))
            self.assertEqual(found["index"].describe()["env_names"], ["KEY"])
            self.assertNotIn("v", json.dumps(found["index"].describe()["env_names"]))
            self.assertEqual(found["index"].as_settings_entry(True)["env"], {"KEY": "v"})

    def test_empty_home_finds_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_servers(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()


class ModelDiscoveryTests(unittest.TestCase):
    def test_listening_ports_are_read_from_proc_and_filtered(self) -> None:
        from kde_ai_assistant.model_discovery import listening_ports

        header = "  sl  local_address rem_address   st tx_queue rx_queue\n"
        tcp = header + "\n".join([
            "   0: 0100007F:CD91 00000000:0000 0A 0 0",     # 127.0.0.1:52625 listening
            "   1: 00000000:1F90 00000000:0000 0A 0 0",     # 0.0.0.0:8080 listening
            "   2: 0100007F:0016 00000000:0000 0A 0 0",     # port 22: below 1024
            "   3: 0A00000A:2328 00000000:0000 0A 0 0",     # 10.0.0.10:9000: not loopback
            "   4: 0100007F:C350 0100007F:D431 01 0 0",     # established, not listening
            "garbage line",
        ]) + "\n"
        tcp6 = header + "   0: 00000000000000000000000001000000:2B67 " + "0" * 32 + ":0000 0A 0 0\n"   # [::1]:11111
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "tcp").write_text(tcp, encoding="ascii")
            Path(tmp, "tcp6").write_text(tcp6, encoding="ascii")
            self.assertEqual(listening_ports(Path(tmp)), [8080, 11111, 52625])
            self.assertEqual(listening_ports(Path(tmp, "missing")), [])

    def test_discovery_finds_only_real_model_services(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from fake_model_service import FakeModelService

        from kde_ai_assistant.model_discovery import discover_local

        service = FakeModelService()
        try:
            port = int(service.base_url.rsplit(":", 1)[1].split("/")[0])
            found = discover_local(ports=[port, 9])
            self.assertEqual([(item["port"], item["models"][0]["id"]) for item in found], [(port, "fake-model")])
            self.assertEqual(discover_local(ports=[port], skip_ports=(port,)), [])
            self.assertEqual(discover_local(ports=[]), [])
        finally:
            service.close()

    def test_loaded_models_come_first_when_the_service_says_which_are_running(self) -> None:
        import json as json_module
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from kde_ai_assistant.model_discovery import discover_local

        class Catalogue(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_GET(self):  # noqa: N802
                routes = {
                    "/v1/models": {"data": [{"id": "big-a"}, {"id": "small-b"}, {"id": "running-c"}]},
                    "/api/ps": {"models": [{"name": "running-c", "model": "running-c"}]},
                }
                payload = routes.get(self.path)
                raw = json_module.dumps(payload if payload is not None else {"error": "no"}).encode()
                self.send_response(200 if payload is not None else 404)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Catalogue)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            found = discover_local(ports=[server.server_address[1]])[0]
            self.assertTrue(found["loaded_known"])
            self.assertEqual([(m["id"], m["loaded"]) for m in found["models"]],
                             [("running-c", True), ("big-a", False), ("small-b", False)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

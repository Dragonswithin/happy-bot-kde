"""What can do file search or web search on this computer, as plain choices for setup's "Set up" button.

The Search & Tools page shows these when the user presses "Set up" next to Files or Web
(``POST /search/choices``); ``search_setup.use`` applies the one they pick. Nothing here changes
anything: it only looks, and only when asked.

Where choices come from, best first (the first ready one is marked ``recommended``):

- ``found``: a tool server the user already set up for another AI program (``mcp_discovery``) whose
  tools look suited to the job (``tool_roles.propose_role``) and that passes a test search: for files
  it must return at least one path that exists on this computer, for the web at least one link (``instant_search.extract_hits``).
  The wording guess alone is not trusted, because tools for offline encyclopedias or notes also
  talk about "documents". Each is started briefly (``_try_found``); ``scan_discovered``, which only
  lists tools and guesses, is shared with ``POST /tools/scan``.
- ``builtin`` (files only): an index the computer already keeps, read by ``file_index_server``.
  KDE's file index is offered when installed; when it is switched off the choice says so and
  using it switches it on. The file-name database (plocate) is offered only when it covers the
  user's home folder, which it does not on systems whose home is a separate btrfs subvolume.
- ``suggested`` (web only): ``WEB_SUGGESTIONS``, web-search tool servers checked against their
  registries and started once to confirm their tool names. A self-hosted SearXNG answering on this
  computer (``local_searxng``) fills in its address and is recommended first.

A choice is a dict: ``id``, ``kind``, ``title``, ``detail`` (one or two plain sentences), ``privacy``
(where the user's words go, or ""), ``ready`` (usable as is), ``problem`` (why not, with what to do),
``inputs`` (``[{"name", "label", "secret", "value", "help_url"}]`` the user fills in) and
``recommended``. No vendor is assumed: suggestions are offers the user picks from.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from . import mcp_discovery, model_discovery
from .mcp_client import McpError, McpServerSpec, McpSession
from .instant_search import extract_hits
from .tool_roles import propose_role

SCAN_STARTUP_SECONDS = 20.0
TEST_SECONDS = 20.0
# Test searches for found servers and for ``search_setup``: plain words, nothing about the user.
TEST_QUERIES = {"file_search": "document", "web_search": "weather"}
PROBE_TIMEOUT_SECONDS = 0.8
RESULT_LIMIT = 8

# Checked 2026-11-23: each package's current version on npm or PyPI, then started over stdio to read
# its tool list. Versions are pinned so a choice runs what was checked; update them deliberately.
WEB_SUGGESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "searxng", "title": "Your own SearXNG",
        "detail": "Searches the web through a SearXNG search engine you run. It needs the JSON format "
                  "switched on in SearXNG's settings.",
        "privacy": "Your web questions go to your SearXNG, which asks the search engines it is set up for.",
        "program": "npx", "command": "npx", "args": ["-y", "mcp-searxng@2.11.0"],
        "inputs": [{"name": "SEARXNG_URL", "label": "SearXNG address", "secret": False,
                    "help_url": "https://docs.searxng.org/"}],
        "tool": "searxng_web_search", "arguments": {},
    },
    {
        "id": "duckduckgo", "title": "DuckDuckGo",
        "detail": "Searches the web with DuckDuckGo. No account or key needed.",
        "privacy": "Your web questions go to DuckDuckGo.",
        "program": "uvx", "command": "uvx", "args": ["duckduckgo-mcp-server@0.7.0"],
        "inputs": [], "tool": "search", "arguments": {"max_results": RESULT_LIMIT},
    },
    {
        "id": "brave", "title": "Brave Search",
        "detail": "Searches the web with Brave Search. Needs a free API key from Brave.",
        "privacy": "Your web questions go to Brave.",
        "program": "npx", "command": "npx", "args": ["-y", "@brave/brave-search-mcp-server@2.2.0"],
        "inputs": [{"name": "BRAVE_API_KEY", "label": "Brave API key", "secret": True,
                    "help_url": "https://brave.com/search/api/"}],
        "tool": "brave_web_search", "arguments": {"count": RESULT_LIMIT},
    },
    {
        "id": "tavily", "title": "Tavily",
        "detail": "Web search made for AI assistants. Needs a free API key from Tavily.",
        "privacy": "Your web questions go to Tavily.",
        "program": "npx", "command": "npx", "args": ["-y", "tavily-mcp@0.2.22"],
        "inputs": [{"name": "TAVILY_API_KEY", "label": "Tavily API key", "secret": True,
                    "help_url": "https://tavily.com/"}],
        "tool": "tavily_search", "arguments": {"max_results": RESULT_LIMIT},
    },
)

BUILTIN_FILE_INDEXES: dict[str, dict[str, Any]] = {
    "kde": {"title": "KDE's file search",
            "detail": "Finds your files by name and by words inside documents, using the index KDE keeps."},
    "locate": {"title": "File names on this computer",
               "detail": "Finds your files by name, using the list the computer updates every day."},
}
PROGRAM_HELP = {"npx": "Node.js (the 'npx' program)", "uvx": "uv (the 'uvx' program)"}


def scan_discovered(candidate: mcp_discovery.DiscoveredServer) -> dict[str, Any]:
    """Start one discovered server briefly: its tools and the roles they suit, or why it would not start."""
    described = candidate.describe()
    described.update({"tools": [], "proposals": [], "error": ""})
    spec = McpServerSpec(candidate.name, candidate.command, candidate.args, candidate.env)
    try:
        session = McpSession(spec, startup_timeout=SCAN_STARTUP_SECONDS)
    except McpError as exc:
        described["error"] = str(exc)
        return described
    try:
        tools = session.list_tools()
        described["tools"] = [tool["name"] for tool in tools]
        described["proposals"] = [found for found in (propose_role(candidate.name, tool) for tool in tools) if found]
    except McpError as exc:
        described["error"] = str(exc)
    finally:
        session.close()
    return described


def _right_kind(hit: dict[str, str], role: str) -> bool:
    if role == "web_search":
        return hit["kind"] == "link"
    # A path-shaped string is not enough (archive entries look like paths); it must be a real file here.
    return hit["kind"] in ("file", "folder") and os.path.exists(hit["location"])


def _try_found(candidate: mcp_discovery.DiscoveredServer, role: str) -> dict[str, Any] | None:
    """The server's proposal for ``role`` if a test search through it returns the right kind of result."""
    spec = McpServerSpec(candidate.name, candidate.command, candidate.args, candidate.env)
    try:
        session = McpSession(spec, startup_timeout=SCAN_STARTUP_SECONDS)
    except McpError:
        return None
    try:
        for tool in session.list_tools():
            proposal = propose_role(candidate.name, tool)
            if proposal is None or proposal["role"] != role:
                continue
            config = proposal["config"]
            result = session.call_tool(config["tool"], {**config["arguments"], config["query_argument"]: TEST_QUERIES[role]},
                                       TEST_SECONDS)
            if not result.is_error and any(_right_kind(hit, role) for hit in extract_hits(result, RESULT_LIMIT)):
                return proposal
    except McpError:
        return None
    finally:
        session.close()
    return None


def _found(role: str, settings: dict[str, Any]) -> list[dict[str, Any]]:
    configured = {(entry["command"], tuple(entry["args"])) for entry in settings["tool_servers"].values()}
    candidates = [c for c in mcp_discovery.discover_servers() if (c.command, c.args) not in configured]
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        tried = list(pool.map(lambda candidate: (candidate, _try_found(candidate, role)), candidates))
    choices = []
    for candidate, proposal in tried:
        if proposal is None:
            continue
        server = candidate.describe()
        choices.append({
            "id": f"found:{server['name']}:{server['source_path']}", "kind": "found",
            "title": server["name"].replace("_", " "),
            "detail": f"Already set up in {server['source']}; Happy Bot would use its "
                      f"{proposal['config']['tool'].replace('_', ' ')} tool.",
            "privacy": "", "ready": True, "problem": "", "inputs": [],
        })
    return choices


def kde_index_state() -> str:
    """``missing``, ``off`` or ``on`` for KDE's file index (Baloo)."""
    if not (shutil.which("baloosearch6") and shutil.which("balooctl6")):
        return "missing"
    try:
        status = subprocess.run(["balooctl6", "status"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "missing"
    return "off" if "disabled" in status.lower() else "on"


def locate_covers_home(home: str | None = None) -> bool:
    """Whether the file-name database lists anything in the user's home folder."""
    program = shutil.which("plocate")
    if not program:
        return False
    home = (home or str(Path.home())).rstrip(os.sep) + os.sep
    try:
        listed = subprocess.run([program, "-l", "1", "--", home], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return listed.startswith(home)


def _builtin_files() -> list[dict[str, Any]]:
    choices = []
    state = kde_index_state()
    if state != "missing":
        info = BUILTIN_FILE_INDEXES["kde"]
        choices.append({
            "id": "builtin:kde", "kind": "builtin", "title": info["title"],
            "detail": info["detail"] + ("" if state == "on" else
                                        " It is switched off; choosing it switches it on. The first time, "
                                        "it takes a while to learn your files."),
            "privacy": "", "ready": True, "problem": "", "inputs": [],
        })
    if locate_covers_home():
        info = BUILTIN_FILE_INDEXES["locate"]
        choices.append({"id": "builtin:locate", "kind": "builtin", "title": info["title"], "detail": info["detail"],
                        "privacy": "", "ready": True, "problem": "", "inputs": []})
    return choices


def _is_searxng(port: int) -> str:
    url = f"http://127.0.0.1:{port}"
    try:
        with urlopen(f"{url}/config", timeout=PROBE_TIMEOUT_SECONDS) as response:
            document = json.loads(response.read(200_000).decode("utf-8", errors="replace"))
    except (URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        # Ports that speak something else (SSH answers with its banner) land here.
        return ""
    brand = document.get("brand") if isinstance(document, dict) else None
    return url if isinstance(brand, dict) and "searxng" in str(brand.get("GIT_URL", "")).lower() else ""


def local_searxng(skip_ports: tuple[int, ...] = ()) -> str:
    """Address of a SearXNG answering on this computer, or ""; asks each listening port for ``/config`` once."""
    ports = [port for port in model_discovery.listening_ports() if port not in skip_ports]
    with ThreadPoolExecutor(max_workers=24) as pool:
        return next((url for url in pool.map(_is_searxng, ports) if url), "")


def suggestion(choice_id: str) -> dict[str, Any] | None:
    return next((item for item in WEB_SUGGESTIONS if f"suggested:{item['id']}" == choice_id), None)


def _suggested_web(skip_ports: tuple[int, ...]) -> list[dict[str, Any]]:
    searxng = local_searxng(skip_ports)
    choices = []
    for item in WEB_SUGGESTIONS:
        program = item["program"]
        missing = not shutil.which(program)
        inputs = [{**field, "value": searxng if field["name"] == "SEARXNG_URL" else ""} for field in item["inputs"]]
        detail = item["detail"] + (" One is running on this computer." if item["id"] == "searxng" and searxng else "")
        choices.append({
            "id": f"suggested:{item['id']}", "kind": "suggested", "title": item["title"], "detail": detail,
            "privacy": item["privacy"], "ready": not missing,
            "problem": f"Needs {PROGRAM_HELP.get(program, program)} installed first. Ask Happy Bot to install it."
                       if missing else "",
            "inputs": inputs,
        })
    if not searxng:
        # A SearXNG the user would have to set up is not the easy choice; move it after the others.
        choices.append(choices.pop(0))
    return choices


def choices(role: str, settings: dict[str, Any], skip_ports: tuple[int, ...] = ()) -> list[dict[str, Any]]:
    """Every choice for ``role`` (``file_search`` or ``web_search``), best first, the best ready one recommended."""
    found = _found(role, settings)
    listed = [*found, *(_builtin_files() if role == "file_search" else _suggested_web(skip_ports))]
    recommended = next((item for item in listed if item["ready"] and not any(
        not field.get("value") for field in item["inputs"])), None)
    for item in listed:
        item["recommended"] = item is recommended
    return listed

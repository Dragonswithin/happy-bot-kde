"""KRunner plugin: the assistant's quick results and file matches in KRunner, and "ask the assistant".

KRunner (Alt+Space, and the launcher's search) loads "DBus runners" listed in
``~/.local/share/krunner/dbusplugins`` (``krunner/kde-ai-assistant.desktop``,
installed by ``scripts/install.sh``) and asks them over the session DBus with
the ``org.kde.krunner1`` interface. The daemon owns the bus name ``SERVICE``
and answers at ``PATH``:

- ``Match(query)``: the same quick results the bar shows
  (``quick_results.gather``), then file matches from the user's index
  (``instant_search``, when a file-search tool is set up), then one "Ask the
  assistant" entry. Matches are remembered by id for ``Run``.
- ``Run(match_id, action_id)``: carries out a quick result
  (``quick_results.activate``), opens a file, or sends the question to the
  assistant in the background (``kde-ai-assistant ask --notify``), whose
  answer arrives as a notification.
- ``Actions()``: none.

Threading: DBus calls arrive on the shared GLib loop (``glib_loop``). Gathering
quick results asks KWin for its windows, which needs that same loop, so each
call is answered from a worker thread (``invocation.return_value`` may be
called from any thread). ``start`` never raises: without PyGObject or a
session bus, KRunner simply does not show the assistant.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from typing import TYPE_CHECKING, Any

from . import glib_loop, instant_search, quick_results

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

SERVICE = "io.github.dragonswithin.KdeAiAssistant.Runner"
PATH = "/runner"
MIN_QUERY = 3
_INTROSPECTION = """
<node>
  <interface name="org.kde.krunner1">
    <method name="Actions"><arg name="matches" type="a(sss)" direction="out"/></method>
    <method name="Run"><arg name="matchId" type="s" direction="in"/><arg name="actionId" type="s" direction="in"/></method>
    <method name="Match"><arg name="query" type="s" direction="in"/><arg name="matches" type="a(sssida{sv})" direction="out"/></method>
  </interface>
</node>
"""
EXACT, POSSIBLE, HELPER = 100, 30, 70


class KRunnerBridge:
    """Answers KRunner for one ``AssistantServer``; see the module docstring."""

    def __init__(self, server: "AssistantServer") -> None:
        self.server = server
        self._matches: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def matches(self, query: str) -> list[tuple[str, str, str, int, float, dict[str, Any]]]:
        """``(id, text, icon, type, relevance, properties)`` for KRunner, best first."""
        query = query.strip()
        if len(query) < MIN_QUERY:
            return []
        found: list[tuple[str, str, str, int, float, dict[str, Any]]] = []
        remembered: dict[str, dict[str, Any]] = {}
        for index, result in enumerate(quick_results.gather(query, self.server.conversations.list())):
            if result["action"]["type"] == "conversation":
                continue
            ident = f"quick-{index}"
            remembered[ident] = {"kind": "quick", "action": result["action"]}
            found.append((ident, result["title"], result["icon"], EXACT if index == 0 else POSSIBLE,
                          0.9 - index * 0.05, {"subtext": result["subtitle"]}))
        try:
            hits = instant_search.search_files(self.server.mcp, self.server.settings, query, 5)
        except Exception:  # noqa: BLE001 - no index or a failing one just means no file matches
            hits = []
        for index, hit in enumerate(hits):
            ident = f"file-{index}"
            remembered[ident] = {"kind": "open", "location": hit["location"]}
            found.append((ident, hit["title"], "document-open", POSSIBLE, 0.6 - index * 0.05,
                          {"subtext": hit["location"]}))
        remembered["ask"] = {"kind": "ask", "query": query}
        found.append(("ask", f"Ask the assistant: {query}", "tools-wizard", HELPER, 0.3,
                      {"subtext": "The answer arrives as a notification"}))
        with self._lock:
            self._matches = remembered
        return found

    def run(self, match_id: str) -> None:
        with self._lock:
            chosen = self._matches.get(match_id)
        if chosen is None:
            return
        if chosen["kind"] == "quick":
            quick_results.activate(chosen["action"])
        elif chosen["kind"] == "open":
            from .desktop_actions import open_location
            open_location(chosen["location"])
        elif chosen["kind"] == "ask":
            launcher = shutil.which("kde-ai-assistant")
            if launcher:
                subprocess.Popen([launcher, "ask", "--notify", "--", chosen["query"]], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def _on_call(self, connection, sender, path, interface, method, parameters, invocation) -> None:
        from gi.repository import GLib

        def answer() -> None:
            try:
                if method == "Match":
                    invocation.return_value(GLib.Variant("(a(sssida{sv}))", (self._variant_matches(parameters.unpack()[0]),)))
                elif method == "Run":
                    self.run(parameters.unpack()[0])
                    invocation.return_value(None)
                else:
                    invocation.return_value(GLib.Variant("(a(sss))", ([],)))
            except Exception as error:  # noqa: BLE001 - KRunner must always get an answer
                invocation.return_dbus_error("org.kde.krunner1.Error", str(error))

        threading.Thread(target=answer, name="krunner-call", daemon=True).start()

    def _variant_matches(self, query: str) -> list:
        from gi.repository import GLib

        return [(ident, text, icon, kind, relevance, {key: GLib.Variant("s", value) for key, value in properties.items()})
                for ident, text, icon, kind, relevance, properties in self.matches(query)]

    def start(self) -> bool:
        """Publish the runner on the session bus; False (and nothing else) if that is not possible."""
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION)
            connection.register_object(PATH, node.interfaces[0], self._on_call, None, None)
            Gio.bus_own_name_on_connection(connection, SERVICE, Gio.BusNameOwnerFlags.REPLACE, None, None)
            glib_loop.ensure_running()
            return True
        except Exception:  # noqa: BLE001 - no PyGObject or bus: KRunner just does not list the assistant
            return False

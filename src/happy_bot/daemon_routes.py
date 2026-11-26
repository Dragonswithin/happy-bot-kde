"""What each daemon endpoint does, separated from HTTP mechanics.

``daemon_http`` authenticates a request, parses it, and looks the endpoint up
in ``ROUTES``; the functions here do the work and return ``(status, payload)``.
They receive the ``AssistantServer`` (for its state, settings and tool-server
manager), the parsed query string and the JSON body. They never touch the
socket.

Endpoints:

- ``GET /health``: daemon status, which parts of setup are complete, the
  user's AIs in order (name and whether online) for the popup's per-chat
  picker, the shared look-and-feel settings (``ui``), and whether offline
  Wikipedia is set up (``wikipedia``).
- ``POST /ui``: change some of those shared settings (``ui_settings``); the
  panel widget and the app both read them, so they stay the same.
- ``GET /context``: desktop context capture (``desktop_context``).
- ``GET /app``, ``POST /app``: whether the Happy Bot app (the floating Happy
  Bot, run by ``happy-bot-app``) is running and starts at login; start it,
  or turn starting at login on or off (``app_control``).
- ``POST /app/show``, ``GET /app/wait?seen=N``: a second launch asks the
  running app to open (``happy-bot app show``), or to open and listen
  (``happy-bot app talk``); the app waits on
  ``/app/wait``, which answers when a request arrives or after 25 seconds.
- ``GET /panel``, ``POST /panel``: the Happy Bot widgets on the user's panels,
  whether they show a search bar or the icon and the bar's width;
  ``{"search_bar": bool}`` and/or ``{"bar_width": 8..60}`` change them all
  (``panel_widget``), for the app's Appearance page.
- ``GET /context/app``: the application the user is working in (name, class,
  window title, icon name, KWin window id; all empty when the user's
  ``agent.app_context`` is "off"), noted by the popup when it is opened from
  the floating button or the hotkey and sent with its requests as background
  (``desktop_context.current_application``); ``screenshots`` says whether an
  AI that sees pictures may see it. Nothing is captured here.
- ``POST /context/screenshot`` ``{"window": id}``: only after the user chose
  "Help with …": a screenshot of that window for the chat's next request
  (``app_context.remember_screenshot``), when an AI that sees pictures may
  see it; ``taken`` says whether one was. With ``preview: true``, capture for
  local display even with a text-only AI. Return its file URL, attachment ID
  and eligible model names. ``desktop: true`` requests the whole desktop.
- ``POST /context/screenshot/edit``: mark a point, crop a rectangle or read text from a
  preview by ID. Edits return a new private preview; coordinates are fractions of its image.
- ``GET /search?q=...``: instant file search through the ``file_search`` role;
  ``GET /search/web?q=...`` the web finder's pages through ``web_search``.
- ``GET /settings`` / ``PUT /settings``: read (redacted) and replace settings.
  The read also carries what the settings page needs to offer choices:
  ``effective_folders`` (where each standard folder is now) and
  ``terminals`` (supported terminals that are installed) and
  ``suggested_instructions`` (the default text of ``agent.instructions``).
- ``GET /tools/discover``: tool servers found in other programs' configs.
- ``POST /tools/import``: copy one discovered server into the settings.
- ``GET /tools/servers[?name=...]``: configured servers, their tools (with
  each tool's arguments and its likely query and result-limit arguments) and
  role proposals. This starts the servers, so it
  can take seconds.
- ``POST /open``: open a file, folder or link (``desktop_actions``).
- ``POST /open/browser-focus``: bring forward the existing default-browser
  window for a clicked ``http`` or ``https`` link if it needs a focus handoff.
- ``POST /models/discover``: find model services running on this computer.
- ``POST /tools/scan``: start each discovered, not yet configured tool
  server briefly to report its tools and the roles it could fill. Slow by
  nature (seconds per server); servers are scanned in parallel
  (``search_choices.scan_discovered``).
- ``POST /search/choices``: what could do file search or web search here,
  best first, for the settings page's "Set up" (``search_choices``).
- ``POST /search/use``: use one of those choices: add its server, assign the
  job, run a test search, and undo it all if the test fails
  (``search_setup``). Can take a minute when a server is downloaded first.
- ``GET /typing``, ``POST /typing/allow``: whether the desktop allows the
  assistant to type into other apps, and asking it now (the RemoteDesktop
  portal's dialog, ``input_portal``) rather than in the middle of a request.
- ``POST /models/probe``: list the models a service offers, to help setup.
- ``POST /models/check``: the full compatibility check of a configured model
  (``model_check``: answering, one and two tool calls, its tool results,
  continuing another AI's conversation, pictures), ``{"name", "results",
  "passed", "message"}``; ``passed`` is false when any check failed.
- ``POST /models/test``: check that a configured model answers and can call
  tools (``model_setup.check_model``). This sends one small request to the model.
- ``GET /models/presets``: the online AI services setup offers, with where to
  get a key (``model_presets``).
- ``POST /models/use``: add a model (found, from a preset with a key, or by
  address), test it and make it the main model or the backup, undoing it if
  it does not answer (``model_setup``).
- ``POST /cancel``: stop a conversation's running turn.
- ``GET /conversations``: saved conversations, newest first
  (``{id, title, created, updated, requests}``).
- ``GET /conversation?id=...``: one conversation's display events, for the
  popup to redraw it.
- ``POST /conversations/delete``: ``{"id": ...}`` or ``{"all": true}``.
- ``POST /history/clear``: clear one explicit ``kind``: search suggestions,
  conversations, activity, undo, previous months' usage, or temporary cache files and graph samples.
- ``POST /conversations/pin``: ``{"id": ..., "pinned": bool}``; pinned ones
  are listed first and kept past ``history_days``.
- ``GET /export`` / ``POST /import``: everything the assistant keeps for the
  user, without secrets (``personal_data``).
- ``GET /tools/catalog`` / ``POST /tools/run``: the built-in tools lent to
  other AI programs through ``happy-bot mcp-serve``, only while the
  user's ``agent.serve_tools`` setting is on. A call that the approval
  policy would put to the user is refused (there is no one to ask), and
  every call is written to the action log.
- ``GET /spend``: this month's tokens and cost per model (``spend``).
- ``GET /check``: the self-check (``self_check.run_checks``): every
  dependency's state with a fix for each problem.
- ``GET /quick?q=...``: results the bar shows besides files (instant
  commands, answers, characters, applications, settings pages, browser
  bookmarks and history when the user switched them on, conversations;
  ``quick_results``).
- ``GET /quick/recent``: what the empty bar suggests (recent applications,
  files, settings pages, chats, and websites when recent websites are
  switched on; ``quick_results.recent``).
- ``GET /web/start``: pinned and frequently visited sites and recent web searches.
  ``POST /web/site`` saves a pin, unpin, hide or unhide action. ``POST /web/search/remember``
  keeps a query the user chose.
- ``POST /quick/activate``: ``{"action": {...}}`` from one of those results;
  an instant command runs its tool here and is written to the action log.
- ``GET /quick/app?path=...``: what an application result's menu offers
  (``{package, source, update, uninstall, autostart}``, ``app_actions``);
  ``POST /quick/app`` (``{"path", "action"}``) does one: ``update`` or
  ``uninstall`` opens a terminal running the user's package manager, where
  the user confirms; ``autostart_on``/``autostart_off`` change the login
  entry. Each is written to the action log.
- ``GET /selection``: the selected text and its window, noted when the
  "Fix selected text" shortcut was pressed (``POST /app/show`` with
  ``fix``; ``selection_fix``). ``POST /selection/rewrite`` (``{"text",
  "style", "instruction"}``) asks an AI the user's privacy setting allows
  for the fixed, shorter, translated or explained text (``text_rewrite``);
  ``POST /selection/replace`` (``{"window", "text"}``) pastes it over the
  selection there and writes the action log.
- ``GET /reminders``: reminders and timers that are set
  (``{id, when, text}``, soonest first; ``tools/reminders.py``).
- ``POST /reminders/cancel``: ``{"id": ...}``.
- ``POST /approve``: the user's answer to an approval request
  (``{"id", "decision": "allow"|"deny", "remember": bool}``).
- ``POST /screenshot``.
- ``POST /voice/listen``: records the microphone until the user pauses
  and returns ``{"text"}`` as the speech service heard it; it blocks for
  as long as the user talks (``voice.Listener``). ``POST /voice/stop``
  (``{"discard": bool}``) ends a recording early: the microphone clicked
  again sends what was said, Escape discards it. ``POST /voice/check``
  sends half a second of silence to the configured service, for the
  settings page's Test button; ``POST /voice/find`` tries the model
  services on this computer that way and returns the first that answers. Errors carry ``voice.VoiceError``'s code.

``POST /ask`` is not here: it streams, so ``daemon_http`` hands it to
``ask_stream``.

Errors the user can act on are returned as ``{"ok": false, "error": ...,
"code": ...}`` with a 4xx/5xx status; ``code`` lets the applet choose a fix
to offer (``not_configured``, ``tool_failed``, ``invalid``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from concurrent.futures import ThreadPoolExecutor

from . import (app_actions, selection_fix, text_rewrite, app_context, app_control, voice, desktop_actions, desktop_context, input_portal, instant_search, mcp_discovery, model_discovery, personal_data,
               model_check, model_presets, model_setup, panel_widget, quick_results, search_choices, search_setup, self_check, spend)
from . import help_screenshot, settings as settings_store, sounds, ui_settings, web_preferences
from .agent_loop import user_folders
from .mcp_client import McpError
from .providers import ProviderError
from .redaction import is_local_address
from .runtime_paths import write_private_file
from .providers.openai_compatible import list_models
from .tool_roles import RoleNotConfigured, find_limit_argument, find_query_argument, propose_role, tool_arguments
from .tools import reminders
from .tools.registry import ToolFailure
from .tools.shell import installed_terminals

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

Reply = tuple[int, dict[str, Any]]
Route = Callable[["AssistantServer", dict[str, list[str]], dict[str, Any]], Reply]

MAX_QUERY_CHARS = 500


def _error(status: int, message: str, code: str) -> Reply:
    return status, {"ok": False, "error": message, "code": code}


def _first(query: dict[str, list[str]], name: str, default: str = "") -> str:
    return (query.get(name) or [default])[0]


def health(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    payload = server.state.as_dict()
    roles = server.settings.get("roles", {})
    payload["setup"] = {
        "file_search": "file_search" in roles,
        "web_search": "web_search" in roles,
        "model": settings_store.active_model(server.settings) is not None,
    }
    # The popup's per-chat picker: names and whether each is online, in the user's order. No secrets.
    payload["models"] = [{"name": name, "online": not is_local_address(server.settings["models"][name]["base_url"])}
                         for name in server.settings.get("model_order", [])]
    payload["ui"] = server.settings.get("ui") or {}
    # The microphone button shows when the user switched it on and a speech service is set.
    voice_settings = server.settings.get("voice") or {}
    payload["voice"] = {"enabled": bool(voice_settings.get("enabled") and voice_settings.get("base_url")),
                        "listening": server.voice.active}
    wikipedia = server.settings.get("wikipedia") or {}
    payload["wikipedia"] = bool(wikipedia.get("server") and wikipedia.get("folder"))  # its finder can be offered
    payload["settings_error"] = server.settings_error
    return 200, payload


def icon_activity(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Current icon cues, immediately on first connection or as soon as any cue changes."""
    return 200, server.activity.wait(_first(query, "seen"))


def play_sound(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    event = body.get("event")
    if event not in ui_settings.SOUND_EVENTS:
        return _error(400, "Unknown sound event.", "invalid")
    if not server.voice.active:
        sounds.play(server.settings["ui"], event)
    return 200, {"ok": True}


def preview_sound(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    event, theme = body.get("event"), body.get("theme")
    if event not in ui_settings.SOUND_EVENTS or theme not in ui_settings.SOUND_THEMES:
        return _error(400, "Choose a listed event and sound theme.", "invalid")
    if server.voice.active:
        return _error(409, "Finish voice input before previewing a sound.", "busy")
    if not sounds.preview(theme, event):
        return _error(503, "Could not play this sound. Check the audio output and that pw-play, paplay or aplay is available.", "audio_unavailable")
    return 200, {"ok": True}


def dismiss_nudge(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    kind = body.get("kind")
    if not isinstance(kind, str) or not server.activity.dismiss_nudge(kind):
        return _error(400, "Unknown mascot nudge", "invalid")
    return 200, {"ok": True}


def context(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    kind = _first(query, "kind", "combined")
    captured = desktop_context.combined_context(kind)
    server.state.update(last_context_kind=kind)
    return 200, {"ok": True, "context": captured}


def change_ui(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Merge ``body["changes"]`` into the shared look-and-feel settings (``ui_settings``); returns them all."""
    changes = body.get("changes")
    if not isinstance(changes, dict):
        return _error(400, "changes must be an object", "invalid")
    try:
        stored = server.update_ui(changes)
    except settings_store.SettingsError as error:
        return _error(400, str(error), "invalid")
    return 200, {"ok": True, "ui": stored["ui"]}


def app_status(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "running": app_control.running(), "autostart": app_control.autostart_enabled()}


def app_change(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """``{"autostart": bool}`` starts it at login or not; ``{"start": true}`` starts it now if it is not running."""
    try:
        if isinstance(body.get("autostart"), bool):
            app_control.set_autostart(body["autostart"])
        if body.get("start") is True and not app_control.running():
            app_control.start()
    except OSError as error:
        return _error(500, f"Could not change how the Happy Bot app starts: {error}", "invalid")
    return app_status(server, query, body)


def panel_status(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, "widgets": panel_widget.panel_widgets()}
    except panel_widget.PanelWidgetError as error:
        return _error(503, f"Could not read the panel: {error}", "unreachable")


def panel_change(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """``{"search_bar": bool, "bar_width": int}`` (either or both) for every Happy Bot panel widget."""
    search_bar, bar_width = body.get("search_bar"), body.get("bar_width")
    if search_bar is not None and not isinstance(search_bar, bool):
        return _error(400, "search_bar must be true or false", "invalid")
    low, high = panel_widget.BAR_WIDTH_RANGE
    if bar_width is not None and (isinstance(bar_width, bool) or not isinstance(bar_width, int)
                                  or not low <= bar_width <= high):
        return _error(400, f"bar_width must be a whole number from {low} to {high}", "invalid")
    if search_bar is None and bar_width is None:
        return _error(400, "give search_bar and/or bar_width", "invalid")
    try:
        return 200, {"ok": True, "widgets": panel_widget.change(search_bar, bar_width)}
    except panel_widget.PanelWidgetError as error:
        return _error(503, f"Could not change the panel: {error}", "unreachable")


def app_show(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    action = str(body.get("action") or "open")
    if action == "fix":  # note the selection now, before the app opens and may take the focus
        server.selection.capture()
    return 200, {"ok": True, "count": app_control.waker.notify(action), "running": app_control.running()}


def _voice_error(error: "voice.VoiceError") -> Reply:
    # 503: no microphone or no sound from it (a headset switched off); 502 only when the speech service fails.
    status = {"busy": 409, "not_set_up": 400, "local_only": 403, "no_speech": 422,
              "no_microphone": 503}.get(error.code, 502)
    return status, {"ok": False, "error": str(error), "code": error.code}


def voice_listen(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    agent = server.settings.get("agent") or {}
    try:
        heard = server.voice.listen(server.settings.get("voice") or voice.VOICE_DEFAULTS, bool(agent.get("local_only")),
                                    server.settings.get("ui", {}))
    except voice.VoiceError as error:
        # A second request should not feed an error tone into an ongoing recording.
        if error.code != "busy":
            sounds.play(server.settings.get("ui", {}), "error")
        return _voice_error(error)
    return 200, {"ok": True, **heard}


def voice_stop(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "was_listening": server.voice.stop(discard=body.get("discard") is True)}


def voice_check(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Checks ``body["voice"]`` (the settings page's unsaved fields) or else the saved voice settings."""
    agent = server.settings.get("agent") or {}
    try:
        wanted = voice.validate_voice(body["voice"]) if isinstance(body.get("voice"), dict) \
            else server.settings.get("voice") or voice.VOICE_DEFAULTS
        return 200, voice.check_service(wanted, bool(agent.get("local_only")))
    except voice.VoiceSettingsError as error:
        return 400, {"ok": False, "error": str(error), "code": "invalid"}
    except voice.VoiceError as error:
        return _voice_error(error)


def voice_find(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """A speech-to-text service on this computer: the user's local AIs' addresses first, then any found."""
    known = [model["base_url"] for model in server.settings.get("models", {}).values()]
    found = voice.find_service(known) or voice.find_service([item["base_url"] for item in model_discovery.discover_local()])
    if not found:
        return 404, {"ok": False, "code": "not_found",
                     "error": "No speech-to-text service answered on this computer."}
    return 200, {"ok": True, "base_url": found}


def app_wait(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        seen = int(_first(query, "seen", "-1"))
    except ValueError:
        return _error(400, "seen must be a number", "invalid")
    return 200, {"ok": True, **app_control.waker.wait(seen)}


def current_application(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """The window the user is in; empty when their app_context setting is "off", so nothing is noted."""
    if (server.settings.get("agent") or {}).get("app_context") == "off":
        return 200, {"ok": True, "app": "", "class": "", "title": "", "icon": "", "window": ""}
    found = desktop_context.current_application()
    return 200, {"ok": True, **found, "screenshots": app_context.screenshots_wanted(server.settings) and bool(found["window"])}


def capture_screenshot(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """``{"window": id}``: after "Help with …", a screenshot of that window for the chat's next request."""
    if (server.settings.get("agent") or {}).get("app_context") == "off":
        return 200, {"ok": True, "taken": False, "reason": "disabled"}
    window = str(body.get("window") or "")
    if body.get("preview") is True:
        path = app_context.preview_screenshot(window, body.get("desktop") is True, server.runtime_dir)
        if not path:
            return 200, {"ok": True, "taken": False}
        return 200, {"ok": True, "taken": True, "url": Path(path).as_uri(), "id": Path(path).stem,
                     "models": app_context.context_models(server.settings, vision=True),
                     "text_models": app_context.context_models(server.settings)}
    taken = app_context.remember_screenshot(server.settings, window, server.runtime_dir)
    return 200, {"ok": True, "taken": taken}


def edit_help_screenshot(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if (server.settings.get("agent") or {}).get("app_context") == "off":
        return _error(403, "Help screenshots are turned off in Behaviour settings.", "disabled")
    path = app_context.preview_path(server.runtime_dir, body.get("id"))
    if not path:
        return _error(404, "This screenshot is no longer available. Take it again.", "not_found")
    try:
        if body.get("action") == "read":
            return 200, {"ok": True, "text": help_screenshot.read_text(Path(path))}
        with app_context.screenshot_lock:
            edited = help_screenshot.edit(Path(path), str(body.get("action")), body.get("coordinates"))
        return 200, {"ok": True, "id": edited.stem, "url": edited.as_uri()}
    except ImportError:
        return _error(503, "Install Python Pillow to crop or mark screenshots.", "unavailable")
    except ValueError as error:
        return _error(400, str(error), "invalid")
    except ToolFailure as error:
        return _error(422, str(error), "tool_failed")
    except OSError:
        return _error(422, "The screenshot could not be edited. Try taking it again.", "tool_failed")


def search(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    if not text:
        return 200, {"ok": True, "query": "", "hits": []}
    try:
        limit = max(1, min(instant_search.MAX_HITS, int(_first(query, "limit", "8"))))
    except ValueError:
        return _error(400, "limit must be a number", "invalid")
    try:
        hits = instant_search.search_files(server.mcp, server.settings, text, limit)
    except RoleNotConfigured:
        return _error(409, "File search is not set up yet.", "not_configured")
    except McpError as exc:
        return _error(502, str(exc), "tool_failed")
    return 200, {"ok": True, "query": text, "hits": hits}


def search_web(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    if not text:
        return 200, {"ok": True, "query": "", "hits": []}
    try:
        hits = instant_search.search_web(server.mcp, server.settings, text, 8)
    except RoleNotConfigured:
        return _error(409, "Web search is not set up yet.", "not_configured")
    except McpError as exc:
        return _error(502, str(exc), "tool_failed")
    return 200, {"ok": True, "query": text, "hits": hits}


def web_start(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    index = server.search_history.index
    ranked = index.frequent_sites() if server.settings["ui"]["search_history"] else []
    # A first load may take a moment to read browser databases. Respect a change
    # to privacy settings or a clear that happened while those reads were running.
    ui = server.settings["ui"]
    current = server.search_history.index
    if index is not current or not ui["search_history"]:
        ranked = []
    sites = web_preferences.site_rows(ranked, ui)
    favicons = current.favicons(sites)
    for site in sites:
        if site["host"] in favicons:
            site["favicon"] = favicons[site["host"]]
    return 200, {"ok": True, "sites": sites, "history_enabled": ui["search_history"],
                 "searches": server.search_history.web_queries(), "search_clear_revision": current.history_since}


def change_web_site(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        server.change_web_site(body.get("url"), body.get("action"))
    except ValueError as exc:
        return _error(400, str(exc), "invalid")
    except OSError:
        return _error(500, "Could not save the site preference.", "save_failed")
    return web_start(server, {}, {})


def remember_web_search(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        server.search_history.remember_web_query(body.get("query"), body.get("revision"))
    except ValueError as exc:
        return _error(400, str(exc), "invalid")
    except OSError:
        return _error(500, "Could not save the web search.", "save_failed")
    return 200, {"ok": True}


def get_settings(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    # ``effective_folders`` is read-only information for the settings UI: where
    # each standard folder currently resolves to, overrides included.
    return 200, {
        "ok": True,
        "settings": settings_store.redacted(server.settings),
        "effective_folders": user_folders(server.settings.get("folders")),
        "terminals": installed_terminals(),
        "suggested_instructions": settings_store.SUGGESTED_INSTRUCTIONS,
    }


def put_settings(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        stored = server.replace_settings(settings_store.merge_redacted(body.get("settings"), server.settings))
    except settings_store.SettingsError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True, "settings": settings_store.redacted(stored)}


def discover_tools(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    configured = {
        (entry["command"], tuple(entry["args"])): name for name, entry in server.settings["tool_servers"].items()
    }
    found = []
    for candidate in mcp_discovery.discover_servers():
        described = candidate.describe()
        described["configured_as"] = configured.get((candidate.command, candidate.args))
        found.append(described)
    return 200, {"ok": True, "servers": found}


def import_tool_server(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    name = str(body.get("name") or "")
    source_path = str(body.get("source_path") or "")
    matches = [
        candidate
        for candidate in mcp_discovery.discover_servers()
        if candidate.name == name and (not source_path or candidate.source_path == source_path)
    ]
    if not matches:
        return _error(404, f"no tool server named '{name}' was found to import", "invalid")
    target = str(body.get("as") or name)
    updated = {**server.settings, "tool_servers": dict(server.settings["tool_servers"])}
    updated["tool_servers"][target] = matches[0].as_settings_entry(read_only=bool(body.get("read_only", False)))
    try:
        stored = server.replace_settings(updated)
    except settings_store.SettingsError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True, "imported": target, "settings": settings_store.redacted(stored)}


def list_tool_servers(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    only = _first(query, "name")
    servers = []
    for name, entry in sorted(server.settings["tool_servers"].items()):
        if only and name != only:
            continue
        item: dict[str, Any] = {
            "name": name,
            "enabled": entry["enabled"],
            "read_only": entry["read_only"],
            "tools": [],
            "proposals": [],
            "error": "",
        }
        if entry["enabled"]:
            try:
                tools = server.mcp.list_tools(name)
            except McpError as exc:
                item["error"] = str(exc)
            else:
                item["tools"] = [
                    {"name": tool["name"], "description": str(tool.get("description") or "")[:300],
                     "arguments": tool_arguments(tool), "query_argument": find_query_argument(tool) or "",
                     "limit_argument": find_limit_argument(tool) or ""}
                    for tool in tools
                ]
                item["proposals"] = [found for found in (propose_role(name, tool) for tool in tools) if found]
        servers.append(item)
    return 200, {"ok": True, "servers": servers}


def open_location(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        desktop_actions.open_location(str(body.get("location") or ""))
    except desktop_actions.DesktopActionError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True}


def focus_browser(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    scheme = body.get("scheme")
    if scheme not in ("http", "https"):
        return _error(400, "Only web browsers can be focused here.", "invalid")
    return 200, {"ok": True, "focused": desktop_actions.focus_default_browser(scheme)}


def screenshot(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, app_context.capture_desktop(server.runtime_dir)


def discover_models(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    def key(base_url: str, model_id: str) -> tuple[str, str]:
        # The same service may be stored with or without its /v1 suffix.
        return base_url.rstrip("/").removesuffix("/v1"), model_id

    configured = {key(model["base_url"], model["model"]): name for name, model in server.settings["models"].items()}
    services = model_discovery.discover_local(skip_ports=(server.state.port,))
    for service in services:
        for model in service["models"]:
            model["configured_as"] = configured.get(key(service["base_url"], model["id"]))
    return 200, {"ok": True, "services": services}


def scan_tool_servers(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    configured = {(entry["command"], tuple(entry["args"])) for entry in server.settings["tool_servers"].values()}
    candidates = [c for c in mcp_discovery.discover_servers() if (c.command, c.args) not in configured]
    if not candidates:
        return 200, {"ok": True, "servers": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return 200, {"ok": True, "servers": list(pool.map(search_choices.scan_discovered, candidates))}


def search_choices_route(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    role = str(body.get("role") or "")
    if role not in settings_store.ROLE_NAMES:
        return _error(400, f"unknown job '{role}'", "invalid")
    return 200, {"ok": True, "choices": search_choices.choices(role, server.settings, skip_ports=(server.state.port,))}


def search_use(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
    result = search_setup.use(server, str(body.get("role") or ""), str(body.get("choice") or ""),
                              {str(key): str(value) for key, value in inputs.items()})
    if not result["ok"]:
        return _error(400, result["error"], "invalid")
    return 200, {**result, "settings": settings_store.redacted(server.settings)}


def typing_status(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "allowed": input_portal.consent_saved()}


def allow_typing(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Shows the desktop's "allow remote control" question now, instead of in the middle of a request."""
    try:
        input_portal.shared().start()
    except input_portal.InputUnavailable as error:
        return _error(409, str(error).capitalize() + ".", "declined")
    return 200, {"ok": True, "allowed": input_portal.consent_saved()}


def probe_models(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """List models at ``base_url``, also trying ``<base_url>/v1`` so a bare address works."""
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return _error(400, "The address must start with http:// or https://", "invalid")
    api_key = body.get("api_key")
    if api_key is None and body.get("name"):
        api_key = server.settings.get("models", {}).get(str(body["name"]), {}).get("api_key", "")
    headers = body.get("headers") if isinstance(body.get("headers"), dict) else {}
    headers = {str(key): str(value) for key, value in headers.items()}
    candidates = [base_url] if base_url.endswith("/v1") else [base_url, f"{base_url}/v1"]
    failure = ""
    for candidate in candidates:
        try:
            models = list_models(candidate, str(api_key or ""), headers=headers)
        except ProviderError as exc:
            failure = failure or str(exc)
            continue
        return 200, {"ok": True, "base_url": candidate, "models": models}
    return _error(502, failure, "unreachable")


def test_model(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Ask the named (or active) model to call a trivial tool; report whether it did (``model_setup.check_model``)."""
    name = str(body.get("name") or server.settings.get("active_model") or "")
    model = server.settings.get("models", {}).get(name)
    if model is None:
        return _error(404, f"no model named '{name}' is set up", "invalid")
    try:
        result = model_setup.check_model(model)
    except ProviderError as exc:
        return _error(502, str(exc), "unreachable")
    return 200, {"ok": True, "name": name, **result}


def check_model_route(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """The named (or first) model's compatibility check (``model_check.run``); blocks while it runs."""
    name = str(body.get("name") or next(iter(server.settings.get("model_order") or []), ""))
    model = server.settings.get("models", {}).get(name)
    if model is None:
        return _error(404, f"no model named '{name}' is set up", "invalid")
    results = model_check.run(model)
    passed, message = model_check.summary(name, results)
    return 200, {"ok": True, "name": name, "results": results, "passed": passed, "message": message}


def model_presets_route(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "presets": model_presets.listing()}


def use_model(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    result = model_setup.use(server, body)
    if not result["ok"]:
        return _error(400, result["error"], "invalid")
    return 200, {**result, "settings": settings_store.redacted(server.settings)}


def cancel(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "cancelled": server.conversations.cancel(str(body.get("conversation_id") or ""))}


def list_conversations(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "conversations": server.conversations.list()}


def get_conversation(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    conversation = server.conversations.get(_first(query, "id"))
    if conversation is None:
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True, "id": conversation.id, "created": conversation.created,
                 "title": conversation.title, "model": conversation.model,
                 "events": conversation.events}


def delete_conversations(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if body.get("all") is True:
        return clear_history(server, query, {"kind": "conversations"})
    if not server.conversations.delete(str(body.get("id") or "")):
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True, "deleted": 1}


def clear_history(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    from . import permissions, undo_journal

    kind = body.get("kind")
    if set(body) != {"kind"} or kind not in ("search", "conversations", "activity", "undo", "cache", "usage"):
        return _error(400, "Choose one type of saved data to clear.", "invalid")
    try:
        if kind == "conversations":
            with server.history_clear_lock:
                deleted = server.conversations.delete_all()
                when = server.conversations.cleared_at
                server.activity.history_cleared("conversation", when)
                write_private_file(server.conversation_clear_marker, str(when))
            return 200, {"ok": True, "deleted": deleted}
        if kind == "search":
            with server.history_clear_lock:
                server.search_history.clear()
                server.krunner.clear()
                server.activity.history_cleared("search", server.search_history.index.history_since)
        elif kind == "activity":
            permissions.clear_activity(server.runtime_dir)
        elif kind == "undo":
            undo_journal.clear_history(server.runtime_dir)
        elif kind == "usage":
            spend.clear_past_usage()
        else:
            server.voice.clear_cache()
            app_context.clear_screenshots(server.runtime_dir)
            server.system_history.clear()
    except OSError as exc:
        return _error(500, f"Could not finish clearing {kind}: {exc}", "clear_failed")
    return 200, {"ok": True}


def pin_conversation(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if not server.conversations.set_pinned(str(body.get("id") or ""), body.get("pinned") is True):
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True}


def approve(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    accepted = server.approvals.resolve(
        str(body.get("id") or ""), str(body.get("decision") or ""), bool(body.get("remember", False)))
    if not accepted:
        return _error(404, "That request is no longer waiting for an answer.", "invalid")
    return 200, {"ok": True}


def export(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "data": personal_data.export_data(server)}


def import_(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, **personal_data.import_data(server, body.get("data"))}
    except (personal_data.BadExport, settings_store.SettingsError) as error:
        return _error(400, str(error), "invalid")


def _lent_tools(server: "AssistantServer"):
    from .tools.catalog import builtin_tools
    from .tools.registry import ToolRegistry

    return ToolRegistry(builtin_tools(server.settings.get("agent")))


def tool_catalog(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if not server.settings["agent"].get("serve_tools"):
        return _error(403, "Lending tools to other programs is switched off in the assistant's settings.", "invalid")
    registry = _lent_tools(server)
    return 200, {"ok": True, "tools": [{"name": spec.name, "description": spec.description,
                                        "inputSchema": spec.parameters} for spec in registry.specs()]}


def run_tool(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    from .permissions import append_audit, needs_approval

    if not server.settings["agent"].get("serve_tools"):
        return _error(403, "Lending tools to other programs is switched off in the assistant's settings.", "invalid")
    name, arguments = str(body.get("name") or ""), body.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(400, "arguments must be an object", "invalid")
    registry = _lent_tools(server)
    if registry.get(name) is None:
        return _error(404, f"there is no tool named {name}", "invalid")
    risk, summary, detail = registry.assess(name, arguments)
    outcome = "refused for another program"
    if needs_approval(server.settings.get("approval_policy", "danger"), risk):
        result = (False, f"Refused: '{summary}' needs the user's approval ({detail or risk}), which can only be "
                         "given in the assistant's own bar.")
    else:
        impossible = registry.precheck(name, arguments)
        result = (False, impossible) if impossible else registry.run(name, arguments)
        outcome = "ran for another program"
    if risk != "read":
        append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": name, "risk": risk,
                                          "outcome": outcome, "arguments": json.dumps(arguments)[:2000]})
    return 200, {"ok": True, "succeeded": result[0], "text": result[1]}


def spending(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **spend.month_summary()}


def check(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    results = self_check.run_checks(server)
    return 200, {"ok": True, "healthy": all(item["ok"] for item in results), "checks": results}


def quick(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    ui = server.settings.get("ui") or {}
    return 200, {"ok": True, "query": text, "results": quick_results.gather(
        text, server.conversations.list(), ui.get("search_bookmarks") is True, ui.get("search_history") is True,
        server.search_history.index, removed=server.search_history.removed_recent())}


def quick_recent(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    ui = server.settings.get("ui") or {}
    return 200, {"ok": True, "results": quick_results.recent(
        server.conversations.list(), ui.get("search_history") is True, since=server.search_history.index.history_since,
        removed=server.search_history.removed_recent())}


def quick_remove_recent(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        server.search_history.remove_recent(body.get("kind"), body.get("target"))
    except ValueError as exc:
        return _error(400, str(exc), "invalid")
    except OSError:
        return _error(500, "Could not remove the recent entry.", "save_failed")
    return 200, {"ok": True}


def quick_activate(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    action = body.get("action")
    if not isinstance(action, dict):
        return _error(400, "action is required", "invalid")
    try:
        return 200, {"ok": True, "message": quick_results.activate(action, server)}
    except quick_results.ActivationError as error:
        return _error(400, str(error), "invalid")


def quick_app(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, **app_actions.describe(_first(query, "path"))}
    except app_actions.AppActionError as error:
        return _error(404, str(error), "invalid")


def quick_app_action(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    from .permissions import append_audit

    path, action = str(body.get("path") or ""), str(body.get("action") or "")
    try:
        message = app_actions.carry_out(path, action, str(server.settings["agent"].get("terminal", "")))
    except app_actions.AppActionError as error:
        return _error(400, str(error), "invalid")
    append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": f"app_{action}",
                                      "risk": "danger" if action == "uninstall" else "change",
                                      "outcome": "chosen from the search bar's menu", "arguments": path[:2000]})
    return 200, {"ok": True, "message": message}


def selection(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **server.selection.current()}


def selection_rewrite(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, **text_rewrite.rewrite(server.settings, str(body.get("text") or ""),
                                                        str(body.get("style") or ""), str(body.get("instruction") or ""))}
    except text_rewrite.RewriteError as error:
        return _error(400, str(error), "invalid")


def selection_replace(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    from .permissions import append_audit

    window, text = str(body.get("window") or ""), str(body.get("text") or "")
    try:
        message = selection_fix.replace(window, text)
    except selection_fix.ReplaceError as error:
        return _error(409, str(error).capitalize(), "invalid")
    append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": "replace_selection",
                                      "risk": "change", "outcome": "chosen in Fix selected text",
                                      "arguments": json.dumps({"window": window, "characters": len(text)})})
    return 200, {"ok": True, "message": message}


def list_reminders(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    items = reminders.upcoming()
    return 200, {"ok": True, "reminders": [
        {"id": item["id"], "when": item["when"].strftime("%Y-%m-%d %H:%M"), "text": item["text"]} for item in items]}


def cancel_reminder(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, "message": reminders.cancel_reminder({"id": str(body.get("id") or "")})}
    except ToolFailure as error:
        return _error(404, str(error), "invalid")


ROUTES: dict[tuple[str, str], Route] = {
    ("GET", "/icon/activity"): icon_activity,
    ("POST", "/sound/play"): play_sound,
    ("POST", "/sound/preview"): preview_sound,
    ("POST", "/icon/nudge/dismiss"): dismiss_nudge,
    ("GET", "/health"): health,
    ("GET", "/context"): context,
    ("GET", "/context/app"): current_application,
    ("POST", "/context/screenshot"): capture_screenshot,
    ("POST", "/context/screenshot/edit"): edit_help_screenshot,
    ("POST", "/ui"): change_ui,
    ("GET", "/app"): app_status,
    ("POST", "/app"): app_change,
    ("POST", "/app/show"): app_show,
    ("POST", "/voice/listen"): voice_listen,
    ("POST", "/voice/stop"): voice_stop,
    ("POST", "/voice/check"): voice_check,
    ("POST", "/voice/find"): voice_find,
    ("GET", "/panel"): panel_status,
    ("POST", "/panel"): panel_change,
    ("GET", "/app/wait"): app_wait,
    ("GET", "/search"): search,
    ("GET", "/search/web"): search_web,
    ("GET", "/web/start"): web_start,
    ("POST", "/web/site"): change_web_site,
    ("POST", "/web/search/remember"): remember_web_search,
    ("GET", "/settings"): get_settings,
    ("PUT", "/settings"): put_settings,
    ("GET", "/tools/discover"): discover_tools,
    ("POST", "/tools/import"): import_tool_server,
    ("GET", "/tools/servers"): list_tool_servers,
    ("POST", "/open"): open_location,
    ("POST", "/open/browser-focus"): focus_browser,
    ("POST", "/screenshot"): screenshot,
    ("POST", "/models/probe"): probe_models,
    ("POST", "/models/discover"): discover_models,
    ("POST", "/tools/scan"): scan_tool_servers,
    ("POST", "/search/choices"): search_choices_route,
    ("POST", "/search/use"): search_use,
    ("GET", "/typing"): typing_status,
    ("POST", "/typing/allow"): allow_typing,
    ("POST", "/models/test"): test_model,
    ("POST", "/models/check"): check_model_route,
    ("GET", "/models/presets"): model_presets_route,
    ("POST", "/models/use"): use_model,
    ("POST", "/cancel"): cancel,
    ("POST", "/approve"): approve,
    ("GET", "/conversations"): list_conversations,
    ("GET", "/conversation"): get_conversation,
    ("POST", "/conversations/delete"): delete_conversations,
    ("POST", "/history/clear"): clear_history,
    ("POST", "/conversations/pin"): pin_conversation,
    ("GET", "/check"): check,
    ("GET", "/spend"): spending,
    ("GET", "/tools/catalog"): tool_catalog,
    ("POST", "/tools/run"): run_tool,
    ("GET", "/export"): export,
    ("POST", "/import"): import_,
    ("GET", "/quick"): quick,
    ("GET", "/quick/recent"): quick_recent,
    ("POST", "/quick/recent/remove"): quick_remove_recent,
    ("POST", "/quick/activate"): quick_activate,
    ("GET", "/quick/app"): quick_app,
    ("POST", "/quick/app"): quick_app_action,
    ("GET", "/selection"): selection,
    ("POST", "/selection/rewrite"): selection_rewrite,
    ("POST", "/selection/replace"): selection_replace,
    ("GET", "/reminders"): list_reminders,
    ("POST", "/reminders/cancel"): cancel_reminder,
}

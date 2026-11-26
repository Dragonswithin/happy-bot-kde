"""Happy Bot's look and feel, kept once in the daemon's settings: the ``ui`` settings.

Happy Bot runs as an app (the floating Happy Bot, ``app_control``) and, optionally, as a panel
widget: two copies of the same widget, which Plasma would give separate settings. Its settings
belong to the app: these live in the daemon's settings (``settings.py`` stores them, under ``ui``),
the app's Appearance and Search & Tools pages change them (``POST /ui``) and both copies read them (``GET /health``),
so the panel's popup looks and behaves like the app's. Only what concerns the panel widget alone
(search bar or icon, the bar's width) and the daemon's address stay with each copy in Plasma.

``UI_DEFAULTS`` lists every key with its default; ``UI_RANGES`` the whole-number ranges::

    "ui": {
      "robot_mascot": true,      # the robot picture instead of the wand, on the panel and in replies
      "robot_style": "pip",       # which robot wears the mascot's expressions
      "mascot_nudges": true,      # offer help with battery, disk, updates or a pending restart
      "mascot_animations": true,  # animate the robot's idle movements and activity poses
      "robot_sounds": false,       # legacy alias for event_sounds.open.enabled
      "sounds_follow_mascot": true, # change all event themes when choosing a different robot
      "event_sounds": {...},       # independent enabled flag and robot theme per event
      "popup_width": 30,          # the popup's size, in grid units: width 20 to 70,
      "popup_height": 26,         #   height 12 to 50
      "floating_docked": false,   # tuck the shortcut into a tab on the nearest side of the screen
      "floating_size": 100,       # size of the floating shortcut as a percent of its theme size, 50 to 200
      "floating_opacity": 40,     # how visible the floating Happy Bot is while not in use, 15 to 100 percent
      "search_bookmarks": false,  # search results include browser bookmarks (browsers.py)
      "search_history": false,    # ... and recently visited websites; both read on this computer only
      "web_pins": [],             # homepages chosen to always appear on the web start page
      "web_hidden": [],           # homepages excluded from its frequent sites
      "floating_x": -1,           # its place, logical pixels from the screen's top left;
      "floating_y": -1,           #   -1 = near the bottom right
      "start_screen": ["files", "web", "help"],  # the start screen's buttons, in order (START_BUTTONS:
                                  #   "files" Find a file, "web" Search the web, "help" Help with the app
                                  #   in use, "system" System info, off unless added); [] shows none
      "imported": []              # which copies ("panel", "app") have handed over their old Plasma
    }                             #   settings, so each does that only once (widget main.qml)

Files are no longer searched while the user types (only in the "Find a file" finder, with fixed
timings), so the old ``instant_*`` settings are gone: ``RETIRED_UI_KEYS`` are dropped from stored
settings instead of being refused as unknown.

Desktop notifications (``ask_stream.notify_finished``, ``happy-bot ask --notify``) show the same
picture as the panel: ``assistant_icon`` names the wand or, with ``robot_mascot`` on, the mascot's
installed theme icon. Pip shares the application icon. Other robots have named icons of their own.

The hotkey belongs to the app too, but it is a desktop shortcut of the app's own copy (set on its
Appearance page), so it is not kept here.
"""

from __future__ import annotations

from typing import Any

from . import web_preferences

SOUND_EVENTS = ("open", "error", "complete", "alarm", "reminder", "attention", "mic_ready", "mic_done", "background", "nudge")


def _default_sounds(theme: str, greeting: bool = False) -> dict[str, dict[str, Any]]:
    return {event: {"enabled": event == "open" and greeting, "theme": theme} for event in SOUND_EVENTS}


UI_DEFAULTS: dict[str, Any] = {
    "robot_mascot": True, "robot_style": "pip", "mascot_animations": True, "robot_sounds": False, "mascot_nudges": True,
    "sounds_follow_mascot": True, "event_sounds": _default_sounds("pip"),
    "popup_width": 30, "popup_height": 26, "search_bookmarks": False, "search_history": False,
    "web_pins": [], "web_hidden": [],
    "floating_docked": False, "floating_size": 100, "floating_opacity": 40, "floating_x": -1, "floating_y": -1,
    "imported": [], "start_screen": ["files", "web", "help"],
}
START_BUTTONS = ("files", "web", "help", "system")
ROBOT_STYLES = ("pip", "rivet", "orbit", "watt", "pixel", "sprig", "nixie", "sprocket", "sonar", "dotty")
UI_RANGES: dict[str, tuple[int, int]] = {
    "popup_width": (20, 70), "popup_height": (12, 50), "floating_opacity": (15, 100), "floating_size": (50, 200),
    "floating_x": (-1, 100_000), "floating_y": (-1, 100_000),
}
WAND_ICON = "tools-wizard"
MASCOT_ICON = "io.github.dragonswithin.happybot"
RETIRED_UI_KEYS = ("instant_search", "instant_min_chars", "instant_delay_ms", "instant_results")
COPIES = ("panel", "app")


class UiSettingsError(ValueError):
    """A ``ui`` value is not acceptable; the message says which and why."""


def _sound_edits(previous: dict[str, Any], edits: Any) -> Any:
    """Apply per-field edits without losing another event's choices. Validation follows the merge."""
    if not isinstance(edits, dict):
        return edits
    sounds = previous.copy()
    for event, fields in edits.items():
        sounds[event] = {**sounds.get(event, {}), **fields} if isinstance(fields, dict) else fields
    return sounds


def merge_ui(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Merge an incremental /ui edit, including robot changes and partial event edits, in order."""
    merged = {**current, **changes}
    sounds = current["event_sounds"]
    if merged["sounds_follow_mascot"] is True and merged["robot_style"] != current["robot_style"]:
        sounds = {event: {**fields, "theme": merged["robot_style"]} for event, fields in sounds.items()}
    if "robot_sounds" in changes:
        sounds = _sound_edits(sounds, {"open": {"enabled": changes["robot_sounds"]}})
    merged["event_sounds"] = _sound_edits(sounds, changes.get("event_sounds", {}))
    return merged


def validate_ui(raw: Any) -> dict[str, Any]:
    """A complete, checked ``ui`` group: missing keys get their defaults, unknown ones are refused."""
    if not isinstance(raw, dict):
        raise UiSettingsError("'ui' must be an object")
    raw = {key: value for key, value in raw.items() if key not in RETIRED_UI_KEYS}
    unknown = sorted(set(raw) - set(UI_DEFAULTS))
    if unknown:
        raise UiSettingsError(f"'ui': unknown setting '{unknown[0]}'")
    ui = {**UI_DEFAULTS, **raw}
    for key, default in UI_DEFAULTS.items():
        value = ui[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise UiSettingsError(f"'ui': '{key}' must be true or false")
        elif isinstance(default, int):
            low, high = UI_RANGES[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise UiSettingsError(f"'ui': '{key}' must be a whole number from {low} to {high}")
    if ui["robot_style"] not in ROBOT_STYLES:
        raise UiSettingsError(f"'ui': 'robot_style' must be one of {', '.join(ROBOT_STYLES)}")
    # Older installations had a greeting switch and a robot, but no per-event preferences.
    sounds = _sound_edits(_default_sounds(ui["robot_style"], ui["robot_sounds"]), raw.get("event_sounds", {}))
    if not isinstance(sounds, dict) or sounds.keys() != set(SOUND_EVENTS):
        raise UiSettingsError("'ui': 'event_sounds' must map known sound events to their settings")
    for event, fields in sounds.items():
        if (not isinstance(fields, dict) or fields.keys() != {"enabled", "theme"}
                or not isinstance(fields["enabled"], bool) or fields["theme"] not in ROBOT_STYLES):
            raise UiSettingsError(f"'ui': sound '{event}' needs an enabled switch and a known robot theme")
    ui["event_sounds"] = sounds
    ui["robot_sounds"] = sounds["open"]["enabled"]
    buttons = ui["start_screen"]
    if (not isinstance(buttons, list) or any(item not in START_BUTTONS for item in buttons)
            or len(set(buttons)) != len(buttons)):
        raise UiSettingsError(f"'ui': 'start_screen' must list some of {', '.join(START_BUTTONS)}, each once")
    imported = ui["imported"]
    if not isinstance(imported, list) or any(item not in COPIES for item in imported):
        raise UiSettingsError(f"'ui': 'imported' may only list {', '.join(COPIES)}")
    try:
        pins, hidden = web_preferences.site_list(ui["web_pins"]), web_preferences.site_list(ui["web_hidden"])
    except ValueError as error:
        raise UiSettingsError(f"'ui': invalid web site preferences: {error}") from error
    if pins.keys() & hidden.keys():
        raise UiSettingsError("'ui': a site cannot be both pinned and hidden")
    return {**ui, "imported": sorted(set(imported)), "start_screen": list(buttons),
            "web_pins": list(pins.values()), "web_hidden": list(hidden.values())}


def robot_theme_icon(style: str) -> str:
    """The base hicolor icon used for one robot's notifications and tray poses."""
    return f"{MASCOT_ICON}-{style}" if style in ROBOT_STYLES and style != "pip" else MASCOT_ICON


def assistant_icon(ui: Any) -> str:
    """The theme icon name for the assistant outside the widget."""
    if isinstance(ui, dict) and ui.get("robot_mascot") is True:
        return robot_theme_icon(ui.get("robot_style", "pip"))
    return WAND_ICON

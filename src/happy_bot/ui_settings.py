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
      "mascot_animations": true,  # animate the greeting and activity poses
      "robot_sounds": false,       # a short chirp when the assistant opens
      "popup_width": 30,          # the popup's size, in grid units: width 20 to 70,
      "popup_height": 26,         #   height 12 to 50
      "floating_opacity": 40,     # how visible the floating Happy Bot is while not in use, 15 to 100 percent
      "search_bookmarks": false,  # search results include browser bookmarks (browsers.py)
      "search_history": false,    # ... and recently visited websites; both read on this computer only
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
installed theme icon (``scripts/install.sh`` and the package put ``contents/images/happy-bot.svg``
there as ``MASCOT_ICON``).

The hotkey belongs to the app too, but it is a desktop shortcut of the app's own copy (set on its
Appearance page), so it is not kept here.
"""

from __future__ import annotations

from typing import Any

UI_DEFAULTS: dict[str, Any] = {
    "robot_mascot": True, "mascot_animations": True, "robot_sounds": False,
    "popup_width": 30, "popup_height": 26, "search_bookmarks": False, "search_history": False,
    "floating_opacity": 40, "floating_x": -1, "floating_y": -1, "imported": [], "start_screen": ["files", "web", "help"],
}
START_BUTTONS = ("files", "web", "help", "system")
UI_RANGES: dict[str, tuple[int, int]] = {
    "popup_width": (20, 70), "popup_height": (12, 50), "floating_opacity": (15, 100),
    "floating_x": (-1, 100_000), "floating_y": (-1, 100_000),
}
WAND_ICON = "tools-wizard"
MASCOT_ICON = "io.github.dragonswithin.happybot"
RETIRED_UI_KEYS = ("instant_search", "instant_min_chars", "instant_delay_ms", "instant_results")
COPIES = ("panel", "app")


class UiSettingsError(ValueError):
    """A ``ui`` value is not acceptable; the message says which and why."""


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
    buttons = ui["start_screen"]
    if (not isinstance(buttons, list) or any(item not in START_BUTTONS for item in buttons)
            or len(set(buttons)) != len(buttons)):
        raise UiSettingsError(f"'ui': 'start_screen' must list some of {', '.join(START_BUTTONS)}, each once")
    imported = ui["imported"]
    if not isinstance(imported, list) or any(item not in COPIES for item in imported):
        raise UiSettingsError(f"'ui': 'imported' may only list {', '.join(COPIES)}")
    return {**ui, "imported": sorted(set(imported)), "start_screen": list(buttons)}


def assistant_icon(ui: Any) -> str:
    """The theme icon name for the assistant outside the widget: the mascot when ``robot_mascot`` is on."""
    return MASCOT_ICON if isinstance(ui, dict) and ui.get("robot_mascot") is True else WAND_ICON

"""The Happy Bot widgets on the user's panels, seen and changed from the app's settings.

Most of Happy Bot's settings live in the daemon (``settings.py``), but how a panel widget looks,
its icon or a search bar (``inputInPanel``) and the bar's width in grid units (``barWidth``, 8 to
60), are that widget's own Plasma settings (its ``General`` group,
``plasmoid/.../contents/config/main.xml``), because only a widget in a panel has them. Happy Bot
has one settings dialog, the app's, so its Appearance page (``ConfigAppearance.qml``, through
``GET``/``POST /panel`` in ``daemon_routes``) reads and changes them here; the widget's own Plasma
settings page only points there.

Both go through the Plasma shell's scripting interface (``evaluateScript`` over DBus, the same
one ``desktop_actions`` uses to find the widget). A written setting reaches the running widget at
once (``reloadConfig``), and ``change`` reads it back so a change that did not take is reported as
a failure. Only widgets in panels count: one on the desktop has no such choice. A
vertical panel always shows the icon, whatever the setting says. Errors are ``PanelWidgetError``
with a message meant for the user; nothing here blocks for more than the DBus call's timeout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .desktop_actions import APPLET_ID

DEFAULT_BAR_WIDTH = 11
BAR_WIDTH_RANGE = (8, 60)  # grid units, as main.xml's barWidth

_READ = ("var out = [];\n"
         "panels().forEach(function (p) { p.widgets().forEach(function (w) {\n"
         "  if (w.type != %(id)s) return;\n"
         "  w.currentConfigGroup = ['General'];\n"
         "  out.push({id: w.id, search_bar: w.readConfig('inputInPanel', false) === true,\n"
         "            bar_width: Number(w.readConfig('barWidth', %(width)d)), vertical: p.formFactor == 'vertical'});\n"
         "}); });\n"
         "print(JSON.stringify(out));")
_WRITE = ("panels().forEach(function (p) { p.widgets().forEach(function (w) {\n"
          "  if (w.type != %(id)s) return;\n"
          "  w.currentConfigGroup = ['General'];\n"
          "  %(writes)s\n"
          "  w.reloadConfig();\n"
          "}); });")


class PanelWidgetError(RuntimeError):
    """The panel widgets could not be read or changed; the message is user-facing."""


def _evaluate(script: str) -> str:
    if not shutil.which("qdbus6"):
        raise PanelWidgetError("qdbus6 is not installed, so the panel cannot be reached")
    try:
        completed = subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
                                    "org.kde.PlasmaShell.evaluateScript", script],
                                   capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as error:
        raise PanelWidgetError("the Plasma shell did not answer") from error
    if completed.returncode != 0:
        raise PanelWidgetError("the Plasma shell did not answer: "
                               + ((completed.stderr or completed.stdout).strip() or "no reason given"))
    return completed.stdout.strip()


def panel_widgets() -> list[dict[str, Any]]:
    """``[{"id", "search_bar", "bar_width", "vertical"}]`` for each Happy Bot widget in a panel."""
    try:
        widgets = json.loads(_evaluate(_READ % {"id": json.dumps(APPLET_ID), "width": DEFAULT_BAR_WIDTH}) or "[]")
    except ValueError as error:
        raise PanelWidgetError("the Plasma shell gave an answer that could not be read") from error
    return [{"id": int(item["id"]), "search_bar": bool(item.get("search_bar")),
             "bar_width": int(item.get("bar_width") or DEFAULT_BAR_WIDTH), "vertical": bool(item.get("vertical"))}
            for item in widgets if isinstance(item, dict)]


def change(search_bar: bool | None = None, bar_width: int | None = None) -> list[dict[str, Any]]:
    """Set a search bar or the icon, and/or the bar's width, in every Happy Bot panel widget.

    Returns the widgets afterwards; raises PanelWidgetError when there is none, a value is out of
    range, or the panel did not take it.
    """
    writes = []
    if search_bar is not None:
        writes.append("w.writeConfig('inputInPanel', %s);" % json.dumps(bool(search_bar)))
    if bar_width is not None:
        if not BAR_WIDTH_RANGE[0] <= bar_width <= BAR_WIDTH_RANGE[1]:
            raise PanelWidgetError("the search bar's width must be %d to %d" % BAR_WIDTH_RANGE)
        writes.append("w.writeConfig('barWidth', %d);" % bar_width)
    if not writes:
        raise PanelWidgetError("nothing to change")
    if not panel_widgets():
        raise PanelWidgetError("Happy Bot is not on a panel")
    _evaluate(_WRITE % {"id": json.dumps(APPLET_ID), "writes": " ".join(writes)})
    widgets = panel_widgets()
    if any((search_bar is not None and widget["search_bar"] != bool(search_bar))
           or (bar_width is not None and widget["bar_width"] != bar_width) for widget in widgets):
        raise PanelWidgetError("the panel did not take the change")
    return widgets

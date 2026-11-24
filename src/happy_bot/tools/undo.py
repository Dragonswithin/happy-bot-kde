"""Undo and activity tools: reverse the assistant's last changes, and say what it did.

``undo_change`` reverses one entry of ``undo_journal`` (the newest one not
yet undone, or the one whose id is given) and marks it undone. Each kind of
entry has its own reversal in ``_REVERSALS``:

- ``moved``: move it back, unless something now occupies the old place;
- ``copied`` / ``file_created``: move the created file to the trash;
- ``file_replaced``: put back the contents saved before the replacement;
- ``file_appended``: cut the file back to its previous length;
- ``folder_created``: remove the created folders if they are still empty;
- ``trashed``: restore it from the trash (``gio trash --restore``);
- ``volume``, ``color_scheme``, ``kde_setting``, ``clipboard``,
  ``default_device`` (sound output or input), ``brightness``,
  ``power_profile``, ``night_light``, ``wallpaper``, ``theme`` (cursor or
  Plasma theme): set the previous value again (an unset KDE setting is
  deleted);
- ``window``: put the window back where it was and as it was.

Risk: undoing is ``danger`` when the reversal removes or replaces data (a
created file goes to the trash, replaced or appended contents are put back),
and ``change`` otherwise. Reversals do not themselves add journal entries,
so undoing twice steps further back instead of redoing.

``recent_activity`` reads the action log the permission gate writes
(``actions.jsonl``, see ``permissions``) and lists what the assistant ran or
was refused, newest first, with which changes can still be undone. It is how
"what did you do today?" is answered from the record rather than from the
model's memory. ``tool_usage`` totals the same log per tool.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from .. import undo_journal
from ..desktop_context import run_command
from ..runtime_paths import runtime_root
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

DESTRUCTIVE_KINDS = ("copied", "file_created", "file_replaced", "file_appended")
MAX_ACTIVITY = 50


def _run(command: list[str], timeout: float = 30.0) -> str:
    if not shutil.which(command[0]):
        raise ToolFailure(f"the '{command[0]}' command is not installed")
    result = run_command(command, timeout=timeout)
    if not result["ok"]:
        raise ToolFailure((result["stderr"] or result["stdout"]).strip() or f"{command[0]} failed")
    return result["stdout"]


def _trash(path: str) -> str:
    if not os.path.lexists(path):
        raise ToolFailure(f"{path} no longer exists, so there is nothing to remove")
    _run(["gio", "trash", "--", path])
    return f"Moved {path} to the trash."


def _undo_moved(data: dict[str, Any]) -> str:
    source, landing = data["source"], data["landing"]
    if not os.path.lexists(landing):
        raise ToolFailure(f"{landing} is no longer there, so it cannot be moved back")
    if os.path.lexists(source):
        raise ToolFailure(f"something is now at {source}, so {landing} was not moved back")
    Path(source).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(landing, source)
    lost = " The file it had replaced was not kept and cannot be brought back." if data.get("replaced") else ""
    return f"Moved {landing} back to {source}.{lost}"


def _undo_replaced(data: dict[str, Any]) -> str:
    backup = data.get("backup") or ""
    if not backup or not os.path.isfile(backup):
        raise ToolFailure(f"the previous contents of {data['path']} were not kept (the file was too large)")
    shutil.copy2(backup, data["path"])
    return f"Put back the previous contents of {data['path']}."


def _undo_appended(data: dict[str, Any]) -> str:
    path = data["path"]
    if not os.path.isfile(path):
        raise ToolFailure(f"{path} no longer exists")
    if os.path.getsize(path) < data["size"]:
        raise ToolFailure(f"{path} is shorter than before the addition, so it was changed since; left as it is")
    os.truncate(path, data["size"])
    return f"Removed what was added to {path}."


def _undo_folder(data: dict[str, Any]) -> str:
    path, topmost = Path(data["path"]), Path(data["topmost"])
    if not path.is_dir():
        raise ToolFailure(f"{path} no longer exists")
    current = path
    while True:
        if any(current.iterdir()):
            raise ToolFailure(f"{current} is not empty, so it was left in place")
        current.rmdir()
        if current == topmost or current.parent == current:
            break
        current = current.parent
    return f"Removed the folder {topmost}."


def _undo_trashed(data: dict[str, Any]) -> str:
    path = data["path"]
    if os.path.lexists(path):
        raise ToolFailure(f"something is already at {path}, so the trashed item was not restored")
    matches = []
    for line in _run(["gio", "trash", "--list"]).splitlines():
        uri, _, original = line.partition("\t")
        if original == path:
            matches.append(uri)
    if not matches:
        raise ToolFailure(f"{path} is no longer in the trash")
    _run(["gio", "trash", "--restore", matches[-1]])
    return f"Restored {path} from the trash."


def _undo_volume(data: dict[str, Any]) -> str:
    _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{data['percent'] / 100:.2f}"])
    _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if data["mute"] else "0"])
    return f"Volume set back to {data['percent']}%" + (" (muted)." if data["mute"] else ".")


def _undo_scheme(data: dict[str, Any]) -> str:
    _run(["plasma-apply-colorscheme", data["scheme"]])
    return f"Colour scheme set back to {data['scheme']}."


def _undo_setting(data: dict[str, Any]) -> str:
    base = ["kwriteconfig6", "--file", data["file"], "--group", data["group"], "--key", data["key"]]
    if data.get("previous") is None:
        _run(base + ["--delete"])
        return f"Removed [{data['group']}] {data['key']} from {data['file']} again."
    _run(base + [data["previous"]])
    return f"Set [{data['group']}] {data['key']} back to {data['previous']}."


def _undo_clipboard(data: dict[str, Any]) -> str:
    _run(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", data["text"]])
    return "Put the previous clipboard contents back."


def _undo_default_device(data: dict[str, Any]) -> str:
    _run(["pactl", f"set-default-{data['kind']}", data["name"]])
    return f"The default sound {'output' if data['kind'] == 'sink' else 'input'} is {data['name']} again."


def _undo_brightness(data: dict[str, Any]) -> str:
    from .power import set_brightness

    set_brightness({"percent": data["percent"]})
    return f"Screen brightness set back to {data['percent']}%."


def _undo_power_profile(data: dict[str, Any]) -> str:
    _run(["powerprofilesctl", "set", data["profile"]])
    return f"Power profile set back to {data['profile']}."


def _undo_night_light(data: dict[str, Any]) -> str:
    from .power import apply_night_light

    apply_night_light(data["enabled"])
    return f"Night light is {'on' if data['enabled'] else 'off'} again."


def _undo_wallpaper(data: dict[str, Any]) -> str:
    _run(["plasma-apply-wallpaperimage", data["image"]])
    return "Put the previous wallpaper back."


def _undo_theme(data: dict[str, Any]) -> str:
    command = {"cursor": "plasma-apply-cursortheme", "plasma": "plasma-apply-desktoptheme"}[data["kind"]]
    _run([command, data["name"]])
    return f"The {data['kind']} theme is {data['name']} again."


def _undo_window(data: dict[str, Any]) -> str:
    from . import windows

    script = ("w.minimized = false; w.fullScreen = false; w.setMaximize(false, false);"
              "w.frameGeometry = {x: args.x, y: args.y, width: args.width, height: args.height};"
              "w.fullScreen = args.fullscreen; w.minimized = args.minimized; return { window: describe(w) };")
    result = windows._run({"window": data["window"], **{name: data[name] for name in
                           ("x", "y", "width", "height", "minimized", "fullscreen")}}, script)
    return "Put the window back: " + windows._describe(result["window"])


_REVERSALS: dict[str, Callable[[dict[str, Any]], str]] = {
    "moved": _undo_moved,
    "copied": lambda data: _trash(data["copy"]),
    "file_created": lambda data: _trash(data["path"]),
    "file_replaced": _undo_replaced,
    "file_appended": _undo_appended,
    "folder_created": _undo_folder,
    "trashed": _undo_trashed,
    "volume": _undo_volume,
    "color_scheme": _undo_scheme,
    "kde_setting": _undo_setting,
    "clipboard": _undo_clipboard,
    "window": _undo_window,
    "default_device": _undo_default_device,
    "brightness": _undo_brightness,
    "power_profile": _undo_power_profile,
    "night_light": _undo_night_light,
    "wallpaper": _undo_wallpaper,
    "theme": _undo_theme,
}


def _target(arguments: dict[str, Any]) -> dict[str, Any]:
    pending = undo_journal.pending()
    wanted = arguments.get("id")
    if wanted:
        for entry in pending:
            if entry["id"] == wanted:
                return entry
        raise ToolFailure(f"there is no change with id {wanted} left to undo. Use recent_activity to see them.")
    if not pending:
        raise ToolFailure("there is nothing left to undo: no reversible change was made since you logged in")
    return pending[0]


def classify_undo(arguments: dict[str, Any]) -> tuple[str, str]:
    try:
        entry = _target(arguments)
    except ToolFailure:
        return RISK_CHANGE, ""
    if entry["kind"] in DESTRUCTIVE_KINDS:
        return RISK_DANGER, f"undoing \"{entry['summary']}\" removes or replaces data"
    return RISK_CHANGE, ""


def summarize_undo(arguments: dict[str, Any]) -> str:
    try:
        return f"Undo: {_target(arguments)['summary']}"
    except ToolFailure:
        return "Undo the last change"


def undo_change(arguments: dict[str, Any]) -> str:
    entry = _target(arguments)
    reverse = _REVERSALS.get(entry["kind"])
    if reverse is None:
        raise ToolFailure(f"changes of kind {entry['kind']} cannot be undone")
    try:
        result = reverse(entry["data"])
    except OSError as error:
        raise ToolFailure(f"could not undo \"{entry['summary']}\": {error.strerror or error}") from error
    undo_journal.mark_undone(entry["id"])
    return result


def _action_log(runtime_dir: Path | None = None) -> list[dict[str, Any]]:
    path = (runtime_dir or runtime_root()) / "actions.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def recent_activity(arguments: dict[str, Any]) -> str:
    limit = arguments.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ACTIVITY:
        raise ToolFailure(f"'limit' must be a whole number from 1 to {MAX_ACTIVITY}")
    since = str(arguments.get("since") or "")
    actions = [record for record in reversed(_action_log()) if str(record.get("time", "")) >= since][:limit]
    lines = ["Actions (newest first; from the assistant's action log since login):"]
    lines += [f"- {record.get('time', '?')}  {record.get('tool', '?')}  [{record.get('outcome', '?')}]  "
              f"{str(record.get('arguments', ''))[:200]}" for record in actions] or ["- none recorded"]
    undoable = undo_journal.pending()[:limit]
    lines.append("Changes that can be undone (newest first; pass the id to undo_change):")
    lines += [f"- {entry['id']}  {entry['time']}  {entry['summary']}" for entry in undoable] or ["- none"]
    return "\n".join(lines)


def tool_usage(arguments: dict[str, Any]) -> str:
    """How often each changing tool ran, failed or was declined since login, from the action log."""
    counts: dict[str, dict[str, int]] = {}
    for record in _action_log():
        outcome = str(record.get("outcome", "?"))
        bucket = "declined" if outcome in ("deny", "timeout", "cancelled") or outcome.startswith("refused") else "ran"
        counts.setdefault(str(record.get("tool", "?")), {"ran": 0, "declined": 0})[bucket] += 1
    if not counts:
        return "No changes have been made since login."
    ordered = sorted(counts.items(), key=lambda item: -(item[1]["ran"] + item[1]["declined"]))
    return "\n".join(f"{name}: ran {value['ran']}, declined {value['declined']}" for name, value in ordered[:40])


def undo_tools() -> list[Tool]:
    return [
        Tool("undo_change", "Undo a change the assistant made: by default the most recent one not yet undone, or "
             "the one with the given id from recent_activity. Works for moving, copying, creating, replacing and "
             "appending to files, new folders, trashing, volume, colour scheme, KDE settings, the clipboard and "
             "window placement. Call it once per change to step further back.",
             object_schema({"id": {"type": "string", "description": "Optional id from recent_activity"}}),
             RISK_CHANGE, undo_change, classify=classify_undo, summarize=summarize_undo),
        Tool("tool_usage", "How often each kind of change was made or declined since login, most used first.",
             object_schema(), RISK_READ, tool_usage, summarize=lambda arguments: "Count the assistant's actions"),
        Tool("recent_activity", "What the assistant actually did since the user logged in, from its action log "
             "(including actions the user declined), and which changes can still be undone. Use it to answer "
             "'what did you do?' instead of relying on memory.",
             object_schema({"limit": {"type": "integer", "description": f"Default 20, max {MAX_ACTIVITY}"},
                            "since": {"type": "string", "description": "Only actions at or after this ISO time, "
                                      "for example 2026-11-23T00:00"}}),
             RISK_READ, recent_activity, summarize=lambda arguments: "Check what the assistant has done"),
    ]

"""Media and audio tools: what is playing, seeking, audio devices, per-app volume, the microphone.

Playback state comes from MPRIS, the DBus interface every Linux media player
(and KDE Connect, for the phone's player) publishes, read through
``session_dbus``. Play, pause and skip stay in ``tools/system.py``
(``media_control``); this module adds what needs the player's state.

Audio devices and application streams come from ``pactl``'s JSON output
(``pactl --format=json``, served by PipeWire's PulseAudio layer), and the
microphone is muted with ``wpctl`` like the output volume is.

``download_media`` saves a video, or only its sound, from a web address into
Downloads with the user's own ``yt-dlp`` (when installed), reporting its
progress lines and recording each saved file for undo.

Music in the user's Music folder is found by file and folder names: playing
writes a temporary ``.m3u`` and opens it with the default player; a saved
playlist goes to ``Music/Playlists`` (recorded for undo).

Risk: listing is ``read``; playing music, saving a playlist, choosing the default output or input, an
application's volume, seeking and muting the microphone are ``change``.
Choosing a default device records the previous one in ``undo_journal``
(kind ``default_device``) so it can be undone.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import session_dbus, undo_journal
from ..desktop_context import run_command
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"


def _player_label(name: str) -> str:
    return name.removeprefix(MPRIS_PREFIX)


def _players() -> list[str]:
    try:
        return session_dbus.names(MPRIS_PREFIX)
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(str(error)) from error


def _choose_player(arguments: dict[str, Any]) -> str:
    players = _players()
    if not players:
        raise ToolFailure("no media player is running")
    wanted = str(arguments.get("player") or "").lower()
    chosen = [name for name in players if wanted in name.lower()] if wanted else players
    if not chosen:
        raise ToolFailure(f"no running player matches '{wanted}'. Running: {', '.join(map(_player_label, players))}")
    return chosen[0]


def _clock(microseconds: Any) -> str:
    if not isinstance(microseconds, (int, float)) or microseconds < 0:
        return "?"
    seconds = int(microseconds // 1_000_000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def describe_player(name: str, state: dict[str, Any]) -> str:
    """One line for a player: status, title, artist, album and position."""
    metadata = state.get("Metadata") or {}
    artists = metadata.get("xesam:artist") or []
    parts = [f"{_player_label(name)}: {state.get('PlaybackStatus', 'unknown')}"]
    if metadata.get("xesam:title"):
        parts.append(f"\"{metadata['xesam:title']}\"")
    if artists:
        parts.append("by " + ", ".join(artists if isinstance(artists, list) else [str(artists)]))
    if metadata.get("xesam:album"):
        parts.append(f"from {metadata['xesam:album']}")
    if metadata.get("mpris:length"):
        parts.append(f"at {_clock(state.get('Position'))} of {_clock(metadata['mpris:length'])}")
    return " ".join(parts)


def now_playing(arguments: dict[str, Any]) -> str:
    players = _players()
    if not players:
        return "No media player is running."
    lines = []
    for name in players:
        try:
            lines.append(describe_player(name, session_dbus.properties(name, MPRIS_PATH, PLAYER_INTERFACE)))
        except session_dbus.DBusError as error:
            lines.append(f"{_player_label(name)}: not answering ({error})")
    return "\n".join(lines)


def seek_media(arguments: dict[str, Any]) -> str:
    target = arguments.get("position_seconds")
    if isinstance(target, bool) or not isinstance(target, (int, float)) or target < 0:
        raise ToolFailure("'position_seconds' must be a number of seconds from the start, 0 or more")
    player = _choose_player(arguments)
    try:
        state = session_dbus.properties(player, MPRIS_PATH, PLAYER_INTERFACE)
        offset = int(target * 1_000_000) - int(state.get("Position") or 0)
        session_dbus.call(player, MPRIS_PATH, PLAYER_INTERFACE, "Seek", "x", (offset,))
    except session_dbus.DBusError as error:
        raise ToolFailure(f"the player refused to seek: {error}") from error
    return f"Moved {_player_label(player)} to {_clock(target * 1_000_000)}."


def _pactl_json(kind: str) -> list[dict[str, Any]]:
    if not shutil.which("pactl"):
        raise ToolFailure("the 'pactl' command is not installed")
    result = run_command(["pactl", "--format=json", "list", kind], timeout=10)
    if not result["ok"]:
        raise ToolFailure(result["stderr"].strip() or "pactl failed")
    try:
        return json.loads(result["stdout"] or "[]")
    except ValueError as error:
        raise ToolFailure("pactl did not return JSON; it may be too old") from error


def _default(kind: str) -> str:
    result = run_command(["pactl", f"get-default-{kind}"], timeout=5)
    return result["stdout"].strip() if result["ok"] else ""


def _percent(entry: dict[str, Any]) -> str:
    channels = list((entry.get("volume") or {}).values())
    return channels[0].get("value_percent", "?") if channels else "?"


def list_audio_devices(arguments: dict[str, Any]) -> str:
    lines = []
    for kind, title in (("sink", "Outputs"), ("source", "Inputs")):
        default = _default(kind)
        lines.append(f"{title} (* is the default):")
        for device in _pactl_json(kind + "s"):
            if kind == "source" and device["name"].endswith(".monitor"):
                continue  # a monitor of an output, not a microphone
            mark = "*" if device["name"] == default else " "
            lines.append(f" {mark} {device.get('description') or device['name']}  [{device['name']}]  "
                         f"{_percent(device)}{', muted' if device.get('mute') else ''}")
    streams = _pactl_json("sink-inputs")
    lines.append("Applications playing sound:")
    lines += [f"  {stream.get('properties', {}).get('application.name', '?')}  (stream {stream['index']})  "
              f"{_percent(stream)}{', muted' if stream.get('mute') else ''}" for stream in streams] or ["  none"]
    return "\n".join(lines)


def _match_device(kind: str, wanted: str) -> dict[str, Any]:
    devices = _pactl_json(kind + "s")
    if kind == "source":
        devices = [device for device in devices if not device["name"].endswith(".monitor")]
    lowered = wanted.lower()
    exact = [device for device in devices if device["name"] == wanted]
    found = exact or [device for device in devices
                      if lowered in device["name"].lower() or lowered in str(device.get("description", "")).lower()]
    if len(found) != 1:
        listing = "; ".join(f"{device.get('description')} [{device['name']}]" for device in devices)
        problem = "no device matches" if not found else f"{len(found)} devices match"
        raise ToolFailure(f"{problem} '{wanted}'. Devices: {listing}")
    return found[0]


def set_default_device(arguments: dict[str, Any]) -> str:
    kind = arguments.get("kind")
    if kind not in ("output", "input"):
        raise ToolFailure("'kind' must be 'output' or 'input'")
    wanted = str(arguments.get("device") or "").strip()
    if not wanted:
        raise ToolFailure("'device' is required: part of the device's name from list_audio_devices")
    pa_kind = "sink" if kind == "output" else "source"
    device = _match_device(pa_kind, wanted)
    previous = _default(pa_kind)
    result = run_command(["pactl", f"set-default-{pa_kind}", device["name"]], timeout=5)
    if not result["ok"]:
        raise ToolFailure(result["stderr"].strip() or "pactl failed")
    if previous and previous != device["name"]:
        undo_journal.record("default_device", f"Changed the default {kind} from {previous}",
                            {"kind": pa_kind, "name": previous})
    return f"The default {kind} is now {device.get('description') or device['name']}."


def set_app_volume(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("application") or "").strip().lower()
    percent = arguments.get("percent")
    mute = arguments.get("mute")
    if not wanted:
        raise ToolFailure("'application' is required")
    if percent is None and mute is None:
        raise ToolFailure("give 'percent' (0 to 150), 'mute', or both")
    if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 150):
        raise ToolFailure("'percent' must be a number from 0 to 150")
    streams = [stream for stream in _pactl_json("sink-inputs")
               if wanted in str(stream.get("properties", {}).get("application.name", "")).lower()
               or wanted in str(stream.get("properties", {}).get("application.process.binary", "")).lower()]
    if not streams:
        raise ToolFailure(f"no application named '{wanted}' is playing sound right now")
    for stream in streams:
        commands = []
        if percent is not None:
            commands.append(["pactl", "set-sink-input-volume", str(stream["index"]), f"{int(percent)}%"])
        if mute is not None:
            commands.append(["pactl", "set-sink-input-mute", str(stream["index"]), "1" if mute else "0"])
        for command in commands:
            result = run_command(command, timeout=5)
            if not result["ok"]:
                raise ToolFailure(result["stderr"].strip() or "pactl failed")
    name = streams[0].get("properties", {}).get("application.name", wanted)
    return f"Set {name}" + (f" to {int(percent)}%" if percent is not None else "") + \
        ("" if mute is None else (", muted" if mute else ", unmuted")) + "."


def set_microphone_mute(arguments: dict[str, Any]) -> str:
    mute = arguments.get("mute")
    if mute not in (True, False, "toggle"):
        raise ToolFailure("'mute' must be true, false or \"toggle\"")
    if not shutil.which("wpctl"):
        raise ToolFailure("the 'wpctl' command is not installed")
    value = "toggle" if mute == "toggle" else ("1" if mute else "0")
    result = run_command(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", value], timeout=5)
    if not result["ok"]:
        raise ToolFailure(result["stderr"].strip() or "wpctl failed")
    state = run_command(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], timeout=5)["stdout"]
    return "The microphone is now " + ("muted." if "MUTED" in state else "on.")


AUDIO_SUFFIXES = (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma")
MAX_TRACKS = 500


def _music_matches(words: list[str], folder: Path) -> list[Path]:
    found = []
    for root, directories, files in os.walk(folder):
        directories[:] = [name for name in directories if not name.startswith(".")]
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() in AUDIO_SUFFIXES and all(word in str(path.relative_to(folder)).lower() for word in words):
                found.append(path)
                if len(found) >= MAX_TRACKS:
                    return sorted(found)
    return sorted(found)


def _music_folder() -> Path:
    from ..agent_loop import user_folders

    return Path(user_folders().get("Music", str(Path.home() / "Music")))


def play_music(arguments: dict[str, Any]) -> str:
    words = str(arguments.get("query") or "").lower().split()
    if not words:
        raise ToolFailure("'query' is required: an artist, album, song or folder name")
    folder = _music_folder()
    tracks = _music_matches(words, folder)
    if not tracks:
        return f"Nothing in {folder} matches '{' '.join(words)}'. A music service can be connected as a tool."
    playlist = _write_playlist(tracks, "assistant-now-playing", Path(tempfile.gettempdir()))
    from ..desktop_actions import open_location

    open_location(str(playlist))
    return f"Playing {len(tracks)} track(s) matching '{' '.join(words)}', starting with {tracks[0].name}."


def _write_playlist(tracks: list[Path], name: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{re.sub(r'[^A-Za-z0-9 _-]', '', name).strip() or 'playlist'}.m3u"
    path.write_text("#EXTM3U\n" + "".join(f"{track}\n" for track in tracks), encoding="utf-8")
    return path


def make_playlist(arguments: dict[str, Any]) -> str:
    name = str(arguments.get("name") or "").strip()
    queries = [str(query).lower().split() for query in arguments.get("include") or [] if str(query).strip()]
    if not name or not queries:
        raise ToolFailure("give a 'name' and 'include': a list of artists, albums, songs or folders")
    folder = _music_folder()
    tracks: list[Path] = []
    for words in queries:
        tracks += [track for track in _music_matches(words, folder) if track not in tracks]
    if not tracks:
        raise ToolFailure(f"nothing in {folder} matches; check the names with list_directory")
    target = folder / "Playlists"
    path = _write_playlist(tracks, name, target)
    from .. import undo_journal

    undo_journal.record("file_created", f"Created {path}", {"path": str(path)})
    return f"Saved the playlist {path} with {len(tracks)} tracks."


def download_media(arguments: dict[str, Any]) -> str:
    """Download a video or its sound from a web address with the user's yt-dlp, into Downloads."""
    from .. import undo_journal
    from ..agent_loop import user_folders
    from .registry import cancel_requested, report_progress

    url = str(arguments.get("url") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        raise ToolFailure("'url' must be an http(s) web address")
    program = shutil.which("yt-dlp")
    if not program:
        raise ToolFailure("yt-dlp is not installed, so media cannot be downloaded")
    folder = Path(user_folders().get("Downloads", str(Path.home() / "Downloads")))
    command = [program, "--no-playlist", "--newline", "--restrict-filenames", "-P", str(folder),
               "--print", "after_move:filepath", "-o", "%(title)s.%(ext)s"]
    if arguments.get("audio_only"):
        command += ["-x", "--audio-format", "mp3"]
    process = subprocess.Popen([*command, "--", url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    saved, tail = [], []
    for line in process.stdout:
        line = line.strip()
        if line.startswith(str(folder)) and os.path.exists(line):
            saved.append(line)
        elif line:
            tail = (tail + [line])[-5:]
            report_progress(line)
        if cancel_requested():
            process.kill()
            raise ToolFailure("stopped at the user's request")
    process.wait()
    if process.returncode != 0 or not saved:
        raise ToolFailure("the download failed: " + " | ".join(tail)[-500:])
    for path in saved:
        undo_journal.record("file_created", f"Downloaded {path}", {"path": path})
    return "Saved " + ", ".join(saved) + "."


def media_tools() -> list[Tool]:
    player = {"type": "string", "description": "Part of the player's name; default is the first running player"}
    return [
        Tool("play_music", "Play music from the user's Music folder matching an artist, album, song or folder "
             "name, in their default player.", object_schema({"query": {"type": "string"}}, ["query"]),
             RISK_CHANGE, play_music, summarize=lambda a: f"Play {a.get('query', '?')}"),
        Tool("make_playlist", "Save a playlist (.m3u in Music/Playlists) of the tracks matching several artists, "
             "albums, songs or folders.", object_schema({"name": {"type": "string"},
                                                          "include": {"type": "array", "items": {"type": "string"}}},
                                                         ["name", "include"]),
             RISK_CHANGE, make_playlist, summarize=lambda a: f"Make the playlist {a.get('name', '?')}"),
        Tool("download_media", "Download a video, or only its sound as MP3, from a web address into Downloads "
             "(with the user's yt-dlp).", object_schema({"url": {"type": "string"}, "audio_only": {"type": "boolean"}},
                                                       ["url"]),
             RISK_CHANGE, download_media, summarize=lambda a: f"Download {a.get('url', '?')}"),
        Tool("now_playing", "What each media player (including a connected phone) is playing: status, title, "
             "artist, album and position.", object_schema(), RISK_READ, now_playing,
             summarize=lambda a: "Check what is playing"),
        Tool("seek_media", "Jump to a position in the playing track.",
             object_schema({"position_seconds": {"type": "number"}, "player": player}, ["position_seconds"]),
             RISK_CHANGE, seek_media, summarize=lambda a: f"Jump to {a.get('position_seconds', '?')} s"),
        Tool("list_audio_devices", "Sound outputs and inputs (which is the default) and the applications playing "
             "sound with their volume.", object_schema(), RISK_READ, list_audio_devices,
             summarize=lambda a: "List sound devices"),
        Tool("set_default_audio_device", "Choose the default sound output (speakers, headphones, HDMI) or input "
             "(microphone).", object_schema({"kind": {"type": "string", "enum": ["output", "input"]},
                                             "device": {"type": "string", "description": "Part of its name"}},
                                            ["kind", "device"]),
             RISK_CHANGE, set_default_device, summarize=lambda a: f"Use {a.get('device', '?')} for sound {a.get('kind', '')}"),
        Tool("set_app_volume", "Set one application's volume or mute it, without changing the others.",
             object_schema({"application": {"type": "string"}, "percent": {"type": "number"},
                            "mute": {"type": "boolean"}}, ["application"]),
             RISK_CHANGE, set_app_volume, summarize=lambda a: f"Change the volume of {a.get('application', '?')}"),
        Tool("set_microphone_mute", "Mute or unmute the microphone.",
             object_schema({"mute": {"description": "true, false or \"toggle\""}}, ["mute"]),
             RISK_CHANGE, set_microphone_mute, summarize=lambda a: "Mute the microphone" if a.get("mute") is True
             else "Unmute the microphone" if a.get("mute") is False else "Toggle the microphone"),
    ]

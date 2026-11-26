"""Play the installed mascot cues on the logged-in user's audio output."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

from .ui_settings import MASCOT_ICON, SOUND_THEMES, SOUND_EVENTS

# The recorder holds this through capture so an overlapping cue cannot be
# transcribed as speech. Its own ready cue plays under the same lock.
audio_lock = threading.RLock()


def _asset(theme: str, event: str) -> Path | None:
    if theme not in SOUND_THEMES or event not in SOUND_EVENTS:
        return None
    # Running directly from the checkout, a local applet install, or a distribution package.
    packages = [Path(__file__).resolve().parents[2] / "plasmoid"]
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(os.pathsep)
    packages.extend(root / "plasma/plasmoids" for root in [data_home, *map(Path, data_dirs)] if root.is_absolute())
    for package in packages:
        path = package / MASCOT_ICON / "contents/sounds" / theme / f"{event}.wav"
        if path.is_file():
            return path
    return None


def preview(theme: str, event: str) -> bool:
    """Play one cue to completion. A preview works even when the event is muted."""
    path = _asset(theme, event)
    if path is None:
        return False
    with audio_lock:
        return _play_file(path)


def _play_file(path: Path) -> bool:
    for name in ("pw-play", "paplay", "aplay"):
        player = shutil.which(name)
        if player:
            try:
                result = subprocess.run([player, str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=4, check=False)
            except subprocess.TimeoutExpired:
                return False
            except OSError:
                continue
            if result.returncode == 0:
                return True
    return False


def play(ui: dict, event: str, *, wait: bool = False) -> bool:
    """Play the user's choice. Scheduled jobs and the mic-ready cue wait for playback."""
    choice = ui.get("event_sounds", {}).get(event, {})
    if not choice.get("enabled") or choice.get("theme") not in SOUND_THEMES:
        return False
    theme = choice["theme"]
    if wait:
        return preview(theme, event)
    threading.Thread(target=preview, args=(theme, event), name="happy-bot-sound", daemon=True).start()
    return True

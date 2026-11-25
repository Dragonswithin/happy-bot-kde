"""The desktop side of "Fix selected text": noting the selection, and putting new text in its place.

Noting: when the "Fix selected text" shortcut is pressed (``happy-bot app fix``, which reaches the
daemon as ``POST /app/show`` with ``fix``), ``SelectionNote.capture`` reads the selected text (the
Wayland primary selection, ``tools.screen.selected_text``) and the window the user is in
(``desktop_context.current_application``) at once, before the Happy Bot app opens, which may
take a few seconds when it has to start. The app then asks for that note (``GET /selection``),
shows the text with its rewrite buttons, and the model side (``text_rewrite``) does the rest.
The note lives in the daemon's memory only, one at a time, and is replaced by the next capture.

Putting back: "Replace" sends the new text with the noted window's KWin id, and ``replace``
pastes it over the selection, the way a person would:

1. the new text goes on the clipboard (``wl-copy``), after the clipboard's current text is kept;
2. that window is brought forward (``tools.windows.focus_window``), where the selection still is;
3. Ctrl+V is pressed through the desktop's RemoteDesktop portal (``input_portal``), so the
   application replaces the selected text with the pasted one, as typing over a selection does;
4. after ``RESTORE_AFTER_SECONDS`` the clipboard gets its earlier text back, so the user's own
   clipboard is not lost (a clipboard that held no text keeps the new text).

Pasting is used rather than typing character by character because it is one step, keeps line
breaks and any character, and is undone with the application's own Undo. Terminals are refused
(``tools.gui.is_terminal``): Ctrl+V there does not paste, and text arriving in a terminal can run
as a command. The portal needs the user's one-time permission ("Allow typing" on the Behaviour
page); without it ``ReplaceError`` says so and nothing changes but the clipboard, which then
holds the new text to paste by hand. ``replace`` blocks for about a second.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time

from typing import Any

from . import desktop_context, input_portal
from .tools import gui, screen, windows
from .tools.registry import ToolFailure

FOCUS_SETTLE_SECONDS = 0.3
RESTORE_AFTER_SECONDS = 1.0
MAX_TEXT_CHARS = 20000


NOTHING_SELECTED = "No text is selected right now."  # what tools.screen.selected_text says then


class SelectionNote:
    """The selection noted when the shortcut was pressed: ``{"text", "window", "app", "title", "terminal"}``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._note: dict[str, Any] | None = None

    def capture(self) -> dict[str, Any]:
        """Read the selection and the window the user is in now, keep it, and return it."""
        try:
            text = screen.selected_text({})
        except ToolFailure:
            text = ""
        found = desktop_context.current_application()
        note = {"text": "" if text == NOTHING_SELECTED else text, "window": found["window"], "app": found["app"],
                "title": found["title"], "terminal": gui.is_terminal({"app": found["class"]})}
        with self._lock:
            self._note = note
        return note

    def current(self) -> dict[str, Any]:
        """The kept note, or a fresh capture when there is none."""
        with self._lock:
            note = self._note
        return note if note is not None else self.capture()


class ReplaceError(RuntimeError):
    """The text was not put back; the message says why and what to do."""


def _clipboard_text() -> str | None:
    if not shutil.which("wl-paste"):
        return None
    try:
        done = subprocess.run(["wl-paste", "--no-newline", "--type", "text/plain"], capture_output=True,
                              timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None


def _set_clipboard(text: str) -> None:
    if not shutil.which("wl-copy"):
        raise ReplaceError("wl-copy (from wl-clipboard) is needed to put the text back")
    try:
        subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=text.encode("utf-8"),
                       timeout=5, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise ReplaceError(f"the clipboard could not be set ({error})") from error


def replace(window_id: str, text: str) -> str:
    """Paste ``text`` over the selection in window ``window_id``; returns what was done or raises ``ReplaceError``."""
    if not text:
        raise ReplaceError("there is no text to put back")
    if len(text) > MAX_TEXT_CHARS:
        raise ReplaceError("that is too much text to put back; copy it instead")
    if not window_id:
        raise ReplaceError("Happy Bot does not know which window the text came from; copy it instead")
    try:
        window = windows.describe_window(window_id)
    except ToolFailure as error:
        raise ReplaceError("the window the text came from is closed; copy it instead") from error
    if gui.is_terminal(window):
        raise ReplaceError("Happy Bot does not paste into terminals, where text can run as a command; copy it instead")
    previous = _clipboard_text()
    _set_clipboard(text)
    try:
        windows.focus_window({"window": window_id})
        time.sleep(FOCUS_SETTLE_SECONDS)
        input_portal.shared().press_keys("ctrl+v")
    except ToolFailure as error:
        raise ReplaceError(f"the window could not be brought forward ({error}); the text is on the clipboard") from error
    except input_portal.InputUnavailable as error:
        raise ReplaceError("Happy Bot may not type into other apps yet: press \"Allow typing…\" on the Behaviour page. "
                           f"The text is on the clipboard to paste by hand. ({error})") from error
    if previous:
        threading.Timer(RESTORE_AFTER_SECONDS, lambda: _restore(previous)).start()
    return f"Replaced the selected text in \"{window.get('title', '')}\"."


def _restore(previous: str) -> None:
    try:
        _set_clipboard(previous)
    except ReplaceError:
        pass

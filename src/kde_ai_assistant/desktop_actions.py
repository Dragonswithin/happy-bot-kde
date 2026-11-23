"""Actions the daemon performs on the desktop for the user.

Counterpart of ``desktop_context`` (which only reads). Each function here
changes something the user can see, runs as the user, and reports failure by
raising ``DesktopActionError`` with a message meant for the user.

``open_location`` hands a file, folder or web link to the desktop's default
handler through ``xdg-open``. The child is detached into its own session so
the opened application outlives the request and the daemon; its output is
discarded. Only absolute paths and http(s) URLs are accepted, so a caller
cannot smuggle options or other URL schemes to the handler.
"""

from __future__ import annotations

import os
import shutil
import subprocess


class DesktopActionError(RuntimeError):
    """The action could not be carried out; the message is user-facing."""


def open_location(location: str) -> None:
    """Open an absolute path or http(s) URL with the default application."""
    target = location.strip()
    is_link = target.startswith(("http://", "https://"))
    if not is_link:
        if not target.startswith("/"):
            raise DesktopActionError("only files, folders and web links can be opened")
        if not os.path.exists(target):
            raise DesktopActionError(f"{target} no longer exists")
    opener = shutil.which("xdg-open")
    if not opener:
        raise DesktopActionError("xdg-open is not installed")
    try:
        subprocess.Popen(
            [opener, target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise DesktopActionError(f"could not open {target}: {exc}") from exc

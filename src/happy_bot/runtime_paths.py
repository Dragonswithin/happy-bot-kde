"""Locations and private-file handling shared by the daemon and its clients.

Everything transient the assistant writes lives in one per-user runtime
directory: ``$XDG_RUNTIME_DIR/happy-bot``, or a uid-suffixed directory
under ``/tmp`` when no runtime directory is set. The daemon owns the files in
it (``daemon.json`` state, the ``token`` bearer secret, screenshots); the CLI
and the applet only read them.

The daemon's default loopback port is derived from the uid so that several
logged-in users do not collide. The same formula is duplicated in the
applet's ``main.qml``; change both together.

``ensure_runtime_root`` refuses a directory it does not own or that is a
symlink, because the ``/tmp`` fallback could be pre-created by another user.
"""

from __future__ import annotations

import math
import os
import re
import stat
import time
from pathlib import Path

APP_DIR_NAME = "happy-bot"
BASE_PORT = 19000
DEFAULT_HOST = "127.0.0.1"


class UnsafeRuntimeDirectory(RuntimeError):
    """The runtime directory exists but is not a private directory we own."""


def default_port() -> int:
    """Loopback port for this user: 19000 for uid 1000, 19001 for 1001, ..."""
    return BASE_PORT + max(0, os.getuid() - 1000)


def runtime_root() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path("/tmp") / f"{APP_DIR_NAME}-{os.getuid()}"


def state_path(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "daemon.json"


def read_clear_time(marker: Path) -> float:
    """Read a private history cutoff; an unreadable marker should not expose older activity."""
    try:
        since = float(marker.read_text(encoding="utf-8"))
        return since if math.isfinite(since) and since >= 0 else time.time()
    except FileNotFoundError:
        return 0
    except (ValueError, OSError):
        return time.time()


def token_path(root: Path | None = None) -> Path:
    return (root or runtime_root()) / "token"


def clear_cache_files(directory: Path, filename_pattern: str | re.Pattern[str]) -> None:
    """Remove generated file names in one real cache directory, without following links."""
    try:
        folder = os.open(directory, os.O_DIRECTORY | os.O_NOFOLLOW)
    except (FileNotFoundError, NotADirectoryError):
        return
    try:
        pattern = re.compile(filename_pattern)
        with os.scandir(folder) as files:
            for file in files:
                if pattern.fullmatch(file.name) and file.is_file(follow_symlinks=False):
                    try:
                        os.unlink(file.name, dir_fd=folder)
                    except FileNotFoundError:
                        pass
    finally:
        os.close(folder)


def ensure_runtime_root(root: Path | None = None) -> Path:
    """Create the runtime directory as 0700 and verify it is safely ours."""
    path = root or runtime_root()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeRuntimeDirectory(f"{path} is not a real directory")
    if info.st_uid != os.getuid():
        raise UnsafeRuntimeDirectory(f"{path} is owned by another user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)
    return path


def write_private_file(path: Path, text: str) -> None:
    """Atomically write ``text`` to ``path`` readable only by this user."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def read_token(root: Path | None = None) -> str:
    """Return the daemon's current bearer token, or "" when it is not running."""
    try:
        return token_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

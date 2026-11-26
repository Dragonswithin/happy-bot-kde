"""The undo journal: what each reversible change was, so it can be reversed.

Tools that change something reversible (moving, copying, creating, replacing
or appending to files; making folders; trashing; volume; colour scheme; a
KDE setting; the clipboard; a window's place) call ``record`` after they
succeeded, with a ``kind`` and the data needed to put things back. The undo
tools (``tools/undo.py``) read the journal newest first and reverse an
entry, then ``mark_undone`` it.

Storage: ``undo.jsonl`` in the runtime directory (``$XDG_RUNTIME_DIR/
happy-bot``, 0600), so the journal lasts until logout, like the action
log. A replaced file's previous contents are copied to ``undo-files/`` next
to it before the replacement (files up to ``MAX_BACKUP_BYTES``); larger files
are recorded as not restorable. The journal keeps the newest ``MAX_ENTRIES``.

Entries are ``{"id", "time", "kind", "summary", "data", "undone"}``. Writers
take ``_lock``; tools run one at a time per turn, but several conversations
can run at once.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_paths import clear_cache_files, ensure_runtime_root

MAX_ENTRIES = 200
MAX_BACKUP_BYTES = 5_000_000
_BACKUP_NAME = re.compile(r"[0-9a-f]{16}-.+", re.DOTALL)
_lock = threading.Lock()


def _journal_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or ensure_runtime_root()) / "undo.jsonl"


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and "id" in entry:
            entries.append(entry)
    return entries


def _write(path: Path, entries: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries[-MAX_ENTRIES:]),
                    encoding="utf-8")
    path.chmod(0o600)


def record(kind: str, summary: str, data: dict[str, Any], runtime_dir: Path | None = None) -> None:
    """Add one reversible change; failures to write are ignored (the change itself already happened)."""
    entry = {"id": secrets.token_hex(6), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
             "summary": summary, "data": data, "undone": False}
    try:
        with _lock:
            # A clear can land between backing up a file and completing its replacement.
            if kind == "file_replaced" and data.get("backup") and not Path(data["backup"]).is_file():
                return
            path = _journal_path(runtime_dir)
            _write(path, _read(path) + [entry])
    except OSError:
        pass


def entries(runtime_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every journal entry, newest first."""
    with _lock:
        return list(reversed(_read(_journal_path(runtime_dir))))


def pending(runtime_dir: Path | None = None) -> list[dict[str, Any]]:
    """Entries not yet undone, newest first."""
    return [entry for entry in entries(runtime_dir) if not entry.get("undone")]


def mark_undone(entry_id: str, runtime_dir: Path | None = None) -> None:
    with _lock:
        path = _journal_path(runtime_dir)
        items = _read(path)
        for entry in items:
            if entry["id"] == entry_id:
                entry["undone"] = True
                _write(path, items)
                return


def clear_history(runtime_dir: Path) -> None:
    """Forget journal entries and Happy Bot's file backups, including copies rotated out of the journal."""
    with _lock:
        # A journal entry may refer to any user path. Only enumerate the private backup folder.
        clear_cache_files(runtime_dir / "undo-files", _BACKUP_NAME)
        _journal_path(runtime_dir).unlink(missing_ok=True)


def back_up(path: Path, runtime_dir: Path | None = None) -> str:
    """Copy ``path`` aside before it is replaced; return the copy's path, or "" if it is too large or unreadable."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_BACKUP_BYTES:
            return ""
        with _lock:
            folder = (runtime_dir or ensure_runtime_root()) / "undo-files"
            folder.mkdir(mode=0o700, exist_ok=True)
            if folder.is_symlink():
                return ""
            copy = folder / f"{secrets.token_hex(8)}-{path.name}"
            shutil.copy2(path, copy)
            copy.chmod(0o600)
            return str(copy)
    except OSError:
        return ""

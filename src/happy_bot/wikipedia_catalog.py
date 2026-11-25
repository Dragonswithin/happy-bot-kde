"""Kiwix's published Wikipedia archives: what can be downloaded, and downloading one safely.

Kiwix publishes Wikipedia as ZIM archives at ``CATALOG`` (one listing page, with each file's
build date and size), in three sizes per language: ``maxi`` (everything, with pictures), ``nopic``
(every article, no pictures) and ``mini`` (the introduction of every article). ``available``
reads the newest build of each for one language, for setup's choices. ``update`` brings one book
in one folder to the newest build: used by setup's download (``wikipedia_setup``, in a background
thread, reporting through a ``Progress``) and by the monthly timer (``happy-bot wikipedia update``,
``wikipedia_library.sync_timer``).

How ``update`` keeps the archive safe (adapted from the maintainer's own updater):

- one run at a time per folder: an ``fcntl`` lock on ``wikipedia_library.OWN_LOCK``; a second run
  returns ``{"action": "busy"}``;
- the download goes to ``NAME.zim.partial`` and resumes from its size with an HTTP Range request
  after an interruption (up to ``ATTEMPTS`` tries); the Kiwix address redirects to a nearby mirror;
- free space for the rest of the file plus ``FREE_SPACE_MARGIN`` is checked first;
- the finished file is checked against the SHA-256 Kiwix publishes beside it (always fetched from
  Kiwix itself); a mismatch deletes the partial file so the next run starts clean;
- only then is it renamed into place (atomic within the folder, so a reader never sees half an
  archive) and the older builds of the same book are deleted.

``Progress`` is shared with the HTTP thread that reports it (``GET /wikipedia``); ``cancel`` (a
``threading.Event``) stops a download between chunks and keeps the partial file for later. Network
calls time out after ``SOCKET_TIMEOUT`` seconds. Errors raise ``CatalogError`` with a plain message.
"""

from __future__ import annotations

import fcntl
import hashlib
import re
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .wikipedia_library import OWN_LOCK, archives

CATALOG = "https://download.kiwix.org/zim/wikipedia"
USER_AGENT = "happy-bot-wikipedia/1"
CHUNK = 8 * 1024 * 1024
FREE_SPACE_MARGIN = 5 * 1024**3
SOCKET_TIMEOUT = 120
ATTEMPTS = 3
FLAVOURS = ("mini", "nopic", "maxi")
_LISTING = re.compile(r'href="(wikipedia_([a-z]{2,3}(?:-[a-z]+)?)_all_(maxi|nopic|mini)_(\d{4}-\d{2})\.zim)"'
                      r'[^\n]*?\s(\d+(?:\.\d+)?[KMGT]?)\s*$', re.M)
_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


class CatalogError(RuntimeError):
    """The catalog could not be read or a download failed; the message says why."""


@dataclass
class Progress:
    """A download's state for the settings page: ``state`` is idle, downloading, verifying, done or failed."""

    state: str = "idle"
    book: str = ""
    done_bytes: int = 0
    total_bytes: int = 0
    message: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"state": self.state, "book": self.book, "done_bytes": self.done_bytes,
                    "total_bytes": self.total_bytes, "message": self.message}


def _open(url: str, headers: dict[str, str] | None = None, method: str = "GET") -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, method=method)
    return urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT)


def _text(url: str) -> str:
    try:
        with _open(url) as response:
            return response.read().decode("utf-8", "replace")
    except OSError as error:
        raise CatalogError(f"Kiwix's list could not be read ({error})") from error


def parse_listing(listing: str, language: str) -> list[dict[str, Any]]:
    """The newest build of each size for ``language`` from Kiwix's listing page, smallest first."""
    newest: dict[str, dict[str, Any]] = {}
    for name, lang, flavour, build, size in _LISTING.findall(listing):
        if lang != language:
            continue
        number, unit = re.fullmatch(r"([\d.]+)([KMGT]?)", size).groups()  # type: ignore[union-attr]
        entry = {"name": name, "book": f"wikipedia_{lang}_all_{flavour}", "flavour": flavour, "build": build,
                 "size": int(float(number) * _UNITS[unit])}
        if flavour not in newest or build > newest[flavour]["build"]:
            newest[flavour] = entry
    return [newest[flavour] for flavour in FLAVOURS if flavour in newest]


def available(language: str) -> list[dict[str, Any]]:
    """What Kiwix offers for ``language`` (``mini``, ``nopic``, ``maxi``), newest builds, smallest first."""
    return parse_listing(_text(CATALOG + "/"), language)


def latest_build(book: str) -> str:
    """The file name of the newest published build of ``book``."""
    names = re.findall(r'href="(' + re.escape(book) + r'_(\d{4}-\d{2})\.zim)"', _text(CATALOG + "/"))
    if not names:
        raise CatalogError(f"Kiwix no longer publishes {book}")
    return max(names, key=lambda item: item[1])[0]


def published_sha256(name: str) -> str:
    text = _text(f"{CATALOG}/{name}.sha256").split()
    digest = text[0].lower() if text else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CatalogError(f"Kiwix's checksum for {name} could not be read")
    return digest


def published_size(name: str) -> int:
    try:
        with _open(f"{CATALOG}/{name}", method="HEAD") as response:
            length = response.headers.get("Content-Length", "")
    except OSError as error:
        raise CatalogError(f"Kiwix did not answer ({error})") from error
    if not length.isdigit():
        raise CatalogError(f"Kiwix did not say how big {name} is")
    return int(length)


def _download(url: str, partial: Path, total: int, progress: Progress, cancel: threading.Event) -> None:
    offset = partial.stat().st_size if partial.exists() else 0
    with _open(url, {"Range": f"bytes={offset}-"} if offset else None) as response:
        if offset and response.status != 206:
            offset = 0  # the mirror ignored the range: start again
        with partial.open("ab" if offset else "wb") as out:
            while chunk := response.read(CHUNK):
                if cancel.is_set():
                    raise CatalogError("The download was stopped; it continues from here next time.")
                out.write(chunk)
                offset += len(chunk)
                progress.set(done_bytes=offset)
    if offset != total:
        raise CatalogError(f"the download ended early ({offset} of {total} bytes)")


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def update(folder: str | Path, book: str, progress: Progress | None = None,
           cancel: threading.Event | None = None) -> dict[str, Any]:
    """Bring ``book`` in ``folder`` to Kiwix's newest build (see the module docstring)."""
    progress = progress or Progress()
    cancel = cancel or threading.Event()
    directory = Path(folder)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / OWN_LOCK).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"action": "busy"}
        latest = latest_build(book)
        local = [archive for archive in archives(directory) if archive.book == book]
        if any(Path(archive.path).name == latest for archive in local):
            return {"action": "current", "file": latest}
        target = directory / latest
        partial = target.with_name(target.name + ".partial")
        total = published_size(latest)
        have = partial.stat().st_size if partial.exists() else 0
        if have > total:
            partial.unlink()
            have = 0
        free = shutil.disk_usage(directory).free
        if free < total - have + FREE_SPACE_MARGIN:
            raise CatalogError(f"Not enough free space: it needs {(total - have + FREE_SPACE_MARGIN) / 1024**3:.0f} GB "
                               f"and {free / 1024**3:.0f} GB are free.")
        progress.set(state="downloading", book=book, done_bytes=have, total_bytes=total, message="")
        problems = []
        for attempt in range(ATTEMPTS):
            try:
                _download(f"{CATALOG}/{latest}", partial, total, progress, cancel)
                break
            except (OSError, CatalogError) as error:
                if cancel.is_set():
                    raise CatalogError(str(error)) from error
                problems.append(str(error))
                time.sleep(min(30, 5 * (attempt + 1)))
        else:
            raise CatalogError("The download kept failing: " + "; ".join(problems[-2:]))
        progress.set(state="verifying")
        if _sha256(partial) != published_sha256(latest):
            partial.unlink()
            raise CatalogError(f"{latest} did not match Kiwix's checksum, so it was deleted; it will be downloaded again.")
        partial.rename(target)
        removed = []
        for old in local:
            Path(old.path).unlink(missing_ok=True)
            removed.append(Path(old.path).name)
        return {"action": "downloaded", "file": latest, "removed": removed}

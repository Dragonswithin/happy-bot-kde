"""Isolate native AT-SPI calls so a disconnected desktop bus cannot abort Happy Bot."""
from __future__ import annotations

import logging
import multiprocessing
import subprocess
import threading
import time
import uuid
from dataclasses import replace

from . import _atspi
from ._atspi import AccessibilityUnavailable, Element, ElementGone, REF_PATTERN, Snapshot, find_elements

_lock = threading.Lock()
_last_restart = float("-inf")
_log = logging.getLogger(__name__)
_process = None
_connection = None


def _portable(snapshot, token):
    return replace(snapshot, elements=[replace(e, node=(token, e.ref)) for e in snapshot.elements])


def _serve(connection):
    # Native nodes stay here. An action always resolves against the exact
    # snapshot inspected, even after a worker restart or a new snapshot.
    snapshots = {}
    try:
        while True:
            operation, args = connection.recv()
            try:
                if operation != "last":
                    _atspi.ensure_enabled()
                if operation == "probe":
                    result = None
                elif operation == "snapshot":
                    snapshot = _atspi.take_snapshot(*args)
                    token = uuid.uuid4().hex
                    snapshots[token] = snapshot
                    if len(snapshots) > 16:
                        del snapshots[next(iter(snapshots))]
                    result = _portable(snapshot, token)
                elif operation == "last":
                    result = next((_portable(s, token)
                                   for token, s in reversed(snapshots.items()) if s.pid == args[0]), None)
                else:
                    (token, ref), *values = args
                    snapshot = snapshots.get(token)
                    element = snapshot.by_ref(ref) if snapshot else None
                    if element is None:
                        raise ElementGone
                    action = {"press": _atspi.press, "text": _atspi.get_text, "set": _atspi.set_text,
                              "focus": _atspi.focus}[operation]
                    result = action(element, *values)
                reply = ("ok", result)
            except _atspi.WindowUnavailable as error:
                reply = ("window", str(error))
            except _atspi.BusUnavailable as error:
                reply = ("bus", str(error))
            except _atspi.WorkerStale as error:
                reply = ("stale", str(error))
            except ElementGone:
                reply = ("gone", "")
            except Exception as error:
                reply = ("error", str(error))
            connection.send(reply)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def _exchange(operation, *args):
    global _process, _connection
    if _connection is None:
        ctx = multiprocessing.get_context("spawn")
        _connection, child = ctx.Pipe()
        _process = ctx.Process(target=_serve, args=(child,), daemon=True)
        try:
            _process.start()
        except Exception:
            _connection.close()
            _connection = None
            raise
        finally:
            child.close()
    try:
        _connection.send((operation, args))
        if not _connection.poll(30):
            raise TimeoutError("accessibility service timed out")
        status, value = _connection.recv()
    except (OSError, EOFError) as error:
        raise _atspi.WorkerStale(
            f"accessibility worker lost during {operation} (exit={_process.exitcode}, {type(error).__name__})"
        ) from error
    if status == "window":
        raise _atspi.WindowUnavailable(value)
    if status == "bus":
        raise _atspi.BusUnavailable(value)
    if status == "stale":
        raise _atspi.WorkerStale(value)
    if status == "gone":
        raise ElementGone
    if status == "error":
        raise AccessibilityUnavailable(value)
    return value


def _reset_worker():
    global _process, _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        _process.kill()
        _process.join()
        _process.close()
        _process = None


def _recover():
    global _last_restart
    _reset_worker()
    try:
        _exchange("probe")
        return
    except _atspi.BusUnavailable as error:
        if time.monotonic() - _last_restart < 60:
            raise AccessibilityUnavailable(f"Accessibility is still unavailable after a recent restart: {error}") from error
        _log.warning("Restarting at-spi-dbus-bus.service after a fresh worker confirmed bus failure: %s", error)
    _last_restart = time.monotonic()
    try:
        subprocess.run(["systemctl", "--user", "restart", "at-spi-dbus-bus.service"],
                       capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise AccessibilityUnavailable(f"Could not restart the desktop accessibility service: {detail.strip()}") from error
    _exchange("probe")


def _call(operation, *args):
    with _lock:
        try:
            return _exchange(operation, *args)
        except (_atspi.WorkerStale, _atspi.BusUnavailable) as error:
            _log.warning("Recovering desktop accessibility during %s: %s", operation, error)
        if operation == "last":
            _reset_worker()
            return None  # cached refs lived in the lost worker
        _recover()
        _log.warning("Desktop accessibility reconnected during %s", operation)
        if operation == "snapshot":
            # Applications register their windows asynchronously after a bus restart.
            for delay in (0, 0.2, 0.5):
                time.sleep(delay)
                try:
                    return _exchange(operation, *args)
                except _atspi.WindowUnavailable:
                    continue
            return _exchange(operation, *args)
        raise AccessibilityUnavailable(
            "Desktop accessibility reconnected. Inspect the window with a fresh snapshot to check the outcome "
            "before taking any further action.")


def take_snapshot(pid: int, title: str) -> Snapshot:
    return _call("snapshot", pid, title)


def last_snapshot(pid: int) -> Snapshot | None:
    return _call("last", pid)


def press(element: Element) -> str:
    return _call("press", element.node)


def set_text(element: Element, text: str) -> None:
    _call("set", element.node, text)


def get_text(element: Element, limit: int) -> str:
    return _call("text", element.node, limit)


def focus(element: Element) -> None:
    _call("focus", element.node)

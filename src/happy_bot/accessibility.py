"""Isolate native AT-SPI calls so a disconnected desktop bus cannot abort Happy Bot."""
from __future__ import annotations

import multiprocessing
import threading
import uuid
from dataclasses import replace

from . import _atspi
from ._atspi import AccessibilityUnavailable, Element, ElementGone, REF_PATTERN, Snapshot, find_elements

_lock = threading.Lock()
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
                if operation == "snapshot":
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
            except ElementGone:
                reply = ("gone", "")
            except Exception as error:
                reply = ("error", str(error))
            connection.send(reply)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def _call(operation, *args):
    global _process, _connection
    with _lock:
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
            _connection.close()
            _connection = None
            _process.kill()
            _process.join()
            _process.close()
            raise AccessibilityUnavailable("The desktop accessibility service disconnected or stopped responding. "
                                           "Take a fresh window snapshot to try again.") from error
        if status == "gone":
            raise ElementGone
        if status == "error":
            raise AccessibilityUnavailable(value)
        return value


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

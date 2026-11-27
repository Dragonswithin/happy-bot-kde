"""Reads and operates other applications' user interfaces through AT-SPI.

AT-SPI is the desktop accessibility interface that screen readers use. Qt,
GTK and browser applications publish their windows as a tree of elements
(buttons, menu items, text fields) with names, states and actions. This
module turns one window's tree into a compact list a text-only model can
read, and performs actions on elements the model picks. It is what lets the
assistant "click Save" without seeing the screen.

Applications only publish their tree while the session's accessibility flag
is on, so ``ensure_enabled`` sets ``org.a11y.Status.IsEnabled`` on first use.
Running applications react at once; no restart is needed. The flag stays on
for the session.

A ``Snapshot`` is one reading of one window: an ordered list of ``Element``
objects, each with a short ref such as ``e12``. Refs are only meaningful for
the snapshot that produced them. The accessibility worker keeps snapshots
so a following action can resolve a ref. The interface
can change between reading and acting; actions therefore re-check that the
element is still attached and report clearly when it is gone, and the model
is told to take a new snapshot.

Dependency: PyGObject with the ``Atspi`` typelib (``at-spi2-core``). It is
imported lazily; without it every function raises ``AccessibilityUnavailable``.

Threading: AT-SPI calls are blocking DBus round trips and the library is not
safe to use from several threads at once, so every entry point takes
``_LOCK``.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any

MAX_NODES = 6000
MAX_DEPTH = 40
MAX_CHILDREN = 400
VALUE_CHARS = 80
ACTION_TIMEOUT_MS = 2500
INTERACTIVE_ROLES = {
    "push button", "button", "toggle button", "check box", "radio button", "menu item", "check menu item",
    "radio menu item", "menu", "combo box", "entry", "text", "password text", "spin button", "slider", "page tab",
    "link", "list item", "tree item", "table cell", "push button menu", "document text", "terminal", "paragraph",
}
CONTEXT_ROLES = {"label", "heading", "static", "alert", "dialog", "frame", "status bar", "notification", "tool tip"}
_LOCK = threading.RLock()
_atspi: Any = None
_bus_guid: str | None = None



class AccessibilityUnavailable(RuntimeError):
    """AT-SPI cannot be used here; the message says why."""


class BusUnavailable(AccessibilityUnavailable):
    """The accessibility address advertised by the session could not be reached."""


class WindowUnavailable(AccessibilityUnavailable):
    """No window for the requested process is registered yet."""


class WorkerStale(AccessibilityUnavailable):
    """Native state must be initialized in a fresh process."""


class ElementGone(RuntimeError):
    """The element is no longer part of the application's interface."""


@dataclass
class Element:
    ref: str
    role: str
    name: str
    depth: int
    showing: bool
    states: tuple[str, ...]
    actions: tuple[str, ...]
    editable: bool
    value: str
    node: Any = field(repr=False, default=None)

    def line(self) -> str:
        parts = [f"{self.ref} {self.role}"]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.value:
            parts.append(f"= {self.value!r}")
        flags = [*self.states, *(["editable"] if self.editable else []), *([] if self.showing else ["hidden"])]
        if flags:
            parts.append(f"[{', '.join(flags)}]")
        return "  " * min(self.depth, 6) + " ".join(parts)


@dataclass
class Snapshot:
    pid: int
    title: str
    application: str
    elements: list[Element]
    truncated: bool

    def by_ref(self, ref: str) -> Element | None:
        return next((element for element in self.elements if element.ref == ref), None)


def _load() -> Any:
    global _atspi
    if _atspi is None:
        try:
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
        except (ImportError, ValueError) as error:
            raise AccessibilityUnavailable(
                f"the accessibility library (PyGObject with at-spi2-core) is not available: {error}") from error
        result = Atspi.init()
        if result not in (0, 1):
            raise WorkerStale(f"AT-SPI initialization failed with code {result}")
        # Method calls wait at most this long. An action that opens a modal
        # dialog never replies while the dialog is up (see ``press``).
        Atspi.set_timeout(ACTION_TIMEOUT_MS, ACTION_TIMEOUT_MS)
        _atspi = Atspi
    return _atspi


def ensure_enabled() -> None:
    """Turn on the session's accessibility flag so applications publish their interfaces."""
    global _bus_guid
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as error:
        raise AccessibilityUnavailable(f"could not access the desktop session bus: {error}") from error

    def connect(address):
        return Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)

    override = os.environ.get("AT_SPI_BUS_ADDRESS")
    probe = None
    if override:
        try:
            probe = connect(override)
        except GLib.Error:
            # This environment belongs to the isolated worker. Let libatspi
            # discover the current address if the inherited one is stale.
            del os.environ["AT_SPI_BUS_ADDRESS"]
    if probe is None:
        try:
            address = bus.call_sync(
                "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress", None,
                None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
            probe = connect(address)
        except GLib.Error as error:
            raise BusUnavailable(f"desktop accessibility bus discovery or connection failed: {error}") from error
    try:
        guid = probe.get_guid()
    finally:
        probe.close_sync(None)
    if _bus_guid == guid:
        return
    if _bus_guid is not None:
        raise WorkerStale("the desktop accessibility bus was replaced")
    bus.call_sync(
        "org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties", "Set",
        GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", True))),
        None, Gio.DBusCallFlags.NONE, 3000, None)
    _bus_guid = guid


def _clean(text: str | None) -> str:
    return " ".join((text or "").replace("&", "").split())


def _states(atspi: Any, node: Any) -> tuple[bool, tuple[str, ...], bool]:
    state_set = node.get_state_set()
    state = atspi.StateType
    flags = []
    if state_set.contains(state.FOCUSED):
        flags.append("focused")
    if state_set.contains(state.CHECKED):
        flags.append("checked")
    if state_set.contains(state.SELECTED):
        flags.append("selected")
    if state_set.contains(state.EXPANDED):
        flags.append("expanded")
    if not state_set.contains(state.ENABLED) and not state_set.contains(state.SENSITIVE):
        flags.append("disabled")
    return state_set.contains(state.SHOWING), tuple(flags), state_set.contains(state.EDITABLE)


def _read_text(node: Any, limit: int) -> tuple[str, int]:
    """Return ``(first `limit` characters, total length)`` of a node's text.

    The Text interface is called through the class because an accessible
    object also has an unrelated ``get_text`` method of its own.
    """
    atspi = _load()
    count = atspi.Text.get_character_count(node)
    return atspi.Text.get_text(node, 0, min(count, limit)), count


def _value(node: Any, editable: bool, role: str) -> str:
    try:
        if node.get_text_iface() is not None and (
                editable or role in ("entry", "text", "document text", "paragraph", "terminal")):
            content, count = _read_text(node, VALUE_CHARS)
            return " ".join(content.split()) + ("…" if count > VALUE_CHARS else "")
    except Exception:  # noqa: BLE001 - a missing interface is normal
        pass
    return ""


def _label_of(atspi: Any, node: Any) -> str:
    """A name for an unnamed element: the label that points at it, else its description."""
    try:
        for relation in node.get_relation_set() or []:
            if relation.get_relation_type() == atspi.RelationType.LABELLED_BY and relation.get_n_targets():
                label = _clean(relation.get_target(0).get_name())
                if label:
                    return label
        return _clean(node.get_description())
    except Exception:  # noqa: BLE001 - relations are optional
        return ""


def _find_window(atspi: Any, pid: int, title: str) -> tuple[Any, Any]:
    desktop = atspi.get_desktop(0)
    candidates = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        try:
            if application is not None and application.get_process_id() == pid:
                for child in range(application.get_child_count()):
                    window = application.get_child_at_index(child)
                    if window is not None:
                        candidates.append((application, window))
        except Exception:  # noqa: BLE001 - an application may vanish mid-walk
            continue
    if not candidates:
        raise WindowUnavailable(
            "this application does not publish its interface for assistive tools, so it cannot be operated this way")
    wanted = _clean(title)
    for application, window in candidates:
        if _clean(window.get_name()) == wanted:
            return application, window
    for application, window in candidates:
        if window.get_state_set().contains(atspi.StateType.ACTIVE):
            return application, window
    return candidates[-1]


def take_snapshot(pid: int, title: str) -> Snapshot:
    """Read the window of process ``pid`` whose title is ``title`` (else its active window)."""
    with _LOCK:
        atspi = _load()
        application, window = _find_window(atspi, pid, title)
        elements: list[Element] = []
        visited = 0
        truncated = False

        def walk(node: Any, depth: int) -> None:
            nonlocal visited, truncated
            if visited >= MAX_NODES or depth > MAX_DEPTH:
                truncated = True
                return
            visited += 1
            try:
                role = node.get_role_name()
                name = _clean(node.get_name()) or _label_of(atspi, node)
                showing, flags, editable = _states(atspi, node)
                action_iface = node.get_action_iface()
                actions = tuple(
                    action_iface.get_action_name(i) for i in range(action_iface.get_n_actions())) if action_iface else ()
                keep = (role in INTERACTIVE_ROLES and (name or editable or actions)) or (
                    role in CONTEXT_ROLES and name and showing) or editable
                if keep:
                    elements.append(Element(
                        f"e{len(elements) + 1}", role, name, depth, showing, flags, actions,
                        editable or node.get_editable_text_iface() is not None, _value(node, editable, role), node))
                count = node.get_child_count()
                if count > MAX_CHILDREN:
                    truncated = True
                for index in range(min(count, MAX_CHILDREN)):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        walk(child, depth + 1)
            except Exception:  # noqa: BLE001 - nodes disappear while an interface changes
                return

        walk(window, 0)
        return Snapshot(pid, _clean(window.get_name()), _clean(application.get_name()), elements, truncated)


def find_elements(snapshot: Snapshot, text: str, actionable_only: bool = False) -> list[Element]:
    """Elements named like ``text``: exact matches, else prefix matches, else substring matches."""
    wanted = _clean(text).lower().rstrip(".…")
    pool = [element for element in snapshot.elements
            if element.name and (not actionable_only or element.actions or element.editable)]
    names = [(element, element.name.lower().rstrip(".…")) for element in pool]
    for test in (lambda name: name == wanted, lambda name: name.startswith(wanted), lambda name: wanted in name):
        matches = [element for element, name in names if test(name)]
        if matches:
            showing = [element for element in matches if element.showing]
            return showing or matches
    return []


def _alive(element: Element) -> Any:
    try:
        element.node.get_role_name()
        if element.node.get_state_set().contains(_load().StateType.DEFUNCT):
            raise ElementGone
    except ElementGone:
        raise
    except Exception as error:  # noqa: BLE001 - any failure means the node is unusable
        raise ElementGone from error
    return element.node


def press(element: Element) -> str:
    """Run the element's primary action (press, click, activate). Returns a short outcome.

    An action that opens a modal dialog does not answer until the dialog is
    closed, so the call times out although it worked. That case is reported
    as pressed-and-waiting rather than as a failure.
    """
    with _LOCK:
        node = _alive(element)
        action = node.get_action_iface()
        if action is None or action.get_n_actions() == 0:
            raise AccessibilityUnavailable(f"{element.role} \"{element.name}\" has no action to perform")
        name = action.get_action_name(0) or "activate"
        try:
            accepted = action.do_action(0)
        except Exception as error:  # noqa: BLE001 - GLib.GError
            if "Did not receive a reply" in str(error) or "timeout" in str(error).lower():
                return f"{name} sent; the application is now busy, most likely showing a dialog"
            raise AccessibilityUnavailable(f"could not {name} \"{element.name}\": {error}") from error
        if not accepted:
            raise AccessibilityUnavailable(f"the application refused to {name} \"{element.name}\"")
        return f"{name} done"


def set_text(element: Element, text: str) -> None:
    """Replace the contents of an editable text element."""
    with _LOCK:
        node = _alive(element)
        if node.get_editable_text_iface() is None:
            raise AccessibilityUnavailable(f"{element.role} \"{element.name}\" is not an editable text field")
        if not _load().EditableText.set_text_contents(node, text):
            raise AccessibilityUnavailable("the application refused the text")


def get_text(element: Element, limit: int) -> str:
    with _LOCK:
        node = _alive(element)
        if node.get_text_iface() is None:
            return element.name
        content, count = _read_text(node, limit)
        return content + (f"\n[{count - limit} more characters]" if count > limit else "")


def focus(element: Element) -> None:
    with _LOCK:
        node = _alive(element)
        component = node.get_component_iface()
        if component is None or not component.grab_focus():
            raise AccessibilityUnavailable(f"could not move keyboard focus to \"{element.name or element.role}\"")


REF_PATTERN = re.compile(r"^e\d+$")

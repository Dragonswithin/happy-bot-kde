"""Synthetic keyboard input through the desktop's RemoteDesktop portal.

Some things cannot be done through an application's accessibility actions:
pressing a shortcut, Enter, Tab or Escape, or typing into a field that offers
no editable-text interface. For those the assistant sends key events through
``org.freedesktop.portal.RemoteDesktop``, the same portal remote-desktop and
automation programs use on Wayland.

The portal needs the user's consent. The first ``start`` shows the desktop's
"allow remote control" dialog; the grant is stored by the portal against a
restore token, which this module saves (0600) in the configuration directory
and presents on later starts so the dialog does not reappear. Declining
raises ``InputUnavailable`` and nothing is sent. ``consent_saved`` reports
whether such a grant is stored, for the self-check and the settings page,
whose "Allow…" button calls ``start`` early (``POST /typing/allow``).

Keys are sent as keysyms (``NotifyKeyboardKeysym``), so no keyboard-layout
mapping is needed here: the compositor finds the key for each symbol.
``press_keys`` takes names such as ``ctrl+s``, ``Return`` or ``alt+F4``;
``type_text`` sends one character at a time.

Dependency: PyGObject (``Gio``). Portal replies arrive as DBus signals on the
shared GLib loop (``glib_loop``). One session is kept for the life of the
daemon and recreated if the portal closes it. Calls are serialised by a lock
and block while the consent dialog is open (up to ``CONSENT_TIMEOUT_SECONDS``).
"""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Any

from . import glib_loop
from .runtime_paths import write_private_file

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
INTERFACE = "org.freedesktop.portal.RemoteDesktop"
DEVICE_KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2
CONSENT_TIMEOUT_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 15.0
KEY_INTERVAL_SECONDS = 0.004

MODIFIERS = {"ctrl": 0xFFE3, "control": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9, "meta": 0xFFEB, "super": 0xFFEB,
             "win": 0xFFEB}
NAMED_KEYS = {
    "return": 0xFF0D, "enter": 0xFF0D, "tab": 0xFF09, "escape": 0xFF1B, "esc": 0xFF1B, "backspace": 0xFF08,
    "delete": 0xFFFF, "del": 0xFFFF, "insert": 0xFF63, "home": 0xFF50, "end": 0xFF57, "left": 0xFF51, "up": 0xFF52,
    "right": 0xFF53, "down": 0xFF54, "pageup": 0xFF55, "page_up": 0xFF55, "pagedown": 0xFF56, "page_down": 0xFF56,
    "space": 0x20, "menu": 0xFF67, "print": 0xFF61, "printscreen": 0xFF61,
    **{f"f{number}": 0xFFBD + number for number in range(1, 13)},
}


class InputUnavailable(RuntimeError):
    """Key input could not be sent; the message says why."""


def keysym_for_character(character: str) -> int:
    """The X keysym for one character: Latin-1 maps to itself, the rest to the Unicode range."""
    if character == "\n":
        return NAMED_KEYS["return"]
    if character == "\t":
        return NAMED_KEYS["tab"]
    code = ord(character)
    return code if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF else 0x01000000 | code


def parse_combination(combination: str) -> tuple[list[int], int]:
    """Split ``ctrl+shift+s`` into modifier keysyms and the final key's keysym."""
    parts = [part.strip() for part in combination.replace(" ", "").split("+")] if combination.strip() != "+" else ["+"]
    if combination.replace(" ", "").endswith("++"):
        parts = [part for part in parts if part] + ["+"]
    parts = [part for part in parts if part]
    if not parts:
        raise InputUnavailable("no key was given")
    *modifier_names, key = parts
    modifiers = []
    for name in modifier_names:
        if name.lower() not in MODIFIERS:
            raise InputUnavailable(f"unknown modifier '{name}' (use ctrl, shift, alt or meta)")
        modifiers.append(MODIFIERS[name.lower()])
    if key.lower() in NAMED_KEYS:
        return modifiers, NAMED_KEYS[key.lower()]
    if key.lower() in MODIFIERS:
        return modifiers, MODIFIERS[key.lower()]
    if len(key) == 1:
        return modifiers, keysym_for_character(key.lower() if modifiers else key)
    raise InputUnavailable(f"unknown key '{key}'")


class KeyboardPortal:
    def __init__(self, token_file: Path) -> None:
        self._token_file = token_file
        self._lock = threading.Lock()
        self._connection: Any = None
        self._session = ""
        self._gio: Any = None
        self._glib: Any = None

    def _connect(self) -> None:
        if self._connection is not None:
            return
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib

            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as error:  # noqa: BLE001 - import or bus failure
            raise InputUnavailable(f"PyGObject and a desktop session are needed to send keys: {error}") from error
        self._gio, self._glib = Gio, GLib
        glib_loop.ensure_running()

    def _request(self, method: str, signature: str, arguments: tuple, options: dict[str, Any], timeout: float) -> dict:
        """Call a portal method that answers through a Request object; return its results."""
        token = "happybot" + secrets.token_hex(6)
        sender = self._connection.get_unique_name()[1:].replace(".", "_")
        request_path = f"{PORTAL_PATH}/request/{sender}/{token}"
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def on_response(connection, sender_name, path, interface, signal, parameters) -> None:
            outcome["code"], outcome["results"] = parameters.unpack()
            done.set()

        subscription = self._connection.signal_subscribe(
            PORTAL, "org.freedesktop.portal.Request", "Response", request_path, None,
            self._gio.DBusSignalFlags.NONE, on_response)
        try:
            options = {**options, "handle_token": self._glib.Variant("s", token)}
            self._connection.call_sync(
                PORTAL, PORTAL_PATH, INTERFACE, method, self._glib.Variant(signature, (*arguments, options)),
                None, self._gio.DBusCallFlags.NONE, 10000, None)
            if not done.wait(timeout):
                raise InputUnavailable("the desktop did not answer the request to control the keyboard")
        except self._glib.Error as error:
            raise InputUnavailable(f"the desktop refused keyboard control: {error.message}") from error
        finally:
            self._connection.signal_unsubscribe(subscription)
        if outcome["code"] == 1:
            raise InputUnavailable("you declined to let the assistant control the keyboard")
        if outcome["code"] != 0:
            raise InputUnavailable("the desktop could not set up keyboard control")
        return outcome["results"]

    def start(self) -> None:
        """Open a keyboard session, showing the consent dialog if the user has not granted it before."""
        self._connect()
        variant = self._glib.Variant
        created = self._request(
            "CreateSession", "(a{sv})", (), {"session_handle_token": variant("s", "happybot" + secrets.token_hex(6))},
            REQUEST_TIMEOUT_SECONDS)
        session = created["session_handle"]
        select: dict[str, Any] = {
            "types": variant("u", DEVICE_KEYBOARD), "persist_mode": variant("u", PERSIST_UNTIL_REVOKED)}
        try:
            saved = self._token_file.read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        if saved:
            select["restore_token"] = variant("s", saved)
        self._request("SelectDevices", "(oa{sv})", (session,), select, REQUEST_TIMEOUT_SECONDS)
        started = self._request("Start", "(osa{sv})", (session, ""), {}, CONSENT_TIMEOUT_SECONDS)
        if not int(started.get("devices", 0)) & DEVICE_KEYBOARD:
            raise InputUnavailable("keyboard control was not granted")
        token = started.get("restore_token")
        if token:
            self._token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_private_file(self._token_file, str(token))
        self._session = session

    def _send(self, keysym: int, pressed: bool) -> None:
        self._connection.call_sync(
            PORTAL, PORTAL_PATH, INTERFACE, "NotifyKeyboardKeysym",
            self._glib.Variant("(oa{sv}iu)", (self._session, {}, keysym, 1 if pressed else 0)),
            None, self._gio.DBusCallFlags.NONE, 5000, None)

    def _with_session(self, action) -> None:
        with self._lock:
            if not self._session:
                self.start()
            try:
                action()
            except Exception as error:  # noqa: BLE001 - GLib.Error: most often a session the portal closed
                if isinstance(error, InputUnavailable):
                    raise
                self._session = ""
                self.start()
                try:
                    action()
                except Exception as second:  # noqa: BLE001
                    raise InputUnavailable(f"sending keys failed: {second}") from second

    def press_keys(self, combination: str) -> None:
        """Press and release one key or combination, for example ``ctrl+s``."""
        modifiers, key = parse_combination(combination)

        def action() -> None:
            for modifier in modifiers:
                self._send(modifier, True)
            self._send(key, True)
            time.sleep(KEY_INTERVAL_SECONDS)
            self._send(key, False)
            for modifier in reversed(modifiers):
                self._send(modifier, False)

        self._with_session(action)

    def type_text(self, text: str) -> None:
        """Type ``text`` into whatever has keyboard focus."""
        def action() -> None:
            for character in text:
                keysym = keysym_for_character(character)
                self._send(keysym, True)
                self._send(keysym, False)
                time.sleep(KEY_INTERVAL_SECONDS)

        self._with_session(action)


_shared: KeyboardPortal | None = None
_shared_lock = threading.Lock()


def token_path() -> Path:
    from .settings import config_dir

    return config_dir() / "keyboard-portal-token"


def consent_saved() -> bool:
    """Whether the user has allowed keyboard control and the portal gave a token to reuse."""
    return token_path().exists()


def shared() -> KeyboardPortal:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = KeyboardPortal(token_path())
        return _shared

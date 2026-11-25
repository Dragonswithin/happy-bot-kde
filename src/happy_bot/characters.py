"""Emoji and special characters for the search bar: "emoji heart", "euro sign", "em dash".

``find(text)`` returns up to ``MAX_RESULTS`` characters for the typed text as
quick results whose action, ``{"type": "character", "target": <character>}``,
puts the character on the clipboard (``quick_results.activate``). Nothing is
sent anywhere and no model is involved.

What is searched:

- emoji, from the dictionaries Plasma's own emoji picker uses
  (``/usr/share/plasma/emoji/<language>.dict``, from plasma-desktop), in the
  user's language (``LC_ALL``, ``LC_MESSAGES`` or ``LANG``, falling back to
  English), with their names and keywords;
- symbols, from Python's Unicode database (``unicodedata``) over the blocks
  people type symbols from (``SYMBOL_BLOCKS``: currency, arrows, maths,
  punctuation, Greek letters...), by their English Unicode names.

When it searches: text that starts or ends with "emoji" searches emoji
("emoji heart", "heart emoji"); text that starts with "symbol", "character" or
"char", or ends with "sign", "symbol" or "character", searches both ("euro
sign", "arrow symbol"). Every word must start a word of the name or a
keyword. Without one of those words only an exact name of two or more words
is offered ("red heart", "em dash"), so ordinary searches stay quiet.

A Plasma ``.dict`` file is Qt's ``qCompress`` output (a 4-byte big-endian
length, then zlib) of a little-endian ``QDataStream``: a count, then per
emoji its text, its name, its category number and a list of keywords, each
string as a 4-byte length and UTF-8 bytes. A file that is missing or does not
parse gives no emoji, never an error. Both tables are built once, on first
use, and kept in memory (a few hundred kilobytes).
"""

from __future__ import annotations

import os
import re
import struct
import threading
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EMOJI_DIR = Path("/usr/share/plasma/emoji")
MAX_RESULTS = 8
SYMBOL_BLOCKS = ((0x00A1, 0x00FF), (0x0391, 0x03C9), (0x2010, 0x205E), (0x2070, 0x209F), (0x20A0, 0x20C0),
                 (0x2100, 0x214F), (0x2150, 0x218B), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2300, 0x23FF),
                 (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF))
_EMOJI_ONLY = re.compile(r"^emojis? (.+)$|^(.+) emojis?$")
_SYMBOL = re.compile(r"^(?:symbol|character|char) (.+)$|^(.+?) (?:symbol|character)$|^(.+ sign)$")
_lock = threading.Lock()
_emoji: list["Character"] | None = None
_symbols: list["Character"] | None = None


@dataclass(frozen=True)
class Character:
    text: str
    name: str  # lower case
    keywords: tuple[str, ...]
    emoji: bool


def _languages() -> list[str]:
    value = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "en"
    full = value.split(".")[0].split("@")[0]
    return list(dict.fromkeys([full, full.split("_")[0], "en"]))


def parse_dict(data: bytes) -> list[Character]:
    """The emoji in one Plasma ``.dict`` file's bytes; raises ``ValueError`` if they do not parse."""
    try:
        raw = zlib.decompress(data[4:])
    except zlib.error as error:
        raise ValueError(f"not a compressed emoji dictionary ({error})") from error
    position = 0

    def number() -> int:
        nonlocal position
        value = struct.unpack_from("<I", raw, position)[0]
        position += 4
        return value

    def string() -> str:
        nonlocal position
        length = number()
        if position + length > len(raw):
            raise ValueError("emoji dictionary ends early")
        value = raw[position:position + length].decode("utf-8")
        position += length
        return value

    found: list[Character] = []
    try:
        for _ in range(number()):
            text, name = string(), string()
            number()  # category
            keywords = tuple(string().lower() for _ in range(number()))
            found.append(Character(text, name.lower(), keywords, True))
    except (struct.error, UnicodeDecodeError) as error:
        raise ValueError(f"emoji dictionary does not parse ({error})") from error
    return found


def _load_emoji(directory: Path = EMOJI_DIR) -> list[Character]:
    for language in _languages():
        path = directory / f"{language}.dict"
        try:
            return parse_dict(path.read_bytes())
        except (OSError, ValueError):
            continue
    return []


def _load_symbols() -> list[Character]:
    found = []
    for first, last in SYMBOL_BLOCKS:
        for point in range(first, last + 1):
            name = unicodedata.name(chr(point), "")
            if name:
                found.append(Character(chr(point), name.lower(), (), False))
    return found


def _tables() -> tuple[list[Character], list[Character]]:
    global _emoji, _symbols
    with _lock:
        if _emoji is None:
            _emoji = _load_emoji()
        if _symbols is None:
            _symbols = _load_symbols()
        return _emoji, _symbols


def _matches(words: list[str], character: Character) -> bool:
    names = character.name.split()
    return all(any(part.startswith(word) for part in names) or any(key.startswith(word) for key in character.keywords)
               for word in words)


def _search(words: list[str], pool: list[Character]) -> list[Character]:
    wanted = " ".join(words)
    found = [character for character in pool if _matches(words, character)]
    # The exact name first, then names holding each word whole, then names where words only start a word,
    # then keyword matches; shorter names first.
    def rank(character: Character) -> tuple[bool, bool, bool, int]:
        names = character.name.split()
        whole = set(names) | {part.removesuffix("wards") for part in names}  # "right" is whole in "rightwards"
        return (character.name != wanted, not all(word in whole for word in words),
                not all(any(part.startswith(word) for part in names) for word in words), len(character.name))
    return sorted(found, key=rank)


def _result(character: Character) -> dict[str, Any]:
    kind = "Emoji" if character.emoji else f"Character · U+{ord(character.text[0]):04X}"
    return {"kind": "quick", "title": character.name[:1].upper() + character.name[1:], "glyph": character.text,
            "subtitle": f"{kind} · Enter copies it",
            "icon": "preferences-desktop-emoticons" if character.emoji else "accessories-character-map",
            "action": {"type": "character", "target": character.text}}


def find(text: str) -> list[dict[str, Any]]:
    """Characters for the typed text, best first (see the module docstring)."""
    said = " ".join(text.lower().split())
    if len(said) < 3:
        return []
    emoji, symbols = _tables()
    only_emoji, symbol = _EMOJI_ONLY.fullmatch(said), _SYMBOL.fullmatch(said)
    if only_emoji:
        found = _search((only_emoji.group(1) or only_emoji.group(2)).split(), emoji)
    elif symbol:
        words = next(group for group in symbol.groups() if group).split()
        found = _search(words, symbols) + _search(words, emoji)
        if words[-1] == "sign" and len(words) > 1:  # "sign" is in symbol names; emoji rarely say it
            found += _search(words[:-1], emoji)
    elif " " in said:
        found = [character for character in (*symbols, *emoji) if character.name == said]
    else:
        found = []
    unique: dict[str, Character] = {}
    for character in found:
        unique.setdefault(character.text, character)
    return [_result(character) for character in list(unique.values())[:MAX_RESULTS]]

"""Site shortcuts for the web finder's start page. Only explicit choices go into settings."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

SITE_COUNT = 8
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_UNSAFE_URL = re.compile(r"[\x00-\x1f\x7f\\]")


def site_identity(url: Any) -> tuple[str, str] | None:
    """A site key and its homepage, dropping page paths, query terms and fragments."""
    if not isinstance(url, str) or _UNSAFE_URL.search(url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
            return None
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{ipaddress.IPv6Address(host)}]"
        elif len(host) > 253 or not all(_LABEL.fullmatch(label) for label in host.split(".")):
            return None
        key = host.removeprefix("www.") if host.count(".") > 1 else host
        port = parts.port
        suffix = f":{port}" if port is not None and port != (443 if parts.scheme == "https" else 80) else ""
        return key + suffix, f"{parts.scheme}://{host}{suffix}/"
    except (ValueError, UnicodeError):
        return None


def site_list(values: Any) -> dict[str, str]:
    """Validate a preference list, normalizing and deduplicating homepage URLs in user order."""
    if not isinstance(values, list):
        raise ValueError("expected a list of website addresses")
    sites = {}
    for value in values:
        identity = site_identity(value)
        if identity is None:
            raise ValueError("expected an http or https website address")
        key, url = identity
        sites.setdefault(key, url)
    return sites


def changed_sites(ui: dict[str, Any], url: Any, action: Any) -> dict[str, list[str]]:
    identity = site_identity(url)
    if identity is None:
        raise ValueError("Choose a site with an http or https address.")
    key, homepage = identity
    pins, hidden = site_list(ui["web_pins"]), site_list(ui["web_hidden"])
    if action == "pin":
        pins.setdefault(key, homepage)
        hidden.pop(key, None)
    elif action == "unpin":
        pins.pop(key, None)
    elif action == "hide":
        pins.pop(key, None)
        hidden.setdefault(key, homepage)
    elif action == "unhide":
        hidden.pop(key, None)
    else:
        raise ValueError("Choose pin, unpin, hide or unhide.")
    return {"web_pins": list(pins.values()), "web_hidden": list(hidden.values())}


def site_field(url: str) -> dict[str, str]:
    """The optional site key for pinning or hiding a typed result."""
    site = site_identity(url)
    return {"site_host": site[0]} if site else {}


def site_rows(ranked: list[dict[str, Any]], ui: dict[str, Any]) -> list[dict[str, Any]]:
    pins = site_list(ui.get("web_pins", []))
    hidden = site_list(ui.get("web_hidden", []))
    titles = {row["host"]: row["title"] for row in ranked if row["host"] in pins}
    rows = [{"host": host, "title": titles.get(host, host), "location": url, "pinned": True}
            for host, url in pins.items()]
    for row in ranked:
        if len(rows) >= SITE_COUNT:
            break
        if row["host"] not in pins and row["host"] not in hidden:
            rows.append({**row, "pinned": False})
    return rows

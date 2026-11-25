"""Finding tools beyond the file index: recent files, browser bookmarks, a download's origin, web pages.

- ``recent_files``: the desktop's record of recently used files
  (``~/.local/share/recently-used.xbel``, written by KDE and GTK apps), for
  "where did I save…" questions, newest first, optionally filtered.
- ``browser_bookmarks``: bookmarks from every browser profile ``browsers``
  finds (the Firefox and Chromium families, native or Flatpak; databases read
  from a temporary copy because browsers keep them locked), matching some
  words.
- ``file_origin``: where a downloaded file came from, from the extended
  attributes browsers set (``user.xdg.origin.url``, ``user.xdg.referrer.url``).
- ``read_web_page``: fetch one http(s) page and return its readable text (or a
  PDF's text through ``pdftotext``), cut to ``MAX_PAGE_CHARS``. Only public
  web addresses are fetched: loopback and private-network hosts are refused,
  for the first address and for every redirect, so a page cannot be used to
  reach the user's own services.

All are ``read``. ``read_web_page`` sends a request to the site named, which
the user asked about; it is left out when the user's "local only" setting is
on (``tools/catalog.py``).
"""

from __future__ import annotations

import html
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .. import browsers
from .registry import RISK_READ, Tool, ToolFailure, object_schema

MAX_LISTED = 40
MAX_PAGE_CHARS = 15000
MAX_DOWNLOAD_BYTES = 8_000_000


def recent_files(arguments: dict[str, Any]) -> str:
    store = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "recently-used.xbel"
    try:
        root = ElementTree.parse(store).getroot()
    except (OSError, ElementTree.ParseError):
        return "No record of recently used files."
    wanted = str(arguments.get("contains") or "").lower()
    items = []
    for bookmark in root.iter("bookmark"):
        href = bookmark.get("href", "")
        if not href.startswith("file://"):
            continue
        path = urllib.parse.unquote(href[7:])
        if wanted and wanted not in path.lower():
            continue
        items.append((bookmark.get("modified") or bookmark.get("visited") or "", path))
    items.sort(reverse=True)
    lines = [f"{when[:16].replace('T', ' ')}  {path}{'' if os.path.exists(path) else '  (no longer there)'}"
             for when, path in items[:MAX_LISTED]]
    return "\n".join(lines) or "No recently used file matches."


def browser_bookmarks(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("contains") or "").lower().split()
    lines = []
    for profile in browsers.profiles():
        pairs = browsers.firefox_bookmarks(profile.folder / "places.sqlite") if profile.family == "firefox" \
            else browsers.chromium_bookmarks(profile.folder / "Bookmarks")
        for title, url in pairs:
            if all(word in f"{title} {url}".lower() for word in wanted):
                lines.append(f"{title or url}  {url}  [{profile.browser}]")
    return "\n".join(list(dict.fromkeys(lines))[:MAX_LISTED]) or "No bookmark matches."


def file_origin(arguments: dict[str, Any]) -> str:
    path = os.path.abspath(os.path.expanduser(str(arguments.get("path") or "")))
    if not os.path.exists(path):
        raise ToolFailure(f"{path} does not exist")
    found = []
    for name in ("user.xdg.origin.url", "user.xdg.referrer.url"):
        try:
            found.append(f"{name.split('.')[-2]}: {os.getxattr(path, name).decode('utf-8', 'replace')}")
        except OSError:
            continue
    return "\n".join(found) or "The file does not record where it came from."


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)


def page_text(markup: str) -> tuple[str, str]:
    """``(title, readable text)`` of an HTML page."""
    extractor = _TextExtractor()
    extractor.feed(markup)
    text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape("".join(extractor.parts)))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return extractor.title.strip(), text


def _public_host(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ToolFailure("only http and https web addresses can be read")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as error:
        raise ToolFailure(f"{parsed.hostname} could not be found") from error
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ToolFailure(f"{parsed.hostname} is on this computer or the local network; only public pages are read")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another public address."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        _public_host(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def read_web_page(arguments: dict[str, Any]) -> str:
    url = str(arguments.get("url") or "").strip()
    _public_host(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Happy Bot)"})
    try:
        with urllib.request.build_opener(_PublicRedirects).open(request, timeout=20) as response:
            kind = response.headers.get_content_type()
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except OSError as error:
        raise ToolFailure(f"the page could not be fetched: {error}") from error
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ToolFailure("the page is too large to read here")
    if kind == "application/pdf" or data[:5] == b"%PDF-":
        if not shutil.which("pdftotext"):
            raise ToolFailure("the address is a PDF and pdftotext is not installed")
        text = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        title = url
    elif kind.startswith("text/html") or kind == "application/xhtml+xml":
        title, text = page_text(data.decode("utf-8", "replace"))
    elif kind.startswith("text/") or kind.endswith("json"):
        title, text = url, data.decode("utf-8", "replace")
    else:
        raise ToolFailure(f"the address is a {kind} file, not a page that can be read as text")
    cut = "" if len(text) <= MAX_PAGE_CHARS else f"\n[cut: {len(text) - MAX_PAGE_CHARS} more characters]"
    return f"{title}\n{url}\n\n{text[:MAX_PAGE_CHARS]}{cut}"


def finding_tools(local_only: bool = False) -> list[Tool]:
    text = {"type": "string"}
    tools = [
        Tool("recent_files", "Files the user opened or saved recently, newest first ('where did I save…').",
             object_schema({"contains": text}), RISK_READ, recent_files, summarize=lambda a: "Check recently used files"),
        Tool("browser_bookmarks", "The user's browser bookmarks (Chromium-family and Firefox) matching some words.",
             object_schema({"contains": text}), RISK_READ, browser_bookmarks, summarize=lambda a: "Look through bookmarks"),
        Tool("file_origin", "Where a downloaded file came from (the web address it was downloaded from).",
             object_schema({"path": text}, ["path"]), RISK_READ, file_origin,
             summarize=lambda a: f"Check where {a.get('path', '?')} came from"),
    ]
    if not local_only:
        tools.append(Tool("read_web_page", "Fetch a public web page or PDF by its address and read its text, to "
                          "summarise it or answer from it.", object_schema({"url": text}, ["url"]), RISK_READ,
                          read_web_page, summarize=lambda a: f"Read {a.get('url', '?')}"))
    return tools

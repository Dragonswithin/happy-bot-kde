"""Reading offline Wikipedia for the popup's Wikipedia finder: finding articles and showing one cleanly.

The reader is the tool server named in the ``wikipedia`` settings (openzim-mcp, set up by
``wikipedia_setup``), asked through the daemon's ``McpManager`` like any tool server. Both calls
name the archive explicitly (``current_archive``: the newest build of the kept ``book`` in the
folder, else the newest archive there), so a folder holding several archives still works.

``search(text)`` gives the finder its matches: an article whose title is exactly what was typed
first (``zim_search`` mode "title", typo-tolerant), then the full-text search's best matches
(mode "fulltext", ranked by relevance, which on the maintainer's English archive found "Python
(programming language)" for "python"; prefix suggestions ranked "PYTH" and "PYTHIA" first and are
not used), without category and list-of pages' duplicates. Each hit is ``{"title", "location"
(the article's path in the archive), "snippet", "kind": "article", "source": "wikipedia"}``.

``article(path)`` gives the article as light Markdown for Happy Bot's own view (headings,
paragraphs, lists, bold and italic, links): the article's HTML is fetched raw (``zim_get`` with
``binary``, a tenth of a second) and cleaned here (``ArticleCleaner``), dropping what reads badly as
text: infoboxes and other tables, navigation boxes, reference marks and lists, pictures, edit
links and pronunciation buttons. The reader's own text conversion keeps the infobox as a heap of
table cells at the top, which is why it is not used. A link to another article keeps that
article's path as its target (no address scheme), so the view can open it in place; outside links
keep their web address. Paths arrive percent-encoded from links ("Windsor%2C_Ontario") and are
decoded, since the archive names entries as written. Very long articles are cut at
``MAX_ARTICLE_CHARS`` with a note.

Calls block for about a second (``TIMEOUT`` at most) and raise ``ReaderError`` with a plain message.
"""

from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote

from .mcp_client import McpError, McpManager
from .wikipedia_library import archives

TIMEOUT = 30.0
MAX_ARTICLE_CHARS = 120_000
SKIP_TAGS = {"script", "style", "table", "figure", "audio", "video", "math", "noscript", "link", "meta", "title"}
# An element is dropped when one of its classes is one of these, or starts with one followed by "-"
# ("navbox-inner"); matching parts of names would drop the page itself ("vector-toc-available").
SKIP_CLASSES = ("infobox", "navbox", "sidebar", "metadata", "mw-editsection", "reference", "references", "reflist",
                "mw-references", "noprint", "thumb", "hatnote", "ext-phonos", "shortdescription",
                "navigation-not-searchable", "toc", "gallery", "mw-empty-elt", "mbox", "ambox", "portal",
                "catlinks", "mw-normal-catlinks", "mw-hidden-catlinks")
VOID_TAGS = {"br", "img", "hr", "wbr", "input", "meta", "link", "source", "col", "area", "base", "embed", "track"}
HEADINGS = {"h2": "## ", "h3": "### ", "h4": "#### ", "h5": "#### ", "h6": "#### "}


class ReaderError(RuntimeError):
    """Offline Wikipedia could not answer; the message says why."""


class ArticleCleaner(HTMLParser):
    """An article's HTML as light Markdown (see the module docstring); feed, then ``markdown()``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip_depth = 0       # >0 while inside something dropped
        self.stack: list[str] = []  # open tags, to know when a dropped element ends
        self.link: list[str] = []   # targets of the open links ("" for a link shown as plain text)
        self.in_body = False

    def _skipped(self, tag: str, attributes: dict[str, str]) -> bool:
        classes = (attributes.get("class") or "").split()
        return (tag in SKIP_TAGS or attributes.get("role") == "note"
                or any(token == name or token.startswith(name + "-") for token in classes for name in SKIP_CLASSES))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "body":
            self.in_body = True
        if tag in VOID_TAGS:
            if tag == "br" and not self.skip_depth:
                self.out.append("\n")
            return
        self.stack.append(tag)
        if self.skip_depth or self._skipped(tag, attributes):
            self.skip_depth += 1
            return
        if tag == "h1":
            self.skip_depth += 1  # the title is shown by the view itself
        elif tag in HEADINGS:
            self.out.append("\n\n" + HEADINGS[tag])
        elif tag in ("p", "div", "section", "blockquote", "dl"):
            self.out.append("\n\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "dt":
            self.out.append("\n\n**")
        elif tag in ("b", "strong"):
            self.out.append("**")
        elif tag in ("i", "em"):
            self.out.append("*")  # Qt draws _text_ underlined, which reads as a link
        elif tag == "a":
            target = _link_target(attributes.get("href", ""))
            self.link.append(target)
            if target:
                self.out.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS or tag not in self.stack:
            return
        while self.stack:  # close anything left open inside it, as browsers do
            open_tag = self.stack.pop()
            if self.skip_depth:
                self.skip_depth -= 1
                if open_tag == tag:
                    return
                continue
            self._close(open_tag)
            if open_tag == tag:
                return

    def _close(self, tag: str) -> None:
        if tag in ("b", "strong"):
            self.out.append("**")
        elif tag in ("i", "em"):
            self.out.append("*")
        elif tag == "dt":
            self.out.append("**")
        elif tag == "a" and self.link:
            target = self.link.pop()
            if target:
                self.out.append(f"]({target})")
        elif tag in HEADINGS or tag in ("p", "ul", "ol", "dl"):
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.in_body:
            return
        text = re.sub(r"\s+", " ", data)
        if self.link and self.link[-1]:
            text = text.replace("[", "(").replace("]", ")")
        self.out.append(text)

    def markdown(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"\[\s*\]\([^)]*\)", "", text)               # links around nothing
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"(?m)^- *$\n?", "", text)                    # empty list items
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(?m)^#{2,4} *\n", "", text)                 # headings left empty
        return text.strip()


def _link_target(href: str) -> str:
    """Another article's path, a web address, or "" for a link shown as plain text (notes, anchors)."""
    if not href or href.startswith("#"):
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if ":" in href.split("/")[0] or href.startswith("/"):
        return ""
    path = href.removeprefix("./").split("#")[0].split("?")[0]
    return path.replace(")", "%29").replace("(", "%28").replace(" ", "_")


def clean_article(html: str) -> tuple[str, bool]:
    """``(markdown, cut)`` for an article's HTML; ``cut`` when it was longer than ``MAX_ARTICLE_CHARS``."""
    cleaner = ArticleCleaner()
    cleaner.feed(html)
    cleaner.close()
    text = cleaner.markdown()
    if len(text) <= MAX_ARTICLE_CHARS:
        return text, False
    cut = text.rfind("\n\n", 0, MAX_ARTICLE_CHARS)
    return text[:cut if cut > 0 else MAX_ARTICLE_CHARS].rstrip(), True


def current_archive(settings: dict[str, Any]) -> str:
    """The archive the finder reads: the newest build of the kept book, else the newest archive in the folder."""
    wikipedia = settings.get("wikipedia") or {}
    found = archives(wikipedia.get("folder") or "")
    kept = [archive for archive in found if archive.book == wikipedia.get("book")]
    chosen = (kept or sorted(found, key=lambda archive: archive.build, reverse=True) or [None])[0]
    if chosen is None:
        raise ReaderError("Offline Wikipedia is not set up, or its archive is no longer there.")
    return chosen.path


def _call(manager: McpManager, settings: dict[str, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = (settings.get("wikipedia") or {}).get("server")
    if not server:
        raise ReaderError("Offline Wikipedia is not set up.")
    try:
        result = manager.call_tool(server, tool, arguments, TIMEOUT)
    except McpError as error:
        raise ReaderError(f"Offline Wikipedia did not answer ({error})") from error
    try:
        data = result.structured if isinstance(result.structured, dict) else json.loads(result.text)
    except ValueError as error:
        raise ReaderError(f"Offline Wikipedia gave an answer Happy Bot cannot read: {result.text[:200]}") from error
    if result.is_error or data.get("error"):
        raise ReaderError(str(data.get("message") or data.get("error") or result.text[:200]))
    return data


def _plain(snippet: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", snippet or "")
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", text.replace("**", ""))  # Markdown emphasis
    return " ".join(text.split())[:200]


def search(manager: McpManager, settings: dict[str, Any], text: str, limit: int = 8) -> list[dict[str, str]]:
    """Articles for the typed text, best first (see the module docstring)."""
    archive = current_archive(settings)
    exact = _call(manager, settings, "zim_search", {"query": text, "mode": "title", "limit": 3,
                                                    "zim_file_path": archive})
    full = _call(manager, settings, "zim_search", {"query": text, "limit": limit + 4, "zim_file_path": archive})
    hits: dict[str, dict[str, str]] = {}
    wanted = text.strip().lower()
    for row in exact.get("results") or []:
        if str(row.get("title", "")).lower() == wanted:
            hits.setdefault(row["path"], {"title": row["title"], "location": row["path"], "snippet": "",
                                          "kind": "article", "source": "wikipedia"})
    for row in full.get("results") or []:
        title, path = str(row.get("title", "")), str(row.get("path", ""))
        if not path or title.startswith(("Category:", "Template:", "Portal:", "Wikipedia:", "File:")):
            continue
        if path in hits:
            hits[path]["snippet"] = _plain(row.get("snippet", ""))
            continue
        hits[path] = {"title": title, "location": path, "snippet": _plain(row.get("snippet", "")),
                      "kind": "article", "source": "wikipedia"}
    return list(hits.values())[:limit]


def article(manager: McpManager, settings: dict[str, Any], path: str) -> dict[str, Any]:
    """``{"title", "path", "text" (light Markdown), "cut"}`` for the article at ``path``."""
    path = unquote(path)  # the archive names entries as written ("Windsor,_Ontario"), links encode them
    if not path or len(path) > 500:
        raise ReaderError("That is not an article.")
    data = _call(manager, settings, "zim_get", {"zim_file_path": current_archive(settings), "entry_path": path,
                                                "binary": True, "max_content_length": 8 * 1024 * 1024})
    if not str(data.get("mime_type", "")).startswith("text/html"):
        raise ReaderError("That page is not an article.")
    try:
        html = base64.b64decode(str(data.get("data") or "")).decode("utf-8", "replace")
    except ValueError as error:
        raise ReaderError("The article could not be read.") from error
    text, cut = clean_article(html)
    return {"title": str(data.get("title") or path.replace("_", " ")), "path": str(data.get("path") or path),
            "text": text, "cut": cut}

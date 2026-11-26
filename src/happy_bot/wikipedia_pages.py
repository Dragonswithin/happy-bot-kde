"""A loopback web server for offline Wikipedia's own pages, so Happy Bot can show them as Wikipedia looks.

Happy Bot shows an article in a web view (ArticleWebView.qml): the archive's page exactly as Kiwix
packed it, with its pictures, infobox and Wikipedia's styles. A web view loads pages over HTTP and
cannot send the daemon's bearer token, and the daemon's API refuses browser requests on purpose, so
the pages come from this separate, read-only server instead of the daemon's API:

- it listens on ``127.0.0.1`` on a free port, started on first use (``url``) and kept for the
  daemon's life;
- every address starts with a random token (``/<token>/<entry path>``) that only the daemon hands
  out (``GET /wikipedia/page``, ``wikipedia_routes``), so another local program cannot guess its way
  in, and a request whose ``Host`` is not this address is refused;
- the rest of the path is the archive entry, percent-decoded once (the archive stores names as
  written, so a picture named ``Renaissance_Center%2C…`` is asked for as ``%252C``); pages link to
  their style sheets and pictures with relative paths (``./_mw_/…css``, ``./_assets_/…``), which
  therefore resolve to the same server;
- only ``GET`` and ``HEAD``; each answer is one archive entry fetched through ``fetch`` (the reader,
  ``wikipedia_reader.entry``), with its own type and a ``Content-Security-Policy`` allowing nothing
  from outside this server, so reading an article never contacts the internet (Wikipedia pages
  otherwise load map tiles and the like from Wikimedia's servers). A page also gets ``FIT_STYLE``,
  which keeps it within the view's width (``fit``).

Requests are served on threads of their own; ``fetch`` may block for a moment. ``close`` stops the
server.
"""

from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import quote, unquote, urlsplit

HOST = "127.0.0.1"
# Added to every page: Happy Bot's view is narrower than a browser, and wide tables and fixed-size
# pictures made the whole page scroll sideways. Pictures shrink to fit; wide tables scroll on their own.
FIT_STYLE = (b'<style id="happy-bot-fit">html,body{max-width:100%;overflow-x:hidden}'
             b"img{max-width:100%;height:auto}table{max-width:100%}"
             b".wikitable{display:block;overflow-x:auto}</style>")
POLICY = ("default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; img-src 'self' data: blob:; "
          "connect-src 'self'; frame-src 'none'; form-action 'none'")


class PageServer:
    """Serves archive entries at ``http://127.0.0.1:<port>/<token>/<entry>`` (see the module docstring)."""

    def __init__(self, fetch: Callable[[str], tuple[bytes, str]]) -> None:
        self.fetch = fetch
        self.token = secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()

    def _start(self) -> ThreadingHTTPServer:
        pages = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - quiet, like the daemon
                return

            def _answer(self, body: bool) -> None:
                server_host = f"{HOST}:{self.server.server_address[1]}"
                prefix = f"/{pages.token}/"
                path = urlsplit(self.path).path
                if self.headers.get("Host") != server_host or not path.startswith(prefix):
                    self.send_error(404)
                    return
                entry = unquote(path[len(prefix):])
                try:
                    data, mime = pages.fetch(entry)
                except Exception:  # noqa: BLE001 - anything that cannot be read is simply not there
                    self.send_error(404)
                    return
                data = self._fit(data, mime)
                self.send_response(200)
                self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") and
                                                         "charset" not in mime else ""))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Security-Policy", POLICY)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                if body:
                    self.wfile.write(data)

            def _fit(self, data: bytes, mime: str) -> bytes:
                return pages.fit(data) if mime.startswith("text/html") else data

            def do_GET(self) -> None:  # noqa: N802 - the standard library's name
                self._answer(True)

            def do_HEAD(self) -> None:  # noqa: N802
                self._answer(False)

        server = ThreadingHTTPServer((HOST, 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="wikipedia-pages", daemon=True).start()
        return server

    @staticmethod
    def fit(page: bytes) -> bytes:
        """``page`` with ``FIT_STYLE`` added at the end of its head (or its start, when it has none)."""
        at = page.find(b"</head>")
        return page[:at] + FIT_STYLE + page[at:] if at >= 0 else FIT_STYLE + page

    def url(self, entry: str) -> str:
        """The address of ``entry``'s page, starting the server if needed."""
        with self._lock:
            if self._server is None:
                self._server = self._start()
            port = self._server.server_address[1]
        return f"http://{HOST}:{port}/{self.token}/{quote(entry, safe='/(),_-.~')}"

    def close(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

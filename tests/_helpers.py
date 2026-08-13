"""
Shared test helpers.

The interesting tests drive a *real* Chromium browser against fixture pages
served on ``localhost`` (localhost bypasses any egress proxy, so these run even
in a network-restricted sandbox). This module provides:

* :func:`fixtures_dir` -- path to ``examples/fixtures``,
* :func:`serve`        -- start a throwaway static server on a random port,
* :func:`browser_available` -- whether Chromium can actually launch here, so
  browser tests can skip cleanly instead of failing on machines without it.
"""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import sys
import threading
from unittest import SkipTest  # recognised as a skip by both pytest and our runner

# Make the package importable when tests are run standalone (python tests/x.py).
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def fixtures_dir() -> str:
    return os.path.join(_REPO, "examples", "fixtures")


class Server:
    """A running static file server; use as a context manager."""

    def __init__(self, directory: str):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
        handler.log_message = lambda *a, **k: None  # keep test output clean
        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "Server":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def serve(directory: str | None = None) -> Server:
    return Server(directory or fixtures_dir())


_BROWSER_OK: bool | None = None


def browser_available() -> bool:
    """True if a headless Chromium can be launched in this environment.

    Cached so the (relatively slow) probe runs at most once per process.
    """
    global _BROWSER_OK
    if _BROWSER_OK is not None:
        return _BROWSER_OK
    try:
        from google_agent.browser import Browser

        with Browser(headless=True, proxy="") as b:
            b  # launched successfully
        _BROWSER_OK = True
    except Exception:
        _BROWSER_OK = False
    return _BROWSER_OK


def requires_browser() -> None:
    """Skip the current test if Chromium cannot launch here."""
    if not browser_available():
        raise SkipTest("Chromium could not be launched in this environment")

"""
browser.py -- the eyes and hands.

A thin wrapper over Playwright's synchronous Chromium API that does exactly
three things the agent needs:

* **open** a URL,
* **read** every clickable element on the page into plain data, and
* **click** one of them (by the index the reader chose).

Keeping this layer dumb means the interesting logic lives in :mod:`reader`, and
means the reader can be tested without a browser at all.
"""

from __future__ import annotations

import glob
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from .reader import Element

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception:  # pragma: no cover - import guard for helpful message
    sync_playwright = None  # type: ignore
    PWTimeout = Exception  # type: ignore


# JavaScript run in the page to collect clickable elements. It returns a compact
# list of {index, text, role, href, context} objects. Elements that are hidden,
# empty, or off-screen-zero-size are skipped so the reader isn't fed noise.
_COLLECT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll('a[href], button, [role=button], input[type=submit], input[type=button]');
  let i = 0;
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;

    const text = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    const aria = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const href = el.getAttribute('href') || '';
    if (!text && !aria && !title) continue;

    const key = (text || aria) + '|' + href;
    if (seen.has(key)) continue;
    seen.add(key);

    let role = 'other';
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') role = 'link';
    else if (tag === 'button' || el.getAttribute('role') === 'button') role = 'button';
    else if (tag === 'input') role = 'input';

    out.push({
      index: i++,
      text: text.slice(0, 200),
      role: role,
      href: href.startsWith('http') ? href : (href ? new URL(href, location.href).href : ''),
      context: [aria, title].filter(Boolean).join(' ').slice(0, 200),
    });
  }
  return out;
}
"""


@dataclass
class Clickable:
    """A clickable element as seen by the browser, paired with its DOM handle
    index so the browser can later click the exact same node."""

    element: Element


class Browser:
    """Synchronous Chromium controller.

    Use as a context manager::

        with Browser(headless=True) as b:
            b.search("weather in tokyo")
            elements = b.read()
            b.click(elements[0])
            print(b.text())
    """

    def __init__(
        self,
        headless: bool = True,
        engine: str = "google",
        slow_mo: int = 0,
        proxy: Optional[str] = None,
    ):
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Run:  pip install playwright  "
                "(the Chromium browser itself is already present in this environment)."
            )
        self.headless = headless
        self.engine = engine
        self.slow_mo = slow_mo
        # Honour an outbound HTTPS proxy if one is configured (managed/cloud
        # environments route all egress through one).
        #   proxy=None  -> auto-detect from HTTPS_PROXY / https_proxy env vars
        #   proxy=""    -> explicitly no proxy (e.g. hitting localhost fixtures)
        #   proxy="..." -> use exactly this proxy
        if proxy is None:
            self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
        else:
            self.proxy = proxy
        self._pw = None
        self._browser = None
        self.page = None

    # -- lifecycle ---------------------------------------------------------- #

    @staticmethod
    def _find_chromium() -> Optional[str]:
        """Locate a pre-installed Chromium binary.

        Managed/offline environments often ship a Chromium build whose version
        does not match the pip-installed Playwright's expected path, which makes
        the normal launch fail with "Executable doesn't exist". When that
        happens we point Playwright at whatever ``chrome``/``headless_shell``
        actually exists under ``PLAYWRIGHT_BROWSERS_PATH`` instead of trying to
        download one (downloads are usually blocked here anyway).
        """
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
        patterns = [
            os.path.join(root, "chromium-*", "chrome-linux", "chrome"),
            os.path.join(root, "chromium_headless_shell-*", "chrome-linux", "headless_shell"),
        ]
        for pat in patterns:
            hits = sorted(glob.glob(pat))
            if hits:
                return hits[-1]  # newest build present
        return None

    def __enter__(self) -> "Browser":
        self._pw = sync_playwright().start()
        launch_kwargs: dict = {"headless": self.headless, "slow_mo": self.slow_mo}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
        try:
            self._browser = self._pw.chromium.launch(**launch_kwargs)
        except Exception:
            exe = self._find_chromium()
            if not exe:
                raise
            self._browser = self._pw.chromium.launch(executable_path=exe, **launch_kwargs)
        ctx = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="en-US",
            # The environment's proxy terminates TLS with its own CA; accept it
            # so navigation isn't blocked by cert errors. (No effect when there
            # is no intercepting proxy.)
            ignore_https_errors=bool(self.proxy),
        )
        self.page = ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._browser = None
            self._pw = None
            self.page = None

    # -- navigation --------------------------------------------------------- #

    def goto(self, url: str, wait_ms: int = 1500) -> None:
        assert self.page is not None
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._settle(wait_ms)

    def search(self, query: str, wait_ms: int = 1500) -> None:
        """Run a search on the configured engine and land on the results page."""
        url = self._search_url(query)
        self.goto(url, wait_ms=wait_ms)

    def _search_url(self, query: str) -> str:
        q = quote_plus(query)
        if self.engine == "duckduckgo":
            return f"https://duckduckgo.com/html/?q={q}"
        if self.engine == "bing":
            return f"https://www.bing.com/search?q={q}"
        return f"https://www.google.com/search?q={q}&hl=en"

    def _settle(self, wait_ms: int) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeout:
            pass
        if wait_ms:
            time.sleep(wait_ms / 1000.0)

    # -- reading ------------------------------------------------------------ #

    def read(self) -> list[Element]:
        """Return every clickable element on the current page as data."""
        assert self.page is not None
        raw = self.page.evaluate(_COLLECT_JS)
        return [
            Element(
                index=r["index"],
                text=r["text"],
                role=r["role"],
                href=r["href"],
                context=r["context"],
            )
            for r in raw
        ]

    def text(self, max_chars: int = 4000) -> str:
        """Visible text of the current page (for cross-referencing / answers)."""
        assert self.page is not None
        body = self.page.evaluate("() => document.body ? document.body.innerText : ''")
        body = " ".join(body.split())
        return body[:max_chars]

    def title(self) -> str:
        assert self.page is not None
        return self.page.title()

    def url(self) -> str:
        assert self.page is not None
        return self.page.url

    # -- acting ------------------------------------------------------------- #

    def click(self, element: Element, wait_ms: int = 1500) -> bool:
        """Click the element the reader picked.

        Strategy: prefer navigating a link's ``href`` directly (robust against
        overlays / new tabs), and fall back to a real DOM click for buttons and
        JS-driven links.
        """
        assert self.page is not None
        if element.role == "link" and element.href.startswith("http"):
            self.goto(element.href, wait_ms=wait_ms)
            return True

        # Re-locate the node by matching text among current clickables and click it.
        selectors = ["a[href]", "button", "[role=button]", "input[type=submit]", "input[type=button]"]
        needle = (element.text or element.context).strip()
        for sel in selectors:
            loc = self.page.locator(sel, has_text=needle) if needle else None
            try:
                if loc is not None and loc.count() > 0:
                    loc.first.click(timeout=5000)
                    self._settle(wait_ms)
                    return True
            except Exception:
                continue
        return False

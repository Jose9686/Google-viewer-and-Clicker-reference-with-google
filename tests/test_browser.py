"""
Browser layer tests.

Two kinds:
* pure unit tests for URL construction (no browser needed), and
* integration tests that launch real Chromium against localhost fixtures and
  check read / content_text / click actually work. Those skip cleanly if a
  browser can't be launched here.
"""

from _helpers import serve, requires_browser  # noqa: E402  (adds repo to sys.path)

from google_agent.browser import Browser


# --------------------------------------------------------------------------- #
# Unit: no browser required
# --------------------------------------------------------------------------- #

def test_search_url_per_engine():
    assert Browser(engine="google")._search_url("a b") == "https://www.google.com/search?q=a+b&hl=en"
    assert Browser(engine="bing")._search_url("a b") == "https://www.bing.com/search?q=a+b"
    assert Browser(engine="duckduckgo")._search_url("a b") == "https://duckduckgo.com/html/?q=a+b"


def test_proxy_none_autodetects_but_empty_disables(monkeypatch=None):
    # Explicit "" -> no proxy, regardless of env.
    import os
    os.environ["HTTPS_PROXY"] = "http://example:1"
    try:
        assert Browser(proxy="").proxy == ""
        assert Browser(proxy=None).proxy == "http://example:1"
        assert Browser(proxy="http://p:2").proxy == "http://p:2"
    finally:
        os.environ.pop("HTTPS_PROXY", None)


# --------------------------------------------------------------------------- #
# Integration: real Chromium on localhost
# --------------------------------------------------------------------------- #

def test_read_lists_clickable_elements():
    requires_browser()
    with serve() as srv, Browser(headless=True, proxy="") as b:
        b.goto(f"{srv.base}/search_task.html")
        elements = b.read()
        texts = [e.text for e in elements]
        assert "France country profile - Wikipedia" in texts
        assert "Sign in" in texts
        # hrefs are absolutised, roles are classified.
        profile = next(e for e in elements if e.text.startswith("France country"))
        assert profile.role == "link"
        assert profile.href.startswith("http") and profile.href.endswith("/france/profile.html")
        settings = next(e for e in elements if e.text == "Settings")
        assert settings.role == "button"


def test_content_text_strips_links_but_text_keeps_them():
    requires_browser()
    with serve() as srv, Browser(headless=True, proxy="") as b:
        b.goto(f"{srv.base}/france/profile.html")
        prose = b.content_text()
        full = b.text()
        # Prose keeps the paragraph...
        assert "France is a country in Western Europe" in prose
        # ...but drops link labels, while full text keeps them.
        assert "Geography of France" not in prose
        assert "Geography of France" in full


def test_click_follows_link():
    requires_browser()
    with serve() as srv, Browser(headless=True, proxy="") as b:
        b.goto(f"{srv.base}/search_task.html")
        target = next(e for e in b.read() if e.text.startswith("France country"))
        assert b.click(target)
        assert b.url().endswith("/france/profile.html")
        assert "France" in b.title()


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())

"""
Agent tests -- the pure logic that doesn't need a browser.

Covers result-link ranking (dedupe by domain, skip engine/relative links) and
answer synthesis / confidence, using plain data.
"""

from _helpers import serve  # noqa: F401,E402  (adds repo to sys.path)

from google_agent.agent import Agent, Source
from google_agent.reader import Element


def _agent():
    return Agent()


def test_domain_and_engine_detection():
    a = _agent()
    assert a._domain("https://en.wikipedia.org/wiki/Paris") == "en.wikipedia.org"
    assert a._domain("notaurl") == ""
    assert a._is_engine_domain("www.google.com")
    assert a._is_engine_domain("duckduckgo.com")
    assert not a._is_engine_domain("en.wikipedia.org")


def test_rank_result_links_dedupes_and_filters():
    a = _agent()
    els = [
        Element(0, "Sign in", role="link", href="https://accounts.google.com/signin"),
        Element(1, "Paris - Wikipedia", role="link", href="https://en.wikipedia.org/wiki/Paris",
                context="capital of France"),
        Element(2, "Paris travel - Wikipedia", role="link", href="https://en.wikipedia.org/wiki/Paris_travel",
                context="France"),
        Element(3, "Relative link", role="link", href="/local/page"),
        Element(4, "Quora answer", role="link", href="https://quora.com/france", context="capital of France"),
    ]
    ranked = a._rank_result_links("capital of France", els)
    domains = [a._domain(el.href) for el, _ in ranked]
    # google search-engine domain filtered out, relative link filtered out,
    # wikipedia included only once (dedupe by domain).
    assert "accounts.google.com" not in domains
    assert domains.count("en.wikipedia.org") == 1
    assert "quora.com" in domains


def test_synthesise_reports_no_sources():
    a = _agent()
    assert "no sources" in a._synthesise("q", []).lower()


def test_synthesise_confidence_scales_with_agreement():
    a = _agent()
    one = [Source("u1", "T1", "France capital is Paris", relevance=2.0)]
    two = [
        Source("u1", "T1", "France capital is Paris", relevance=2.0),
        Source("u2", "T2", "The capital of France is Paris", relevance=1.8),
    ]
    assert "confidence: low" in a._synthesise("capital of France", one)
    assert "confidence: high" in a._synthesise("capital of France", two)


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())

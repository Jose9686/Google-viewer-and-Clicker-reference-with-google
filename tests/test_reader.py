"""
Offline tests for the reader -- no browser, no network.

Run:  python -m pytest -q      (or)      python tests/test_reader.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_agent.reader import Element, HeuristicReader, LLMReader


def _results_page():
    """A fake Google-results-page's worth of clickable elements."""
    return [
        Element(0, "Sign in", role="link", href="https://accounts.google.com/signin"),
        Element(1, "Settings", role="button"),
        Element(2, "Paris - Wikipedia", role="link",
                href="https://en.wikipedia.org/wiki/Paris",
                context="Paris is the capital and most populous city of France"),
        Element(3, "France travel deals - book now", role="link",
                href="https://ads.example.com/france", context="sponsored"),
        Element(4, "What is the capital of France? - Quora", role="link",
                href="https://quora.com/capital-of-france"),
    ]


def test_selects_relevant_result_over_chrome():
    reader = HeuristicReader()
    choice = reader.select("capital of France", _results_page())
    assert choice.should_click
    # Should pick Wikipedia or Quora (real answers), never "Sign in"/"Settings".
    assert choice.element.index in (2, 4), choice.reason
    assert "capital" in choice.element.searchable.lower() or "france" in choice.element.searchable.lower()


def test_phrase_boost_prefers_exact_match():
    reader = HeuristicReader()
    choice = reader.select("capital of France", _results_page())
    # Wikipedia's context contains the exact phrase "capital and most populous".
    top_indices = [el.index for el, _ in choice.ranked[:2]]
    assert 2 in top_indices


def test_declines_when_nothing_relevant():
    reader = HeuristicReader(threshold=0.5)
    els = [
        Element(0, "Sign in", role="link", href="https://accounts.google.com/signin"),
        Element(1, "Cookie preferences", role="button"),
    ]
    choice = reader.select("photosynthesis in deep sea vents", els)
    assert not choice.should_click, choice.reason


def test_negative_markers_penalise_ads():
    reader = HeuristicReader()
    score_ad = reader.relevance("france", "France travel deals sponsored advertisement")
    score_real = reader.relevance("france", "France country in Europe capital Paris")
    assert score_real > score_ad


def test_llm_reader_falls_back_on_bad_output():
    # A "model" that returns junk -> should fall back to heuristic, not crash.
    reader = LLMReader(complete=lambda prompt: "banana")
    choice = reader.select("capital of France", _results_page())
    assert choice.should_click
    assert "fell back" in choice.reason


def test_llm_reader_uses_valid_index():
    reader = LLMReader(complete=lambda prompt: "I choose [2]")
    choice = reader.select("capital of France", _results_page())
    assert choice.element.index == 2
    assert "LLM" in choice.reason


def test_searchable_excludes_raw_href():
    # A URL's directory path must not become scorable text.
    el = Element(0, "Edit this page", role="link", href="https://x.org/france/edit.html")
    assert "france" not in el.searchable.lower()
    assert "edit this page" in el.searchable.lower()


def test_href_path_does_not_pull_selection_off_task():
    # "Edit" link lives under /france/ but its text is irrelevant; the element
    # whose *text* matches the goal must win.
    reader = HeuristicReader()
    els = [
        Element(0, "Edit this page", role="link", href="https://x.org/france/edit.html"),
        Element(1, "France population statistics", role="link", href="https://x.org/p/1"),
    ]
    choice = reader.select("france population", els)
    assert choice.element.index == 1, choice.reason


def test_declines_when_only_offtopic_links_present():
    reader = HeuristicReader()
    els = [
        Element(0, "Edit this page", role="link", href="https://x.org/france/edit.html"),
        Element(1, "View history", role="link", href="https://x.org/france/hist.html"),
    ]
    choice = reader.select("france population", els)
    # Nothing matches "france population" by text -> low score, not a strong pick.
    assert choice.score < 0.30, choice.reason


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())

"""
google_agent
============

A small, self-contained agent that *reads a web page and decides what to click*.

Three moving parts:

* ``browser``  -- drives a real Chromium browser (via Playwright): open a page,
                  read every clickable element, click one.
* ``reader``   -- the "brain". Given a goal and the list of clickable elements,
                  it scores each one and selects the best. Ships with a fully
                  local, no-API-key scorer (:class:`HeuristicReader`) and a
                  pluggable interface so you can drop in a real LLM later.
* ``agent``    -- the loop that ties them together: search -> read -> select ->
                  click -> extract -> cross-reference -> answer.

Nothing here talks to a paid service or needs an API key out of the box: the
default "reader" runs entirely on your machine.
"""

from .reader import Reader, HeuristicReader, LLMReader, Element, Choice
from .browser import Browser, Clickable
from .agent import Agent, AgentResult

__all__ = [
    "Reader",
    "HeuristicReader",
    "LLMReader",
    "Element",
    "Choice",
    "Browser",
    "Clickable",
    "Agent",
    "AgentResult",
]

__version__ = "0.1.0"

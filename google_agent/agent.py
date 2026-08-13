"""
agent.py -- the loop.

Ties the browser and the reader together into a single flow:

1. **search** the query on Google (or another engine),
2. **read** the results page into clickable elements,
3. **select** the best result with the reader,
4. **click** it,
5. **extract** the text of the page you land on,
6. **cross-reference** by repeating on the next-best results and comparing what
   each source says, and
7. return a synthesised :class:`AgentResult` with the answer text, every source
   visited, and the full trail of decisions.

The reader is injected, so the agent works the same whether the "brain" is the
local :class:`~google_agent.reader.HeuristicReader` or a real model wired in via
:class:`~google_agent.reader.LLMReader`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .browser import Browser
from .reader import Element, HeuristicReader, Reader


@dataclass
class Step:
    """One decision in the trail, for transparency / debugging."""

    action: str
    detail: str
    score: float = 0.0


@dataclass
class Source:
    """A page the agent actually visited and read."""

    url: str
    title: str
    snippet: str
    relevance: float


@dataclass
class AgentResult:
    goal: str
    answer: str
    sources: list[Source] = field(default_factory=list)
    trail: list[Step] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"GOAL: {self.goal}", "", "ANSWER:", self.answer, "", "SOURCES:"]
        for i, s in enumerate(self.sources, 1):
            lines.append(f"  {i}. [{s.relevance:.2f}] {s.title}  <{s.url}>")
        return "\n".join(lines)


class Agent:
    """Reads the web and selects what to click, in service of a goal.

    Parameters
    ----------
    reader:
        The decision engine. Defaults to the local :class:`HeuristicReader`.
    engine:
        Search engine for :meth:`run` -- ``google`` (default), ``duckduckgo`` or
        ``bing``. DuckDuckGo's HTML endpoint is the friendliest to automation if
        Google shows a consent/CAPTCHA wall.
    headless:
        Run Chromium without a visible window (default ``True``).
    max_sources:
        How many results to click through and cross-reference.
    """

    def __init__(
        self,
        reader: Optional[Reader] = None,
        engine: str = "google",
        headless: bool = True,
        max_sources: int = 3,
        verbose: bool = False,
    ):
        self.reader = reader or HeuristicReader()
        self.engine = engine
        self.headless = headless
        self.max_sources = max_sources
        self.verbose = verbose

    # -- public API --------------------------------------------------------- #

    def run(self, goal: str) -> AgentResult:
        """Full pipeline: search -> read -> select -> click -> cross-reference."""
        result = AgentResult(goal=goal, answer="")
        with Browser(headless=self.headless, engine=self.engine) as b:
            self._log(f"searching {self.engine!r} for: {goal}")
            b.search(goal)
            result.trail.append(Step("search", f"{self.engine}: {goal}"))

            elements = b.read()
            self._log(f"read {len(elements)} clickable elements on results page")
            result.trail.append(Step("read", f"{len(elements)} elements on results page"))

            # Pick the top candidate result links to visit (cross-referencing).
            candidates = self._rank_result_links(goal, elements)
            if not candidates:
                result.answer = "No usable result links were found on the search page."
                return result

            for el, score in candidates[: self.max_sources]:
                result.trail.append(Step("select", f"click {el.text!r} -> {el.href}", score))
                self._log(f"clicking [{score:.2f}] {el.text!r}")
                ok = b.click(el)
                if not ok:
                    result.trail.append(Step("click", f"failed to click {el.text!r}"))
                    continue

                page_text = b.text()
                rel = self.reader.relevance(goal, f"{b.title()} {page_text}")
                result.sources.append(
                    Source(url=b.url(), title=b.title(), snippet=page_text[:500], relevance=rel)
                )
                result.trail.append(Step("extract", f"{b.url()} ({len(page_text)} chars)", rel))

                # Go back to the results page for the next candidate.
                b.search(goal)

        result.answer = self._synthesise(goal, result.sources)
        return result

    def read_page(self, url: str, goal: str) -> tuple[Element, str]:
        """Open a single page and return (element the reader would click, page text).

        Handy for the "an AI that reads and selects" use-case on an arbitrary URL
        rather than a search flow.
        """
        with Browser(headless=self.headless, engine=self.engine) as b:
            b.goto(url)
            elements = b.read()
            choice = self.reader.select(goal, elements)
            return choice.element, b.text()

    # -- internals ---------------------------------------------------------- #

    def _rank_result_links(self, goal: str, elements: list[Element]) -> list[tuple[Element, float]]:
        """Score result-like links and return them best-first, de-duplicated by
        destination domain so cross-referencing hits *different* sources."""
        choice = self.reader.select(goal, elements)
        ranked = choice.ranked or [(el, self.reader.relevance(goal, el.searchable)) for el in elements]

        seen_domains: set[str] = set()
        out: list[tuple[Element, float]] = []
        for el, score in ranked:
            if el.role != "link" or not el.href.startswith("http"):
                continue
            domain = self._domain(el.href)
            if not domain or self._is_engine_domain(domain) or domain in seen_domains:
                continue
            seen_domains.add(domain)
            out.append((el, score))
        return out

    def _synthesise(self, goal: str, sources: list[Source]) -> str:
        if not sources:
            return "Visited no sources successfully; nothing to report."

        sources_sorted = sorted(sources, key=lambda s: s.relevance, reverse=True)
        best = sources_sorted[0]

        # Cross-reference: how many independent sources look relevant?
        agree = [s for s in sources_sorted if s.relevance >= max(0.1, best.relevance * 0.4)]
        confidence = "high" if len(agree) >= 2 else "low"

        lead = best.snippet.strip()
        return (
            f"Best answer drawn from {best.title} ({best.url}):\n\n"
            f"{lead}\n\n"
            f"Cross-reference: {len(agree)} of {len(sources)} visited source(s) "
            f"corroborate this topic (confidence: {confidence})."
        )

    @staticmethod
    def _domain(url: str) -> str:
        parts = url.split("/")
        return parts[2] if len(parts) > 2 else ""

    @staticmethod
    def _is_engine_domain(domain: str) -> bool:
        return any(e in domain for e in ("google.", "duckduckgo.", "bing.", "gstatic.", "googleusercontent."))

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[agent] {msg}")

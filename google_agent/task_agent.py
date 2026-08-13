"""
task_agent.py -- give it a task, it just does it.

Where :class:`~google_agent.agent.Agent` runs one fixed shape (search -> click a
few results -> compare), :class:`TaskAgent` is an open-ended autonomous loop:

    perceive the page  ->  decide the single best thing to click toward the task
    ->  click it  ->  perceive again  ->  ... until the task is satisfied or it
    runs out of promising links / steps.

It drives itself. You don't approve each step; you hand it a goal and a place to
start (a URL, a search query, or nothing -- in which case it searches the task
text) and it navigates on its own, then hands back the most relevant page it
found plus a full transcript of what it did and why.

The decision at each step is made by a :class:`~google_agent.reader.Reader`, so
the exact same loop runs on the local no-API-key brain or, if you plug one in via
:class:`~google_agent.reader.LLMReader`, on a real model -- which navigates
multi-hop paths far better.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .browser import Browser
from .reader import Element, HeuristicReader, Reader


@dataclass
class Visit:
    """One page the agent perceived, with how relevant its *prose* was."""

    step: int
    url: str
    title: str
    relevance: float
    prose: str

    def __str__(self) -> str:
        return f"#{self.step} [{self.relevance:5.2f}] {self.title}  <{self.url}>"


@dataclass
class Act:
    """One decision the agent took."""

    step: int
    kind: str          # navigate | click | stop
    detail: str
    score: float = 0.0


@dataclass
class TaskRun:
    task: str
    answer: str = ""
    answer_url: str = ""
    visits: list[Visit] = field(default_factory=list)
    acts: list[Act] = field(default_factory=list)
    steps: int = 0
    stopped_because: str = ""

    def summary(self) -> str:
        lines = [f"TASK: {self.task}", ""]
        lines.append("WHAT IT DID:")
        for a in self.acts:
            score = f" ({a.score:.2f})" if a.kind == "click" else ""
            lines.append(f"  {a.step}. {a.kind}: {a.detail}{score}")
        lines.append(f"  -> stopped: {self.stopped_because}")
        lines.append("")
        lines.append(f"ANSWER  <{self.answer_url}>:")
        lines.append(self.answer or "(nothing found)")
        return "\n".join(lines)


class TaskAgent:
    """An autonomous, goal-driven web navigator.

    Parameters
    ----------
    reader:
        Decision engine (defaults to the local :class:`HeuristicReader`).
    engine:
        Search engine used when no explicit start URL is given.
    headless / proxy / max_steps:
        Browser + loop controls. ``max_steps`` bounds how many pages it will
        perceive before giving up (a hard stop so it can never run forever).
    click_threshold:
        Minimum reader score for a link to be worth clicking. When the best
        remaining link scores below this, the agent decides it has arrived and
        stops. Raise it to make the agent pickier / stop sooner.
    """

    def __init__(
        self,
        reader: Optional[Reader] = None,
        engine: str = "google",
        headless: bool = True,
        max_steps: int = 8,
        click_threshold: float = 0.30,
        proxy: Optional[str] = None,
        verbose: bool = False,
    ):
        self.reader = reader or HeuristicReader()
        self.engine = engine
        self.headless = headless
        self.max_steps = max_steps
        self.click_threshold = click_threshold
        self.proxy = proxy
        self.verbose = verbose

    def do(
        self,
        task: str,
        start_url: Optional[str] = None,
        start_query: Optional[str] = None,
    ) -> TaskRun:
        """Run the task to completion and return a :class:`TaskRun`."""
        run = TaskRun(task=task)
        visited: set[str] = set()

        with Browser(headless=self.headless, engine=self.engine, proxy=self.proxy) as b:
            # -- where to begin ------------------------------------------- #
            if start_url:
                b.goto(start_url)
                run.acts.append(Act(0, "navigate", f"start at {start_url}"))
            elif start_query is not None:
                b.search(start_query or task)
                run.acts.append(Act(0, "navigate", f"search {self.engine}: {start_query or task}"))
            else:
                b.search(task)
                run.acts.append(Act(0, "navigate", f"search {self.engine}: {task}"))

            # -- perceive / decide / act loop ----------------------------- #
            for step in range(1, self.max_steps + 1):
                run.steps = step
                url = b.url()
                visited.add(self._key(url))

                prose = b.content_text()
                rel = self.reader.relevance(task, f"{b.title()} {prose}")
                run.visits.append(Visit(step, url, b.title(), rel, prose[:600]))
                self._log(f"step {step}: at {url}  (relevance {rel:.2f})")

                # DECIDE: best unvisited link to click toward the task.
                elements = b.read()
                candidates = [
                    e for e in elements
                    if e.role in ("link", "button")
                    and not (e.href.startswith("http") and self._key(e.href) in visited)
                    and not self._is_search_engine(e.href)
                ]
                choice = self.reader.select(task, candidates)

                if not choice.should_click or choice.score < self.click_threshold:
                    run.acts.append(Act(step, "stop", "no link worth clicking toward the task"))
                    run.stopped_because = (
                        f"arrived -- best remaining link scored "
                        f"{(choice.score if choice.element else 0):.2f} < {self.click_threshold}"
                    )
                    break

                el = choice.element
                if el.href.startswith("http"):
                    visited.add(self._key(el.href))
                run.acts.append(Act(step, "click", f"{el.text!r} -> {el.href or '(js)'}", choice.score))
                self._log(f"step {step}: click {el.text!r} (score {choice.score:.2f})")

                if not b.click(el):
                    run.acts.append(Act(step, "stop", f"could not click {el.text!r}"))
                    run.stopped_because = "a click failed"
                    break
            else:
                run.stopped_because = f"hit step budget ({self.max_steps})"

            # -- answer = most relevant page it *navigated to* ------------ #
            # Exclude the entry page (visit #1): a search/landing page's title
            # tends to echo the query, which would otherwise beat the real
            # answer page on relevance.
            answer_pool = run.visits[1:] or run.visits
            if answer_pool:
                best = max(answer_pool, key=lambda v: v.relevance)
                run.answer = best.prose
                run.answer_url = best.url

        return run

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _key(url: str) -> str:
        """Identity for visited-tracking: strip fragment and trailing slash."""
        u = url.split("#", 1)[0]
        return u[:-1] if u.endswith("/") else u

    @staticmethod
    def _is_search_engine(href: str) -> bool:
        return any(e in href for e in ("google.", "duckduckgo.", "bing.", "gstatic."))

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[task] {msg}")

"""
learner.py -- read pages, remember them, answer from memory.

This is the "have the AI learn from a course" flow, done for real: the agent
*reads* the material and *remembers* it, then answers questions from everything
it has read. It does not fake course completion or earn credentials -- it builds
knowledge you (or it) can query later.

Two ways to feed it:

* :meth:`Learner.study` -- read one page into memory,
* :meth:`Learner.study_course` -- start on a page and follow "Next" links
  lesson-by-lesson, remembering each page as it goes.

Then :meth:`Learner.ask` answers from the accumulated :class:`~google_agent.memory.Memory`,
which persists to disk so knowledge builds up across runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .browser import Browser
from .memory import Answer, Memory
from .reader import HeuristicReader, Reader

# Link text that means "go to the next piece of the course".
_NEXT_HINTS = ("next", "continue", "forward", "next lesson", "next module",
               "next chapter", "next page", "→", "»")


@dataclass
class StudyReport:
    """What a study session covered."""

    pages_read: list[str] = field(default_factory=list)
    notes_added: int = 0
    total_notes: int = 0

    def __str__(self) -> str:
        return (f"studied {len(self.pages_read)} page(s), "
                f"learned {self.notes_added} new note(s); "
                f"memory now holds {self.total_notes}")


class Learner:
    """Reads web pages into a persistent :class:`Memory` and answers from it.

    Parameters
    ----------
    memory:
        An existing memory to grow (defaults to a fresh one). Load a saved one
        with ``Memory.load(path)`` to keep accumulating knowledge.
    reader:
        Used only to pick the "next" link when walking a course.
    headless / proxy:
        Browser controls (``proxy=""`` for localhost fixtures/tests).
    """

    def __init__(
        self,
        memory: Optional[Memory] = None,
        reader: Optional[Reader] = None,
        engine: str = "google",
        headless: bool = True,
        proxy: Optional[str] = None,
        verbose: bool = False,
    ):
        self.memory = memory or Memory()
        self.reader = reader or HeuristicReader()
        self.engine = engine
        self.headless = headless
        self.proxy = proxy
        self.verbose = verbose

    # -- studying ----------------------------------------------------------- #

    def study(self, *urls: str) -> StudyReport:
        """Read each URL and remember its prose."""
        report = StudyReport()
        with Browser(headless=self.headless, engine=self.engine, proxy=self.proxy) as b:
            for url in urls:
                b.goto(url)
                added = self.memory.learn_page(b.url(), b.title(), b.content_text(max_chars=8000))
                report.pages_read.append(b.url())
                report.notes_added += added
                self._log(f"read {b.url()} -> +{added} notes")
        report.total_notes = len(self.memory)
        return report

    def study_course(self, start_url: str, max_pages: int = 20) -> StudyReport:
        """Start on a page and follow 'Next' links, remembering each lesson.

        Stops when there's no next link, a page repeats, or ``max_pages`` is
        reached. It reads and remembers -- it does not click quiz answers or
        mark anything complete.
        """
        report = StudyReport()
        visited: set[str] = set()
        with Browser(headless=self.headless, engine=self.engine, proxy=self.proxy) as b:
            b.goto(start_url)
            for _ in range(max_pages):
                key = self._key(b.url())
                if key in visited:
                    break
                visited.add(key)

                added = self.memory.learn_page(b.url(), b.title(), b.content_text(max_chars=8000))
                report.pages_read.append(b.url())
                report.notes_added += added
                self._log(f"lesson {len(report.pages_read)}: {b.title()!r} -> +{added} notes")

                nxt = self._find_next(b, visited)
                if nxt is None:
                    self._log("no next link -> course finished")
                    break
                b.click(nxt)
        report.total_notes = len(self.memory)
        return report

    # -- asking ------------------------------------------------------------- #

    def ask(self, question: str, k: int = 5) -> Answer:
        """Answer a question from everything learned so far."""
        return self.memory.answer(question, k=k)

    # -- persistence -------------------------------------------------------- #

    def save(self, path: str) -> None:
        self.memory.save(path)

    @classmethod
    def load(cls, path: str, **kw) -> "Learner":
        return cls(memory=Memory.load(path), **kw)

    # -- internals ---------------------------------------------------------- #

    def _find_next(self, b: Browser, visited: set[str]):
        """Pick the link that advances the course, if any."""
        candidates = [
            e for e in b.read()
            if e.role in ("link", "button")
            and not (e.href.startswith("http") and self._key(e.href) in visited)
        ]
        # Prefer an explicit "next"/"continue" link.
        for e in candidates:
            low = e.text.lower()
            if any(h in low for h in _NEXT_HINTS):
                return e
        return None

    @staticmethod
    def _key(url: str) -> str:
        u = url.split("#", 1)[0]
        return u[:-1] if u.endswith("/") else u

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[learn] {msg}")

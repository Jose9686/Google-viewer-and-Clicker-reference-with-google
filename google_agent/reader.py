"""
reader.py -- the part that *reads and selects*.

Given a goal (what the user is trying to do) and a list of clickable elements
scraped off a page, a :class:`Reader` decides which one to click -- or that none
of them are worth clicking.

The default implementation, :class:`HeuristicReader`, is a small local relevance
model. It needs no API key, no network, and no external service: it tokenizes the
goal and each element's text and ranks candidates by how well they overlap, with
a few sensible biases (prefer real result links over nav chrome, penalise
"login"/"sign in"/ad-looking junk, reward exact phrase matches). That is the
"basic LLM with no rails" at the heart of this project -- a self-contained reader
you fully control.

If you later want a real model in the driver's seat, implement :class:`Reader`
(or subclass :class:`LLMReader`) and hand it to the :class:`~google_agent.agent.Agent`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #

@dataclass
class Element:
    """A single thing on the page the reader may choose to click.

    This is deliberately decoupled from the browser layer so the reader can be
    unit-tested with plain dicts and so alternative front-ends (a different
    automation library, a saved HTML fixture) can feed it too.
    """

    index: int
    text: str
    role: str = "link"            # link | button | input | other
    href: str = ""
    context: str = ""             # nearby text, aria-label, title, etc.

    @property
    def searchable(self) -> str:
        """The text a reader should consider for this element.

        Deliberately excludes the raw ``href``: a URL's directory path (e.g.
        ``/france/edit.html``) would otherwise hand every link in that section a
        free keyword match and pull the agent off-task. The link's visible text
        and its aria-label/title (``context``) are the honest signal.
        """
        return " ".join(p for p in (self.text, self.context) if p)


@dataclass
class Choice:
    """The reader's decision."""

    element: Optional[Element]
    score: float
    reason: str
    ranked: list[tuple[Element, float]] = field(default_factory=list)

    @property
    def should_click(self) -> bool:
        return self.element is not None


# --------------------------------------------------------------------------- #
# Tokenisation / scoring helpers (shared by the local reader)
# --------------------------------------------------------------------------- #

_WORD_RE = re.compile(r"[a-z0-9]+")

# Very small English stop-word list -- enough to stop "the/of/and" from
# dominating overlap scores without pulling in a heavyweight NLP dependency.
_STOP = frozenset(
    """
    a an the of to in on at for and or but is are was were be been being this
    that these those it its with as by from into your you i we they he she
    """.split()
)

# Words that usually mark a link as *not* the content you want.
_NEGATIVE = {
    "login": 1.5, "signin": 1.5, "sign": 0.8, "register": 1.2, "subscribe": 1.2,
    "advertisement": 2.0, "ad": 1.0, "sponsored": 2.0, "cookie": 1.2,
    "privacy": 0.8, "terms": 0.8, "settings": 1.0, "preferences": 1.0,
    "cart": 1.0, "checkout": 1.0, "download": 0.5,
}


def tokenize(text: str) -> list[str]:
    """Lower-case, split on non-alphanumerics, drop stop-words."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP]


def _term_frequencies(tokens: Sequence[str]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0
    return tf


# --------------------------------------------------------------------------- #
# Reader interface
# --------------------------------------------------------------------------- #

class Reader:
    """Interface: read a goal + elements, return a :class:`Choice`.

    Subclass this to plug in any decision engine you like -- a rule set, a local
    model, or a remote LLM. The :class:`~google_agent.agent.Agent` only depends
    on this method.
    """

    #: Elements scoring below this are treated as "nothing worth clicking".
    threshold: float = 0.05

    def select(self, goal: str, elements: Sequence[Element]) -> Choice:  # pragma: no cover - interface
        raise NotImplementedError

    # Convenience so a Reader can also judge free text (used for cross-referencing).
    def relevance(self, goal: str, text: str) -> float:  # pragma: no cover - interface
        raise NotImplementedError


class HeuristicReader(Reader):
    """Local, dependency-free reader.

    Scores each element by keyword overlap with the goal (TF weighting), then
    applies biases:

    * exact multi-word phrase match from the goal -> strong boost
    * being a real result link (has an off-site href) -> mild boost
    * matching one of the negative markers (login/ad/cookie...) -> penalty

    It is intentionally transparent: :attr:`Choice.reason` explains every pick,
    and :attr:`Choice.ranked` exposes the full scoreboard so you can see *why*
    it clicked what it clicked.
    """

    def __init__(self, threshold: float = 0.05, negative: Optional[dict[str, float]] = None):
        self.threshold = threshold
        self.negative = dict(_NEGATIVE if negative is None else negative)

    # -- core scoring ------------------------------------------------------- #

    def _score_text(self, goal_tf: dict[str, float], goal_phrases: list[str], text: str) -> tuple[float, str]:
        tokens = tokenize(text)
        if not tokens:
            return 0.0, "empty"
        tf = _term_frequencies(tokens)

        # Overlap: sum over shared terms of min(goal_tf, elem_tf), then normalise
        # by element length so short exact matches beat long vague ones.
        overlap = sum(min(w, tf.get(t, 0.0)) for t, w in goal_tf.items())
        norm = overlap / math.sqrt(len(tokens))

        reasons = []
        if overlap:
            reasons.append(f"{overlap:.0f} shared term(s)")

        # Phrase bonus: reward contiguous goal phrases appearing verbatim.
        low = text.lower()
        phrase_bonus = 0.0
        for ph in goal_phrases:
            if ph in low:
                phrase_bonus += 0.6 * len(ph.split())
                reasons.append(f'phrase "{ph}"')

        # Negative markers.
        penalty = 0.0
        for t in tokens:
            if t in self.negative:
                penalty += self.negative[t]
        if penalty:
            reasons.append(f"-{penalty:.1f} junk")

        score = norm + phrase_bonus - penalty
        return score, ", ".join(reasons) or "no overlap"

    def select(self, goal: str, elements: Sequence[Element]) -> Choice:
        goal_tokens = tokenize(goal)
        goal_tf = _term_frequencies(goal_tokens)
        goal_phrases = self._phrases(goal)

        ranked: list[tuple[Element, float]] = []
        best: Optional[Element] = None
        best_score = -math.inf
        best_reason = ""

        for el in elements:
            score, why = self._score_text(goal_tf, goal_phrases, el.searchable)

            # Structural biases independent of text content.
            if el.role == "link" and self._looks_offsite(el.href):
                score += 0.15
            if el.role == "button":
                score += 0.05  # buttons are often the actionable thing

            ranked.append((el, score))
            if score > best_score:
                best, best_score, best_reason = el, score, why

        ranked.sort(key=lambda pair: pair[1], reverse=True)

        if best is None or best_score < self.threshold:
            return Choice(
                element=None,
                score=best_score if best is not None else 0.0,
                reason=f"nothing above threshold {self.threshold} (best={best_score:.3f})",
                ranked=ranked,
            )

        return Choice(element=best, score=best_score, reason=best_reason, ranked=ranked)

    def relevance(self, goal: str, text: str) -> float:
        goal_tf = _term_frequencies(tokenize(goal))
        score, _ = self._score_text(goal_tf, self._phrases(goal), text)
        return score

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _phrases(goal: str, max_len: int = 3) -> list[str]:
        """Contiguous 2- and 3-word phrases from the goal (stop-words kept so
        the phrase reads naturally, e.g. "capital of france")."""
        words = _WORD_RE.findall(goal.lower())
        out: list[str] = []
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                out.append(" ".join(words[i:i + n]))
        return out[:max_len * 4]

    @staticmethod
    def _looks_offsite(href: str) -> bool:
        if not href.startswith("http"):
            return False
        parts = href.split("/")
        domain = parts[2] if len(parts) > 2 else ""
        return "google." not in domain


class LLMReader(Reader):
    """Adapter that lets any text-completion function act as the reader.

    You supply a ``complete(prompt) -> str`` callable (local llama.cpp, an API
    client, whatever). This class formats the elements into a prompt, asks for a
    single index, and parses it. If the callable is unavailable or returns
    garbage, it falls back to the local :class:`HeuristicReader` so the agent
    never gets stuck.

    Example::

        reader = LLMReader(complete=my_model.generate)
        agent = Agent(reader=reader)
    """

    def __init__(self, complete: Callable[[str], str], fallback: Optional[Reader] = None, threshold: float = 0.0):
        self.complete = complete
        self.fallback = fallback or HeuristicReader()
        self.threshold = threshold

    def _prompt(self, goal: str, elements: Sequence[Element]) -> str:
        lines = [f"[{el.index}] ({el.role}) {el.text}  {el.href}".strip() for el in elements]
        listing = "\n".join(lines)
        return (
            "You are reading a web page and choosing ONE element to click.\n"
            f"Goal: {goal}\n\n"
            "Clickable elements:\n"
            f"{listing}\n\n"
            "Reply with only the number in [brackets] of the best element to "
            "click toward the goal, or -1 if none help. Number:"
        )

    def select(self, goal: str, elements: Sequence[Element]) -> Choice:
        try:
            raw = self.complete(self._prompt(goal, elements))
            m = re.search(r"-?\d+", raw or "")
            if m:
                idx = int(m.group())
                if idx == -1:
                    return Choice(None, 0.0, "model declined (returned -1)")
                for el in elements:
                    if el.index == idx:
                        return Choice(el, 1.0, "chosen by LLM")
        except Exception as exc:  # noqa: BLE001 - fall back on any model failure
            return self._fallback(goal, elements, note=f"LLM error: {exc}")
        return self._fallback(goal, elements, note="LLM output unparseable")

    def relevance(self, goal: str, text: str) -> float:
        return self.fallback.relevance(goal, text)

    def _fallback(self, goal: str, elements: Sequence[Element], note: str) -> Choice:
        choice = self.fallback.select(goal, elements)
        choice.reason = f"{note}; fell back to heuristic ({choice.reason})"
        return choice

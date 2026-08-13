"""
memory.py -- what the agent has learned.

This is the "learning" part, done honestly. The agent doesn't train weights; it
*reads and remembers*. As it visits pages it breaks the prose into short notes
and stores each one with its source. Later it can **recall** notes relevant to a
question and **answer** by pulling together what it learned -- across every page
it has read, not just one -- which is the cross-referencing you wanted.

The store is:

* **persistent** -- ``save``/``load`` to a JSON file, so knowledge survives
  between runs and accumulates over time,
* **searchable** -- ``recall`` ranks notes by TF-IDF-style relevance to a query
  (terms that are rare across your notes count for more), and
* **source-attributed** -- every note remembers which page it came from, so
  answers can cite sources and flag when several independent pages agree.

It needs no API key and no network -- just the text the browser already reads.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .reader import tokenize

# Split prose into sentence-ish chunks on ., !, ? boundaries.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# BM25 tuning: k1 controls term-frequency saturation, b controls how much long
# notes are penalised. These are the standard defaults and work well here.
_BM25_K1 = 1.5
_BM25_B = 0.75


def _stem(token: str) -> str:
    """Crude singulariser so "inputs"/"input" and "produces"/"produce" match.

    Strips a single trailing 's' from longer words (not 'ss'). Applied to both
    stored notes and queries, so even imperfect stems stay consistent on both
    sides -- the point is that the two forms collide, not that the stem is a
    real word.
    """
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _terms(text: str) -> list[str]:
    return [_stem(t) for t in tokenize(text)]


@dataclass
class Note:
    """A single thing the agent learned, and where it learned it."""

    text: str
    source_url: str = ""
    source_title: str = ""

    def to_dict(self) -> dict:
        return {"text": self.text, "source_url": self.source_url, "source_title": self.source_title}

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        return cls(text=d.get("text", ""), source_url=d.get("source_url", ""),
                   source_title=d.get("source_title", ""))


@dataclass
class Recall:
    """A note the agent recalled, with how well it matched the question."""

    note: Note
    score: float


@dataclass
class Answer:
    """The agent's answer assembled from memory."""

    text: str
    recalls: list[Recall] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    corroborating_sources: int = 0

    def __str__(self) -> str:
        if not self.recalls:
            return self.text
        lines = [self.text, "", "Based on what I've read:"]
        for r in self.recalls:
            src = r.note.source_title or r.note.source_url or "unknown"
            lines.append(f"  - {r.note.text}  ({src})")
        return "\n".join(lines)


class Memory:
    """A persistent, searchable store of notes the agent has learned.

    Parameters
    ----------
    min_words:
        Sentences shorter than this are skipped when learning (drops nav
        fragments and boilerplate like "Next" or "Read more").
    """

    def __init__(self, min_words: int = 4):
        self.notes: list[Note] = []
        self.min_words = min_words
        self._keys: set[str] = set()   # dedupe by (source, normalised text)

    # -- learning ----------------------------------------------------------- #

    def learn_text(self, text: str, source_url: str = "", source_title: str = "") -> int:
        """Break ``text`` into notes and remember them. Returns notes added."""
        added = 0
        for sentence in self._sentences(text):
            if self._remember(Note(sentence, source_url, source_title)):
                added += 1
        return added

    def learn_page(self, url: str, title: str, prose: str) -> int:
        """Convenience: remember a page the browser just read."""
        return self.learn_text(prose, source_url=url, source_title=title)

    def _remember(self, note: Note) -> bool:
        key = f"{note.source_url}|{note.text.lower()}"
        if key in self._keys:
            return False
        self._keys.add(key)
        self.notes.append(note)
        return True

    def _sentences(self, text: str) -> Iterable[str]:
        for raw in _SENTENCE_RE.split(text or ""):
            s = " ".join(raw.split()).strip()
            if len(s.split()) >= self.min_words:
                yield s

    # -- recall ------------------------------------------------------------- #

    def _index(self) -> tuple[list[dict[str, float]], list[int], dict[str, int]]:
        """Build per-note term frequencies, note lengths, and doc frequencies."""
        tfs: list[dict[str, float]] = []
        lengths: list[int] = []
        df: dict[str, int] = {}
        for note in self.notes:
            terms = _terms(note.text)
            tf: dict[str, float] = {}
            for t in terms:
                tf[t] = tf.get(t, 0.0) + 1.0
            tfs.append(tf)
            lengths.append(len(terms))
            for t in tf:
                df[t] = df.get(t, 0) + 1
        return tfs, lengths, df

    def recall(self, query: str, k: int = 5) -> list[Recall]:
        """Return the ``k`` notes most relevant to ``query``, best first.

        Ranks with **BM25**: a query term counts more when it's rare across all
        notes (idf), its weight saturates rather than growing without bound with
        repetition (k1), and long notes are gently penalised so a short note
        isn't unfairly favoured just for being short (b). Terms are stemmed so
        singular/plural forms match.
        """
        q_terms = set(_terms(query))
        if not q_terms or not self.notes:
            return []

        tfs, lengths, df = self._index()
        n = len(self.notes)
        avgdl = (sum(lengths) / n) if n else 0.0

        scored: list[Recall] = []
        for note, tf, dl in zip(self.notes, tfs, lengths):
            score = 0.0
            for t in q_terms:
                f = tf.get(t, 0.0)
                if not f:
                    continue
                # BM25 idf (never negative thanks to the +1 inside the log).
                idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
                denom = f + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * (dl / avgdl if avgdl else 1.0))
                score += idf * (f * (_BM25_K1 + 1.0)) / denom
            if score > 0:
                scored.append(Recall(note, score))

        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    def answer(self, query: str, k: int = 5) -> Answer:
        """Assemble an answer to ``query`` from memory, with sources.

        Cross-references: reports how many *distinct* sources support the topic,
        so you can tell a lone claim from a corroborated one.
        """
        recalls = self.recall(query, k=k)
        if not recalls:
            return Answer(text="I haven't learned anything about that yet.")

        sources = []
        for r in recalls:
            s = r.note.source_url or r.note.source_title
            if s and s not in sources:
                sources.append(s)

        best = recalls[0].note
        lead = best.text
        return Answer(
            text=lead,
            recalls=recalls,
            sources=sources,
            corroborating_sources=len(sources),
        )

    # -- persistence -------------------------------------------------------- #

    def save(self, path: str) -> None:
        data = {"version": 1, "notes": [n.to_dict() for n in self.notes]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str, min_words: int = 4) -> "Memory":
        mem = cls(min_words=min_words)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return mem
        for d in data.get("notes", []):
            mem._remember(Note.from_dict(d))
        return mem

    # -- misc --------------------------------------------------------------- #

    def sources(self) -> list[str]:
        seen: list[str] = []
        for n in self.notes:
            s = n.source_url or n.source_title
            if s and s not in seen:
                seen.append(s)
        return seen

    def __len__(self) -> int:
        return len(self.notes)

    def __repr__(self) -> str:
        return f"Memory({len(self.notes)} notes from {len(self.sources())} source(s))"

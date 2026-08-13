"""
Learner tests -- read a course, remember it, answer from memory.

Drives real Chromium across the localhost course fixture

    course/lesson1.html -> lesson2.html -> lesson3.html   (via "Next lesson")

and checks the agent walks every lesson, accumulates notes, persists them, and
answers questions from the right lesson. Skips cleanly if a browser can't run.
"""

import os
import tempfile

from _helpers import serve, requires_browser  # noqa: E402  (adds repo to sys.path)

from google_agent.learner import Learner
from google_agent.memory import Memory


def test_study_course_walks_all_lessons():
    requires_browser()
    with serve() as srv:
        learner = Learner(headless=True, proxy="")
        report = learner.study_course(f"{srv.base}/course/lesson1.html")
        assert len(report.pages_read) == 3, report.pages_read
        assert report.pages_read[0].endswith("/lesson1.html")
        assert report.pages_read[-1].endswith("/lesson3.html")
        assert report.notes_added >= 3


def test_learns_facts_answerable_from_memory():
    requires_browser()
    with serve() as srv:
        learner = Learner(headless=True, proxy="")
        learner.study_course(f"{srv.base}/course/lesson1.html")

        produce = learner.ask("what does photosynthesis produce")
        assert any(w in produce.text.lower() for w in ("glucose", "oxygen")), produce.text

        inputs = learner.ask("what are the inputs to photosynthesis")
        assert any(w in inputs.text.lower() for w in ("carbon dioxide", "water", "light")), inputs.text


def test_course_walk_persists_and_reloads():
    requires_browser()
    path = os.path.join(tempfile.gettempdir(), "course_memory_test.json")
    try:
        with serve() as srv:
            learner = Learner(headless=True, proxy="")
            learner.study_course(f"{srv.base}/course/lesson1.html")
            learner.save(path)

        # New learner, no browser -- answers purely from the saved file.
        reloaded = Learner(memory=Memory.load(path))
        ans = reloaded.ask("where does photosynthesis happen")
        assert "chloroplast" in ans.text.lower() or "leaves" in ans.text.lower(), ans.text
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_study_single_pages():
    requires_browser()
    with serve() as srv:
        learner = Learner(headless=True, proxy="")
        report = learner.study(f"{srv.base}/course/lesson2.html", f"{srv.base}/course/lesson3.html")
        assert len(report.pages_read) == 2
        assert report.total_notes >= 2


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())

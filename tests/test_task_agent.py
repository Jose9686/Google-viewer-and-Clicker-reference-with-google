"""
TaskAgent tests -- "give it a task and it does it".

These are the tests that matter most: they prove that when you hand the agent a
goal and a starting page, it navigates *on its own* to the answer, stops when
it's arrived, never loops, and always terminates.

They drive real Chromium against the localhost fixture chain:

    search_task.html  ->  france/profile.html  ->  france/population.html

and skip cleanly if a browser can't be launched.
"""

from _helpers import serve, requires_browser  # noqa: E402  (adds repo to sys.path)

from google_agent.task_agent import TaskAgent


def _run(task: str, page: str = "search_task.html", **kw):
    """Serve fixtures and run a task, returning the TaskRun."""
    srv = serve()
    srv.__enter__()
    try:
        agent = TaskAgent(headless=True, proxy="", **kw)
        return agent.do(task, start_url=f"{srv.base}/{page}"), srv.base
    finally:
        srv.__exit__()


def test_navigates_itself_to_the_answer():
    """The whole point: task in, correct page out, with nobody steering."""
    requires_browser()
    run, _ = _run("france population")
    assert run.answer_url.endswith("/france/population.html"), run.summary()
    assert "68 million" in run.answer


def test_transcript_shows_two_clicks_then_stop():
    requires_browser()
    run, _ = _run("france population")
    clicks = [a for a in run.acts if a.kind == "click"]
    stops = [a for a in run.acts if a.kind == "stop"]
    assert len(clicks) == 2, [a.detail for a in run.acts]
    assert len(stops) == 1
    assert "arrived" in run.stopped_because


def test_never_revisits_a_page():
    requires_browser()
    run, _ = _run("france population")
    urls = [v.url for v in run.visits]
    assert len(urls) == len(set(urls)), urls


def test_ignores_login_ads_and_nav_chrome():
    requires_browser()
    run, _ = _run("france population")
    clicked = " ".join(a.detail.lower() for a in run.acts if a.kind == "click")
    for junk in ("sign in", "settings", "privacy", "(ad)", "cheese"):
        assert junk not in clicked, f"agent clicked junk: {junk!r} in {clicked!r}"


def test_respects_step_budget():
    requires_browser()
    run, _ = _run("france population", max_steps=1)
    assert run.steps <= 1
    assert "step budget" in run.stopped_because


def test_terminates_and_declines_when_nothing_matches():
    """An off-topic task must still terminate quickly and not click nonsense."""
    requires_browser()
    run, _ = _run("underwater basket weaving championship", max_steps=6)
    # It should stop almost immediately (nothing on the page matches the task).
    assert run.stopped_because  # set -> loop ended cleanly
    assert run.steps <= 6
    clicks = [a for a in run.acts if a.kind == "click"]
    assert len(clicks) <= 1, [a.detail for a in clicks]


def test_answer_is_not_the_entry_page():
    requires_browser()
    run, base = _run("france population")
    assert run.answer_url != f"{base}/search_task.html"


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())

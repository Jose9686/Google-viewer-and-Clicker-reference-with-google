"""
cli.py -- command-line front door.

Examples
--------
Ask a question (search -> click -> cross-reference)::

    python -m google_agent "what is the capital of france"

Use the automation-friendly engine and show the browser::

    python -m google_agent --engine duckduckgo --show "best python web scraper"

Just read one page and see what the agent *would* click toward a goal::

    python -m google_agent --url https://example.com --goal "more information"
"""

from __future__ import annotations

import argparse
import sys

from .agent import Agent
from .task_agent import TaskAgent
from .learner import Learner
from .memory import Memory


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="google_agent",
        description="An AI that reads a web page and selects what to click, then cross-references answers.",
    )
    p.add_argument("query", nargs="*", help="the question / goal to pursue")
    p.add_argument("--engine", default="google", choices=["google", "duckduckgo", "bing"],
                   help="search engine (default: google; duckduckgo is friendliest to automation)")
    p.add_argument("--sources", type=int, default=3, help="how many results to click + cross-reference")
    p.add_argument("--show", action="store_true", help="show the browser window (default: headless)")
    p.add_argument("--verbose", "-v", action="store_true", help="print each decision as it happens")
    p.add_argument("--url", help="read a single URL instead of searching")
    p.add_argument("--goal", help="goal to use with --url (what to click toward)")
    p.add_argument("--task", action="store_true",
                   help="autonomous mode: navigate on its own until the task is done "
                        "(uses --start-url or searches the query)")
    p.add_argument("--start-url", help="page to start the autonomous task from")
    p.add_argument("--max-steps", type=int, default=8, help="autonomous step budget (default 8)")

    # -- learning / memory ---------------------------------------------------
    p.add_argument("--learn", nargs="+", metavar="URL",
                   help="read these page(s) into memory (what the agent has learned)")
    p.add_argument("--course", metavar="URL",
                   help="walk a course from this URL, following 'Next' links, learning each page")
    p.add_argument("--ask", metavar="QUESTION",
                   help="answer a question from memory (what it has already read)")
    p.add_argument("--memory", default="agent_memory.json", metavar="PATH",
                   help="memory file to read/write (default: agent_memory.json)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    agent = Agent(
        engine=args.engine,
        headless=not args.show,
        max_sources=args.sources,
        verbose=args.verbose,
    )

    # Single-page "read and select" mode.
    if args.url:
        goal = args.goal or " ".join(args.query) or "the most relevant link"
        element, text = agent.read_page(args.url, goal)
        print(f"Read {args.url} ({len(text)} chars of text).")
        if element is None:
            print(f"Nothing worth clicking toward goal: {goal!r}")
        else:
            print(f"Would click -> [{element.role}] {element.text!r}  {element.href}")
        return 0

    query = " ".join(args.query).strip()

    # Learning / memory modes: read pages into a persistent memory, then answer
    # questions from what it has read. These operate on --memory (a JSON file).
    if args.learn or args.course or args.ask:
        import os

        memory = Memory.load(args.memory) if os.path.exists(args.memory) else Memory()
        learner = Learner(memory=memory, engine=args.engine,
                          headless=not args.show, verbose=args.verbose)

        if args.course:
            report = learner.study_course(args.course, max_pages=20)
            print(report)
            learner.save(args.memory)
        if args.learn:
            report = learner.study(*args.learn)
            print(report)
            learner.save(args.memory)
        if args.ask:
            ans = learner.ask(args.ask)
            print(ans)
        elif not (args.learn or args.course):
            print("Nothing to do. Use --learn/--course to read, and --ask to query.")
        return 0

    # Autonomous task mode: hand it a goal, it drives itself to completion.
    if args.task:
        if not query and not args.start_url:
            print("--task needs a task description (and optionally --start-url).")
            return 2
        task_agent = TaskAgent(
            engine=args.engine,
            headless=not args.show,
            max_steps=args.max_steps,
            verbose=args.verbose,
        )
        run = task_agent.do(query or "explore", start_url=args.start_url)
        print(run.summary())
        return 0

    # Search + cross-reference mode.
    if not query:
        build_parser().print_help()
        return 2

    result = agent.run(query)
    print(result.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())

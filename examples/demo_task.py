"""
Autonomous task demo -- no internet needed.

Serves the fixture pages on localhost and turns :class:`TaskAgent` loose on a
multi-hop task:

    task: "france population"
    search page  ->  France country profile  ->  Population of France  ->  done

The agent decides each hop by itself, stops when no link is worth clicking any
more, and reports the page it judged most relevant. Watch the transcript: it
takes two clicks across three pages with no step-by-step guidance.

Run:  python examples/demo_task.py
"""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from google_agent.task_agent import TaskAgent   # noqa: E402

FIXTURES = os.path.join(ROOT, "fixtures")


def serve(directory: str) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    httpd, port = serve(FIXTURES)
    base = f"http://127.0.0.1:{port}"
    task = "france population"
    print(f"Serving fixtures at {base}\n")

    try:
        agent = TaskAgent(headless=True, proxy="", verbose=True, max_steps=6)
        run = agent.do(task, start_url=f"{base}/search_task.html")
        print("\n" + "=" * 64)
        print(run.summary())
        print("=" * 64)

        # Sanity check for the demo: it should have landed on the population page.
        ok = "population of france is approximately 68 million" in run.answer.lower()
        print(f"\nReached the right answer page: {ok}")
        return 0 if ok else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())

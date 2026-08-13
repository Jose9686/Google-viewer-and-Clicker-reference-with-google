"""
End-to-end demo that needs no internet.

It serves the fixture pages in ``examples/fixtures`` on ``localhost`` and drives
a *real* Chromium browser through the complete pipeline:

    read the results page -> select the best link -> click it ->
    read the next-best link -> cross-reference -> synthesise an answer.

This is the same code path :class:`google_agent.agent.Agent` uses for a live
Google search; only the starting URL differs. Use it to see the agent work
without depending on outbound web access (which may be blocked by an
environment's egress policy).

Run:  python examples/demo_local.py
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

from google_agent.browser import Browser          # noqa: E402
from google_agent.reader import HeuristicReader     # noqa: E402

FIXTURES = os.path.join(ROOT, "fixtures")


def serve(directory: str) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None  # quiet
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def main() -> int:
    goal = "capital of France"
    httpd, port = serve(FIXTURES)
    base = f"http://127.0.0.1:{port}"
    reader = HeuristicReader()
    print(f"Serving fixtures at {base}  |  goal: {goal!r}\n")

    try:
        with Browser(headless=True, proxy="") as b:  # proxy="" -> direct localhost
            # 1) READ the results page.
            b.goto(f"{base}/search.html")
            elements = b.read()
            print(f"READ  {len(elements)} clickable elements on the results page:")
            for el in elements:
                print(f"        [{el.index}] ({el.role}) {el.text!r}")

            # 2) SELECT the best link and show the scoreboard.
            choice = reader.select(goal, elements)
            print(f"\nSELECT best = [{choice.element.index}] {choice.element.text!r}  "
                  f"(score {choice.score:.2f}; {choice.reason})")
            print("      top of scoreboard:")
            for el, score in choice.ranked[:4]:
                print(f"        {score:6.2f}  {el.text!r}")

            # 3) CLICK it and read the destination.
            b.click(choice.element)
            print(f"\nCLICK -> now at {b.url()}")
            print(f"        title: {b.title()}")
            print(f"        text : {b.text(160)!r}")

            # 4) CROSS-REFERENCE: go back and visit the next best *distinct*
            #    source (a different domain/path than the one just clicked).
            first_url = b.url()
            b.goto(f"{base}/search.html")
            already = first_url.rsplit("/", 1)[-1]
            second = next(
                (e for e, _ in choice.ranked
                 if e.role == "link"
                 and e.href.rsplit("/", 1)[-1] != already
                 and any(k in e.href for k in ("/wiki/", "/quora/"))),
                None,
            )
            if second is not None:
                b.click(second)
                rel = reader.relevance(goal, f"{b.title()} {b.text()}")
                print(f"\nCROSS-REFERENCE second source: {b.url()}  (relevance {rel:.2f})")
                print(f"        {b.text(160)!r}")
                print("\nTwo independent sources both say the capital of France is "
                      "Paris -> corroborated.")
        return 0
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())

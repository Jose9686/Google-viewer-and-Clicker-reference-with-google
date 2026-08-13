"""
Learning demo -- read a course, remember it, answer from memory. No internet.

Serves a 3-lesson course on localhost and has the agent:

  1. walk the course lesson by lesson (following "Next lesson" links),
  2. remember the prose of every page into a persistent Memory,
  3. save that memory to disk, and
  4. answer questions using only what it read -- pulling facts from whichever
     lesson had them, and citing the source.

Run:  python examples/demo_learn.py
"""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ROOT))

from google_agent.learner import Learner       # noqa: E402
from google_agent.memory import Memory          # noqa: E402

FIXTURES = os.path.join(ROOT, "fixtures")


def serve(directory: str):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    httpd, port = serve(FIXTURES)
    base = f"http://127.0.0.1:{port}"
    mem_path = os.path.join(tempfile.gettempdir(), "photosynthesis_memory.json")
    print(f"Serving course at {base}\n")

    try:
        # 1-3) LEARN: walk the course and remember every lesson.
        learner = Learner(headless=True, proxy="", verbose=True)
        report = learner.study_course(f"{base}/course/lesson1.html")
        learner.save(mem_path)
        print(f"\n{report}")
        print(f"memory saved to {mem_path}\n")

        # 4) ASK: answer from memory, reloading it from disk to prove it persisted.
        recalled = Learner(memory=Memory.load(mem_path))
        questions = [
            "what does photosynthesis produce",
            "what are the inputs to photosynthesis",
            "where does photosynthesis happen",
        ]
        ok = True
        for q in questions:
            ans = recalled.ask(q, k=2)
            print(f"Q: {q}")
            print(f"A: {ans.text}")
            src = ans.sources[0] if ans.sources else "(none)"
            print(f"   source: {src}  |  corroborating sources: {ans.corroborating_sources}\n")
            if not ans.recalls:
                ok = False

        # Sanity: the "produce" question should surface glucose/oxygen.
        produce = recalled.ask("what does photosynthesis produce", k=1)
        hit = any(w in produce.text.lower() for w in ("glucose", "oxygen"))
        print(f"Answered from learned material: {hit}")
        return 0 if (ok and hit) else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())

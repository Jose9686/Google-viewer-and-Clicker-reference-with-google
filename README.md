# Google viewer & clicker — an AI that reads and selects

A small, self-contained agent that **reads a web page, decides what to click**,
clicks it, and **cross-references** what it finds across several pages to answer
a question.

It's built around the idea you asked for: a *basic-level "reader" with no
external rails* — the default decision engine runs **entirely on your machine**,
needs **no API key**, and talks to **no paid service**. You own the brain and
can see exactly why it clicks what it clicks. When you want a real language
model driving instead, there's a one-line hook for that too.

```
search  ->  read the page  ->  select the best element  ->  click  ->
extract text  ->  cross-reference the next sources  ->  answer
```

## What's inside

| Piece | File | Job |
|-------|------|-----|
| **Reader** | `google_agent/reader.py` | The brain. Scores every clickable element against your goal and picks one — or decides nothing's worth clicking. Fully local (`HeuristicReader`) with a pluggable LLM adapter (`LLMReader`). |
| **Browser** | `google_agent/browser.py` | The eyes and hands. Drives real Chromium (Playwright): open a page, read every clickable element into plain data, click one. |
| **Agent** | `google_agent/agent.py` | The fixed loop. Search → read → select → click → extract → cross-reference → synthesise an answer, with a full decision trail. |
| **TaskAgent** | `google_agent/task_agent.py` | The **autonomous** loop. Hand it a task; it perceives → decides → clicks → repeats *on its own* until the task is done or it runs out of promising links. |
| **CLI** | `google_agent/cli.py` | `python -m google_agent "your question"` |

## Install

```bash
pip install -r requirements.txt
# Chromium itself is already present in this environment; no "playwright install" needed.
```

## Use it

**Ask a question** (search → click → cross-reference):

```bash
python -m google_agent "what is the capital of france"
```

**Read a single page and see what it *would* click** toward a goal:

```bash
python -m google_agent --url https://en.wikipedia.org/wiki/Paris --goal "history section"
```

**Options**

```
--engine {google,duckduckgo,bing}   search engine (duckduckgo is friendliest to automation)
--sources N                         how many results to click + cross-reference (default 3)
--show                              show the browser window (default: headless)
--verbose / -v                      print each decision as it happens
--url URL / --goal GOAL             read one page instead of searching
```

**From Python:**

```python
from google_agent import Agent

result = Agent(engine="duckduckgo", verbose=True).run("who painted the mona lisa")
print(result.summary())      # answer + ranked sources
for step in result.trail:    # every decision, for transparency
    print(step.action, step.detail)
```

## Autonomous mode — hand it a task, it just does it

`TaskAgent` doesn't stop after one click. You give it a goal and (optionally) a
starting page; it drives itself — perceive the page, pick the single best link
toward the task, click, repeat — and stops on its own when no link is worth
clicking any more, then hands back the page it judged most relevant plus a full
transcript of every move.

```bash
# autonomous: navigate a site on its own until the task is satisfied
python -m google_agent --task "france population" --start-url https://en.wikipedia.org/wiki/France -v
```

```python
from google_agent import TaskAgent

run = TaskAgent(verbose=True, max_steps=8).do(
    "france population",
    start_url="https://en.wikipedia.org/wiki/France",
)
print(run.summary())     # what it clicked, why, where it stopped, and the answer
```

You control how far it roams with `max_steps` (a hard cap so it can never loop
forever) and how picky it is with `click_threshold`. It never re-visits a page
and never needs step-by-step approval. See it work offline over a real browser:

```bash
python examples/demo_task.py     # search -> France profile -> Population page, two clicks, no guidance
```

For genuinely tricky multi-hop paths (where the right link's *label* doesn't
obviously match the goal), plug a real model into the same loop via `LLMReader`
— the navigation gets much smarter with zero other changes.

## The reader (how "select" works)

`HeuristicReader` tokenises your goal and each element's text and scores
candidates by keyword overlap, then applies biases:

- **exact phrase match** from the goal → strong boost (`"capital of france"`),
- being a **real off-site result link** → mild boost,
- matching **junk markers** (`login`, `sign in`, `sponsored`, `cookie`, …) → penalty.

Every pick is explained (`choice.reason`) and the full scoreboard is exposed
(`choice.ranked`), so nothing is a black box.

**Want a real LLM to choose instead?** Give any `complete(prompt) -> str`
callable to `LLMReader`. It formats the elements, asks the model for one index,
and *falls back to the local reader* if the model errors or replies with
nonsense — so the agent never gets stuck:

```python
from google_agent import Agent, LLMReader

reader = LLMReader(complete=my_model.generate)   # llama.cpp, an API client, anything
Agent(reader=reader).run("...")
```

## Run the demo (no internet needed)

```bash
python examples/demo_local.py
```

It serves fixture pages on `localhost` and drives a real browser through the
whole pipeline — read → select → click → cross-reference — printing the
scoreboard at each step. Good for seeing the agent work end-to-end offline.

## Tests

25 tests, runnable two ways — with pytest, or with **zero extra dependencies**:

```bash
python tests/run_all.py            # no dependencies needed
python -m pytest -q tests/         # if you have pytest (pip install -r requirements-dev.txt)
```

What's covered:

- **`test_reader.py`** (offline, no browser) — relevant results beat nav chrome,
  ads get penalised, the reader declines when nothing fits, URL paths don't
  pollute scoring, and the `LLMReader` falls back cleanly on bad model output.
- **`test_agent.py`** (offline) — result-link ranking dedupes by domain and
  drops search-engine/relative links; answer confidence scales with agreement.
- **`test_browser.py`** (real Chromium on localhost) — reading clickable
  elements, prose extraction excluding links, and clicking to navigate.
- **`test_task_agent.py`** (real Chromium on localhost) — the autonomous agent
  navigates itself to the right page, records a truthful transcript, never
  revisits a page, ignores login/ads/chrome, respects the step budget, and
  always terminates (even on an off-topic task).

Browser-backed tests **skip cleanly** (not fail) if Chromium can't launch, so
the offline tests still run anywhere.

## Notes on running against live Google

- **Automation-friendliness:** Google often shows a consent wall or CAPTCHA to
  automated browsers. If a live Google run comes back with no usable links, try
  `--engine duckduckgo` — its HTML endpoint is much friendlier to automation and
  the exact same read/select/click code runs against it.
- **Restricted networks:** in a sandboxed or managed environment, outbound web
  access may be blocked by an egress policy (only package registries, GitHub,
  etc. allowed). The browser layer auto-detects an `HTTPS_PROXY` and the
  pre-installed Chromium binary, but if the policy denies a host there's nothing
  the code can do — run it somewhere with open web access, or use the offline
  demo above to see the pipeline in action.

## Layout

```
google_agent/
  __init__.py     public API
  reader.py       the brain: read & select (HeuristicReader, LLMReader)
  browser.py      real-Chromium control: open, read (+ prose), click
  agent.py        the fixed search -> select -> click -> cross-reference loop
  task_agent.py   the autonomous perceive -> decide -> act loop (TaskAgent)
  cli.py          command-line entry point
examples/
  demo_local.py   offline end-to-end demo: read -> select -> click -> cross-reference
  demo_task.py    offline autonomous demo: multi-hop navigation, no guidance
  fixtures/       fake search + content pages
tests/
  test_reader.py       offline unit tests for the reader
  test_agent.py        offline unit tests for Agent ranking / synthesis
  test_browser.py      real-Chromium tests: read, prose, click
  test_task_agent.py   real-Chromium tests: autonomous navigation
  run_all.py           zero-dependency test runner (no pytest needed)
```

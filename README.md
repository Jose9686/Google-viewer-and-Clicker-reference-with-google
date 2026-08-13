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
| **Agent** | `google_agent/agent.py` | The loop. Search → read → select → click → extract → cross-reference → synthesise an answer, with a full decision trail. |
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

```bash
python tests/test_reader.py        # or:  python -m pytest -q
```

The reader is tested offline (no browser, no network): relevant results beat
nav chrome, ads get penalised, the reader declines when nothing fits, and the
LLM adapter falls back cleanly on bad model output.

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
  browser.py      real-Chromium control: open, read, click
  agent.py        the search -> select -> click -> cross-reference loop
  cli.py          command-line entry point
examples/
  demo_local.py   offline end-to-end demo over localhost fixtures
  fixtures/       fake search + content pages
tests/
  test_reader.py  offline unit tests for the reader
```

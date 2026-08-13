"""
Run the whole test suite without pytest:

    python tests/run_all.py

Discovers every ``tests/test_*.py``, runs its ``test_*`` functions, and prints a
combined pass / skip / fail summary. Exit code is non-zero if anything failed.
(``pytest`` also works if installed -- this is just the zero-dependency path.)
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from _run import run_module  # noqa: E402


def _load(path: str):
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    total_rc = 0
    for path in files:
        print(f"\n===== {os.path.basename(path)} =====")
        mod = _load(path)
        rc = run_module(vars(mod))
        total_rc |= rc
    print("\n" + ("ALL GREEN" if total_rc == 0 else "SOME TESTS FAILED"))
    return total_rc


if __name__ == "__main__":
    sys.exit(main())

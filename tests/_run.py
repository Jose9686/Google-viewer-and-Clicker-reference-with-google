"""
Tiny standalone test runner so the suite works without pytest installed.

Each test file ends with::

    if __name__ == "__main__":
        from _run import run_module
        run_module(globals())

``run_module`` finds every ``test_*`` callable in the module, runs it, and
reports pass / skip / fail. A test signals a skip by raising
``unittest.SkipTest`` (via ``_helpers.requires_browser``); any other exception
is a failure. Exit code is non-zero if anything failed.
"""

from __future__ import annotations

import sys
import traceback
from unittest import SkipTest


def run_module(namespace: dict) -> int:
    tests = [
        (name, obj)
        for name, obj in sorted(namespace.items())
        if name.startswith("test_") and callable(obj)
    ]
    passed = skipped = failed = 0
    for name, fn in tests:
        try:
            fn()
        except SkipTest as exc:
            skipped += 1
            print(f"SKIP  {name}: {exc}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc or 'assertion failed'}")
        except Exception:  # noqa: BLE001 - report unexpected errors as failures
            failed += 1
            print(f"ERROR {name}:")
            traceback.print_exc()
        else:
            passed += 1
            print(f"PASS  {name}")

    print(f"\n{passed} passed, {skipped} skipped, {failed} failed")
    rc = 1 if failed else 0
    if namespace.get("__name__") == "__main__":
        sys.exit(rc)
    return rc

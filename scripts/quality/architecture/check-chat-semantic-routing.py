#!/usr/bin/env python3
"""Block new natural-language keyword routers on the Command Deck path."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DECK = ROOT / "console" / "src" / "deck"
OPERATOR_SOURCE = ROOT / "services" / "operator-service" / "src"
SEMANTIC_REGEX = re.compile(
    r"^_[A-Z0-9_]*(?:INTENT|TERMS|MARKERS|VERBS)[A-Z0-9_]*.*=\s*re\.compile",
    re.MULTILINE,
)


def violations() -> list[str]:
    failures: list[str] = []
    for name in ("action-intent.ts", "action-intent.test.ts"):
        if (DECK / name).exists():
            failures.append(f"client natural-language router returned: console/src/deck/{name}")

    submit_hook = (DECK / "use-command-deck-submit.ts").read_text(encoding="utf-8")
    for token in ("detectActionIntent", "submitAction("):
        if token in submit_hook:
            failures.append(
                f"client submit path contains forbidden natural-language branch: {token}"
            )

    for path in sorted(OPERATOR_SOURCE.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if SEMANTIC_REGEX.search(path.read_text(encoding="utf-8")):
            failures.append(f"new chat intent regex module is not allowed: {relative}")
    return failures


def main() -> int:
    failures = violations()
    if failures:
        for failure in failures:
            print(f"chat-semantic-routing: ERROR: {failure}", file=sys.stderr)
        return 1
    print("chat-semantic-routing: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

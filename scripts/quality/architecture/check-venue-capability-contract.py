#!/usr/bin/env python3
"""Keep venue selection inside one contract.

FDAI-CONST-001 allows a venue to differ only in credentials, endpoints, scale, and provider
scope. That is provable only while every venue-selected binding is enumerated in one place.
Before `fdai/runtime/venue.py` existed, seven call sites each read `FDAI_EXECUTION_VENUE`
and applied their own default, so a new venue-sensitive capability could appear anywhere
and no check would fail.

This gate fails when the environment variable is read, or a venue literal is compared,
anywhere under the core-control-plane source tree except the contract module itself.

Exit codes: 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = ROOT / "services/core-control-plane/src/fdai"
CONTRACT = SOURCE_ROOT / "runtime/venue.py"

_ENV_READ = re.compile(r"FDAI_EXECUTION_VENUE")
_VENUE_COMPARISON = re.compile(r"""(?:==|!=)\s*["'](?:local|deployed)["']""")


def _display(path: Path) -> str:
    """Return a repo-relative path when possible, so findings stay readable."""

    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _violations(source_root: Path, contract: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path == contract or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            relative = _display(path)
            if _ENV_READ.search(line):
                findings.append(
                    f"{relative}:{number}: reads FDAI_EXECUTION_VENUE directly; "
                    f"use resolve_execution_venue() from {_display(contract)}"
                )
            if _VENUE_COMPARISON.search(line):
                findings.append(
                    f"{relative}:{number}: compares a venue literal; "
                    f"use ExecutionVenue and select_capability() instead"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=SOURCE_ROOT,
        help="Directory to scan (defaults to the core-control-plane source tree).",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=CONTRACT,
        help="The one module allowed to resolve the venue.",
    )
    args = parser.parse_args(argv)

    if not args.contract.exists():
        print(f"venue-capability-contract: FAILED - missing contract module {args.contract}")
        return 1

    findings = _violations(args.source_root.resolve(), args.contract.resolve())
    if findings:
        for finding in findings:
            print(f"venue-capability-contract: {finding}")
        print(f"venue-capability-contract: FAILED with {len(findings)} violation(s).")
        return 1
    print("venue-capability-contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

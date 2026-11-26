#!/usr/bin/env python3
"""Regenerate pytest shard weights from a measured full-suite run.

Run the suite once per CI mode (regression, coverage, integration) with durations enabled, then
feed every log here:

    FDAI_PYTEST_MODE=regression bash scripts/quality/ci/run-python-tests.sh \
        --durations=0 --durations-min=0.01 | tee regression.log
    FDAI_PYTEST_MODE=coverage bash scripts/quality/ci/run-python-tests.sh \
        --durations=0 --durations-min=0.01 | tee coverage.log
    python3 scripts/quality/ci/update-pytest-shard-durations.py regression.log coverage.log

Integration mode needs the loopback validation database; run it through
``scripts/automation/with-local-test-database.py``.

The shard plugin prices a file by its recorded seconds, so stale or missing weights make one
shard much slower than the rest and the slowest shard sets the CI wall time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_LINE = re.compile(
    r"^\s*(?P<seconds>[0-9]+(?:\.[0-9]+)?)s (?:call|setup|teardown)\s+(?P<path>\S+?)::"
)
_SCHEMA_VERSION = 1
_DEFAULT_SECONDS_PER_TEST = 0.001
_MINIMUM_FILE_SECONDS = 0.5


def parse_durations(lines: list[str]) -> dict[str, float]:
    """Sum call, setup, and teardown seconds per test file from a ``--durations`` report."""
    totals: dict[str, float] = {}
    for line in lines:
        match = _LINE.match(line)
        if match:
            path = match["path"]
            totals[path] = totals.get(path, 0.0) + float(match["seconds"])
    return {path: round(seconds, 3) for path, seconds in totals.items()}


def build_weights(totals: dict[str, float], repository_root: Path) -> dict[str, object]:
    """Keep files that still exist and cost at least the recording threshold."""
    files = {
        path: seconds
        for path, seconds in sorted(totals.items())
        if seconds >= _MINIMUM_FILE_SECONDS
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        and (repository_root / path).is_file()
    }
    return {
        "schema_version": _SCHEMA_VERSION,
        "default_seconds_per_test": _DEFAULT_SECONDS_PER_TEST,
        "minimum_recorded_file_seconds": _MINIMUM_FILE_SECONDS,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "logs",
        type=Path,
        nargs="+",
        help="pytest output that includes --durations=0, one per mode (regression, coverage, "
        "integration); a file measured in several keeps its largest value",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("pytest-shard-durations.json"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).parents[3])
    arguments = parser.parse_args(argv)

    totals: dict[str, float] = {}
    for log in arguments.logs:
        measured = parse_durations(log.read_text(encoding="utf-8", errors="replace").splitlines())
        for path, seconds in measured.items():
            totals[path] = max(seconds, totals.get(path, 0.0))
    if not totals:
        print("no duration lines found; run pytest with --durations=0", file=sys.stderr)
        return 1
    payload = build_weights(totals, arguments.repository_root)
    arguments.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {len(payload['files'])} files from {len(totals)} measured")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

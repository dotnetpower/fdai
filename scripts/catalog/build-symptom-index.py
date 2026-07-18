#!/usr/bin/env python3
"""Compile the symptom -> scenarios index for cold-start reuse.

Writes `rule-catalog/chaos-scenarios/chaos-scenarios.index.json` from
`load_all()` (dev / tooling) or `load_promoted()` (production build).

Run modes:

    python scripts/catalog/build-symptom-index.py [--promoted-only]

Default is `load_all()` so the local index reflects everything under
`collected/**` too - useful before scenarios have been promoted. Pass
`--promoted-only` to build the runtime artifact.

Exit code non-zero on catalog validation failure (the loader raises
`ScenarioCatalogError` before the index can be built).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from fdai.core.chaos.scenario_catalog import DEFAULT_ROOT
from fdai.core.chaos.symptom_index import (
    build_from_all,
    build_from_promoted,
    write_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--promoted-only",
        action="store_true",
        help="Build from load_promoted() (runtime artifact). Default: load_all().",
    )
    p.add_argument(
        "--out",
        type=pathlib.Path,
        default=DEFAULT_ROOT / "chaos-scenarios.index.json",
        help="Output path (default: %(default)s).",
    )
    args = p.parse_args(argv)

    idx = build_from_promoted() if args.promoted_only else build_from_all()
    write_snapshot(idx, args.out)
    print(
        f"wrote {args.out}  signals={len(idx.all_signals())}  "
        f"total_refs={idx.size()}  buckets={len(idx.by_key)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

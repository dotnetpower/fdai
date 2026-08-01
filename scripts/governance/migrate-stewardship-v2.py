#!/usr/bin/env python3
"""Render a reviewed stewardship v2 candidate without editing the source file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from fdai.core.stewardship import (
    StewardshipMigrationError,
    StewardshipValidationError,
    migrate_stewardship_mapping_to_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("config/agent-stewardship.yaml"),
        help="v1 or v2 stewardship YAML source",
    )
    parser.add_argument("--output", type=Path, help="new candidate path; stdout when omitted")
    args = parser.parse_args()

    source = args.input.resolve()
    if args.output is not None and args.output.resolve() == source:
        parser.error("--output MUST differ from --input; in-place migration is not supported")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise StewardshipMigrationError("stewardship source MUST be a YAML mapping")
        candidate = migrate_stewardship_mapping_to_v2(raw)
    except (OSError, yaml.YAMLError, StewardshipMigrationError, StewardshipValidationError) as exc:
        print(f"migrate-stewardship-v2: {exc}", file=sys.stderr)
        return 1

    rendered = yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True)
    if args.output is None:
        sys.stdout.write(rendered)
        return 0
    if args.output.exists():
        parser.error("--output already exists; choose a new review path")
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

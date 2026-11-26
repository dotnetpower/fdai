#!/usr/bin/env python3
"""Assemble a complete runtime v2 directory from connected-host release artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdai_deployment_cli.runtime_build import build_runtime_release


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def main(argv: list[str] | None = None) -> int:
    """Build a local runtime release without network access or cloud mutation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--deployment-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_runtime_release(
            _absolute(args.source_root),
            _absolute(args.descriptor),
            _absolute(args.deployment_bundle),
            _absolute(args.output),
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"runtime release build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

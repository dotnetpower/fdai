#!/usr/bin/env python3
"""Copy prebuilt local runtime artifacts into an unsigned offline kit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdai_deployment_cli.runtime_stage import stage_runtime_release


def main(argv: list[str] | None = None) -> int:
    """Stage an exact runtime inventory without downloading or executing artifacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--deployment-bundle", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--platform-tag", required=True)
    args = parser.parse_args(argv)
    try:
        digest = stage_runtime_release(
            args.source,
            args.kit,
            deployment_bundle=args.deployment_bundle,
            source_commit=args.source_commit,
            platform_tag=args.platform_tag,
        )
    except (OSError, ValueError) as exc:
        print(f"runtime staging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"runtime_release_digest": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

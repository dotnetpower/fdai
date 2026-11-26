#!/usr/bin/env python3
"""Command-line facade for the durable roadmap verification queue."""

from __future__ import annotations

import argparse
import json

import roadmap_verification as queue


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync")
    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--owner", required=True)
    claim_parser.add_argument("--lease-seconds", type=int, default=1800)
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = queue.queue_paths()
    if arguments.command == "sync":
        created = queue.sync(paths)
        print(f"roadmap-verification: synchronized queue ({created} new job(s))")
        return 0
    if arguments.command == "claim":
        job = queue.claim(
            paths,
            owner=arguments.owner,
            lease_seconds=arguments.lease_seconds,
        )
        print(json.dumps(job, ensure_ascii=True, sort_keys=True) if job else "null")
        return 0
    counts = queue.status(paths)
    total = sum(counts.values())
    summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) or "empty"
    print(f"roadmap-verification: {total} job(s) ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

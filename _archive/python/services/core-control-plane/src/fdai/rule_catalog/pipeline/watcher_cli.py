"""CLI entrypoint for the SourceWatcher.

Usage
-----

    python -m fdai.rule_catalog.pipeline.watcher_cli \\
        [--sources-root rule-catalog/sources] \\
        [--output-root  rule-catalog/sources] \\
        [--now 2026-07-06T03:00:00+00:00] \\
        [--dry-run] [--verify]

Iterates every ``rule-catalog/sources/*/manifest.yaml``, asks the
watcher whether the source is due at ``now``, and invokes the collector
CLI for each due source. Produces a JSON summary on stdout.

Exits:

- ``0`` - every due source collected cleanly (or nothing was due).
- ``2`` - at least one manifest failed to load, one cadence was
  unrecognized, or one collector invocation returned non-zero.

Cron schedule
-------------

The Container Apps Job spec in
``infra/modules/compute/container-apps/rule_watcher_job.tf`` runs this
CLI once a day at ``0 3 * * *`` UTC. The watcher filters by cadence, so
the same daily job also picks up weekly / monthly sources on their due
day - no per-cadence job proliferation.

The CLI never auto-promotes. Snapshots + verify reports land on disk
and become inputs to the reviewed catalog-as-code PR that governs the
rule catalog.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from fdai.rule_catalog.pipeline.collect_cli import main as collect_main
from fdai.rule_catalog.pipeline.watcher import SourceWatcher, WatcherError
from fdai.rule_catalog.schema.source_manifest import (
    ManifestError,
    load_source_manifest_from_yaml,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "rule-catalog").is_dir():
            return parent
    return Path.cwd()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-rule-watcher",
        description=(
            "Iterate rule-catalog source manifests and invoke the collector "
            "CLI for every source due under its cadence. Snapshots + verify "
            "reports are produced; promotion stays a reviewed catalog-as-code PR."
        ),
    )
    parser.add_argument(
        "--sources-root",
        type=Path,
        default=None,
        help=(
            "Directory containing per-source manifest folders "
            "(default <repo>/rule-catalog/sources)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repo root (defaults to the auto-detected one).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Snapshot output root forwarded to the collector CLI + used by "
            "the watcher to locate SNAPSHOT.json "
            "(default <repo>/rule-catalog/sources)."
        ),
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="ISO-8601 timestamp override (default: current UTC).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Forwarded to collect: fetch + hash without writing snapshots.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Forwarded to collect: run parser + verifier after snapshot.",
    )
    return parser


def _parse_now(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root or _repo_root()
    sources_root = args.sources_root or (repo_root / "rule-catalog" / "sources")
    output_root = args.output_root or (repo_root / "rule-catalog" / "sources")

    if not sources_root.is_dir():
        print(f"error: sources root not found: {sources_root}", file=sys.stderr)
        return 2

    if args.now is not None:
        try:
            now = _parse_now(args.now)
        except ValueError as exc:
            print(
                f"error: --now is not a valid ISO-8601 timestamp: {exc}",
                file=sys.stderr,
            )
            return 2
    else:
        now = datetime.now(tz=UTC)

    watcher = SourceWatcher(snapshot_root=output_root)

    manifest_paths = sorted(sources_root.glob("*/manifest.yaml"))
    entries: list[dict[str, object]] = []
    exit_code = 0

    for manifest_path in manifest_paths:
        entry: dict[str, object] = {"manifest": str(manifest_path)}

        try:
            manifest = load_source_manifest_from_yaml(manifest_path)
        except ManifestError as exc:
            entry["error"] = str(exc)
            entry["due"] = False
            entries.append(entry)
            exit_code = 2
            continue

        entry["source_id"] = manifest.id
        entry["cadence"] = manifest.cadence.value

        try:
            due = watcher.is_due(manifest, now=now)
        except WatcherError as exc:
            entry["error"] = str(exc)
            entry["due"] = False
            entries.append(entry)
            exit_code = 2
            continue

        entry["due"] = due
        if not due:
            entries.append(entry)
            continue

        collect_argv: list[str] = [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(output_root),
        ]
        if args.dry_run:
            collect_argv.append("--dry-run")
        if args.verify:
            collect_argv.append("--verify")

        # Capture the collector's stdout so the watcher can nest its
        # summary under `entry["collect"]` and emit one well-formed JSON
        # document on the outer stdout. The collector's stderr flows
        # through untouched so cron logs still surface the error text.
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = collect_main(collect_argv)
        entry["collect_exit_code"] = result
        raw_stdout = buf.getvalue()
        try:
            entry["collect"] = json.loads(raw_stdout)
        except json.JSONDecodeError:
            entry["collect_raw"] = raw_stdout
        if result != 0:
            exit_code = 2
        entries.append(entry)

    summary = {
        "now": now.isoformat(),
        "sources_root": str(sources_root),
        "entries": entries,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["main"]

"""CLI entrypoint for the rule-catalog collector pipeline.

Usage
-----

    python -m fdai.rule_catalog.pipeline.collect_cli \\
        --manifest rule-catalog/sources/gatekeeper-library/manifest.yaml \\
        [--dry-run]

Exits:

- ``0`` - snapshot written (or dry-run summary printed).
- ``2`` - manifest / fetch / hash-mismatch error.
- ``64`` - usage error.

The snapshot lands under
``rule-catalog/sources/<id>/<short-revision>/`` next to a
``SNAPSHOT.json`` provenance file. The T0 catalog is NOT touched - a
future normalization stage promotes snapshots into
``rule-catalog/catalog/`` under the same governance pipeline as the
existing hand-authored rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from fdai.rule_catalog.pipeline.collect import CollectorPipeline
from fdai.rule_catalog.pipeline.collect.fetch import FetchError
from fdai.rule_catalog.pipeline.parse import (
    ParseError,
    ParserNotImplementedError,
    build_parser,
    verify_parsed_rules,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.source_manifest import ManifestError
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


def _repo_root() -> Path:
    # Walks up from this file until a ``rule-catalog/`` sibling appears -
    # matches the resolution used by the process entrypoint.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "rule-catalog").is_dir():
            return parent
    return Path.cwd()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-rule-collect",
        description=(
            "Fetch a rule-catalog source at its pinned revision, hash the "
            "resulting tree, and write a snapshot under "
            "rule-catalog/sources/<id>/<revision>/. Parser + normalization "
            "stages ship in follow-up phases; this CLI only guarantees a "
            "deterministic, provenance-stamped snapshot."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the source manifest YAML.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + hash but skip writing snapshot bytes.",
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
        help="Override snapshot output root (defaults to <repo>/rule-catalog/sources).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "After snapshot, run the parser + loader end-to-end and report "
            "any schema / cross-reference issues. Currently only rule-yaml "
            "sources are verifiable; other parsers exit with a typed error."
        ),
    )
    parser.add_argument(
        "--catalog-root",
        type=Path,
        default=None,
        help=(
            "Root of the target rule-catalog for --verify cross-references "
            "(defaults to <repo>/rule-catalog). ActionType + resource-type "
            "vocabulary are read from this root."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root or _repo_root()

    try:
        pipeline = CollectorPipeline(
            repo_root=repo_root,
            output_root=args.output_root,
        )
        report = pipeline.collect_from_manifest_path(args.manifest, dry_run=args.dry_run)
    except (ManifestError, FetchError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary: dict[str, object] = {
        "source_id": report.source_id,
        "resolved_revision": report.resolved_revision,
        "content_sha256": report.content_sha256,
        "file_count": report.file_count,
        "parser": report.parser,
        "license": report.license,
        "snapshot_dir": str(report.snapshot_dir),
        "mismatch": report.mismatch,
        "dry_run": args.dry_run,
    }

    exit_code = 0
    if report.mismatch:
        exit_code = 2

    if args.verify and exit_code == 0:
        verify_summary, verify_code = _run_verify(
            report_snapshot_dir=report.snapshot_dir,
            parser_name=report.parser,
            catalog_root=args.catalog_root or (repo_root / "rule-catalog"),
            dry_run=args.dry_run,
        )
        summary["verify"] = verify_summary
        if verify_code != 0:
            exit_code = verify_code

    print(json.dumps(summary, indent=2, sort_keys=True))
    return exit_code


def _run_verify(
    *,
    report_snapshot_dir: Path,
    parser_name: str,
    catalog_root: Path,
    dry_run: bool,
) -> tuple[dict[str, object], int]:
    """Parse + verify the just-collected snapshot.

    Returns ``(summary_dict, exit_code)``. Verify is skipped in dry-run
    mode because the snapshot bytes are not on disk (there is nothing
    to parse against a stable path).
    """
    if dry_run:
        return ({"skipped": "dry-run", "issues": []}, 0)

    try:
        parser_impl = build_parser(parser_name)
    except (ParseError, ParserNotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ({"error": str(exc), "issues": []}, 2)

    tree_root = report_snapshot_dir / "tree"
    try:
        parsed = parser_impl.parse(tree_root)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ({"error": str(exc), "issues": []}, 2)

    action_types_root = catalog_root / "action-types"
    vocab_file = catalog_root / "vocabulary" / "resource-types.yaml"
    if not action_types_root.is_dir() or not vocab_file.is_file():
        message = (
            f"catalog root missing action-types/ or vocabulary/resource-types.yaml "
            f"under {catalog_root!r}"
        )
        print(f"error: {message}", file=sys.stderr)
        return ({"error": message, "issues": []}, 2)

    schema_registry = PackageResourceSchemaRegistry()
    probes_root = catalog_root / "probes"
    action_types = load_ontology_catalog(
        catalog_root,
        schema_registry=schema_registry,
        probes_root=probes_root if probes_root.is_dir() else None,
    ).action_types
    with vocab_file.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))

    verification = verify_parsed_rules(
        parsed.rules,
        schema_registry=schema_registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=catalog_root.parent / "policies",
        remediation_root=catalog_root / "remediation",
    )

    issues_payload = [
        {"origin": issue.origin, "key": issue.key, "message": issue.message}
        for issue in verification.issues
    ]
    summary = {
        "parser": parser_name,
        "parsed": parsed.rule_count,
        "verified": verification.verified_count,
        "issues": issues_payload,
    }
    return (summary, 0 if verification.passed else 2)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = ["main"]

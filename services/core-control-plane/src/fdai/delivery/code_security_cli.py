"""Operator CLI for code-security findings and remediation packs.

``export`` ingests one or more SARIF documents (from FDAI's deterministic lane, Microsoft MDASH,
GitHub code scanning, Opengrep, Trivy, or another SARIF 2.1.0 producer), builds canonical issues
with one severity per root cause, and writes a remediation pack plus FDAI's own pack record. Keep
the record where developers cannot edit it; ``import-result`` uses it to validate the result file
that a coding-agent session returns.

Example::

    python -m fdai.delivery.code_security_cli export \
        --sarif mdash.sarif:external --sarif opengrep.sarif:deterministic \
        --revision <40-hex commit> --repo-alias payments-api --out ./packs

    python -m fdai.delivery.code_security_cli import-result \
        --record ./packs/fdai-remediation-<id>.record.json \
        --result <pack>/result/remediation-result.json

The CLI performs no network calls and grants no execution authority.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.security.code_findings import (
    AnalysisContext,
    Lane,
    Occurrence,
    PackMode,
    PackRecord,
    PackRequest,
    ProjectRoot,
    RemediationResultRejectedError,
    SarifIngestContext,
    SarifIngestError,
    build_issues,
    import_remediation_result,
    ingest_sarif,
    render_remediation_pack,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import (
    CodeSecurityCatalogError,
    Exposure,
    load_code_security_catalog,
)

_UPLOAD = (
    "Return result/remediation-result.json to your FDAI operator. The operator validates it with "
    "`python -m fdai.delivery.code_security_cli import-result`."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-code-security")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="build a remediation pack from SARIF")
    export.add_argument("--sarif", action="append", required=True, help="FILE:LANE")
    export.add_argument("--revision", required=True)
    export.add_argument("--repo-alias", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--mode", choices=[mode.value for mode in PackMode], default="full")
    export.add_argument("--exposure", choices=[item.value for item in Exposure], default="unknown")
    export.add_argument("--known-exploited", help="file with one advisory id per line")
    export.add_argument("--projects", help="JSON list of project roots")
    export.add_argument("--source-root", action="append", default=[])
    export.add_argument("--coverage-limit", action="append", default=[])
    export.add_argument(
        "--catalog-root", default=str(repo_asset_root() / "rule-catalog" / "code-security")
    )
    result = sub.add_parser("import-result", help="validate a returned remediation result")
    result.add_argument("--record", required=True)
    result.add_argument("--result", required=True)
    return parser


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _export(args: argparse.Namespace) -> dict[str, object]:
    catalog = load_code_security_catalog(Path(args.catalog_root))
    occurrences: list[Occurrence] = []
    dropped: dict[str, int] = {}
    for spec in args.sarif:
        file_name, _, lane = spec.rpartition(":")
        ingested = ingest_sarif(
            Path(file_name).read_bytes(),
            SarifIngestContext(
                lane=Lane(lane), revision=args.revision, source_roots=tuple(args.source_root)
            ),
        )
        occurrences.extend(ingested.occurrences)
        for item in ingested.dropped:
            dropped[item.reason] = dropped.get(item.reason, 0) + 1
    known = frozenset(
        line.strip()
        for line in (
            Path(args.known_exploited).read_text().splitlines() if args.known_exploited else []
        )
        if line.strip()
    )
    issues = build_issues(
        occurrences,
        catalog,
        AnalysisContext(
            revision=args.revision, exposure=Exposure(args.exposure), known_exploited=known
        ),
    )
    projects = tuple(
        ProjectRoot(**entry)
        for entry in (json.loads(Path(args.projects).read_text()) if args.projects else [])
    )
    limits = list(args.coverage_limit)
    if dropped:
        limits.append(
            "Scanner results not ingested: "
            + ", ".join(f"{reason}={count}" for reason, count in sorted(dropped.items()))
        )
    pack = render_remediation_pack(
        issues,
        catalog,
        PackRequest(
            repository_alias=args.repo_alias,
            base_commit=args.revision,
            created_at=datetime.now(UTC),
            mode=PackMode(args.mode),
            coverage_limits=tuple(limits),
            project_roots=projects,
            upload_instructions=_UPLOAD,
        ),
    )
    out = Path(args.out)
    root = out / pack.directory_name
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for relative, data in pack.files.items():
        _write_private(root / relative, data)
    record = {
        "pack_id": pack.pack_id,
        "manifest_sha256": pack.manifest_sha256,
        "base_commit": args.revision,
        "issue_ids": list(pack.issue_ids),
        "expires_at": pack.expires_at.isoformat(),
        "revoked": False,
    }
    record_path = out / f"{pack.directory_name}.record.json"
    _write_private(record_path, (json.dumps(record, indent=2) + "\n").encode())
    return {
        "ok": True,
        "pack_dir": str(out / pack.directory_name),
        "record": str(record_path),
        "occurrences": len(occurrences),
        "issues": len(issues),
        "issues_in_pack": len(pack.issue_ids),
        "dropped": dropped,
    }


def _import(args: argparse.Namespace) -> dict[str, object]:
    record_doc = json.loads(Path(args.record).read_text())
    record = PackRecord(
        pack_id=record_doc["pack_id"],
        manifest_sha256=record_doc["manifest_sha256"],
        base_commit=record_doc["base_commit"],
        issue_ids=frozenset(record_doc["issue_ids"]),
        expires_at=datetime.fromisoformat(record_doc["expires_at"]),
        revoked=bool(record_doc.get("revoked", False)),
    )
    imported = import_remediation_result(Path(args.result).read_bytes(), record, datetime.now(UTC))
    return {
        "ok": True,
        "pack_id": imported.pack_id,
        "final_head": imported.final_head,
        "claims": [
            {
                "issue_id": claim.issue_id,
                "status": claim.status.value,
                "validation": claim.validation.value,
                "commits": list(claim.commits),
                "next_step": claim.next_step.value,
            }
            for claim in imported.claims
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = _export(args) if args.command == "export" else _import(args)
    except RemediationResultRejectedError as exc:
        output = {"ok": False, "reason": exc.reason, "error": str(exc)}
    except (CodeSecurityCatalogError, SarifIngestError, ValueError, OSError, KeyError) as exc:
        output = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(output, indent=2))
    return 0 if output.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

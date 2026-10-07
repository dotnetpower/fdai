"""Review commands of the code-security operator CLI.

``import-result`` binds a returned result to the registry record. ``verify-fixes`` rescans the
claimed commit's SARIF against the export-time baseline receipt and records ``fixed_verified``,
``still_present``, or ``inconclusive`` per claim. ``adjudicate`` records a human decision on a
false-positive claim with an approval reference. Every review record is appended to the
registry's immutable review log.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.security.code_findings import (
    AnalysisContext,
    Lane,
    RemediationResultRejectedError,
    SarifIngestContext,
    build_issues,
    import_remediation_result,
    ingest_sarif,
)
from fdai.core.security.code_findings.adjudication import (
    AdjudicationDecision,
    adjudicate_false_positive,
)
from fdai.core.security.code_findings.receipts import (
    baseline_from_dict,
    build_receipt,
    receipt_from_dict,
)
from fdai.core.security.code_findings.result_import import ImportedRemediationResult
from fdai.core.security.code_findings.verification import verify_fix_claims
from fdai.delivery.persistence.state_store_code_security_registry import open_pack_registry
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.shared.providers.remediation_pack import PackRegistryError, RemediationPackRegistry

_REGISTRY_HELP = "registry directory, or `state-store` for FDAI_STATE_STORE_DSN"


def pairs(values: list[str]) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` options."""
    parsed = {}
    for value in values:
        key, sep, item = value.partition("=")
        if not sep or not key or not item:
            raise ValueError(f"expected KEY=VALUE, got {value!r}")
        parsed[key] = item
    return parsed


def add_review_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    result = sub.add_parser("import-result", help="validate a returned remediation result")
    result.add_argument("--registry", required=True, help=_REGISTRY_HELP)
    result.add_argument("--result", required=True)
    verify = sub.add_parser("verify-fixes", help="verify fix claims with an equivalent rescan")
    verify.add_argument("--registry", required=True, help=_REGISTRY_HELP)
    verify.add_argument("--result", required=True)
    verify.add_argument("--rescan-sarif", action="append", required=True, help="FILE:LANE")
    verify.add_argument("--rescan-revision", required=True)
    verify.add_argument("--rules-version", action="append", default=[], help="PRODUCER=VERSION")
    verify.add_argument("--full-repository", action="append", default=[], help="PRODUCER")
    verify.add_argument("--supersedes", action="append", default=[], help="PRODUCER=OLD_VERSION")
    verify.add_argument("--source-root", action="append", default=[])
    verify.add_argument("--catalog-root", required=True)
    adjudicate = sub.add_parser("adjudicate", help="decide a false-positive claim")
    adjudicate.add_argument("--registry", required=True, help=_REGISTRY_HELP)
    adjudicate.add_argument("--result", required=True)
    adjudicate.add_argument("--issue", required=True)
    adjudicate.add_argument(
        "--decision", choices=[d.value for d in AdjudicationDecision], required=True
    )
    adjudicate.add_argument("--claimant", required=True)
    adjudicate.add_argument("--adjudicator", required=True)
    adjudicate.add_argument("--approval-ref", required=True)
    adjudicate.add_argument("--rationale", required=True)
    adjudicate.add_argument("--single-operator", action="store_true")


def _imported(registry: RemediationPackRegistry, result_path: str) -> ImportedRemediationResult:
    raw = Path(result_path).read_bytes()
    try:
        pack_id = str(json.loads(raw)["pack_id"])
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise RemediationResultRejectedError("malformed_result") from exc
    record = asyncio.run(registry.get(pack_id))
    if record is None:
        raise RemediationResultRejectedError("unknown_pack")
    return import_remediation_result(raw, record, datetime.now(UTC))


def import_result(args: argparse.Namespace) -> dict[str, object]:
    imported = _imported(open_pack_registry(args.registry), args.result)
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


def verify_fixes(args: argparse.Namespace) -> dict[str, object]:
    registry = open_pack_registry(args.registry)
    imported = _imported(registry, args.result)
    baseline = asyncio.run(registry.get_baseline(imported.pack_id))
    if baseline is None:
        raise PackRegistryError(f"pack {imported.pack_id} has no baseline receipt")
    catalog = load_code_security_catalog(Path(args.catalog_root))
    ingested = []
    for spec in args.rescan_sarif:
        file_name, _, lane = spec.rpartition(":")
        ingested.append(
            ingest_sarif(
                Path(file_name).read_bytes(),
                SarifIngestContext(
                    lane=Lane(lane),
                    revision=args.rescan_revision,
                    source_roots=tuple(args.source_root),
                ),
            )
        )
    rescan_issues = build_issues(
        [occ for result in ingested for occ in result.occurrences],
        catalog,
        AnalysisContext(revision=args.rescan_revision),
    )
    supersedes = {k: frozenset({v}) for k, v in pairs(args.supersedes).items()}
    rescan = build_receipt(
        args.rescan_revision,
        catalog.version_stamp(),
        ingested,
        rules_versions=pairs(args.rules_version),
        full_repository=frozenset(args.full_repository),
        supersedes=supersedes,
    )
    verdicts = verify_fix_claims(
        imported.claims,
        baseline_from_dict(baseline["issues"]),
        receipt_from_dict(baseline["receipt"]),
        rescan,
        rescan_issues,
        imported.final_head,
    )
    rows = [
        {
            "issue_id": item.issue_id,
            "claim": item.claim.value,
            "verdict": item.verdict.value,
            "reasons": list(item.reasons),
        }
        for item in verdicts
    ]
    asyncio.run(
        registry.append_review(
            imported.pack_id,
            {"kind": "fix_verification", "rescan_revision": args.rescan_revision, "verdicts": rows},
        )
    )
    return {"ok": True, "pack_id": imported.pack_id, "verdicts": rows}


def adjudicate(args: argparse.Namespace) -> dict[str, object]:
    registry = open_pack_registry(args.registry)
    imported = _imported(registry, args.result)
    claim = next((c for c in imported.claims if c.issue_id == args.issue), None)
    if claim is None:
        raise ValueError(f"result has no claim for {args.issue}")
    record = adjudicate_false_positive(
        claim,
        pack_id=imported.pack_id,
        claimant=args.claimant,
        adjudicator=args.adjudicator,
        approval_ref=args.approval_ref,
        decision=AdjudicationDecision(args.decision),
        rationale=args.rationale,
        decided_at=datetime.now(UTC),
        single_operator_profile=args.single_operator,
    )
    document = {
        "kind": "false_positive_adjudication",
        "issue_id": record.issue_id,
        "decision": record.decision.value,
        "issue_disposition": record.issue_disposition,
        "claimant": record.claimant,
        "adjudicator": record.adjudicator,
        "approval_ref": record.approval_ref,
        "rationale": record.rationale,
        "single_operator_profile": record.single_operator_profile,
        "decided_at": record.decided_at.isoformat(),
    }
    asyncio.run(registry.append_review(imported.pack_id, document))
    return {"ok": True, "pack_id": imported.pack_id, **document}


__all__ = ["add_review_commands", "adjudicate", "import_result", "pairs", "verify_fixes"]

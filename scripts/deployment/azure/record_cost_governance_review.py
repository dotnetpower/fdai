#!/usr/bin/env python3
"""Record one authority-neutral review of exact Cost Governance evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from fdai.delivery.persistence.postgres_cost_governance_review import (
    PostgresCostPromotionReviewStore,
)
from fdai.shared.providers.cost_governance_review import (
    CostPromotionReview,
    CostPromotionReviewStore,
    CostReviewDecision,
    CostReviewTargetKind,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_INPUT_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class ReadyCostReviewTarget:
    """One exact target selected from a complete review-ready campaign."""

    campaign_id: str
    campaign_evidence_digest: str
    revision_pin_digest: str
    campaign_report_digest: str
    target_kind: CostReviewTargetKind
    target_id: str


def load_ready_cost_review_target(
    path: Path,
    *,
    target_kind: CostReviewTargetKind,
    target_id: str,
) -> ReadyCostReviewTarget:
    """Load one target only when the complete six-target campaign is ready."""

    document, campaign_evidence_digest = _load_json_with_digest(path)
    if set(document) != {"campaign_id", "ready", "revision_pin_digest", "targets"}:
        raise ValueError("Cost review readiness fields are invalid")
    if document["ready"] is not True:
        raise ValueError("Cost review campaign MUST be ready")
    campaign_id = _text(document, "campaign_id")
    revision_pin_digest = _digest(document, "revision_pin_digest")
    raw_targets = document["targets"]
    if not isinstance(raw_targets, list) or len(raw_targets) != 6:
        raise ValueError("Cost review readiness MUST contain six independent targets")
    validated_targets = _validated_targets(raw_targets)
    matches = [
        item
        for item in validated_targets
        if item["target_kind"] == target_kind.value and item["target_id"] == target_id
    ]
    if len(matches) != 1:
        raise ValueError("Cost review target MUST appear exactly once")
    report_digest = matches[0]["campaign_report_digest"]
    return ReadyCostReviewTarget(
        campaign_id=campaign_id,
        campaign_evidence_digest=campaign_evidence_digest,
        revision_pin_digest=revision_pin_digest,
        campaign_report_digest=report_digest,
        target_kind=target_kind,
        target_id=target_id,
    )


async def record_cost_promotion_review(
    *,
    ready_target: ReadyCostReviewTarget,
    request_id: str,
    reviewer_identity: str,
    decision: CostReviewDecision,
    rationale: str,
    reviewed_at: datetime,
    retention_days: int,
    evidence_refs: tuple[str, ...],
    store: CostPromotionReviewStore,
) -> tuple[CostPromotionReview, bool]:
    """Append one target review without granting approval or promotion authority."""

    if not 90 <= retention_days <= 2_555:
        raise ValueError("Cost review retention_days MUST be in [90, 2555]")
    review = CostPromotionReview(
        schema_version="1.0.0",
        request_id=request_id,
        campaign_id=ready_target.campaign_id,
        campaign_evidence_digest=ready_target.campaign_evidence_digest,
        revision_pin_digest=ready_target.revision_pin_digest,
        campaign_report_digest=ready_target.campaign_report_digest,
        target_kind=ready_target.target_kind,
        target_id=ready_target.target_id,
        reviewer_identity=reviewer_identity,
        decision=decision,
        rationale=rationale,
        reviewed_at=reviewed_at,
        evidence_refs=tuple(
            dict.fromkeys(
                (*evidence_refs, f"campaign-report:{ready_target.campaign_report_digest}")
            )
        ),
        retention_until=reviewed_at + timedelta(days=retention_days),
    )
    inserted = await store.append_cost_promotion_review(review)
    return review, inserted


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--target-kind", choices=tuple(CostReviewTargetKind), required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--decision", choices=tuple(CostReviewDecision), required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--evidence-ref", action="append", required=True)
    return parser


async def _run(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    *,
    reviewed_at: datetime,
) -> dict[str, object]:
    dsn = environ.get("FDAI_STATE_STORE_DSN", "").strip()
    reviewer_identity = environ.get("FDAI_COST_REVIEWER_IDENTITY", "").strip()
    if not dsn:
        raise ValueError("FDAI_STATE_STORE_DSN MUST be configured")
    if not reviewer_identity:
        raise ValueError("FDAI_COST_REVIEWER_IDENTITY MUST be configured")
    ready_target = load_ready_cost_review_target(
        args.readiness,
        target_kind=CostReviewTargetKind(args.target_kind),
        target_id=args.target_id,
    )
    review, inserted = await record_cost_promotion_review(
        ready_target=ready_target,
        request_id=args.request_id,
        reviewer_identity=reviewer_identity,
        decision=CostReviewDecision(args.decision),
        rationale=args.rationale,
        reviewed_at=reviewed_at,
        retention_days=_retention_days(args.policy),
        evidence_refs=tuple(args.evidence_ref),
        store=PostgresCostPromotionReviewStore(dsn=dsn),
    )
    return {
        "inserted": inserted,
        "review": {**review.to_mapping(), "review_id": review.review_id},
    }


def _load_json(path: Path) -> dict[str, Any]:
    return _load_json_with_digest(path)[0]


def _load_json_with_digest(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("Cost review input is unavailable or too large")
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cost review input is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Cost review input MUST contain an object")
    return value, f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _validated_targets(values: list[object]) -> tuple[dict[str, str], ...]:
    targets: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Cost review target record is invalid")
        kind = value.get("target_kind")
        target_id = value.get("target_id")
        decision = value.get("decision")
        report_digest = value.get("campaign_report_digest")
        if (
            not isinstance(kind, str)
            or kind not in CostReviewTargetKind
            or not isinstance(target_id, str)
            or not target_id
            or decision != "ready-for-independent-review"
            or not isinstance(report_digest, str)
            or _DIGEST.fullmatch(report_digest) is None
        ):
            raise ValueError("Cost review target record is invalid")
        targets.append(
            {
                "campaign_report_digest": report_digest,
                "target_id": target_id,
                "target_kind": kind,
            }
        )
    identities = {(item["target_kind"], item["target_id"]) for item in targets}
    kind_counts = Counter(item["target_kind"] for item in targets)
    if len(identities) != 6 or kind_counts != {
        CostReviewTargetKind.PACKAGE_ACTIVATION.value: 1,
        CostReviewTargetKind.ACTION_TYPE.value: 4,
        CostReviewTargetKind.WORKFLOW.value: 1,
    }:
        raise ValueError("Cost review target set is invalid")
    return tuple(targets)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Cost review input contains duplicate JSON keys")
        result[key] = value
    return result


def _text(document: Mapping[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"Cost review {name} is invalid")
    return value


def _digest(document: Mapping[str, object], name: str) -> str:
    value = _text(document, name)
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"Cost review {name} is invalid")
    return value


def _retention_days(path: Path) -> int:
    policy = _load_json(path)
    value = policy.get("retention_days")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Cost review policy retention_days is invalid")
    return value


def main(argv: list[str] | None = None) -> int:
    """Run one protected review-only record append."""

    try:
        result = asyncio.run(
            _run(
                _parser().parse_args(argv),
                os.environ,
                reviewed_at=datetime.now(tz=UTC),
            )
        )
    except psycopg.Error:
        print("Cost review database is unavailable", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Cost review failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ReadyCostReviewTarget",
    "load_ready_cost_review_target",
    "main",
    "record_cost_promotion_review",
]

"""Import and evaluate exact-revision Cost Governance W7 evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from fdai.delivery.persistence.postgres_cost_governance_validation import (
    PostgresCostGovernanceValidationStore,
)
from fdai.shared.providers.cost_governance_campaign import CostCampaignEpisode
from fdai.shared.providers.cost_governance_lifecycle import (
    CostLifecycleReceipt,
    CostRevisionPin,
)
from psycopg.rows import dict_row

from .campaign_import import (
    CostCampaignImportContext,
    import_cost_campaign_observations,
    load_cost_campaign_import_policy,
    load_cost_campaign_observation_batch,
)
from .review_targets import CostReadinessTarget, load_cost_readiness_targets
from .validation import (
    CostObservationCampaignReducer,
    CostPromotionReadinessGate,
    CostReadinessBlock,
    CostReadinessDecision,
    CostReadinessTargetKind,
)

_PACKAGE_ID = "cost-governance"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pin")
    importer = commands.add_parser("import")
    importer.add_argument("--batch", type=Path, required=True)
    importer.add_argument("--policy", type=Path, required=True)
    importer.add_argument("--catalog-root", type=Path, required=True)
    importer.add_argument("--source-workflow-path", required=True)
    importer.add_argument("--source-run-id", type=int, required=True)
    importer.add_argument("--source-run-attempt", type=int, required=True)
    importer.add_argument("--source-artifact-name", required=True)
    importer.add_argument("--imported-at")
    evaluator = commands.add_parser("evaluate")
    evaluator.add_argument("--campaign-id", required=True)
    evaluator.add_argument("--catalog-root", type=Path, required=True)
    evaluator.add_argument("--require-ready", action="store_true")
    return parser


async def _run(args: argparse.Namespace, environ: dict[str, str]) -> tuple[int, dict[str, object]]:
    dsn = environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise ValueError("FDAI_STATE_STORE_DSN MUST be configured")
    pin, enabled = await read_current_pin(dsn)
    if args.command == "pin":
        return 0, {
            "enabled": enabled,
            "revision_pin": pin.to_mapping(),
            "revision_pin_digest": pin.digest,
        }
    if not enabled:
        raise ValueError("Cost Governance package MUST be enabled for W7 campaign evidence")
    targets = load_cost_readiness_targets(args.catalog_root)
    store = PostgresCostGovernanceValidationStore(dsn=dsn)
    if args.command == "import":
        policy = load_cost_campaign_import_policy(args.policy)
        batch = load_cost_campaign_observation_batch(
            args.batch,
            maximum_episodes=policy.maximum_batch_episodes,
        )
        imported_at = (
            datetime.now(tz=UTC) if args.imported_at is None else _timestamp(args.imported_at)
        )
        report = await import_cost_campaign_observations(
            batch,
            revision_pin=pin,
            context=CostCampaignImportContext(
                source_workflow_path=args.source_workflow_path,
                source_run_id=args.source_run_id,
                source_run_attempt=args.source_run_attempt,
                source_artifact_name=args.source_artifact_name,
                imported_at=imported_at,
            ),
            policy=policy,
            allowed_target_ids=frozenset(
                item.target_id
                for item in targets
                if item.kind is not CostReadinessTargetKind.PACKAGE_ACTIVATION
            ),
            store=store,
        )
        return 0, report.to_mapping()

    receipts = await store.read_cost_lifecycle_receipts(_PACKAGE_ID, limit=10_000)
    episodes = await store.read_cost_campaign_episodes(
        args.campaign_id,
        pin.digest,
        limit=10_000,
    )
    result = evaluate_cost_campaign(
        campaign_id=args.campaign_id,
        revision_pin=pin,
        lifecycle_receipts=receipts,
        episodes=episodes,
        targets=targets,
    )
    return (3 if args.require_ready and not result["ready"] else 0), result


def evaluate_cost_campaign(
    *,
    campaign_id: str,
    revision_pin: CostRevisionPin,
    lifecycle_receipts: tuple[CostLifecycleReceipt, ...],
    episodes: tuple[CostCampaignEpisode, ...],
    targets: tuple[CostReadinessTarget, ...],
) -> dict[str, object]:
    """Evaluate every independent target and retain explicit missing-target blocks."""

    reducer = CostObservationCampaignReducer()
    gate = CostPromotionReadinessGate()
    results: list[dict[str, object]] = []
    for target in targets:
        review_target = (
            None if target.kind is CostReadinessTargetKind.PACKAGE_ACTIVATION else target.target_id
        )
        selected = tuple(
            episode
            for episode in episodes
            if review_target is None or review_target in episode.target_refs
        )
        if not selected:
            results.append(
                {
                    "blocks": [
                        CostReadinessBlock.INSUFFICIENT_COHORT.value,
                        CostReadinessBlock.MISSING_LIVE_AUTHORITATIVE_EVIDENCE.value,
                    ],
                    "campaign_report_digest": None,
                    "decision": CostReadinessDecision.BLOCKED.value,
                    "sample_count": 0,
                    "target_id": target.target_id,
                    "target_kind": target.kind.value,
                }
            )
            continue
        report = reducer.reduce(
            revision_pin,
            selected,
            review_target_id=review_target,
        )
        readiness = gate.evaluate(
            report=report,
            lifecycle_receipts=lifecycle_receipts,
            thresholds=target.thresholds,
            target_kind=target.kind,
            target_id=target.target_id,
        )
        results.append(
            {
                "accuracy": str(report.accuracy),
                "blocks": [item.value for item in readiness.blocks],
                "campaign_report_digest": report.digest,
                "decision": readiness.decision.value,
                "policy_escape_count": report.policy_escape_count,
                "sample_count": report.sample_count,
                "shadow_dwell_seconds": report.shadow_dwell_seconds,
                "target_id": target.target_id,
                "target_kind": target.kind.value,
                "unauthorized_disclosure_count": report.unauthorized_disclosure_count,
            }
        )
    ready = bool(results) and all(
        item["decision"] == CostReadinessDecision.READY_FOR_INDEPENDENT_REVIEW.value
        for item in results
    )
    return {
        "campaign_id": campaign_id,
        "ready": ready,
        "revision_pin_digest": revision_pin.digest,
        "targets": results,
    }


async def read_current_pin(dsn: str) -> tuple[CostRevisionPin, bool]:
    """Read the exact active release identity and enablement state."""

    pin, enabled, _effective_at = await read_current_activation(dsn)
    return pin, enabled


async def read_current_activation(dsn: str) -> tuple[CostRevisionPin, bool, datetime]:
    """Read the exact active release identity, enablement, and revision boundary."""

    async with await psycopg.AsyncConnection.connect(
        _psycopg_dsn(dsn),
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        cursor = await connection.execute(
            """
            SELECT package_id, package_version, source_revision, wheel_digest,
                   image_digest, asset_manifest_digest, semantic_profile_digest,
                   ontology_release_digest, runtime_config_digest, revision,
                   available, enabled, effective_at
              FROM vertical_package_activation
             WHERE package_id = %s
            """,
            (_PACKAGE_ID,),
        )
        row = await cursor.fetchone()
    if row is None or not row["available"]:
        raise ValueError("Cost Governance exact release is unavailable")
    try:
        pin = CostRevisionPin(
            package_id=str(row["package_id"]),
            package_version=str(row["package_version"]),
            source_revision=str(row["source_revision"]),
            wheel_digest=str(row["wheel_digest"]),
            image_digest=str(row["image_digest"]),
            asset_manifest_digest=str(row["asset_manifest_digest"]),
            semantic_profile_digest=str(row["semantic_profile_digest"]),
            ontology_release_digest=str(row["ontology_release_digest"]),
            runtime_config_digest=str(row["runtime_config_digest"]),
            activation_revision=int(row["revision"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Cost Governance exact release pin is incomplete") from exc
    effective_at = row["effective_at"]
    if not isinstance(effective_at, datetime) or effective_at.tzinfo is None:
        raise ValueError("Cost Governance activation effective time is incomplete")
    return pin, bool(row["enabled"]), effective_at.astimezone(UTC)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--imported-at MUST be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--imported-at MUST include a timezone")
    return parsed.astimezone(UTC)


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def main(argv: list[str] | None = None) -> int:
    """Run one trusted import or review-only evaluation."""

    try:
        status, result = asyncio.run(_run(_parser().parse_args(argv), dict(os.environ)))
    except psycopg.Error:
        print("Cost Governance validation database is unavailable", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Cost Governance validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "evaluate_cost_campaign",
    "main",
    "read_current_activation",
    "read_current_pin",
]

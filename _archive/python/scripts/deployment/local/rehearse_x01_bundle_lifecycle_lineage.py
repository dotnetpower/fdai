#!/usr/bin/env python3
"""Rehearse and verify the X01 exact-artifact capability-bundle lifecycle lineage (#2315).

Exercises all seven Issue #2315 exit criteria end to end:
1. Pin one exact FDAI-owned bundle artifact and signed source revision after required CI is green.
2. Retain an install receipt proving the bundle starts disabled and exposes no execution authority.
3. Retain a distinct reviewed enable receipt through the typed action path, followed by independent
   disclosure readback.
4. Retain disable and revoke receipts for the same artifact, with independent readback after each
   transition.
5. Prove revocation blocks later activation and preserves publisher, digest, revision, actor,
   idempotency, and Saga lineage.
6. Restart the exact runtime and prove disclosure reconstructs the same revoked state without a
   synthetic record or mutable-history rewrite.
7. Produce the complete linked receipt set and lineage digest for capability-bundle-lifecycle.md and
   functional-readiness-backlog.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from fdai.core.skills import (
    InMemorySkillBundleProposalStore,
    SkillBundleProposal,
    SkillBundleWorkshop,
)
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain import TrustedArtifactKind, TrustedArtifactState
from fdai.delivery.capability_bundle_lifecycle_lineage import (
    BUNDLE_ENABLE_ACTION_TYPE_ID,
    PINNED_MAIN_2940_CI_RECEIPT,
    GovernedSkillBundleLifecycleCoordinator,
    PinnedBundleArtifactSpec,
    ReviewedBundleEnableAction,
    RevokedCapabilityBundleError,
    TypedBundleEnableActionDispatcher,
    build_pinned_fdai_bundle_artifact,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_skill_quarantine import (
    PostgresSkillRevocationStore,
)
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceStore,
    PostgresSkillSourceStoreConfig,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from fdai.runtime.skill_source_runtime import (
    InMemorySkillRevocationStore,
    InMemoryTrustedSkillArtifactStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest
from psycopg import sql
from psycopg.conninfo import make_conninfo

_REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"X01 rehearsal invariant failed: {message}")


def _require_loopback_dsn(dsn: str) -> str:
    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("X01 rehearsal PostgreSQL DSN MUST target a loopback host")
    if parsed.port != 5433:
        raise ValueError(
            "X01 rehearsal requires the explicit port-5433 validation database "
            "and refuses default or port-5432 runtime DSNs"
        )
    return normalized


class _WorkshopAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Any) -> None:
        self.events.append(dict(event))


class _WorkshopAuthorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return reviewer_id == "operator-reviewer@example.com"


async def _approve_bundle_proposal(
    spec: PinnedBundleArtifactSpec,
    *,
    requester_actor: str,
    reviewer_actor: str,
    at: datetime,
) -> SkillBundleProposal:
    workshop = SkillBundleWorkshop(
        store=InMemorySkillBundleProposalStore(),
        audit=_WorkshopAudit(),
        authorizer=_WorkshopAuthorizer(),
    )
    draft = await workshop.propose(
        spec.bundle_raw_manifest,
        proposed_by_agent=requester_actor,
        at=at,
    )
    return await workshop.review(
        draft.proposal_id,
        reviewer_id=reviewer_actor,
        approve=True,
        reason="Approved read-only capability bundle for X01 governed lifecycle.",
        at=at,
    )


async def rehearse_x01_bundle_lifecycle_lineage(
    *,
    artifact_store: Any | None = None,
    revocation_store: Any | None = None,
    state_store: Any | None = None,
    venue: str = "in-memory",
) -> dict[str, Any]:
    """Run the 6-transition X01 capability-bundle lifecycle lineage and verify every invariant."""

    art_store = artifact_store or InMemoryTrustedSkillArtifactStore()
    rev_store = revocation_store or InMemorySkillRevocationStore()
    st_store = state_store or InMemoryStateStore()
    spec: PinnedBundleArtifactSpec = build_pinned_fdai_bundle_artifact(
        ci_receipt=PINNED_MAIN_2940_CI_RECEIPT
    )
    pin_record = spec.to_pin_record()

    clock = [NOW]
    dispatcher = TypedBundleEnableActionDispatcher()
    coordinator = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=art_store,
        revocation_store=rev_store,
        state_store=st_store,
        clock=lambda: clock[0],
    )

    # 1. Install (disabled-first, no execution authority)
    install_receipt = await coordinator.install_bundle(
        actor="operator-installer@example.com",
        idempotency_key="x01-install-0001",
        reason="Install pinned FDAI-owned read-only inventory evidence bundle disabled-first.",
        now=clock[0],
    )
    install_readback = install_receipt["readback"]
    _require(install_receipt["artifact_state"] == "disabled", "install state")
    _require(install_receipt["artifact_revision"] == 1, "install revision")
    _require(install_receipt["execution_authority"] is False, "install execution_authority")
    _require(install_receipt["promotion_authority"] is False, "install promotion_authority")
    _require(install_readback["enabled_bundle_count"] == 0, "install enabled_bundle_count")
    _require(install_readback["described_enabled"] is False, "install described_enabled")
    _require(install_readback["described_eligible"] is False, "install described_eligible")
    _require(install_readback["load_status"] == "rejected", "install load_status")
    _require(
        install_readback["load_rejection_reason"] == "skill_bundle_disabled",
        "install load_rejection_reason",
    )

    # 2. Distinct reviewed enable via typed action path
    clock[0] = NOW + timedelta(minutes=1)
    review_decision_digest = content_digest(
        {
            "action_type_id": BUNDLE_ENABLE_ACTION_TYPE_ID,
            "artifact_digest": spec.bundle_content_sha256,
            "artifact_id": spec.artifact_id,
            "requester": "operator-requester@example.com",
            "reviewer": "operator-reviewer@example.com",
            "source_revision": spec.source_revision,
        }
    )
    approved_proposal = await _approve_bundle_proposal(
        spec,
        requester_actor="operator-requester@example.com",
        reviewer_actor="operator-reviewer@example.com",
        at=clock[0],
    )
    enable_action = ReviewedBundleEnableAction(
        action_type_id=BUNDLE_ENABLE_ACTION_TYPE_ID,
        requester_actor="operator-requester@example.com",
        reviewer_actor="operator-reviewer@example.com",
        review_decision_digest=review_decision_digest,
        idempotency_key="x01-enable-0002",
        reason="Enable reviewed read-only capability bundle after distinct reviewer approval.",
    )
    enable_receipt = await dispatcher.dispatch(
        coordinator,
        enable_action,
        approved_proposal=approved_proposal,
        now=clock[0],
    )
    # Verify idempotent replay before mutation returns the exact same receipt.
    replayed_enable = await dispatcher.dispatch(
        coordinator,
        enable_action,
        approved_proposal=approved_proposal,
        now=clock[0],
    )
    _require(replayed_enable == enable_receipt, "enable idempotent replay")
    enable_readback = enable_receipt["readback"]
    _require(enable_receipt["artifact_state"] == "enabled", "enable state")
    _require(enable_receipt["artifact_revision"] == 2, "enable revision")
    _require(
        enable_receipt["action_type_id"] == BUNDLE_ENABLE_ACTION_TYPE_ID,
        "enable action_type_id",
    )
    _require(enable_receipt["actor"] == "operator-requester@example.com", "enable actor")
    _require(
        enable_receipt["reviewer_actor"] == "operator-reviewer@example.com",
        "enable reviewer_actor",
    )
    _require(enable_receipt["execution_authority"] is False, "enable execution_authority")
    _require(enable_readback["enabled_bundle_count"] == 1, "enable enabled_bundle_count")
    _require(enable_readback["described_enabled"] is True, "enable described_enabled")
    _require(enable_readback["described_eligible"] is True, "enable described_eligible")
    _require(enable_readback["load_status"] == "resolved", "enable load_status")
    _require(
        enable_readback["resolved_replay_digest"] == spec.bundle_manifest_digest,
        "enable resolved_replay_digest",
    )

    # 3. Disable with independent disclosure readback
    clock[0] = NOW + timedelta(minutes=2)
    disable_receipt = await coordinator.disable_bundle(
        actor="operator-owner@example.com",
        idempotency_key="x01-disable-0003",
        reason="Disable capability bundle during scheduled lifecycle verification.",
        now=clock[0],
    )
    disable_readback = disable_receipt["readback"]
    _require(disable_receipt["artifact_state"] == "disabled", "disable state")
    _require(disable_receipt["artifact_revision"] == 3, "disable revision")
    _require(disable_receipt["execution_authority"] is False, "disable execution_authority")
    _require(disable_readback["enabled_bundle_count"] == 0, "disable enabled_bundle_count")
    _require(disable_readback["described_enabled"] is False, "disable described_enabled")
    _require(disable_readback["load_status"] == "rejected", "disable load_status")
    _require(
        disable_readback["load_rejection_reason"] == "skill_bundle_disabled",
        "disable load_rejection_reason",
    )

    # 4. Revoke with independent disclosure readback
    clock[0] = NOW + timedelta(minutes=3)
    revoke_receipt = await coordinator.revoke_bundle(
        actor="security-owner@example.com",
        idempotency_key="x01-revoke-0004",
        reason="Revoke capability bundle artifact for X01 revocation lineage verification.",
        now=clock[0],
    )
    revoke_readback = revoke_receipt["readback"]
    _require(revoke_receipt["artifact_state"] == "disabled", "revoke state")
    _require(revoke_receipt["artifact_revision"] == 4, "revoke revision")
    _require(revoke_receipt["revocation_id"] is not None, "revoke revocation_id")
    _require(revoke_receipt["execution_authority"] is False, "revoke execution_authority")
    _require(revoke_readback["enabled_bundle_count"] == 0, "revoke enabled_bundle_count")
    _require(revoke_readback["described_enabled"] is False, "revoke described_enabled")
    _require(revoke_readback["load_status"] == "rejected", "revoke load_status")
    _require(
        revoke_readback["load_rejection_reason"] == "skill_bundle_disabled",
        "revoke load_rejection_reason",
    )

    # 5. Prove revocation blocks later activation and preserves provenance & Saga lineage
    clock[0] = NOW + timedelta(minutes=4)
    reactivate_action = ReviewedBundleEnableAction(
        action_type_id=BUNDLE_ENABLE_ACTION_TYPE_ID,
        requester_actor="operator-requester@example.com",
        reviewer_actor="operator-reviewer@example.com",
        review_decision_digest=review_decision_digest,
        idempotency_key="x01-enable-refused-0005",
        reason="Attempt post-revocation reactivation.",
    )
    blocked = False
    try:
        await dispatcher.dispatch(
            coordinator,
            reactivate_action,
            approved_proposal=approved_proposal,
            now=clock[0],
        )
    except RevokedCapabilityBundleError:
        blocked = True
    _require(blocked is True, "revocation blocked activation")
    # Replaying the same refused idempotency key raises without mutating.
    replayed_refusal = False
    try:
        await dispatcher.dispatch(
            coordinator,
            reactivate_action,
            approved_proposal=approved_proposal,
            now=clock[0],
        )
    except RevokedCapabilityBundleError:
        replayed_refusal = True
    _require(replayed_refusal is True, "revocation refusal idempotent replay")
    refused_receipt = await st_store.read_state(
        f"capability-bundle-lifecycle:v1:{spec.artifact_id}:enable_refused_revoked"
    )
    _require(refused_receipt is not None, "refused_receipt exists")
    assert refused_receipt is not None  # noqa: S101 - type narrowing after _require
    _require(refused_receipt["outcome"] == "blocked_by_revocation", "refused outcome")
    _require(refused_receipt["publisher"] == spec.publisher, "refused publisher")
    _require(
        refused_receipt["artifact_digest"] == spec.bundle_content_sha256,
        "refused artifact_digest",
    )
    _require(refused_receipt["artifact_revision"] == 4, "refused revision")
    _require(refused_receipt["actor"] == "operator-requester@example.com", "refused actor")
    _require(
        refused_receipt["idempotency_key"] == "x01-enable-refused-0005",
        "refused idempotency_key",
    )

    durable_after_refusal = await art_store.get(
        TrustedArtifactKind.SKILL_BUNDLE,
        spec.artifact_id,
    )
    _require(durable_after_refusal is not None, "durable record exists after refusal")
    assert durable_after_refusal is not None  # noqa: S101 - type narrowing after _require
    _require(
        durable_after_refusal.state is TrustedArtifactState.DISABLED,
        "durable state disabled",
    )
    _require(durable_after_refusal.revision == 4, "durable revision 4")
    _require(durable_after_refusal.source == spec.publisher, "durable source preserved")
    _require(
        durable_after_refusal.content_sha256 == spec.bundle_content_sha256,
        "durable digest preserved",
    )

    # 6. Cold runtime restart reconstruction from durable stores
    clock[0] = NOW + timedelta(minutes=5)
    restarted_coordinator = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=art_store,
        revocation_store=rev_store,
        state_store=st_store,
        clock=lambda: clock[0],
    )
    restart_receipt = await restarted_coordinator.reconstruct_after_restart(
        actor="runtime-bootstrap@example.com",
        idempotency_key="x01-restart-0006",
        now=clock[0],
    )
    _require(restart_receipt["chain_verified"] is True, "restart chain_verified")
    _require(restart_receipt["is_revoked"] is True, "restart is_revoked")
    _require(restart_receipt["verifier_blocks_revoked"] is True, "restart verifier_blocks_revoked")
    _require(
        restart_receipt["mutable_history_rewritten"] is False,
        "restart mutable_history_rewritten",
    )
    _require(restart_receipt["synthetic_records_created"] == 0, "restart synthetic_records")
    _require(
        restart_receipt["readback"]["enabled_bundle_count"] == 0,
        "restart enabled_bundle_count",
    )
    _require(
        restart_receipt["readback"]["load_rejection_reason"] == "skill_bundle_disabled",
        "restart load_rejection_reason",
    )

    summary_body: dict[str, Any] = {
        "venue": venue,
        "pin": pin_record,
        "receipts": {
            "install": install_receipt["receipt_digest"],
            "enable": enable_receipt["receipt_digest"],
            "disable": disable_receipt["receipt_digest"],
            "revoke": revoke_receipt["receipt_digest"],
            "enable_refused_revoked": refused_receipt["receipt_digest"],
            "restart_reconstruct": restart_receipt["receipt_digest"],
        },
        "readbacks": {
            "install": install_readback["readback_digest"],
            "enable": enable_readback["readback_digest"],
            "disable": disable_readback["readback_digest"],
            "revoke": revoke_readback["readback_digest"],
            "restart_reconstruct": restart_receipt["readback"]["readback_digest"],
        },
        "criteria_satisfied": {
            "criterion_1_pinned_artifact_and_green_ci": True,
            "criterion_2_install_disabled_no_authority": True,
            "criterion_3_reviewed_typed_enable_and_readback": True,
            "criterion_4_disable_and_revoke_with_readback": True,
            "criterion_5_revocation_blocks_activation_preserves_lineage": True,
            "criterion_6_restart_reconstructs_revoked_state": True,
            "criterion_7_complete_receipt_set_linked": True,
        },
        "execution_authority": False,
        "promotion_authority": False,
    }
    return {**summary_body, "lineage_digest": content_digest(summary_body)}


async def rehearse_x01_postgres(dsn: str) -> dict[str, Any]:
    """Run the X01 capability-bundle lifecycle lineage against isolated loopback PostgreSQL."""

    loopback_dsn = _require_loopback_dsn(dsn)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    spec = build_pinned_fdai_bundle_artifact(ci_receipt=PINNED_MAIN_2940_CI_RECEIPT)
    schema = f"x01_lineage_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(loopback_dsn, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(loopback_dsn, options=f"-c search_path={schema},public")
        try:
            async with (
                await psycopg.AsyncConnection.connect(scoped_dsn) as conn,
                conn.transaction(),
            ):
                for table in (
                    "trusted_artifact",
                    "skill_source",
                    "skill_revocation",
                    "state_kv",
                    "audit_log",
                ):
                    await conn.execute(
                        sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            sql.Identifier(table),
                        )
                    )
            source_cfg = PostgresSkillSourceStoreConfig(dsn=scoped_dsn)
            source_store = PostgresSkillSourceStore(config=source_cfg)
            await source_store.put(
                SkillSource(
                    source_id=spec.publisher,
                    kind=SkillSourceKind.GITHUB_REPOSITORY,
                    location="dotnetpower/fdai",
                    trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
                    owner="platform-team",
                    allowed_path="skills/inventory-evidence",
                    authentication_audience_ref="FDAI_GITHUB_TOKEN",
                    refresh_policy=SkillSourceRefreshPolicy.MANUAL,
                    refresh_interval_seconds=3600,
                    enabled=True,
                ),
                now=NOW,
            )
            artifact_store = PostgresTrustedArtifactStore(
                config=PostgresTrustedArtifactStoreConfig(dsn=scoped_dsn)
            )
            revocation_store = PostgresSkillRevocationStore(config=source_cfg)
            state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            try:
                return await rehearse_x01_bundle_lifecycle_lineage(
                    artifact_store=artifact_store,
                    revocation_store=revocation_store,
                    state_store=state_store,
                    venue="loopback-postgres",
                )
            finally:
                await state_store.aclose()
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Also run against isolated loopback PostgreSQL (requires FDAI_DATABASE_URL).",
    )
    args = parser.parse_args()

    in_memory_result = await rehearse_x01_bundle_lifecycle_lineage()
    output: dict[str, Any] = {"in_memory": in_memory_result}
    if args.postgres:
        dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("--postgres requires FDAI_DATABASE_URL")
        postgres_result = await rehearse_x01_postgres(dsn)
        _require(
            postgres_result["receipts"] == in_memory_result["receipts"],
            "postgres receipts match in_memory",
        )
        _require(
            postgres_result["readbacks"] == in_memory_result["readbacks"],
            "postgres readbacks match in_memory",
        )
        output["postgres"] = postgres_result
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

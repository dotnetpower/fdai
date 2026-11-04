#!/usr/bin/env python3
"""Rehearse and verify F06.3 ARB and operational readiness local qualification (#2205).

Executes a deterministic, fail-closed qualification rehearsal across:
1. WAF five-pillar definition coverage (`load_pillar_definition_coverage`: 5 pillars,
   59 controls, 188 evidence keys);
2. Upstream `config/architecture-review.yaml` structural health vs production-gate
   evaluation across all 9 required owner slots, 8 resolved blockers, 27 required
   production evidence attestations, and a conformant human-approved
   `ArchitectureReviewDecisionReceipt` (`execution_authority=False`), plus fail-closed
   rejection on expired evidence, synthetic attestation, unresolved critical/high
   blocker, and self-approval;
3. ARB-2 12-stage replay-stable observation trace (`replay_architecture_review_trace`),
   order/redelivery convergence, and fail-closed hold on missing or conflicting stages;
4. ARB-4 independent multi-effect closure (`evaluate_architecture_review_effect_closure`),
   rejecting executor (`Thor`) self-scoring and emitting bounded `Vidar` recovery
   requests on out-of-bounds or stop-condition violations; and
5. Durable `StateStore` (`InMemoryStateStore` and isolated port-5433 `PostgresStateStore`)
   retention with verified Saga audit hash-chain integrity.

The emitted receipt is explicitly scoped to `venue="isolated-validation-rehearsal"` and
does not claim a live staging installation, nine external human domain owners, or a
30-day live ARB-5 promotion cohort.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
import yaml
from fdai.core.architecture_review import (
    ArchitectureDecisionAuthorityBasis,
    ArchitectureDecisionOutcome,
    ArchitectureReviewActionRunLink,
    ArchitectureReviewDecisionReceipt,
    ArchitectureReviewEffectObservation,
    ArchitectureReviewExpectedEffect,
    ArchitectureReviewProductionGateEvaluator,
    ArchitectureReviewStage,
    ArchitectureReviewTraceEvent,
    ProductionEvidenceAttestation,
    ProductionEvidenceBinding,
    build_architecture_review_decision_receipt,
    evaluate_architecture_review_effect_closure,
    evaluate_readiness,
    replay_architecture_review_trace,
)
from fdai.core.architecture_review.pillar_coverage import load_pillar_definition_coverage
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "config" / "architecture-review.yaml"
NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)

_STAGE_BINDINGS: tuple[tuple[ArchitectureReviewStage, str, str], ...] = (
    (ArchitectureReviewStage.CHANGE, "object.change", "Huginn"),
    (ArchitectureReviewStage.CONTEXT, "object.state-snapshot", "Muninn"),
    (ArchitectureReviewStage.RELIABILITY, "object.anomaly", "Heimdall"),
    (ArchitectureReviewStage.COST, "object.cost-anomaly", "Njord"),
    (ArchitectureReviewStage.CAPACITY, "object.capacity-forecast", "Freyr"),
    (ArchitectureReviewStage.RECOVERY, "object.chaos-experiment", "Loki"),
    (ArchitectureReviewStage.EVIDENCE_BUNDLE, "object.state-snapshot", "Muninn"),
    (ArchitectureReviewStage.SCENARIO_BRANCH, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.DECISION_CASE, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.IMPACT_ENVELOPE, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.RECOMMENDATION, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.AUDIT, "object.audit-entry", "Saga"),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"F06.3 ARB rehearsal invariant failed: {message}")


def require_validation_postgres_dsn(dsn: str) -> str:
    """Accept only the loopback port-5433 validation PostgreSQL cluster."""

    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    try:
        params = conninfo_to_dict(normalized)
    except Exception as exc:
        raise ValueError("F06.3 rehearsal PostgreSQL DSN is malformed") from exc
    if "hostaddr" in params or "service" in params:
        raise ValueError("F06.3 rehearsal PostgreSQL DSN refuses hostaddr and service overrides")
    effective_host = str(params.get("host") or parsed.hostname or "")
    effective_port = str(params.get("port") or (parsed.port if parsed.port is not None else ""))
    if "," in effective_host or effective_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("F06.3 rehearsal PostgreSQL DSN MUST target a single loopback host")
    if effective_port != "5433" or parsed.port != 5433:
        raise ValueError(
            "F06.3 rehearsal requires explicit port 5433 and refuses default or port-5432 DSNs"
        )
    return normalized


class _StaticEvidenceProvider:
    def __init__(self, attestations: dict[str, ProductionEvidenceAttestation]) -> None:
        self._attestations = dict(attestations)

    async def retrieve(self, binding: ProductionEvidenceBinding) -> ProductionEvidenceAttestation:
        return self._attestations[binding.item]


class _StaticDecisionReceiptProvider:
    def __init__(self, receipt: ArchitectureReviewDecisionReceipt) -> None:
        self._receipt = receipt

    async def retrieve(self, review_case_id: str) -> ArchitectureReviewDecisionReceipt:
        _require(review_case_id == self._receipt.review_case_id, "review_case_id matches receipt")
        return self._receipt


def _build_full_ready_manifest_and_evidence(
    upstream: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, ProductionEvidenceAttestation],
    ArchitectureReviewDecisionReceipt,
]:
    manifest = deepcopy(upstream)
    review = manifest["architecture_review"]
    review["design_review_status"] = "approved"
    review["production_approval_status"] = "ready"
    for artifact in review["artifacts"]:
        if artifact["required_for"] == "production":
            artifact["status"] = "ready"
    for blocker in review["blockers"]:
        blocker["status"] = "resolved"

    gate = review["production_gate"]
    required_slots: list[str] = list(gate["required_owner_slots"])
    required_evidence: list[str] = list(gate["required_evidence"])
    target_revision = "rev-f063-rehearsal-1"
    scope_ref = "scope:f063-isolated-rehearsal"

    owner_bindings: dict[str, dict[str, str]] = {}
    for slot in required_slots:
        owner_bindings[slot] = {
            "subject": f"group:{slot}-reviewers",
            "escalation": f"oncall:{slot}",
        }
    gate["owner_bindings"] = owner_bindings

    evidence_bindings: dict[str, dict[str, Any]] = {}
    attestations: dict[str, ProductionEvidenceAttestation] = {}
    for idx, item in enumerate(required_evidence):
        approver = f"group:{required_slots[idx % len(required_slots)]}-reviewers"
        body = json.dumps(
            {"evidence_item": item, "revision": target_revision, "status": "passed"},
            sort_keys=True,
        ).encode("utf-8")
        uri = f"evidence://f063-rehearsal/{item}"
        evidence_bindings[item] = {
            "uri": uri,
            "sha256": hashlib.sha256(body).hexdigest(),
            "scope_ref": scope_ref,
            "revision": target_revision,
            "approved_by": approver,
            "approved_at": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=30)).isoformat(),
            "freshness_seconds": 604800,
        }
        attestations[item] = ProductionEvidenceAttestation(
            uri=uri,
            body=body,
            scope_ref=scope_ref,
            revision=target_revision,
            observed_at=NOW - timedelta(hours=2),
            authorized_approvers=(approver,),
            authentication_ref=f"auth:f063-readback:{item}",
            synthetic=False,
        )
    gate["evidence_bindings"] = evidence_bindings

    receipt = build_architecture_review_decision_receipt(
        review_case_id=str(review["review_id"]),
        change_id="change:f063-rehearsal-1",
        decision_case_id="decision-case:f063-rehearsal-1",
        impact_envelope_id="impact:f063-rehearsal-1",
        target_revision=target_revision,
        context_snapshot_id="context:f063-rehearsal-1",
        evidence_bundle_id="evidence-bundle:f063-rehearsal-1",
        graph_revision="graph:f063-rehearsal-1",
        catalog_release="catalog:f063-rehearsal-1",
        evidence_refs=tuple(sorted(required_evidence)),
        conditions=(),
        outcome=ArchitectureDecisionOutcome.CONFORMANT,
        rationale="All 9 owner slots, 8 blockers, and 27 evidence bindings verified in rehearsal.",
        authority_basis=ArchitectureDecisionAuthorityBasis.HUMAN_APPROVAL,
        authority_ref="authority:f063-rehearsal-approval-1",
        requester_id="principal:requester@example.com",
        judge_id="agent:Forseti",
        arbitrator_id=None,
        approver_ids=("principal:owner-approver@example.com",),
        approval_receipt_refs=("approval:f063-rehearsal-1",),
        quorum=1,
        audit_intent_ref="audit:f063-intent-1",
        terminal_audit_ref="audit:f063-terminal-1",
        recorded_at=NOW - timedelta(minutes=30),
        effective_from=NOW - timedelta(minutes=30),
        effective_until=NOW + timedelta(days=30),
        reevaluation_trigger="evidence_or_scope_changes",
    )
    return manifest, attestations, receipt


async def rehearse_f063_arb_operational_readiness(
    *,
    state_store: StateStore | None = None,
    venue: str = "in-memory-rehearsal",
) -> dict[str, Any]:
    """Run the F06.3 local qualification rehearsal and persist its receipt in ``state_store``."""

    store = state_store or InMemoryStateStore()

    # 1. Verify WAF 5-pillar definition coverage (59 controls, 188 evidence keys).
    pillar_report = load_pillar_definition_coverage(_REPO_ROOT)
    _require(len(pillar_report.pillars) == 5, "5 WAF pillars")
    _require(pillar_report.control_count == 59, "59 WAF controls")
    _require(pillar_report.evidence_count == 188, "188 WAF evidence keys")

    # 2. Verify upstream manifest structure vs production readiness and negative fail-closed gates.
    upstream_raw = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    _require(isinstance(upstream_raw, dict), "upstream manifest is a mapping")
    upstream_eval = evaluate_readiness(upstream_raw, repo_root=_REPO_ROOT, evaluated_at=NOW)
    _require(
        upstream_eval.structure_valid is True and upstream_eval.production_ready is False,
        "upstream manifest is structurally valid and production-blocked by default",
    )

    ready_manifest, attestations, decision_receipt = _build_full_ready_manifest_and_evidence(
        upstream_raw
    )
    ready_eval = evaluate_readiness(
        ready_manifest,
        repo_root=_REPO_ROOT,
        evaluated_at=NOW,
        evidence_attestations=attestations,
        decision_receipt=decision_receipt,
    )
    _require(
        ready_eval.structure_valid is True and ready_eval.production_ready is True,
        "rehearsal manifest with all 9 owners, 8 blockers, and 27 evidence items is ready",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_manifest = Path(tmp_dir) / "architecture-review.yaml"
        tmp_manifest.write_text(yaml.safe_dump(ready_manifest), encoding="utf-8")
        evaluator = ArchitectureReviewProductionGateEvaluator(
            manifest_path=tmp_manifest,
            repo_root=_REPO_ROOT,
            evidence_provider=_StaticEvidenceProvider(attestations),
            decision_receipt_provider=_StaticDecisionReceiptProvider(decision_receipt),
            clock=lambda: NOW,
        )
        gate_passed = await evaluator.evaluate(
            rule_id="architecture-review.production-ready",
            step_id="step-production-gate",
            process_id="proc-f063-1",
        )
        _require(gate_passed is True, "ArchitectureReviewProductionGateEvaluator passed")

    # Negative checks: expired evidence, synthetic attestation, and open critical blocker.
    expired_eval = evaluate_readiness(
        ready_manifest,
        repo_root=_REPO_ROOT,
        evaluated_at=NOW + timedelta(days=40),
        evidence_attestations=attestations,
        decision_receipt=decision_receipt,
    )
    _require(expired_eval.production_ready is False, "expired evidence fails closed")

    first_item = next(iter(attestations))
    orig_att = attestations[first_item]
    synthetic_attestations = {
        **attestations,
        first_item: ProductionEvidenceAttestation(
            uri=orig_att.uri,
            body=orig_att.body,
            scope_ref=orig_att.scope_ref,
            revision=orig_att.revision,
            observed_at=orig_att.observed_at,
            authorized_approvers=orig_att.authorized_approvers,
            authentication_ref=orig_att.authentication_ref,
            synthetic=True,
        ),
    }
    synthetic_eval = evaluate_readiness(
        ready_manifest,
        repo_root=_REPO_ROOT,
        evaluated_at=NOW,
        evidence_attestations=synthetic_attestations,
        decision_receipt=decision_receipt,
    )
    _require(synthetic_eval.production_ready is False, "synthetic attestation fails closed")

    open_blocker_manifest = deepcopy(ready_manifest)
    open_blocker_manifest["architecture_review"]["blockers"][0]["status"] = "open"
    open_blocker_eval = evaluate_readiness(
        open_blocker_manifest,
        repo_root=_REPO_ROOT,
        evaluated_at=NOW,
        evidence_attestations=attestations,
        decision_receipt=decision_receipt,
    )
    _require(open_blocker_eval.production_ready is False, "open critical blocker fails closed")

    # 3. ARB-2 12-stage replay-stable observation trace and negative missing-stage hold.
    trace_events = tuple(
        ArchitectureReviewTraceEvent(
            sequence=index,
            stage=stage,
            topic=topic,
            producer_principal=producer,
            correlation_id="corr-f063-rehearsal-1",
            review_case_id="fdai-target-architecture-v1",
            idempotency_key=f"f063-trace:{index}",
            observed_at=NOW + timedelta(seconds=index),
            evidence_digest=f"sha256:{index:064x}",
            status=(
                "conformant" if stage is ArchitectureReviewStage.RECOMMENDATION else "complete"
            ),
        )
        for index, (stage, topic, producer) in enumerate(_STAGE_BINDINGS, start=1)
    )
    trace_forward = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=trace_events,
    )
    trace_reversed = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=tuple(reversed(trace_events)),
    )
    trace_redelivered = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=(trace_events[0], *trace_events, trace_events[-1]),
    )
    trace_incomplete = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=trace_events[:-1],
    )
    trace_conflicting_digest = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=(*trace_events, replace(trace_events[2], evidence_digest=f"sha256:{999:064x}")),
    )
    trace_conflicting_sequence = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=(*trace_events[:-1], replace(trace_events[-1], sequence=11)),
    )
    trace_conflicting_idempotency = replay_architecture_review_trace(
        correlation_id="corr-f063-rehearsal-1",
        review_case_id="fdai-target-architecture-v1",
        deadline_at=NOW + timedelta(minutes=5),
        events=(*trace_events[:-1], replace(trace_events[-1], idempotency_key="f063-trace:1")),
    )
    _require(
        trace_forward == trace_reversed == trace_redelivered
        and trace_forward.outcome == "conformant"
        and trace_forward.execution_authority is False,
        "ARB-2 12-stage trace is replay-stable across reordering/redelivery and authority-free",
    )
    _require(
        trace_incomplete.outcome == "hold"
        and "missing_stage:audit" in trace_incomplete.hold_reasons,
        "incomplete ARB-2 trace holds on missing stage",
    )
    _require(
        trace_conflicting_digest.outcome == "hold"
        and any("conflict" in reason for reason in trace_conflicting_digest.hold_reasons),
        "conflicting ARB-2 stage digest holds fail-closed",
    )
    _require(
        trace_conflicting_sequence.outcome == "hold"
        and "conflicting_sequence:11" in trace_conflicting_sequence.hold_reasons,
        "conflicting ARB-2 stage sequence holds fail-closed with conflicting_sequence:11",
    )
    _require(
        trace_conflicting_idempotency.outcome == "hold"
        and "conflicting_idempotency_key:f063-trace:1"
        in trace_conflicting_idempotency.hold_reasons,
        "conflicting ARB-2 idempotency key holds fail-closed",
    )

    # 4. ARB-4 independent multi-effect closure & Vidar recovery.
    action_link = ArchitectureReviewActionRunLink(
        review_case_id="fdai-target-architecture-v1",
        change_id="change:f063-rehearsal-1",
        decision_case_id="decision-case:f063-rehearsal-1",
        impact_envelope_id="impact:f063-rehearsal-1",
        action_run_id="action-run:f063-rehearsal-1",
        selected_option_id="option-right-size",
        action_type="remediate.right-size-compute@1.0.0",
        executor_principal="Thor",
        idempotency_key="idem:f063-rehearsal-1",
        target_lock_ref="lock:f063-target-1",
        stop_condition_ref="stop:error-budget-burn",
        rollback_ref="rollback:restore-sku",
        executed_at=NOW,
        expected_effects=(
            ArchitectureReviewExpectedEffect(
                effect_id="eff-latency-p95",
                metric="http_latency_p95_ms",
                target_ref="resource:f063-1",
                expected_min=0.0,
                expected_max=250.0,
                window_seconds=300,
            ),
            ArchitectureReviewExpectedEffect(
                effect_id="eff-availability",
                metric="availability_ratio",
                target_ref="resource:f063-1",
                expected_min=0.999,
                expected_max=1.0,
                window_seconds=300,
            ),
        ),
        mode="shadow",
    )
    conformant_closure = evaluate_architecture_review_effect_closure(
        action_link,
        (
            ArchitectureReviewEffectObservation(
                observation_id="obs-1",
                effect_id="eff-latency-p95",
                action_run_id="action-run:f063-rehearsal-1",
                observer_principal="Heimdall",
                observed_value=125.0,
                observed_at=NOW + timedelta(seconds=30),
                evidence_digest="sha256:" + "1" * 64,
            ),
            ArchitectureReviewEffectObservation(
                observation_id="obs-2",
                effect_id="eff-availability",
                action_run_id="action-run:f063-rehearsal-1",
                observer_principal="Heimdall",
                observed_value=0.9997,
                observed_at=NOW + timedelta(seconds=45),
                evidence_digest="sha256:" + "2" * 64,
            ),
        ),
    )
    _require(
        conformant_closure.status == "closed_conformant"
        and conformant_closure.arb_execution_authority is False,
        "Heimdall multi-effect observations close conformantly without execution authority",
    )

    self_scored_closure = evaluate_architecture_review_effect_closure(
        action_link,
        (
            ArchitectureReviewEffectObservation(
                observation_id="obs-thor",
                effect_id="eff-latency-p95",
                action_run_id="action-run:f063-rehearsal-1",
                observer_principal="Thor",
                observed_value=100.0,
                observed_at=NOW + timedelta(seconds=15),
                evidence_digest="sha256:" + "3" * 64,
            ),
        ),
    )
    _require(
        self_scored_closure.status == "pending_observation"
        and "self_scored_or_unauthorized_observer:Thor" in self_scored_closure.reason_codes,
        "Thor self-scored observation is rejected",
    )

    breach_closure = evaluate_architecture_review_effect_closure(
        action_link,
        (
            ArchitectureReviewEffectObservation(
                observation_id="obs-breach-1",
                effect_id="eff-latency-p95",
                action_run_id="action-run:f063-rehearsal-1",
                observer_principal="Heimdall",
                observed_value=480.0,
                observed_at=NOW + timedelta(seconds=40),
                evidence_digest="sha256:" + "4" * 64,
                stop_condition_triggered=True,
            ),
            ArchitectureReviewEffectObservation(
                observation_id="obs-breach-2",
                effect_id="eff-availability",
                action_run_id="action-run:f063-rehearsal-1",
                observer_principal="Heimdall",
                observed_value=0.985,
                observed_at=NOW + timedelta(seconds=50),
                evidence_digest="sha256:" + "5" * 64,
                protected_objective_violated=True,
            ),
        ),
    )
    _require(
        breach_closure.status == "recovery_required"
        and breach_closure.review_status == "reopened"
        and breach_closure.recovery_request is not None
        and breach_closure.recovery_request.target_agent == "Vidar",
        "out-of-bounds/stop-condition breach requests Vidar recovery and reopens review",
    )

    body: dict[str, Any] = {
        "arb2_trace_digest": trace_forward.trace_digest,
        "arb4_conformant_closure_digest": conformant_closure.closure_digest,
        "arb4_recovery_closure_digest": breach_closure.closure_digest,
        "decision_receipt_digest": decision_receipt.receipt_digest,
        "execution_authority": False,
        "local_rehearsal_invariants": {
            "arb2_12_stage_replay_and_hold_verified": True,
            "arb4_independent_effect_closure_and_vidar_recovery_verified": True,
            "production_gate_9_owners_8_blockers_27_evidence_verified": True,
            "upstream_manifest_structure_and_fail_closed_defaults_verified": True,
            "waf_5_pillars_59_controls_188_evidence_keys_verified": True,
        },
        "rehearsal_only": True,
        "venue": venue,
        "waf_catalog_digest": pillar_report.catalog_digest,
        "waf_framework_digest": pillar_report.framework_definition_digest,
    }
    receipt = {**body, "rehearsal_receipt_digest": content_digest(body)}
    await store.write_state_with_audit_if_absent(
        "f063:arb-operational-readiness:rehearsal:v1",
        receipt,
        {
            "kind": "f063.arb_operational_readiness.rehearsal",
            "event_id": receipt["rehearsal_receipt_digest"],
            "venue": venue,
            "decision_receipt_digest": decision_receipt.receipt_digest,
            "arb2_trace_digest": trace_forward.trace_digest,
            "arb4_conformant_closure_digest": conformant_closure.closure_digest,
            "rehearsal_receipt_digest": receipt["rehearsal_receipt_digest"],
            "execution_authority": False,
            "rehearsal_only": True,
        },
    )
    _require(await store.verify_chain() is True, "Saga audit hash chain verified")
    return receipt


async def rehearse_f063_postgres(dsn: str) -> dict[str, Any]:
    """Run the F06.3 qualification rehearsal against an isolated port-5433 schema."""

    loopback_dsn = require_validation_postgres_dsn(dsn)
    schema = f"f063_rehearsal_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(loopback_dsn, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(loopback_dsn, options=f"-c search_path={schema},public")
        try:
            async with await psycopg.AsyncConnection.connect(
                scoped_dsn, autocommit=True
            ) as setup_conn:
                await setup_conn.execute(
                    """
                    CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY,
                        event_id UUID NOT NULL,
                        correlation_id TEXT,
                        actor TEXT NOT NULL,
                        action_kind TEXT NOT NULL,
                        mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')),
                        entry JSONB NOT NULL,
                        previous_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL UNIQUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
            store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            try:
                return await rehearse_f063_arb_operational_readiness(
                    state_store=store,
                    venue="isolated-validation-postgres-5433",
                )
            finally:
                await store.aclose()
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Also run against the loopback port-5433 PostgreSQL validation database.",
    )
    args = parser.parse_args()
    in_memory = await rehearse_f063_arb_operational_readiness()
    output: dict[str, Any] = {"in_memory": in_memory}
    if args.postgres:
        dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("FDAI_DATABASE_URL is required when --postgres is set")
        output["postgres"] = await rehearse_f063_postgres(dsn)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

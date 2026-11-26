from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping
from fdai.core.operational_planning.prospective_lineage import ProspectiveLineageMaterializer
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationResultEvent,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.rule_semantic_generation.test_ledger import _result

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class _PostTurnCoordinator:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput) -> object:
        self.inputs.append(review_input)
        return object()


class _Retention:
    def __init__(self) -> None:
        self.calls = 0

    async def delete_due(self, **_kwargs: object) -> tuple[str, ...]:
        self.calls += 1
        return ()


class _EvidenceConflictSink:
    def __init__(self) -> None:
        self.calls = 0

    async def append(self, _revision: object) -> bool:
        self.calls += 1
        return True


class _ProspectiveMaterializer(ProspectiveLineageMaterializer):
    def __init__(self) -> None:
        self.materialized = 0
        self.sealed = 0

    async def materialize(self, _lineage: object) -> bool:
        self.materialized += 1
        return True

    async def seal_saga(self, *, lineage_id: str, subgraph_digest: str) -> bool:
        del lineage_id, subgraph_digest
        self.sealed += 1
        return True


def _review_input(**overrides: object) -> PostTurnReviewInput:
    values = {
        "review_id": "review-authority-1",
        "principal_scope": "principal-scope-1",
        "operator_turn_id": "operator-turn-1",
        "assistant_turn_id": "assistant-turn-1",
        "completed_at": NOW,
    }
    values.update(overrides)
    return PostTurnReviewInput(**values)  # type: ignore[arg-type]


def _activation_payload(result: RuleGenerationActivationResultEvent) -> dict[str, object]:
    payload = result.model_dump(mode="json")
    payload["producer_principal"] = "Mimir"
    return payload


async def test_norns_rejects_non_saga_audit_outcome_learning() -> None:
    norns = Norns(min_outcome_samples=1, rollback_alarm_rate=0.0)

    await norns.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Mallory",
            "action_type": "remediate.rollback",
            "result": "rollback",
            "correlation_id": "audit-forged-1",
            "idempotency_key": "audit-forged-1",
        },
    )

    assert norns.pending_candidates == []
    assert norns.outcome_rate("remediate.rollback") is None
    assert norns.behavior_snapshot()["audit_outcome:invalid_producer"] == 1


async def test_norns_rejects_non_var_approval_learning() -> None:
    norns = Norns(rejection_revise_threshold=1)

    await norns.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Mallory",
            "action_type": "remediate.delete-storage",
            "state": "rejected",
            "correlation_id": "approval-forged-1",
            "idempotency_key": "approval-forged-1",
        },
    )

    assert norns.pending_candidates == []
    assert norns.rejection_count("remediate.delete-storage") == 0
    assert norns.behavior_snapshot()["approval:invalid_producer"] == 1


async def test_norns_rejects_raw_post_turn_body_without_recorded_consent() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    review = _review_input(operator_body="Inspect the incident.", assistant_body="Done.")

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Bragi",
            "kind": "post_turn_review",
            "correlation_id": "review-authority-1",
            "idempotency_key": "post-turn-review:review-authority-1",
            "review": review_input_to_mapping(review),
        },
    )

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review_raw_body_without_consent"] == 1


async def test_norns_records_post_turn_fence_only_after_valid_review() -> None:
    coordinator = _PostTurnCoordinator()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    malformed = review_input_to_mapping(_review_input())
    del malformed["assistant_turn_id"]
    corrected = review_input_to_mapping(_review_input())

    for review in (malformed, corrected):
        await norns.on_typed_message(
            "object.post-turn-review",
            {
                "producer_principal": "Bragi",
                "kind": "post_turn_review",
                "correlation_id": "review-replay-1",
                "idempotency_key": "post-turn-review:review-replay-1",
                "review": review,
            },
        )

    assert coordinator.inputs == [_review_input()]


async def test_norns_rejects_forged_shadow_review_update() -> None:
    norns = Norns()
    target = "remediate.enable-tde"
    await norns.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "action_type": target,
            "shadow_mode": True,
            "observed_at": NOW.isoformat(),
            "correlation_id": "shadow-authority-1",
            "idempotency_key": "shadow-authority-1",
        },
    )
    before = norns.shadow_dwell_evidence(target)
    assert before is not None
    assert before.reviewed_count == 0

    await norns.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Mallory",
            "action_type": target,
            "shadow_review_update": True,
            "shadow_observation_id": "shadow-authority-1",
            "operator_reviewed": True,
            "operator_agreed": True,
            "policy_escape": False,
            "correlation_id": "shadow-review-forged-1",
            "idempotency_key": "shadow-review-forged-1",
        },
    )

    after = norns.shadow_dwell_evidence(target)
    assert after is not None
    assert after.reviewed_count == 0


async def test_mimir_quarantines_non_norns_rule_candidate() -> None:
    mimir = Mimir()

    await mimir.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Mallory",
            "proposed_by": "Norns",
            "proposal_kind": "new",
            "target_rule_id": "rule.example",
            "source_signal": "handoff_fingerprint",
            "evidence": {"occurrence_count": 1},
            "correlation_id": "candidate-forged-1",
            "idempotency_key": "candidate-forged-1",
        },
    )

    assert mimir.pending_candidates() == ()
    assert mimir.quarantined_candidates()[-1]["quarantine_reason"] == "invalid_producer"


def test_candidate_guard_rejects_free_form_proposer_identity() -> None:
    verdict = CandidateGuard().inspect(
        {
            "producer_principal": "Mallory",
            "proposed_by": "Mallory",
            "proposal_kind": "new",
            "target_rule_id": "rule.example",
            "source_signal": "handoff_fingerprint",
            "evidence": {"occurrence_count": 1},
        }
    )

    assert verdict.accepted is False
    assert verdict.reason == "invalid_provenance:proposed_by"


async def test_mimir_rejects_unexpected_activation_result_producer() -> None:
    store = InMemoryStateStore()
    mimir = Mimir()
    mimir.bind_rule_generation_state_store(store)
    result = _result()
    payload = _activation_payload(result)
    payload["producer_principal"] = "Mallory"

    with pytest.raises(ValueError, match="published by Mimir"):
        await mimir.on_typed_message("rule.semantic-generation.activation-results", payload)

    assert (
        await store.read_state(f"mimir:rule-generation-activation-result:{result.idempotency_key}")
        is None
    )


async def test_mimir_rejects_activation_result_without_issued_command() -> None:
    store = InMemoryStateStore()
    mimir = Mimir()
    mimir.bind_rule_generation_state_store(store)
    result = _result()

    with pytest.raises(ValueError, match="no issued command"):
        await mimir.on_typed_message(
            "rule.semantic-generation.activation-results",
            _activation_payload(result),
        )

    assert (
        await store.read_state(f"mimir:rule-generation-activation-result:{result.idempotency_key}")
        is None
    )


async def test_muninn_rejects_non_heimdall_forecast_outcome() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    muninn = Muninn()
    muninn.bind_bus(bus)

    await muninn.on_typed_message(
        "object.forecast-outcome",
        {
            "producer_principal": "Mallory",
            "correlation_id": "forecast-forged-1",
            "idempotency_key": "forecast-forged-1",
        },
    )

    assert bus.messages_on("object.context-index") == []
    assert muninn.behavior_snapshot()["forecast_outcome:invalid_producer"] == 1


async def test_muninn_rejects_non_huginn_retention_tick() -> None:
    retention = _Retention()
    muninn = Muninn(
        case_history_retention=retention,  # type: ignore[arg-type]
        case_history_clock=lambda: NOW + timedelta(days=90),
    )

    await muninn.on_typed_message(
        "object.event",
        {
            "producer_principal": "Mallory",
            "event_id": "case-history-retention:forged",
            "idempotency_key": "case-history-retention:forged",
            "correlation_id": "case-history-retention:forged",
            "source": "case-history-retention-scheduler",
            "event_type": "case_history.retention_due",
        },
    )

    assert retention.calls == 0
    assert muninn.behavior_snapshot()["case_history:retention_invalid_producer"] == 1


async def test_muninn_rejects_non_saga_document_index_audit() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    muninn = Muninn()
    muninn.bind_bus(bus)

    await muninn.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Mallory",
            "kind": "document_ingestion",
            "stage": "protection_check",
            "audited_topic": "object.approval",
            "decision": "approved",
            "document_id": "doc-forged",
            "upload_id": "upload-forged",
            "correlation_id": "document-forged-1",
            "idempotency_key": "document-forged-1",
        },
    )

    assert bus.messages_on("object.context-index") == []
    assert muninn.behavior_snapshot()["document_index:invalid_producer"] == 1


async def test_muninn_rejects_non_heimdall_detection_readiness() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    muninn = Muninn()
    muninn.bind_bus(bus)

    await muninn.on_typed_message(
        "object.drift",
        {
            "producer_principal": "Mallory",
            "kind": "detection_readiness",
            "resource_id": "cluster/example",
            "generated_at": NOW.isoformat(),
            "decision": "ready",
            "observations": [],
            "authority_ceiling": "shadow",
            "correlation_id": "readiness-forged-1",
            "idempotency_key": "readiness-forged-1",
        },
    )

    assert bus.messages_on("object.state-snapshot") == []
    assert muninn.behavior_snapshot()["detection_readiness:invalid_producer"] == 1


async def test_muninn_rejects_non_heimdall_evidence_conflict() -> None:
    sink = _EvidenceConflictSink()
    muninn = Muninn(evidence_conflict_sink=sink)  # type: ignore[arg-type]

    await muninn.on_typed_message(
        "object.evidence-conflict",
        {
            "producer_principal": "Mallory",
            "correlation_id": "conflict-forged-1",
            "idempotency_key": "conflict-forged-1",
        },
    )

    assert sink.calls == 0
    assert muninn.behavior_snapshot()["evidence_conflict:invalid_producer"] == 1


async def test_muninn_rejects_non_forseti_prospective_lineage() -> None:
    materializer = _ProspectiveMaterializer()
    muninn = Muninn(prospective_lineage_materializer=materializer)

    await muninn.on_typed_message(
        "object.prospective-lineage",
        {
            "producer_principal": "Mallory",
            "correlation_id": "lineage-forged-1",
            "idempotency_key": "lineage-forged-1",
        },
    )

    assert materializer.materialized == 0
    assert muninn.behavior_snapshot()["prospective_lineage:invalid_producer"] == 1

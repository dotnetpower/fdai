"""Local composition of the prediction-learning P4-P5 case-history path.

These tests prove current-revision cohorts, correction and deletion fences, scope partitioning,
and idempotent redelivery and demotion over real in-memory components. The replay, shadow,
review, and O7 promotion receipts are fixtures, and Pattern admission is a stub, so the module
does not prove P5 qualification, `case-history-read` admission, or Pattern-to-T1 intake.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.agents._framework.adapters import InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    OperationalCaseInput,
    OperationalOutcomeClass,
    OperationalReceiptType,
)
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCheckReceipts,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogValidationRequest,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    ReviewedReplayAuthority,
    ReviewedReplayPersistedAuthorityVerifier,
    ReviewedReplayPromotionEvidence,
    ReviewedReplayReceiptVerifier,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.core.risk_gate import PromotionMetrics
from fdai.core.tiers.t1_lightweight import (
    LearnedAction,
    OperationalCaseContext,
    T1Config,
    T1Outcome,
    T1Tier,
)
from fdai.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Event, Mode, OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.case_history.test_operational_case import (
    _case_input,
    _receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)


class _Validator:
    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
        common = {
            "candidate_digest": request.candidate.digest,
            "artifact_digest": request.artifact_digest,
        }
        return CatalogCheckReceipts(
            schema=SchemaCheckReceipt(
                **common,
                schema_version=request.schema_version,
                passed=True,
            ),
            replay=ReplayCheckReceipt(
                **common,
                replay_version="prediction-learning-p45-v1",
                first_result_digest=request.candidate.digest,
                second_result_digest=request.candidate.digest,
                passed=True,
            ),
            shadow=ShadowCheckReceipt(
                **common,
                scenario_set_id=request.candidate.scenario_set_version,
                baseline_result_digest="1" * 64,
                challenger_result_digest="2" * 64,
                regression_passed=True,
                policy_escapes=0,
                passed=True,
            ),
            policy=PolicyCheckReceipt(
                **common,
                policy_version="prediction-learning-p45-policy-v1",
                policy_escapes=0,
                passed=True,
            ),
        )


class _Publisher:
    def __init__(self) -> None:
        self.packages: list[CatalogReviewPackage] = []

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        already_existed = any(
            item.content_digest == package.content_digest for item in self.packages
        )
        if not already_existed:
            self.packages.append(package)
        return CatalogReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref=f"catalog-review:{package.content_digest[:16]}",
            already_existed=already_existed,
        )


class _FixedEmbedding:
    dim = 3

    async def embed(self, _text: str) -> tuple[float, float, float]:
        return (1.0, 0.0, 0.0)


class _ReadAdmission:
    async def admit(self, **values: object) -> DecisionEvidenceAdmission:
        evidence_digest = cast(str, values["evidence_digest"])
        scope_digest = cast(str, values["scope_digest"])
        purpose_id = cast(str, values["purpose_id"])
        source_revision = cast(str, values["source_revision"])
        return DecisionEvidenceAdmission(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            receipt_digest="sha256:" + "c" * 64,
            verification_bundle_digest="sha256:" + "d" * 64,
            verified_at=NOW,
            valid_until=NOW + timedelta(days=1),
        )


def _with_enforce_audit(case_input: OperationalCaseInput) -> OperationalCaseInput:
    receipts = tuple(
        _receipt(
            OperationalReceiptType.AUDIT,
            "1",
            (("event_type", "action.completed"), ("decision", "auto"), ("mode", "enforce")),
        )
        if receipt.receipt_type is OperationalReceiptType.AUDIT
        else receipt
        for receipt in case_input.receipts
    )
    return replace(case_input, receipts=receipts)


def _input(
    marker: str,
    outcome_class: OperationalOutcomeClass,
    *,
    corrected: bool = False,
    access_scope_digest: str = "f" * 64,
    event_time_cutoff: datetime | None = None,
) -> OperationalCaseInput:
    source = _with_enforce_audit(_case_input(outcome_class=outcome_class))
    receipts = (
        source.receipts
        if corrected
        else tuple(
            receipt
            for receipt in source.receipts
            if receipt.receipt_type is not OperationalReceiptType.EVALUATION
        )
    )
    next_marker = {
        "a": "b",
        "b": "c",
        "c": "d",
        "d": "e",
        "e": "f",
        "f": "1",
    }[marker]
    return replace(
        source,
        case_identity_digest=marker * 64,
        correlation_digest=marker * 64,
        access_scope_digest=access_scope_digest,
        event_time_cutoff=event_time_cutoff or NOW - timedelta(days=1),
        receipts=receipts,
        source_identity_digest=marker * 64,
        evidence_refs=(marker * 64, next_marker * 64),
    )


def _raw(name: str, case_input: OperationalCaseInput) -> dict[str, Any]:
    return {
        "id": f"operational-case:{name}",
        "event_id": f"operational-case:{name}",
        "correlation_id": case_input.correlation_digest,
        "idempotency_key": f"operational-case:{name}",
        "source": "fdai.case-history",
        "event_type": "case_history.operational_case.v1",
        "resource_id": case_input.failure_fingerprint.digest,
        "attributes": case_input.to_mapping(),
    }


def _action_type() -> OntologyActionType:
    action_types = load_action_type_catalog(
        REPO_ROOT / "rule-catalog/action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    return next(item for item in action_types if item.name == "ops.restart-service")


def _promotion_receipt(
    action_type: OntologyActionType,
    package: CatalogReviewPackage,
    *,
    ready: bool = True,
) -> OperationalPromotionReceipt:
    return OperationalPromotionReceipt(
        fdai_revision=package.candidate.fdai_revision,
        scenario_set_version=package.candidate.scenario_set_version,
        action_type_name=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=action_type_digest(action_type),
        evidence_digest="8" * 64,
        observation_days=30.0,
        live_observation_days=30,
        sample_count=500,
        benchmark_samples=250,
        live_shadow_samples=250,
        correct_count=500,
        accuracy=1.0,
        accuracy_ci_lower=0.99,
        accuracy_ci_upper=1.0,
        benchmark_accuracy=1.0,
        benchmark_accuracy_ci_lower=0.99,
        benchmark_accuracy_ci_upper=1.0,
        live_shadow_accuracy=1.0,
        live_shadow_accuracy_ci_lower=0.99,
        live_shadow_accuracy_ci_upper=1.0,
        policy_escapes=0,
        rollback_rate=0.0,
        recurrence_rate=0.0,
        executed_samples=250,
        recurrence_complete_samples=250,
        recurrence_incomplete_samples=0,
        simulation_review_rate=0.0,
        causal_evidence_failures=0,
        ready=ready,
        gaps=() if ready else ("insufficient_evidence",),
        decision_evidence_receipt_digest="sha256:" + "6" * 64 if ready else None,
        decision_evidence_verification_bundle_digest="sha256:" + "7" * 64 if ready else None,
    )


def _metrics(
    receipt: OperationalPromotionReceipt,
    *,
    samples: int | None = None,
) -> PromotionMetrics:
    return PromotionMetrics(
        action_type=receipt.action_type_name,
        shadow_days=receipt.live_observation_days,
        samples=receipt.sample_count if samples is None else samples,
        accuracy=receipt.accuracy,
        policy_escapes=receipt.policy_escapes,
    )


def _wire() -> tuple[InMemoryBus, Huginn, Muninn, Norns, Mimir, _Publisher, InMemoryStateStore]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    durable = InMemoryStateStore()
    materializer = CaseHistoryMaterializer(
        metadata=InMemoryCaseHistoryMetadataStore(),
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    publisher = _Publisher()
    huginn = Huginn()
    muninn = Muninn(
        case_history=materializer,
        durable_state_store=durable,
        case_history_clock=lambda: NOW,
    )
    norns = Norns(
        case_history_materializer=materializer,
        operational_state_store=durable,
        clock=lambda: NOW,
    )
    mimir = Mimir(
        catalog_candidate_compiler=CatalogCandidateCompiler(
            validator=_Validator(),
            catalog_version="catalog-v2026.09.30",
            schema_version="2.0.0",
            expected_fdai_revision="a" * 40,
            expected_scenario_set_version="v2026.08",
            clock=lambda: NOW,
        ),
        catalog_review_publisher=publisher,
        catalog_review_state_store=durable,
        clock=lambda: NOW,
    )
    mimir.bind_case_history(materializer)
    saga = Saga(audit_chain=InMemoryAuditChain())
    for agent in (huginn, muninn, norns, mimir, saga):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.pattern", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    bus.subscribe("object.rule", "Saga", saga.on_typed_message)
    bus.subscribe("object.state-snapshot", "Saga", saga.on_typed_message)
    return bus, huginn, muninn, norns, mimir, publisher, durable


def _materializer(muninn: Muninn) -> CaseHistoryMaterializer:
    materializer = muninn._case_history
    assert materializer is not None
    return materializer


async def _replay_package(
    candidate: dict[str, Any],
    materializer: CaseHistoryMaterializer,
) -> CatalogReviewPackage:
    publisher = _Publisher()
    replay = Mimir(
        catalog_candidate_compiler=CatalogCandidateCompiler(
            validator=_Validator(),
            catalog_version="catalog-v2026.09.30",
            schema_version="2.0.0",
            expected_fdai_revision="a" * 40,
            expected_scenario_set_version="v2026.08",
            clock=lambda: NOW,
        ),
        catalog_review_publisher=publisher,
        clock=lambda: NOW,
    )
    replay.bind_case_history(materializer)
    replay.bind_bus(InMemoryBus(registry=load_pantheon(), isolate_handlers=False))
    await replay.on_typed_message("object.rule-candidate", dict(candidate))
    assert len(publisher.packages) == 1
    return publisher.packages[0]


async def _assert_candidate_source_refused(
    candidate: dict[str, Any],
    materializer: CaseHistoryMaterializer,
) -> None:
    mimir = Mimir(
        catalog_candidate_compiler=CatalogCandidateCompiler(
            validator=_Validator(),
            catalog_version="catalog-v2026.09.30",
            schema_version="2.0.0",
            expected_fdai_revision="a" * 40,
            expected_scenario_set_version="v2026.08",
            clock=lambda: NOW,
        ),
        catalog_review_publisher=_Publisher(),
        clock=lambda: NOW,
    )
    mimir.bind_case_history(materializer)
    mimir.bind_bus(InMemoryBus(registry=load_pantheon(), isolate_handlers=False))
    with pytest.raises(PermissionError, match="no longer current"):
        await mimir.on_typed_message("object.rule-candidate", dict(candidate))


async def test_p4_p5_pattern_and_candidate_chain_is_correction_aware_and_fail_closed() -> None:
    bus, huginn, muninn, norns, _mimir, publisher, durable = _wire()
    first_success = _input("a", OperationalOutcomeClass.SUCCESS)
    control = _input("b", OperationalOutcomeClass.ROLLBACK)
    corrected_success = _input("a", OperationalOutcomeClass.SUCCESS, corrected=True)

    await huginn.ingest(_raw("success-v1", first_success))
    await huginn.ingest(_raw("control", control))
    old_candidate = dict(bus.messages_on("object.rule-candidate")[-1].payload)
    old_pattern = dict(bus.messages_on("object.pattern")[-1].payload)
    await huginn.ingest(_raw("success-v2-correction", corrected_success))

    final_context = dict(bus.messages_on("object.context-index")[-1].payload)
    final_cases = cast(list[dict[str, object]], final_context["cases"])
    assert {case["revision"] for case in final_cases} == {1, 2}
    assert len({case["case_id"] for case in final_cases}) == 2
    assert final_context["cohort_snapshot_ref"].endswith(
        final_context["idempotency_key"].rsplit(":", 1)[1]
    )

    final_candidate = dict(bus.messages_on("object.rule-candidate")[-1].payload)
    final_pattern = dict(bus.messages_on("object.pattern")[-1].payload)
    assert final_candidate["case_scope"] == {
        "access_scope_digest": first_success.access_scope_digest,
        "purpose": first_success.purpose,
    }
    assert final_candidate != old_candidate
    assert final_pattern["pattern_id"] == final_candidate["suggested_pattern"]
    assert len(publisher.packages) == 2
    final_package = publisher.packages[-1]
    materializer = _materializer(muninn)
    replayed = await _replay_package(final_candidate, materializer)
    assert replayed.content_digest == final_package.content_digest
    assert replayed.candidate.digest == final_package.candidate.digest
    assert final_package.replay.first_result_digest == final_package.replay.second_result_digest
    assert final_package.replay.first_result_digest == final_package.candidate.digest

    await norns.on_typed_message("object.context-index", final_context)
    assert bus.messages_on("object.rule-candidate")[-1].payload == final_candidate
    restarted_muninn = Muninn(
        case_history=materializer,
        durable_state_store=durable,
        case_history_clock=lambda: NOW,
    )
    await restarted_muninn.on_typed_message("object.pattern", final_pattern)
    retained = await restarted_muninn.read_operating_pattern(
        cohort_key=final_pattern["cohort_key"],
        pattern_id=final_pattern["pattern_id"],
        access_scope_digest=first_success.access_scope_digest,
        purpose=first_success.purpose,
    )
    assert retained is not None
    assert retained["execution_authority"] is False
    assert retained["promotion_authority"] is False

    assert (
        await muninn.read_operating_pattern(
            cohort_key=old_pattern["cohort_key"],
            pattern_id=old_pattern["pattern_id"],
            access_scope_digest=first_success.access_scope_digest,
            purpose=first_success.purpose,
        )
        is None
    )
    await _assert_candidate_source_refused(old_candidate, materializer)

    action_type = _action_type()
    receipt = _promotion_receipt(action_type, final_package)
    authority = ReviewedReplayAuthority(
        (
            ReviewedReplayPromotionEvidence(
                action_type=action_type.name,
                action_type_version=action_type.version,
                action_type_digest=receipt.action_type_digest,
                fdai_revision=receipt.fdai_revision,
                scenario_set_version=receipt.scenario_set_version,
                candidate_digest=final_package.candidate.digest,
                package_digest=final_package.content_digest,
                replay_first_digest=final_package.replay.first_result_digest,
                replay_second_digest=final_package.replay.second_result_digest,
                promotion_evidence_digest=receipt.evidence_digest,
                review_ref="governance-review:prediction-learning-p45",
                reviewer_principal="independent-governance-reviewer",
                approved=True,
            ),
        )
    )
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(authority),
    )
    await registry.refresh_for_update(action_type.name)
    assert (
        registry.consider_promotion(
            action_type=action_type,
            metrics=_metrics(receipt, samples=0),
            receipt=receipt,
        ).mode
        is Mode.SHADOW
    )
    assert (
        registry.consider_promotion(
            action_type=action_type,
            metrics=_metrics(_promotion_receipt(action_type, final_package, ready=False)),
            receipt=_promotion_receipt(action_type, final_package, ready=False),
        ).mode
        is Mode.SHADOW
    )
    promoted = registry.consider_promotion(
        action_type=action_type,
        metrics=_metrics(receipt),
        receipt=receipt,
    )
    await registry.persist(action_type.name)
    assert promoted.mode is Mode.ENFORCE
    first_demote = registry.demote(action_type.name)
    second_demote = registry.demote(action_type.name)
    assert first_demote.mode is second_demote.mode is Mode.SHADOW
    assert second_demote.demoted_at == first_demote.demoted_at

    metadata = cast(InMemoryCaseHistoryMetadataStore, materializer._metadata)
    deleted_case = final_cases[0]
    record = await metadata.latest(
        str(deleted_case["case_id"]),
        access_scope_digest=first_success.access_scope_digest,
    )
    assert record is not None and record.storage_ref is not None
    await metadata.mark_deletion_started(
        record.case_id,
        access_scope_digest=record.access_scope_digest,
        revision=record.revision,
        storage_refs=(record.storage_ref,),
        started_at=record.deletion_due_at,
    )
    await _assert_candidate_source_refused(final_candidate, materializer)


async def test_p4_p5_negative_scope_and_stale_revision_boundaries() -> None:
    bus, huginn, muninn, norns, _mimir, _publisher, _durable = _wire()
    success = _input("c", OperationalOutcomeClass.SUCCESS)
    control = _input("d", OperationalOutcomeClass.ROLLBACK)
    cross_scope = _input(
        "e",
        OperationalOutcomeClass.ROLLBACK,
        access_scope_digest="e" * 64,
    )
    stale = _input(
        "f",
        OperationalOutcomeClass.ROLLBACK,
        event_time_cutoff=NOW - timedelta(days=365),
    )

    await huginn.ingest(_raw("success", success))
    await huginn.ingest(_raw("cross-scope-control", cross_scope))
    assert bus.messages_on("object.rule-candidate") == []
    await huginn.ingest(_raw("control", control))
    before = len(bus.messages_on("object.rule-candidate"))
    stale_context = dict(bus.messages_on("object.context-index")[-1].payload)
    stale_cases = [dict(case) for case in cast(list[dict[str, object]], stale_context["cases"])]
    stale_cases[0]["event_time_cutoff"] = stale.event_time_cutoff.isoformat()
    stale_context["cases"] = stale_cases
    await norns.on_typed_message("object.context-index", stale_context)
    assert len(bus.messages_on("object.rule-candidate")) == before

    pattern = bus.messages_on("object.pattern")[-1].payload
    assert (
        await muninn.read_operating_pattern(
            cohort_key=pattern["cohort_key"],
            pattern_id=pattern["pattern_id"],
            access_scope_digest="e" * 64,
            purpose=success.purpose,
        )
        is None
    )


async def test_authorized_pattern_read_does_not_bypass_unbound_current_case_reuse() -> None:
    bus, huginn, muninn, _norns, _mimir, _publisher, durable = _wire()
    success = _input("a", OperationalOutcomeClass.SUCCESS, corrected=True)
    control = _input("b", OperationalOutcomeClass.ROLLBACK)
    await huginn.ingest(_raw("success", success))
    await huginn.ingest(_raw("control", control))
    pattern = bus.messages_on("object.pattern")[-1].payload
    reader = OperatingPatternQuery(
        store=durable,
        materializer=lambda: _materializer(muninn),
        admission=_ReadAdmission(),
        source_revision="example-release",
        clock=lambda: NOW,
    )
    invocation = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="operator-one",
        principal_scope_digest="sha256:" + "f" * 64,
        purposes=("operations-review",),
        authentication_receipt_ref="sha256:" + "e" * 64,
        authentication_request_ref="semantic-request-one",
    )
    result = await reader.read(
        {
            "access_scope_digest": success.access_scope_digest,
            "purpose": success.purpose,
            "failure_fingerprint": None,
            "limit": 20,
        },
        invocation,
    )
    case_ref = result["patterns"][0]["case_refs"][0]
    context = OperationalCaseContext(
        case_ref=case_ref,
        failure_fingerprint=success.failure_fingerprint.digest,
        resource_type=success.failure_fingerprint.resource_type,
        action_type=success.action_type,
        required_topology_role="service",
        graph_digest="a" * 64,
        owner_digest="b" * 64,
        evidence_cutoff=success.event_time_cutoff,
        access_scope_digest=success.access_scope_digest,
        purpose=success.purpose,
    )
    library = InMemoryPatternLibrary()
    library.add(
        vector=(1.0, 0.0, 0.0),
        action=LearnedAction(
            signature="sig-operational",
            rule_id="learned.operational.restart-service",
            action_type=success.action_type,
            params={"target": "service-a"},
            incident_id="case-success",
            success_rate=1.0,
            reuse_count=3,
            operational_case=context,
        ),
    )
    event = Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "event-10",
            "source": "example",
            "event_type": "change_detected",
            "detected_at": NOW.isoformat(),
            "ingested_at": NOW.isoformat(),
            "mode": "shadow",
            "payload": {"resource": {"type": "kubernetes.service", "props": {}}},
        }
    )
    decision = await T1Tier(
        embedding_model=_FixedEmbedding(),
        pattern_library=library,
        current_reuse_verifier=None,
        case_history=_materializer(muninn),
        config=T1Config(similarity_threshold=0.1, min_success_rate=0.1),
        clock=lambda: NOW,
    ).evaluate(event=event)
    assert result["patterns"][0]["pattern_id"] == pattern["pattern_id"]
    assert result["execution_authority"] is False
    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "current_reuse_verifier_unavailable"

"""Story #370 governed operational-learning composition on one pinned release."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.agents._framework.adapters import InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    FailureFingerprint,
    OperationalCaseInput,
    OperationalEvidenceSourceKind,
    OperationalOutcomeClass,
    OperationalReceiptFact,
    OperationalReceiptType,
)
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCheckReceipts,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogValidationRequest,
    EligibleOperationalOutcome,
    PinnedLearningRelease,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    ReviewedReplayAuthority,
    ReviewedReplayPersistedAuthorityVerifier,
    ReviewedReplayPromotionEvidence,
    ReviewedReplayReceiptVerifier,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
    operational_case_event,
)
from fdai.core.risk_gate import PromotionMetrics
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode, OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIO_PATH = (
    REPO_ROOT
    / "services/core-control-plane/tests/scenarios/operational-learning"
    / "v2026.08-governed-learning.json"
)


class _Validator:
    def __init__(self, scenario_set_version: str) -> None:
        self._scenario_set_version = scenario_set_version

    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
        common = {
            "candidate_digest": request.candidate.digest,
            "artifact_digest": request.artifact_digest,
        }
        replay_digest = request.candidate.digest
        return CatalogCheckReceipts(
            schema=SchemaCheckReceipt(
                **common,
                schema_version=request.schema_version,
                passed=True,
            ),
            replay=ReplayCheckReceipt(
                **common,
                replay_version="operational-learning-replay-v1",
                first_result_digest=replay_digest,
                second_result_digest=replay_digest,
                passed=True,
            ),
            shadow=ShadowCheckReceipt(
                **common,
                scenario_set_id=self._scenario_set_version,
                baseline_result_digest="1" * 64,
                challenger_result_digest="2" * 64,
                regression_passed=True,
                policy_escapes=0,
                passed=True,
            ),
            policy=PolicyCheckReceipt(
                **common,
                policy_version="operational-learning-policy-v1",
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


def _scenario() -> dict[str, Any]:
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _receipt(
    receipt_type: OperationalReceiptType,
    marker: str,
    outcome: OperationalOutcomeClass,
    *,
    occurred_at: datetime,
) -> OperationalReceiptFact:
    if receipt_type is OperationalReceiptType.AUDIT:
        facts: tuple[tuple[str, str | bool | int], ...] = (
            ("event_type", "action.completed"),
            ("decision", "auto"),
            ("mode", "enforce"),
        )
    elif receipt_type is OperationalReceiptType.ACTION:
        facts = (
            ("action_type", "remediate.tag-add"),
            ("execution_outcome", outcome.value),
            ("dry_run_digest", "d" * 64),
            ("terminal_receipt_digest", "e" * 64),
            ("rollback_receipt_digest", "f" * 64),
            ("affected_resource_count", 1),
        )
    else:
        verified = outcome is OperationalOutcomeClass.SUCCESS
        facts = (
            ("label", "verified" if verified else "mismatch"),
            ("verification_status", "verified" if verified else "mismatch"),
            ("execution_outcome", outcome.value),
            ("rollback_succeeded", outcome is OperationalOutcomeClass.ROLLBACK),
            ("recurrence", False),
        )
    return OperationalReceiptFact(
        receipt_type=receipt_type,
        receipt_digest=marker * 64,
        occurred_at=occurred_at,
        facts=facts,
    )


def _outcome(
    marker: str,
    outcome: OperationalOutcomeClass,
    scenario: dict[str, Any],
    *,
    source_synthetic: bool = False,
    evidence_complete: bool = True,
    conflict_digests: tuple[str, ...] = (),
    cutoff: datetime | None = None,
) -> EligibleOperationalOutcome:
    reviewed_at = _timestamp(scenario["reviewed_at"])
    event_time_cutoff = cutoff or reviewed_at - timedelta(days=1)
    return EligibleOperationalOutcome(
        release=PinnedLearningRelease(
            fdai_revision=scenario["fdai_revision"],
            scenario_set_version=scenario["scenario_set_version"],
        ),
        correlation_digest=marker * 64,
        purpose="operational-learning",
        access_scope_digest="9" * 64,
        redaction_policy_version="1.0.0",
        event_time_cutoff=event_time_cutoff,
        reviewed_at=reviewed_at,
        maximum_age=timedelta(days=30),
        failure_fingerprint=FailureFingerprint(
            resource_type=scenario["resource_type"],
            failure_mechanism=scenario["failure_mechanism"],
            symptom_codes=("endpoint_owner_mismatch", "request_route_failure"),
            topology_roles=("client", "service", "selected_workload"),
            ownership_shape=("service_selects_workload",),
        ),
        action_type=scenario["action_type"],
        outcome_class=outcome,
        source_kind=OperationalEvidenceSourceKind.LIVE,
        source_identity_digest=marker.swapcase().lower() * 64,
        source_synthetic=source_synthetic,
        evidence_complete=evidence_complete,
        conflict_digests=conflict_digests,
        receipts=tuple(
            _receipt(receipt_type, digest_marker, outcome, occurred_at=event_time_cutoff)
            for receipt_type, digest_marker in (
                (OperationalReceiptType.AUDIT, "1"),
                (OperationalReceiptType.ACTION, "2"),
                (OperationalReceiptType.RESPONSE_OUTCOME, "3"),
            )
        ),
    )


def _wire(
    scenario: dict[str, Any],
) -> tuple[InMemoryBus, _Publisher, InMemoryStateStore]:
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
    durable = InMemoryStateStore()
    publisher = _Publisher()
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        durable_state_store=durable,
    )
    norns = Norns(clock=lambda: _timestamp(scenario["reviewed_at"]))
    mimir = Mimir(
        catalog_candidate_compiler=CatalogCandidateCompiler(
            validator=_Validator(scenario["scenario_set_version"]),
            catalog_version="catalog-v2026.08",
            schema_version="2.0.0",
            expected_fdai_revision=scenario["fdai_revision"],
            expected_scenario_set_version=scenario["scenario_set_version"],
            clock=lambda: _timestamp(scenario["reviewed_at"]),
        ),
        catalog_review_publisher=publisher,
    )
    saga = Saga(audit_chain=InMemoryAuditChain())
    for agent in (muninn, norns, mimir, saga):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    bus.subscribe("object.rule", "Saga", saga.on_typed_message)
    return bus, publisher, durable


async def _publish_case(bus: InMemoryBus, case_input: OperationalCaseInput) -> None:
    await bus.publish("Huginn", "object.event", operational_case_event(case_input))


def _action_type(name: str) -> OntologyActionType:
    action_types = load_action_type_catalog(
        REPO_ROOT / "rule-catalog/action-types",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    return next(item for item in action_types if item.name == name)


def _promotion_receipt(
    action_type: OntologyActionType,
    scenario: dict[str, Any],
) -> OperationalPromotionReceipt:
    assert action_type.provenance is not None
    return OperationalPromotionReceipt(
        fdai_revision=scenario["fdai_revision"],
        scenario_set_version=scenario["scenario_set_version"],
        action_type_name=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=action_type_digest(action_type),
        evidence_digest="8" * 64,
        observation_days=14.0,
        live_observation_days=14,
        sample_count=100,
        benchmark_samples=50,
        live_shadow_samples=50,
        correct_count=100,
        accuracy=1.0,
        accuracy_ci_lower=0.96,
        accuracy_ci_upper=1.0,
        benchmark_accuracy=1.0,
        benchmark_accuracy_ci_lower=0.92,
        benchmark_accuracy_ci_upper=1.0,
        live_shadow_accuracy=1.0,
        live_shadow_accuracy_ci_lower=0.92,
        live_shadow_accuracy_ci_upper=1.0,
        policy_escapes=0,
        rollback_rate=0.0,
        recurrence_rate=0.0,
        executed_samples=50,
        recurrence_complete_samples=50,
        recurrence_incomplete_samples=0,
        simulation_review_rate=0.0,
        causal_evidence_failures=0,
        ready=True,
        gaps=(),
        decision_evidence_receipt_digest="sha256:" + "6" * 64,
        decision_evidence_verification_bundle_digest="sha256:" + "7" * 64,
    )


async def test_pinned_release_publishes_once_then_promotes_only_after_review() -> None:
    scenario = _scenario()
    bus, publisher, _ = _wire(scenario)
    success = _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input()
    rollback = _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input()

    await _publish_case(bus, success)
    await _publish_case(bus, rollback)
    await _publish_case(bus, rollback)

    expected = scenario["expected"]
    assert (
        len(bus.messages_on("object.context-index")[-1].payload["cases"])
        == expected["immutable_cases"]
    )
    assert len(bus.messages_on("object.rule-candidate")) == expected["rule_candidates"]
    assert len(publisher.packages) == expected["catalog_reviews"]
    package = publisher.packages[0]
    assert package.candidate.fdai_revision == scenario["fdai_revision"]
    assert package.candidate.scenario_set_version == scenario["scenario_set_version"]
    assert package.review_required is True

    state = InMemoryStateStore()
    action_type = _action_type(scenario["action_type"])
    receipt = _promotion_receipt(action_type, scenario)
    authority = ReviewedReplayAuthority(
        (
            ReviewedReplayPromotionEvidence(
                action_type=action_type.name,
                action_type_version=action_type.version,
                action_type_digest=receipt.action_type_digest,
                fdai_revision=scenario["fdai_revision"],
                scenario_set_version=scenario["scenario_set_version"],
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
                replay_first_digest=package.replay.first_result_digest,
                replay_second_digest=package.replay.second_result_digest,
                promotion_evidence_digest=receipt.evidence_digest,
                review_ref="governance-review:v2026.08",
                reviewer_principal="independent-governance-reviewer",
                approved=True,
            ),
        )
    )
    registry = StateStoreActionPromotionRegistry(
        store=state,
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(authority),
    )
    assert registry.mode_of(action_type.name).value == expected["mode_before_review"]

    await registry.refresh_for_update(action_type.name)
    promoted = registry.consider_promotion(
        action_type=action_type,
        metrics=_promotion_metrics(receipt),
        receipt=receipt,
    )
    await registry.persist(action_type.name)
    assert promoted.mode.value == expected["mode_after_review"]

    duplicate = registry.consider_promotion(
        action_type=action_type,
        metrics=_promotion_metrics(receipt),
        receipt=receipt,
    )
    assert duplicate.promoted_at == promoted.promoted_at

    restarted = StateStoreActionPromotionRegistry(
        store=state,
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(authority),
    )
    await restarted.refresh(action_type.name)
    assert restarted.mode_of(action_type.name) is Mode.ENFORCE

    await restarted.refresh_for_update(action_type.name)
    restarted.demote(action_type.name)
    await restarted.persist(action_type.name)
    after_demotion = StateStoreActionPromotionRegistry(
        store=state,
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(authority),
    )
    await after_demotion.refresh(action_type.name)
    assert after_demotion.mode_of(action_type.name).value == expected["mode_after_demotion"]


def _promotion_metrics(receipt: OperationalPromotionReceipt) -> PromotionMetrics:
    return PromotionMetrics(
        action_type=receipt.action_type_name,
        shadow_days=receipt.live_observation_days,
        samples=receipt.sample_count,
        accuracy=receipt.accuracy,
        policy_escapes=receipt.policy_escapes,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"evidence_complete": False}, "incomplete"),
        ({"source_synthetic": True}, "labeled live"),
        ({"conflict_digests": ("c" * 64,)}, "conflicting"),
        (
            {"cutoff": datetime(2026, 1, 1, tzinfo=UTC)},
            "stale",
        ),
    ],
)
def test_eligible_outcome_composer_rejects_negative_evidence(
    overrides: dict[str, Any],
    message: str,
) -> None:
    scenario = _scenario()

    with pytest.raises(ValueError, match=message):
        _outcome(
            "c",
            OperationalOutcomeClass.SUCCESS,
            scenario,
            **overrides,
        ).to_case_input()


async def test_norns_and_mimir_reject_tampered_case_review_evidence() -> None:
    scenario = _scenario()
    bus, _, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    candidate = dict(bus.messages_on("object.rule-candidate")[0].payload)
    evidence = dict(candidate["evidence"])
    reviews = [dict(item) for item in evidence["case_reviews"]]
    reviews[0]["source_synthetic"] = True
    evidence["case_reviews"] = reviews
    candidate["evidence"] = evidence

    negative_bus, _, _ = _wire(scenario)
    await negative_bus.publish("Norns", "object.rule-candidate", candidate)

    outcomes = negative_bus.messages_on("object.rule")
    assert outcomes[-1].payload["outcome"] == "quarantined"
    assert outcomes[-1].payload["reason"] == ("catalog_compile:case_evidence_synthetic_live")

    context = dict(bus.messages_on("object.context-index")[-1].payload)
    context_cases = [dict(item) for item in context["cases"]]
    context_cases[0]["evidence_complete"] = False
    context["cases"] = context_cases
    before = len(bus.messages_on("object.rule-candidate"))
    await bus.publish("Muninn", "object.context-index", context)
    assert len(bus.messages_on("object.rule-candidate")) == before


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"evidence_complete": False}, "case_evidence_incomplete"),
        ({"source_synthetic": True}, "case_evidence_synthetic_live"),
        ({"conflict_digests": ["c" * 64]}, "case_evidence_conflicting"),
        (
            {"event_time_cutoff": "2026-01-01T00:00:00+00:00"},
            "candidate_digest_conflict",
        ),
    ],
)
async def test_mimir_independently_rejects_negative_case_reviews(
    mutation: dict[str, Any],
    reason: str,
) -> None:
    scenario = _scenario()
    bus, _, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    candidate = dict(bus.messages_on("object.rule-candidate")[0].payload)
    evidence = dict(candidate["evidence"])
    reviews = [dict(item) for item in evidence["case_reviews"]]
    reviews[0].update(mutation)
    evidence["case_reviews"] = reviews
    candidate["evidence"] = evidence

    negative_bus, _, _ = _wire(scenario)
    await negative_bus.publish("Norns", "object.rule-candidate", candidate)

    assert negative_bus.messages_on("object.rule")[-1].payload["reason"] == (
        f"catalog_compile:{reason}"
    )


async def test_mimir_rejects_duplicate_immutable_case_review() -> None:
    scenario = _scenario()
    bus, _, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    candidate = dict(bus.messages_on("object.rule-candidate")[0].payload)
    evidence = dict(candidate["evidence"])
    reviews = [dict(item) for item in evidence["case_reviews"]]
    reviews[1] = dict(reviews[0])
    evidence["case_reviews"] = reviews
    candidate["evidence"] = evidence

    negative_bus, _, _ = _wire(scenario)
    await negative_bus.publish("Norns", "object.rule-candidate", candidate)

    assert negative_bus.messages_on("object.rule")[-1].payload["reason"] == (
        "catalog_compile:candidate_schema_invalid"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"evidence_complete": False},
        {"source_synthetic": True},
        {"conflict_digests": ["c" * 64]},
        {"event_time_cutoff": "2026-01-01T00:00:00+00:00"},
    ],
)
async def test_norns_holds_negative_case_reviews(mutation: dict[str, Any]) -> None:
    scenario = _scenario()
    bus, _, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    context = dict(bus.messages_on("object.context-index")[-1].payload)
    cases = [dict(item) for item in context["cases"]]
    cases[0].update(mutation)
    context["cases"] = cases

    before = len(bus.messages_on("object.rule-candidate"))
    await bus.publish("Muninn", "object.context-index", context)

    assert len(bus.messages_on("object.rule-candidate")) == before


async def test_norns_holds_duplicate_case_revision() -> None:
    scenario = _scenario()
    bus, _, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    context = dict(bus.messages_on("object.context-index")[-1].payload)
    cases = [dict(item) for item in context["cases"]]
    cases[1] = dict(cases[0])
    context["cases"] = cases

    before = len(bus.messages_on("object.rule-candidate"))
    await bus.publish("Muninn", "object.context-index", context)

    assert len(bus.messages_on("object.rule-candidate")) == before


async def test_reviewed_replay_authority_rejects_another_release() -> None:
    scenario = _scenario()
    bus, publisher, _ = _wire(scenario)
    await _publish_case(
        bus,
        _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input(),
    )
    await _publish_case(
        bus,
        _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input(),
    )
    package = publisher.packages[0]
    action_type = _action_type(scenario["action_type"])
    receipt = _promotion_receipt(action_type, scenario)
    authority = ReviewedReplayAuthority(
        (
            ReviewedReplayPromotionEvidence(
                action_type=action_type.name,
                action_type_version=action_type.version,
                action_type_digest=receipt.action_type_digest,
                fdai_revision=scenario["fdai_revision"],
                scenario_set_version=scenario["scenario_set_version"],
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
                replay_first_digest=package.replay.first_result_digest,
                replay_second_digest=package.replay.second_result_digest,
                promotion_evidence_digest=receipt.evidence_digest,
                review_ref="governance-review:v2026.08",
                reviewer_principal="independent-governance-reviewer",
                approved=True,
            ),
        )
    )
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        receipt_verifier=ReviewedReplayReceiptVerifier(authority),
    )

    record = registry.consider_promotion(
        action_type=action_type,
        metrics=_promotion_metrics(receipt),
        receipt=replace(receipt, fdai_revision="b" * 40),
    )

    assert record.mode is Mode.SHADOW

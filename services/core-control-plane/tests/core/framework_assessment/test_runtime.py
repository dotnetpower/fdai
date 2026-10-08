"""Failure-boundary and replay tests for shared WAF and CAF assessment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.framework_assessment import (
    FRAMEWORK_ASSESSMENT_TOPIC,
    FrameworkApplicabilityDecision,
    FrameworkApplicabilityStatus,
    FrameworkAssessmentProfile,
    FrameworkAssessmentRequest,
    FrameworkAssessmentRuntime,
    FrameworkAssessmentService,
    FrameworkEvaluationStatus,
    FrameworkEvidenceReceipt,
    FrameworkOwnerBinding,
    FrameworkSatisfactionStatus,
    FrameworkTradeoffRecord,
    replay_framework_assessment,
)
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkCrosswalkKind,
    FrameworkCrosswalkReference,
    FrameworkEvidenceRole,
    FrameworkGenerationContract,
    FrameworkProcessPhase,
    FrameworkRelationshipState,
    FrameworkRequirementKind,
    FrameworkScopeKind,
    canonical_digest,
    load_framework_assessment_catalog,
)

ROOT = Path(__file__).resolve().parents[5]
GENERATED = ROOT / "rule-catalog/framework-assessments/generated"
NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
SCOPE_DIGEST = canonical_digest({"scope": "example"})


def _catalog(framework_id: str) -> FrameworkAssessmentCatalog:
    return load_framework_assessment_catalog(GENERATED / f"{framework_id}.json")


def _profile(
    catalog: FrameworkAssessmentCatalog,
    *,
    not_applicable: str | None = None,
    na_expired: bool = False,
) -> FrameworkAssessmentProfile:
    decisions = []
    owners = []
    for control in catalog.controls:
        if control.control_id == not_applicable:
            decision = FrameworkApplicabilityDecision(
                control_id=control.control_id,
                status=FrameworkApplicabilityStatus.NOT_APPLICABLE,
                requested_by="requester@example.com",
                owner_slot=control.owner_slot,
                cadence_days=control.cadence_days,
                justification="The typed deployment profile excludes this area.",
                approved_by="approver@example.com",
                approved_at=NOW - timedelta(days=10),
                expires_at=NOW - timedelta(seconds=1) if na_expired else NOW + timedelta(days=30),
            )
        else:
            decision = FrameworkApplicabilityDecision(
                control_id=control.control_id,
                status=FrameworkApplicabilityStatus.APPLICABLE,
                requested_by="requester@example.com",
                owner_slot=control.owner_slot,
                cadence_days=control.cadence_days,
            )
        decisions.append(decision)
        owners.append(
            FrameworkOwnerBinding(
                control_id=control.control_id,
                owner_slot=control.owner_slot,
                owner_identity=f"{control.owner_slot}@example.com",
            )
        )
    is_waf = catalog.framework_scope is FrameworkScopeKind.WORKLOAD
    return FrameworkAssessmentProfile.create(
        profile_id=f"{catalog.framework_id}-profile",
        framework_id=catalog.framework_id,
        framework_version=catalog.framework_version,
        catalog_digest=catalog.catalog_digest,
        scope_kind=(FrameworkScopeKind.WORKLOAD if is_waf else FrameworkScopeKind.CLOUD_ESTATE),
        scope_digest=SCOPE_DIGEST,
        ontology_release="2026.09",
        applicability=tuple(decisions),
        owners=tuple(owners),
        reviewed_by="reviewer@example.com",
        reviewed_at=NOW - timedelta(days=1),
        inventory_generation="inventory-1" if is_waf else None,
        hierarchy_generation=None if is_waf else "hierarchy-1",
        operating_model=None if is_waf else "platform-operating-model",
        environment_classes=() if is_waf else ("development",),
        regulatory_context=(),
    )


def _receipt(
    catalog: FrameworkAssessmentCatalog,
    control_id: str,
    requirement_index: int,
) -> FrameworkEvidenceReceipt:
    control = next(item for item in catalog.controls if item.control_id == control_id)
    requirement = control.evidence[requirement_index]
    assert requirement.authoritative_producer is not None
    return FrameworkEvidenceReceipt(
        framework_id=catalog.framework_id,
        control_id=control_id,
        requirement_id=requirement.requirement_id,
        evidence_ref=f"evidence://{control_id}/{requirement_index}",
        evidence_kind=requirement.kind.value,
        producer=requirement.authoritative_producer,
        source_identity="observer@example.com",
        scope_digest=SCOPE_DIGEST,
        observed_at=NOW - timedelta(minutes=2),
        recorded_at=NOW - timedelta(minutes=1),
        evidence_digest=canonical_digest(
            {"control_id": control_id, "requirement": requirement_index}
        ),
        freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=FrameworkSatisfactionStatus.SATISFIED,
        evidence_role=requirement.evidence_role,
        process_phase=requirement.process_phase,
        inventory_generation=(
            "inventory-1"
            if requirement.generation_contract is FrameworkGenerationContract.INVENTORY
            else None
        ),
        hierarchy_generation=(
            "hierarchy-1"
            if requirement.generation_contract is FrameworkGenerationContract.HIERARCHY
            else None
        ),
    )


def _control_receipts(
    catalog: FrameworkAssessmentCatalog,
    control_id: str,
) -> tuple[FrameworkEvidenceReceipt, ...]:
    control = next(item for item in catalog.controls if item.control_id == control_id)
    return tuple(_receipt(catalog, control_id, index) for index in range(len(control.evidence)))


def _request(
    catalog: FrameworkAssessmentCatalog,
    evidence: tuple[FrameworkEvidenceReceipt, ...] = (),
    *,
    profile: FrameworkAssessmentProfile | None = None,
    tradeoffs: tuple[FrameworkTradeoffRecord, ...] = (),
) -> FrameworkAssessmentRequest:
    return FrameworkAssessmentRequest(
        assessment_id=f"assessment-{catalog.framework_id}",
        profile=profile or _profile(catalog),
        evaluated_at=NOW,
        recorded_at=NOW,
        evidence=tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.control_id,
                    item.requirement_id,
                    item.evidence_ref,
                ),
            )
        ),
        tradeoffs=tradeoffs,
    )


def _result_control(result: Any, control_id: str):
    return next(item for item in result.controls if item.control_id == control_id)


def test_complete_exact_scope_waf_evidence_satisfies_one_control() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id

    result = FrameworkAssessmentRuntime(catalog).assess(
        _request(catalog, _control_receipts(catalog, control_id))
    )

    control = _result_control(result, control_id)
    assert len(result.controls) == 59
    assert control.evaluation is FrameworkEvaluationStatus.EVALUATED
    assert control.satisfaction is FrameworkSatisfactionStatus.SATISFIED
    assert control.evidence_complete is True
    assert result.execution_authority is False


def test_supporting_requirements_neither_decide_nor_veto_a_control() -> None:
    catalog = _catalog("azure-mcsb")
    supported = next(item for item in catalog.controls if item.control_id == "NS-8")
    gated = next(item for item in catalog.controls if item.control_id == "NS-2")
    assert {item.evidence_role for item in supported.evidence} == {
        FrameworkEvidenceRole.DECISIVE,
        FrameworkEvidenceRole.SUPPORTING_ONLY,
    }

    def manual(control_id: str) -> FrameworkEvidenceReceipt:
        control = next(item for item in catalog.controls if item.control_id == control_id)
        index = next(
            position
            for position, item in enumerate(control.evidence)
            if item.kind is FrameworkRequirementKind.ARTIFACT
        )
        return _receipt(catalog, control_id, index)

    result = FrameworkAssessmentRuntime(catalog).assess(
        _request(catalog, (manual(supported.control_id), manual(gated.control_id)))
    )

    assert _result_control(result, "NS-8").satisfaction is FrameworkSatisfactionStatus.SATISFIED
    assert _result_control(result, "NS-2").satisfaction is FrameworkSatisfactionStatus.UNKNOWN


@pytest.mark.parametrize(
    ("change", "limitation"),
    [
        ({"complete": False}, "incomplete_evidence"),
        ({"truncated": True}, "truncated_evidence"),
        ({"conflicting": True}, "conflicting_evidence"),
        ({"synthetic": True}, "synthetic_evidence"),
        ({"provider_error": "unsupported_resource_type"}, "provider_error"),
        ({"scope_digest": canonical_digest({"scope": "wrong"})}, "wrong_scope"),
        ({"inventory_generation": "inventory-stale"}, "wrong_inventory_generation"),
    ],
)
def test_rule_evidence_failure_boundaries_remain_unknown(
    change: dict[str, object],
    limitation: str,
) -> None:
    catalog = _catalog("azure-waf")
    control = next(
        item
        for item in catalog.controls
        if any(requirement.kind.value == "rule" for requirement in item.evidence)
    )
    receipts = list(_control_receipts(catalog, control.control_id))
    index = next(
        index
        for index, requirement in enumerate(control.evidence)
        if requirement.kind.value == "rule"
    )
    receipts[index] = replace(receipts[index], **change)

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, tuple(receipts)))

    assessed = _result_control(result, control.control_id)
    assert assessed.evaluation is FrameworkEvaluationStatus.NOT_EVALUATED
    assert assessed.satisfaction is FrameworkSatisfactionStatus.UNKNOWN
    assert limitation in assessed.limitations


def test_stale_rule_evidence_remains_unknown() -> None:
    catalog = _catalog("azure-waf")
    control = next(
        item
        for item in catalog.controls
        if any(requirement.kind.value == "rule" for requirement in item.evidence)
    )
    receipts = list(_control_receipts(catalog, control.control_id))
    index = next(
        index
        for index, requirement in enumerate(control.evidence)
        if requirement.kind.value == "rule"
    )
    receipt = receipts[index]
    receipts[index] = replace(
        receipt,
        observed_at=NOW - timedelta(seconds=receipt.freshness_ceiling_seconds + 1),
        recorded_at=NOW - timedelta(seconds=receipt.freshness_ceiling_seconds),
    )

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, tuple(receipts)))

    assessed = _result_control(result, control.control_id)
    assert assessed.satisfaction is FrameworkSatisfactionStatus.UNKNOWN
    assert "stale_evidence" in assessed.limitations


def test_supporting_external_evidence_cannot_establish_satisfaction() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    supporting = tuple(
        replace(item, evidence_role=FrameworkEvidenceRole.SUPPORTING_ONLY)
        for item in _control_receipts(catalog, control_id)
    )

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, supporting))

    control = _result_control(result, control_id)
    assert control.satisfaction is FrameworkSatisfactionStatus.UNKNOWN
    assert "supporting_evidence_only" in control.limitations


def test_approved_not_applicable_is_separate_from_missing_evidence() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id

    result = FrameworkAssessmentRuntime(catalog).assess(
        _request(catalog, profile=_profile(catalog, not_applicable=control_id))
    )
    expired = FrameworkAssessmentRuntime(catalog).assess(
        _request(
            catalog,
            profile=_profile(catalog, not_applicable=control_id, na_expired=True),
        )
    )

    assert _result_control(result, control_id).satisfaction is (
        FrameworkSatisfactionStatus.NOT_APPLICABLE
    )
    assert _result_control(expired, control_id).satisfaction is (
        FrameworkSatisfactionStatus.UNKNOWN
    )


@pytest.mark.parametrize(
    "missing_phase",
    [FrameworkProcessPhase.PROCEDURE, FrameworkProcessPhase.EXECUTION],
)
def test_caf_process_controls_require_procedure_and_execution(
    missing_phase: FrameworkProcessPhase,
) -> None:
    catalog = _catalog("azure-caf")
    control_id = "strategy"
    complete = _control_receipts(catalog, control_id)
    missing = tuple(item for item in complete if item.process_phase is not missing_phase)

    satisfied = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, complete))
    unknown = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, missing))

    assert _result_control(satisfied, control_id).satisfaction is (
        FrameworkSatisfactionStatus.SATISFIED
    )
    assert _result_control(unknown, control_id).satisfaction is (
        FrameworkSatisfactionStatus.UNKNOWN
    )


def test_tradeoff_is_retained_without_downgrading_failed_control() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    receipts = list(_control_receipts(catalog, control_id))
    receipts[0] = replace(
        receipts[0],
        outcome=FrameworkSatisfactionStatus.FAILED,
    )
    tradeoff = FrameworkTradeoffRecord(
        tradeoff_id="tradeoff-1",
        scope_digest=SCOPE_DIGEST,
        affected_control_ids=(control_id,),
        decision_owner="architecture-owner@example.com",
        rationale_digest=canonical_digest({"reason": "reviewed"}),
        approved_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )

    result = FrameworkAssessmentRuntime(catalog).assess(
        _request(catalog, tuple(receipts), tradeoffs=(tradeoff,))
    )

    assert _result_control(result, control_id).satisfaction is (FrameworkSatisfactionStatus.FAILED)
    assert result.tradeoffs == (tradeoff,)


def test_assessment_replay_is_deterministic() -> None:
    catalog = _catalog("azure-caf")
    request = _request(catalog, _control_receipts(catalog, "ready"))
    runtime = FrameworkAssessmentRuntime(catalog)
    first = runtime.assess(request)

    second = replay_framework_assessment(runtime, request, first.result_digest)

    assert second == first
    with pytest.raises(ValueError, match="digest mismatch"):
        replay_framework_assessment(runtime, request, canonical_digest({"wrong": True}))


class _StateStore:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def append_audit_entry(self, entry: Mapping[str, object]) -> None:
        self.entries.append(dict(entry))


class _EventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        self.published.append((topic, key, dict(payload)))
        return object()


async def test_service_audits_before_publishing_no_authority_result() -> None:
    catalog = _catalog("azure-caf")
    state_store = _StateStore()
    event_bus = _EventBus()
    service = FrameworkAssessmentService(
        FrameworkAssessmentRuntime(catalog),
        state_store,
        event_bus,
    )

    result = await service.assess(_request(catalog))

    assert state_store.entries[0]["result_digest"] == result.result_digest
    assert event_bus.published[0][0] == FRAMEWORK_ASSESSMENT_TOPIC
    assert event_bus.published[0][2]["execution_authority"] is False


def test_runtime_rejects_unknown_evidence_targets() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    receipt = _receipt(catalog, control_id, 0)
    runtime = FrameworkAssessmentRuntime(catalog)

    with pytest.raises(ValueError, match="unknown control"):
        runtime.assess(_request(catalog, (replace(receipt, control_id="unknown-control"),)))
    with pytest.raises(ValueError, match="unknown requirement"):
        runtime.assess(_request(catalog, (replace(receipt, requirement_id="unknown:requirement"),)))


@pytest.mark.parametrize(
    ("change", "limitation"),
    [
        ({"framework_id": "azure-caf"}, "wrong_framework"),
        ({"producer": "unreviewed-producer"}, "wrong_producer"),
        ({"evidence_kind": "unknown"}, "wrong_evidence_kind"),
        (
            {
                "observed_at": NOW + timedelta(seconds=1),
                "recorded_at": NOW + timedelta(seconds=2),
            },
            "evidence_after_cutoff",
        ),
        ({"process_phase": FrameworkProcessPhase.EXECUTION}, "wrong_process_phase"),
    ],
)
def test_decisive_evidence_identity_failures_are_explicit(
    change: dict[str, object],
    limitation: str,
) -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    receipts = list(_control_receipts(catalog, control_id))
    receipts[0] = replace(receipts[0], **change)

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, tuple(receipts)))

    control = _result_control(result, control_id)
    assert control.satisfaction is FrameworkSatisfactionStatus.UNKNOWN
    assert limitation in control.limitations


def test_hierarchy_generation_and_unexpected_generation_fail_closed() -> None:
    caf = _catalog("azure-caf")
    caf_receipts = list(_control_receipts(caf, "ready"))
    caf_receipts[0] = replace(
        caf_receipts[0],
        hierarchy_generation="hierarchy-stale",
    )
    caf_result = FrameworkAssessmentRuntime(caf).assess(_request(caf, tuple(caf_receipts)))
    assert (
        "wrong_hierarchy_generation"
        in _result_control(
            caf_result,
            "ready",
        ).limitations
    )

    waf = _catalog("azure-waf")
    control = next(
        item
        for item in waf.controls
        if any(
            requirement.generation_contract is FrameworkGenerationContract.NONE
            for requirement in item.evidence
        )
    )
    receipts = list(_control_receipts(waf, control.control_id))
    index = next(
        index
        for index, requirement in enumerate(control.evidence)
        if requirement.generation_contract is FrameworkGenerationContract.NONE
    )
    receipts[index] = replace(receipts[index], inventory_generation="inventory-1")
    waf_result = FrameworkAssessmentRuntime(waf).assess(_request(waf, tuple(receipts)))
    assert (
        "unexpected_generation_binding"
        in _result_control(
            waf_result,
            control.control_id,
        ).limitations
    )


@pytest.mark.parametrize(
    ("change", "limitation"),
    [
        ({"framework_id": "azure-caf"}, "supporting_wrong_framework"),
        (
            {"scope_digest": canonical_digest({"scope": "wrong"})},
            "supporting_wrong_scope",
        ),
        (
            {
                "observed_at": NOW + timedelta(seconds=1),
                "recorded_at": NOW + timedelta(seconds=2),
            },
            "supporting_evidence_after_cutoff",
        ),
        ({"provider_error": "unavailable"}, "supporting_provider_error"),
        ({"complete": False}, "supporting_incomplete_evidence"),
        ({"truncated": True}, "supporting_truncated_evidence"),
        ({"conflicting": True}, "supporting_conflicting_evidence"),
        ({"synthetic": True}, "supporting_synthetic_evidence"),
        (
            {"inventory_generation": "inventory-stale"},
            "supporting_wrong_inventory_generation",
        ),
    ],
)
def test_supporting_evidence_failure_boundaries_are_visible(
    change: dict[str, object],
    limitation: str,
) -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    supporting = replace(
        _receipt(catalog, control_id, 0),
        evidence_role=FrameworkEvidenceRole.SUPPORTING_ONLY,
        **change,
    )

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, (supporting,)))

    assert limitation in _result_control(result, control_id).limitations


def test_stale_supporting_evidence_is_visible() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    supporting = _receipt(catalog, control_id, 0)
    supporting = replace(
        supporting,
        evidence_role=FrameworkEvidenceRole.SUPPORTING_ONLY,
        observed_at=NOW - timedelta(seconds=supporting.freshness_ceiling_seconds + 1),
        recorded_at=NOW - timedelta(seconds=supporting.freshness_ceiling_seconds),
    )

    result = FrameworkAssessmentRuntime(catalog).assess(_request(catalog, (supporting,)))

    assert (
        "supporting_stale_evidence"
        in _result_control(
            result,
            control_id,
        ).limitations
    )


def test_requirement_not_applicable_requires_current_independent_approval() -> None:
    catalog = _catalog("azure-waf")
    control_id = catalog.controls[0].control_id
    receipts = list(_control_receipts(catalog, control_id))
    approved = replace(
        receipts[0],
        outcome=FrameworkSatisfactionStatus.NOT_APPLICABLE,
        not_applicable_justification="The component is absent from the exact scope.",
        not_applicable_requested_by="requester@example.com",
        not_applicable_approved_by="approver@example.com",
        approval_expires_at=NOW + timedelta(days=1),
    )
    receipts[0] = approved
    runtime = FrameworkAssessmentRuntime(catalog)

    result = runtime.assess(_request(catalog, tuple(receipts)))
    receipts[0] = replace(approved, approval_expires_at=NOW)
    expired = runtime.assess(_request(catalog, tuple(receipts)))

    assert _result_control(result, control_id).satisfaction is (
        FrameworkSatisfactionStatus.SATISFIED
    )
    assert _result_control(expired, control_id).satisfaction is (
        FrameworkSatisfactionStatus.UNKNOWN
    )
    assert (
        "not_applicable_approval_expired"
        in _result_control(
            expired,
            control_id,
        ).limitations
    )


def test_runtime_rejects_profile_owner_pin_and_tradeoff_mismatches() -> None:
    waf = _catalog("azure-waf")
    with pytest.raises(ValueError, match="profile pins"):
        FrameworkAssessmentRuntime(waf).assess(
            _request(waf, profile=_profile(_catalog("azure-caf")))
        )

    profile = _profile(waf)
    first = profile.applicability[0]
    wrong_decisions = (
        replace(first, owner_slot="wrong-owner"),
        *profile.applicability[1:],
    )
    wrong_owners = (
        replace(profile.owners[0], owner_slot="wrong-owner"),
        *profile.owners[1:],
    )
    wrong_profile = FrameworkAssessmentProfile.create(
        profile_id=profile.profile_id,
        framework_id=profile.framework_id,
        framework_version=profile.framework_version,
        catalog_digest=profile.catalog_digest,
        scope_kind=profile.scope_kind,
        scope_digest=profile.scope_digest,
        ontology_release=profile.ontology_release,
        applicability=wrong_decisions,
        owners=wrong_owners,
        reviewed_by=profile.reviewed_by,
        reviewed_at=profile.reviewed_at,
        inventory_generation=profile.inventory_generation,
        hierarchy_generation=None,
        operating_model=None,
        environment_classes=(),
        regulatory_context=(),
    )
    with pytest.raises(ValueError, match="owner does not match"):
        FrameworkAssessmentRuntime(waf).assess(_request(waf, profile=wrong_profile))

    tradeoff = FrameworkTradeoffRecord(
        tradeoff_id="tradeoff-invalid",
        scope_digest=canonical_digest({"scope": "wrong"}),
        affected_control_ids=(waf.controls[0].control_id,),
        decision_owner="owner@example.com",
        rationale_digest=canonical_digest({"reason": "reviewed"}),
        approved_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="scope"):
        FrameworkAssessmentRuntime(waf).assess(_request(waf, tradeoffs=(tradeoff,)))
    with pytest.raises(ValueError, match="unknown control"):
        FrameworkAssessmentRuntime(waf).assess(
            _request(
                waf,
                tradeoffs=(
                    replace(
                        tradeoff,
                        scope_digest=SCOPE_DIGEST,
                        affected_control_ids=("unknown-control",),
                    ),
                ),
            )
        )
    with pytest.raises(ValueError, match="outside"):
        FrameworkAssessmentRuntime(waf).assess(
            _request(
                waf,
                tradeoffs=(
                    replace(
                        tradeoff,
                        scope_digest=SCOPE_DIGEST,
                        approved_at=NOW + timedelta(seconds=1),
                        expires_at=NOW + timedelta(days=1),
                    ),
                ),
            )
        )


def test_unmapped_and_blocked_catalog_states_remain_explicit() -> None:
    catalog = _catalog("azure-waf")
    first = catalog.controls[0]
    blocked_requirement = first.evidence[0].model_copy(
        update={
            "authoritative_producer": None,
            "blocked_dependency": "external-owner",
        }
    )
    changed = first.model_copy(
        update={
            "evidence": (blocked_requirement, *first.evidence[1:]),
            "crosswalk": (
                FrameworkCrosswalkReference(
                    target_kind=FrameworkCrosswalkKind.MANUAL_EVIDENCE,
                    target_ref=None,
                    relationship=FrameworkRelationshipState.UNMAPPED,
                ),
            ),
        }
    )
    changed_catalog = catalog.model_copy(update={"controls": (changed, *catalog.controls[1:])})

    result = FrameworkAssessmentRuntime(changed_catalog).assess(_request(catalog))

    control = _result_control(result, first.control_id)
    assert control.mapping_state == "unmapped"
    assert control.evaluation is FrameworkEvaluationStatus.BLOCKED
    assert "blocked_dependency:external-owner" in control.limitations


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: FrameworkApplicabilityDecision(
                control_id="control",
                status=FrameworkApplicabilityStatus.APPLICABLE,
                requested_by="requester",
                owner_slot="owner",
                cadence_days=0,
            ),
            "cadence_days",
        ),
        (
            lambda: FrameworkApplicabilityDecision(
                control_id="control",
                status=FrameworkApplicabilityStatus.APPLICABLE,
                requested_by="requester",
                owner_slot="owner",
                cadence_days=1,
                justification="unexpected",
            ),
            "cannot carry",
        ),
        (
            lambda: FrameworkApplicabilityDecision(
                control_id="control",
                status=FrameworkApplicabilityStatus.NOT_APPLICABLE,
                requested_by="requester",
                owner_slot="owner",
                cadence_days=1,
            ),
            "complete approval",
        ),
        (
            lambda: FrameworkApplicabilityDecision(
                control_id="control",
                status=FrameworkApplicabilityStatus.NOT_APPLICABLE,
                requested_by="same",
                owner_slot="owner",
                cadence_days=1,
                justification="reason",
                approved_by="same",
                approved_at=NOW,
                expires_at=NOW + timedelta(days=1),
            ),
            "distinct",
        ),
        (
            lambda: FrameworkTradeoffRecord(
                tradeoff_id="tradeoff",
                scope_digest=SCOPE_DIGEST,
                affected_control_ids=(),
                decision_owner="owner",
                rationale_digest=canonical_digest({"reason": "test"}),
                approved_at=NOW,
                expires_at=NOW + timedelta(days=1),
            ),
            "requires affected",
        ),
    ],
)
def test_value_contracts_reject_invalid_shapes(factory: Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        factory()


def test_profile_evidence_request_and_tradeoff_validation_boundaries() -> None:
    waf = _catalog("azure-waf")
    profile = _profile(waf)
    with pytest.raises(ValueError, match="environment_classes"):
        replace(profile, environment_classes=("z", "a"))
    with pytest.raises(ValueError, match="only an inventory"):
        replace(profile, hierarchy_generation="hierarchy-1")
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(profile, profile_digest=canonical_digest({"wrong": True}))
    assert "profile_digest" not in profile.to_dict(include_digest=False)

    receipt = _receipt(waf, waf.controls[0].control_id, 0)
    with pytest.raises(ValueError, match="recorded_at"):
        replace(receipt, recorded_at=receipt.observed_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="at least 60"):
        replace(receipt, freshness_ceiling_seconds=59)
    with pytest.raises(ValueError, match="N/A fields require"):
        replace(receipt, not_applicable_justification="unexpected")
    with pytest.raises(ValueError, match="complete approval"):
        replace(receipt, outcome=FrameworkSatisfactionStatus.NOT_APPLICABLE)

    with pytest.raises(ValueError, match="recorded_at"):
        FrameworkAssessmentRequest(
            assessment_id="assessment",
            profile=profile,
            evaluated_at=NOW,
            recorded_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="evidence MUST be unique"):
        _request(waf, (receipt, receipt))

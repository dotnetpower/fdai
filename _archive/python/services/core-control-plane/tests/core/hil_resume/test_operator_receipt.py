from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.core.hil_resume import (
    EscalationPolicy,
    HumanNonResponseSupervisor,
    RequestOutcome,
    ResolveOutcome,
    ResolveResult,
)
from fdai.core.hil_resume.integrity import action_payload_hash
from fdai.core.hil_resume.operator_receipt import (
    OPERATOR_RECEIPT_PREFIX,
    OperatorReceiptRefusal,
    operator_receipt_key,
    operator_receipt_refusal,
)
from fdai.core.hil_resume.report_line import (
    ReportLineHilCoordinator,
    _revision,
    report_line_audit_detail,
)
from fdai.core.human_reporting import (
    ApprovalContactConsentService,
    ReportingGraphEdge,
    ReportingGraphSnapshot,
    ReportLineApprovalRouter,
    ReportLineRoutingPolicy,
)
from fdai.shared.contracts.models import (
    Action,
    ActionInterface,
    ActionStopCondition,
    Autonomy,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CeilingByTier,
    CeilingRole,
    CheckLogic,
    CheckLogicKind,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
    StopConditionKind,
    TierCeiling,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel


def _message(**overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "park-key-1",
        "decision": "approve",
        "approver_oid": "approver-a",
        "justification": "Reviewed the exact action.",
        "decided_at": "2026-09-29T01:00:00+00:00",
        "receipt_ref": "operator-receipt-1",
    }
    message.update(overrides)
    return message


def _receipt(**overrides: Any) -> dict[str, Any]:
    receipt = {**_message(), "already_recorded": False, "delivered": True}
    receipt.update(overrides)
    return receipt


def test_receipt_key_matches_the_operator_record() -> None:
    assert OPERATOR_RECEIPT_PREFIX == "operator-hil-decision:"
    assert operator_receipt_key("approval-1") == "operator-hil-decision:approval-1"


def test_matching_receipt_admits_the_published_decision() -> None:
    assert operator_receipt_refusal(_receipt(), _message()) is None


def test_decided_at_compares_instants_not_renderings() -> None:
    assert (
        operator_receipt_refusal(_receipt(), _message(decided_at="2026-09-29T10:00:00+09:00"))
        is None
    )
    assert operator_receipt_refusal(_receipt(), _message(decided_at="2026-09-29T01:00:00Z")) is None


@pytest.mark.parametrize(
    ("recorded", "published"),
    [
        ("2026-09-29T01:00:00+00:00", "2026-09-29T01:00:01+00:00"),
        ("2026-09-29T01:00:00+00:00", None),
        (None, "2026-09-29T01:00:00+00:00"),
        (None, None),
        ("2026-09-29T01:00:00+00:00", "not-a-timestamp"),
        ("2026-09-29T01:00:00", "2026-09-29T01:00:00"),
        ("2026-09-29T01:00:00+00:00", 1_790_000_000),
    ],
)
def test_decided_at_must_name_the_same_aware_instant(recorded: object, published: object) -> None:
    receipt = _receipt(decided_at=recorded)
    message = _message(decided_at=published)
    if recorded is None:
        del receipt["decided_at"]
    if published is None:
        del message["decided_at"]

    assert operator_receipt_refusal(receipt, message) is OperatorReceiptRefusal.DECIDED_AT_MISMATCH


def test_approver_comparison_ignores_case_and_surrounding_space() -> None:
    assert operator_receipt_refusal(_receipt(), _message(approver_oid=" Approver-A ")) is None


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        (None, OperatorReceiptRefusal.MISSING),
        ("approve", OperatorReceiptRefusal.MALFORMED),
        (_receipt(approval_id="approval-2"), OperatorReceiptRefusal.APPROVAL_MISMATCH),
        (_receipt(idempotency_key="park-key-2"), OperatorReceiptRefusal.IDENTITY_MISMATCH),
        (_receipt(receipt_ref="operator-receipt-2"), OperatorReceiptRefusal.IDENTITY_MISMATCH),
        (_receipt(decision="reject"), OperatorReceiptRefusal.DECISION_MISMATCH),
        (_receipt(approver_oid="approver-b"), OperatorReceiptRefusal.APPROVER_MISMATCH),
        (_receipt(justification="Other reason."), OperatorReceiptRefusal.JUSTIFICATION_MISMATCH),
    ],
)
def test_divergent_or_missing_receipt_refuses_the_decision(
    receipt: object,
    expected: OperatorReceiptRefusal,
) -> None:
    assert operator_receipt_refusal(receipt, _message()) is expected


@pytest.mark.parametrize("field", ["approval_id", "idempotency_key", "receipt_ref", "decision"])
def test_identity_fields_absent_on_both_sides_never_match(field: str) -> None:
    receipt = _receipt()
    message = _message()
    del receipt[field]
    del message[field]

    assert operator_receipt_refusal(receipt, message) is not None


def test_empty_approver_never_matches() -> None:
    assert (
        operator_receipt_refusal(_receipt(approver_oid=" "), _message(approver_oid=" "))
        is OperatorReceiptRefusal.APPROVER_MISMATCH
    )


def test_missing_justification_matches_only_an_empty_one() -> None:
    receipt = _receipt()
    message = _message()
    del receipt["justification"]
    del message["justification"]

    assert operator_receipt_refusal(receipt, message) is None
    assert operator_receipt_refusal(receipt, _message(justification="")) is None
    assert (
        operator_receipt_refusal(receipt, _message(justification=7))
        is OperatorReceiptRefusal.JUSTIFICATION_MISMATCH
    )


def test_development_attestation_must_match_exactly() -> None:
    attestation = {"approval_id": "approval-1", "block_digest": "sha256:abc"}
    recorded = _receipt(development_attestation=attestation)

    assert (
        operator_receipt_refusal(recorded, _message(development_attestation=dict(attestation)))
        is None
    )
    assert (
        operator_receipt_refusal(recorded, _message())
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(_receipt(), _message(development_attestation=attestation))
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(
            recorded,
            _message(development_attestation={**attestation, "block_digest": "sha256:def"}),
        )
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )
    assert (
        operator_receipt_refusal(
            _receipt(development_attestation="x"),
            _message(development_attestation="x"),
        )
        is OperatorReceiptRefusal.ATTESTATION_MISMATCH
    )


def _sample_action(idem: str = "dispatch-idem") -> Action:
    return Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",  # type: ignore[arg-type]
        idempotency_key=idem,
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/stg1",
        operation=Operation.TAG,
        params={"tag_value": "team-a"},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=["object-storage.owner-tag.required"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _sample_rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="object-storage.owner-tag.required",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/object_storage/owner_tag_required.rego",
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates="remediate.tag-add",
        parameters={"tag_name": "owner", "tag_value": "unknown"},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _sample_action_type(
    *,
    name: str = "remediate.tag-add",
    execution_path: ExecutionPath | None = None,
    semantic_refs: list[str] | None = None,
    owner_hil: bool = False,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        execution_path=execution_path,
        required_evidence_semantic_refs=semantic_refs or [],
        ceiling_by_tier=(
            CeilingByTier(
                t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.OWNER),
            )
            if owner_hil
            else None
        ),
    )


class _ToggleReportLineGraphs:
    def __init__(self) -> None:
        self.available = True
        self.edge_digest = "b" * 64

    async def current_graph(self, *, at: datetime | None = None) -> ReportingGraphSnapshot:
        observed_at = at or datetime(2026, 7, 1, tzinfo=UTC)
        edges = (
            (
                ReportingGraphEdge(
                    case_id="case-1",
                    edge_digest=self.edge_digest,
                    subject_ref="requester-a",
                    manager_ref="manager-a",
                    effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                    effective_until=datetime(2100, 1, 1, tzinfo=UTC),
                ),
            )
            if self.available
            else ()
        )
        return ReportingGraphSnapshot(
            revision="a" * 64,
            observed_at=observed_at,
            edges=edges,
        )


class _AnyRoleEligible:
    async def is_eligible(self, **_kwargs: Any) -> bool:
        return True


def _build_report_line_coordinator(
    *,
    store: InMemoryStateStore | None = None,
    graphs: _ToggleReportLineGraphs | None = None,
    select_action: bool = True,
    owner_hil: bool = False,
    mark_resolved_return: bool = True,
) -> tuple[ReportLineHilCoordinator, InMemoryStateStore, _ToggleReportLineGraphs]:
    state_store = store or InMemoryStateStore()
    graph_source = graphs or _ToggleReportLineGraphs()
    router = ReportLineApprovalRouter(
        graphs=graph_source,
        eligibility=_AnyRoleEligible(),
        policy=ReportLineRoutingPolicy(
            action_types=frozenset({"remediate.tag-add"} if select_action else set()),
            quorum_by_action={},
        ),
    )
    consent = ApprovalContactConsentService(state_store)
    channel = InMemoryHilChannel()
    escalation = HumanNonResponseSupervisor(
        state_store=state_store,
        channel=channel,
        policy=EscalationPolicy(decision_timeout_seconds=60),
    )
    action_type = _sample_action_type(owner_hil=owner_hil)
    coordinator = ReportLineHilCoordinator(
        store=state_store,
        router=router,
        consent=consent,
        escalation=escalation,
        channel=channel,
        load_controller=None,
        action_types={action_type.name: action_type},
        rules={"object-storage.owner-tag.required": _sample_rule()},
        audit=AsyncMock(return_value=None),
        mark_resolved=AsyncMock(return_value=mark_resolved_return),
        race_result=AsyncMock(
            return_value=ResolveResult(
                outcome=ResolveOutcome.ALREADY_RESOLVED,
                approval_id="aid-race",
            )
        ),
        logger=logging.getLogger("test.report_line"),
    )
    return coordinator, state_store, graph_source


async def test_report_line_helpers_and_guard_branches() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    assert ReportLineHilCoordinator.contact_consent_expired({}, at=now) is True
    assert (
        ReportLineHilCoordinator.contact_consent_expired(
            {"contact_consent_expires_at": "invalid-iso"},
            at=now,
        )
        is True
    )
    assert (
        ReportLineHilCoordinator.contact_consent_expired(
            {"contact_consent_expires_at": "2026-07-05T13:00:00"},
            at=now,
        )
        is True
    )
    assert (
        ReportLineHilCoordinator.contact_consent_expired(
            {"contact_consent_expires_at": "2026-07-05T13:00:00Z"},
            at=now,
        )
        is False
    )

    with pytest.raises(ValueError, match="report-line approval revision MUST be non-negative"):
        _revision({"revision": -1})

    assert report_line_audit_detail({}) == {}
    assert report_line_audit_detail(
        {"report_line_route": {"route_digest": "d1", "path_revision": "", "graph_revision": None}}
    ) == {"report_line_route_digest": "d1"}

    unselected_coord, _, _ = _build_report_line_coordinator(select_action=False)
    action = _sample_action()
    assert await unselected_coord.plan(action=action, submitter_oid="requester-a", at=now) is None
    assert await unselected_coord.prepare_request(
        action=action, submitter_oid="requester-a", at=now
    ) == (None, None)

    coord, _, graphs = _build_report_line_coordinator(
        owner_hil=True,
        mark_resolved_return=False,
    )
    assert (
        await coord.route_is_current(
            parked={},
            action=action,
            approver_oid="manager-a",
            at=now,
        )
        is True
    )
    assert (
        await coord.guard_approval(
            parked={},
            action=action,
            approval_id="aid-no-route",
            approver_oid="manager-a",
        )
        is None
    )

    graphs.available = False
    assert (
        await coord.route_is_current(
            parked={"report_line_route": {"route_digest": "d1"}, "submitter_oid": "requester-a"},
            action=action,
            approver_oid="manager-a",
            at=now,
        )
        is False
    )
    race = await coord.guard_approval(
        parked={"report_line_route": {"route_digest": "d1"}, "submitter_oid": "requester-a"},
        action=action,
        approval_id="aid-race",
        approver_oid="manager-a",
    )
    assert race is not None and race.outcome is ResolveOutcome.ALREADY_RESOLVED


async def test_report_line_decide_contact_validation_and_race_branches() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    coord, store, graphs = _build_report_line_coordinator(mark_resolved_return=False)

    missing = await coord.decide_contact(
        approval_id="aid-missing",
        requester_oid="requester-a",
        consent=True,
        expected_consent_revision=0,
        at=now,
    )
    assert missing.outcome is RequestOutcome.REPORT_LINE_ROUTE_UNAVAILABLE

    await store.write_state("hil_park:aid-pending", {"status": "pending"})
    pending = await coord.decide_contact(
        approval_id="aid-pending",
        requester_oid="requester-a",
        consent=True,
        expected_consent_revision=0,
        at=now,
    )
    assert pending.outcome is RequestOutcome.ALREADY_PARKED

    await store.write_state("hil_park:aid-resolved", {"status": "resolved"})
    resolved = await coord.decide_contact(
        approval_id="aid-resolved",
        requester_oid="requester-a",
        consent=True,
        expected_consent_revision=0,
        at=now,
    )
    assert resolved.outcome is RequestOutcome.CONTACT_DECLINED

    await store.write_state(
        "hil_park:aid-no-evidence",
        {"status": "awaiting_contact_consent"},
    )
    with pytest.raises(ValueError, match="missing consent or route evidence"):
        await coord.decide_contact(
            approval_id="aid-no-evidence",
            requester_oid="requester-a",
            consent=True,
            expected_consent_revision=0,
            at=now,
        )

    async def _park_with_consent(aid: str, patch: dict[str, Any] | None = None) -> Any:
        act = _sample_action(idem=f"idem-{aid}")
        rt, cs = await coord.prepare_request(
            action=act,
            submitter_oid="requester-a",
            at=now,
        )
        assert rt is not None and cs is not None
        payload: dict[str, Any] = {
            "approval_id": aid,
            "status": "awaiting_contact_consent",
            "submitter_oid": "requester-a",
            "contact_consent_id": cs.consent_id,
            "report_line_route": {
                "route_digest": rt.digest,
                "path_revision": rt.path_revision,
                "graph_revision": rt.graph_revision,
            },
            "action": act.model_dump(mode="json"),
            "action_hash": action_payload_hash(act.model_dump(mode="json")),
            "rule_id": "object-storage.owner-tag.required",
            "approval_context": {
                "reasons": [],
                "blast_radius_summary": "",
                "ttl_seconds": 1800,
                "expires_at": "2026-07-05T13:00:00+00:00",
            },
            "revision": 0,
            **(patch or {}),
        }
        await store.write_state(f"hil_park:{aid}", payload)
        return cs

    await _park_with_consent("aid-decline-race")
    declined_race = await coord.decide_contact(
        approval_id="aid-decline-race",
        requester_oid="requester-a",
        consent=False,
        expected_consent_revision=0,
        at=now,
    )
    assert declined_race.outcome is RequestOutcome.ALREADY_PARKED

    consent_exp = await _park_with_consent("aid-exp-race")
    exp_race = await coord.decide_contact(
        approval_id="aid-exp-race",
        requester_oid="requester-a",
        consent=True,
        expected_consent_revision=0,
        at=consent_exp.expires_at,
    )
    assert exp_race.outcome is RequestOutcome.ALREADY_PARKED

    for aid, patch, match in (
        ("aid-bad-action", {"action_hash": "tampered"}, "action integrity is invalid"),
        ("aid-bad-rule", {"rule_id": "missing.rule"}, "approval rule is unavailable"),
    ):
        await _park_with_consent(aid, patch)
        with pytest.raises(ValueError, match=match):
            await coord.decide_contact(
                approval_id=aid,
                requester_oid="requester-a",
                consent=True,
                expected_consent_revision=0,
                at=now,
            )

    await _park_with_consent("aid-route-gone")
    graphs.available = False
    route_gone = await coord.decide_contact(
        approval_id="aid-route-gone",
        requester_oid="requester-a",
        consent=True,
        expected_consent_revision=0,
        at=now,
    )
    assert route_gone.outcome is RequestOutcome.REPORT_LINE_ROUTE_UNAVAILABLE
    graphs.available = True

    base_cas = store.compare_and_set_state_with_audit
    for aid, concurrent_state, expected_outcome in (
        ("aid-cas-pending", {"status": "pending"}, RequestOutcome.ALREADY_PARKED),
        ("aid-cas-changed", {"status": "resolved", "decision": "reject"}, None),
    ):
        await _park_with_consent(aid)

        async def _cas_fail(
            key: str,
            value: Mapping[str, Any],
            *,
            expected_revision: int,
            audit_entry: Mapping[str, Any],
            _state: dict[str, Any] = concurrent_state,
        ) -> bool:
            if audit_entry.get("action_kind") == "hil.report_line.contact_consented":
                await store.write_state(key, _state)
                return False
            return await base_cas(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

        store.compare_and_set_state_with_audit = _cas_fail  # type: ignore[method-assign]
        if expected_outcome is not None:
            cas_res = await coord.decide_contact(
                approval_id=aid,
                requester_oid="requester-a",
                consent=True,
                expected_consent_revision=0,
                at=now,
            )
            assert cas_res.outcome is expected_outcome
        else:
            with pytest.raises(
                ValueError,
                match="report-line approval park changed during contact consent",
            ):
                await coord.decide_contact(
                    approval_id=aid,
                    requester_oid="requester-a",
                    consent=True,
                    expected_consent_revision=0,
                    at=now,
                )
        store.compare_and_set_state_with_audit = base_cas  # type: ignore[method-assign]

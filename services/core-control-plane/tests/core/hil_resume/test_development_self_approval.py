"""An Owner's development self-approval admits only the exact, freshly confirmed parked action."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.control_loop.development_request import prepare_development_park
from fdai.core.executor.direct_api import DirectApiExecutionOutcome, DirectApiExecutionResult
from fdai.core.hil_resume import HilResumeCoordinator, ResolveOutcome
from fdai.core.hil_resume.development import (
    DEVELOPMENT_ADMISSION_ACTOR,
    OPERATOR_RECEIPT_PREFIX,
    admit_development_self_approval,
    park_block,
)
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.delivery.development_bindings import (
    BINDING_PREFIX,
    PreparedDevelopmentBindingRegistry,
    azure_scope_value_digest,
)
from fdai.shared.contracts.models import (
    Action,
    ExecutionPath,
    FullAuthorityDevelopmentProfile,
    Mode,
    OntologyActionType,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.development_approval import (
    DevelopmentApprovalAttestation,
    development_authentication_evidence_digest,
    fresh_development_authentication,
)

from tests.contracts.test_development_authority import NOW, _profile
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.hil_resume.test_coordinator import _RULE_ID, _coordinator, _rule
from tests.core.risk_gate.test_development_authority import _action as _action_type

SUBSCRIPTION = "00000000-0000-0000-0000-00000000de01"
GROUP = "rg-fdai-dev"
TARGET = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}"
    "/providers/Microsoft.Insights/metricAlerts/cpu-high"
)
REVISION = "sha256:" + "1" * 64
APPROVAL_ID = "dev-approval-1"
IDENTITY_REF = "identity/change"


class _Revisions:
    def __init__(self, revision: str | None = REVISION) -> None:
        self.revision = revision

    async def read_revision(self, target_ref: str) -> str | None:
        assert target_ref == TARGET
        return self.revision


def _action_type_for() -> OntologyActionType:
    return _action_type().model_copy(update={"execution_path": ExecutionPath.DIRECT_API})


def _profile_for(action_type: OntologyActionType, now: datetime) -> FullAuthorityDevelopmentProfile:
    base = _profile(now=now, action_type_digest="sha256:" + action_type_digest(action_type))
    raw = base.model_dump(mode="json")
    raw["scope"] = {
        "tenant_digest": base.scope.tenant_digest,
        "subscription_digest": azure_scope_value_digest(SUBSCRIPTION),
        "resource_group_digests": [azure_scope_value_digest(GROUP)],
    }
    return FullAuthorityDevelopmentProfile.model_validate(raw)


def _parked_action() -> Action:
    return _direct_action(target=TARGET, mode=Mode.ENFORCE, citing_rules=(_RULE_ID,)).model_copy(
        update={"executor_identity_ref": IDENTITY_REF}
    )


def _authorized() -> ExecutionAuthorizationResult:
    return ExecutionAuthorizationResult(
        status=ExecutionAuthorizationStatus.AUTHORIZED,
        decision_digest="sha256:" + "a" * 64,
        evaluator_ref="test",
        reason_codes=("authorized",),
        executor_identity_ref=IDENTITY_REF,
    )


class _Scenario:
    def __init__(self) -> None:
        # The coordinator checks park expiry against wall-clock time, so the scenario starts now.
        self.base = datetime.now(tz=UTC).replace(microsecond=0)
        self.clock = [self.base]
        self.action_type = _action_type_for()
        self.profile = _profile_for(self.action_type, self.base)
        self.store = InMemoryStateStore()
        self.registry = PreparedDevelopmentBindingRegistry(
            profile=self.profile, store=self.store, clock=lambda: self.clock[0]
        )
        self.revisions = _Revisions()
        self.action = _parked_action()

    async def block(self, **overrides: Any) -> dict[str, Any] | None:
        arguments: dict[str, Any] = {
            "profile": self.profile,
            "bindings": self.registry,
            "revisions": self.revisions,
            "initiator": self.profile.owner_principal,
            "action": self.action,
            "action_type": self.action_type,
            "authorization": _authorized(),
            "unified": SimpleNamespace(decision="hil", quorum=2),
        }
        arguments.update(overrides)
        return await prepare_development_park(**arguments)

    async def park(self) -> tuple[HilResumeCoordinator, dict[str, Any]]:
        block = await self.block()
        assert block is not None
        coordinator, _, _, _ = _coordinator(state_store=self.store)
        coordinator._request_clock = lambda: self.clock[0]
        coordinator._action_types_by_name = {self.action_type.name: self.action_type}
        coordinator.bind_development_authority(
            profile=self.profile, bindings=self.registry, revisions=self.revisions
        )
        await coordinator.request_approval(
            action=self.action,
            rule=_rule(),
            submitter_oid=self.profile.owner_principal,
            correlation_id="development-correlation",
            approval_id=APPROVAL_ID,
            development_authority=block,
        )
        parked = await self.store.read_state(f"hil_park:{APPROVAL_ID}")
        assert parked is not None
        return coordinator, parked

    def attestation(
        self,
        block: dict[str, Any],
        *,
        authenticated_at: datetime | None = None,
        principal: str | None = None,
    ) -> dict[str, Any]:
        signed = authenticated_at or self.base + timedelta(seconds=60)
        owner = principal or self.profile.owner_principal
        return DevelopmentApprovalAttestation(
            confirmation_id="confirmation-1",
            approval_id=APPROVAL_ID,
            block_digest=block["block_digest"],
            binding_digest=block["binding_digest"],
            profile_digest=block["profile_digest"],
            authenticated_principal=owner,
            authenticated_at=signed,
            authentication_evidence_digest=development_authentication_evidence_digest(
                principal=owner,
                auth_time=int(signed.timestamp()),
                token_id="token-1",
                approval_id=APPROVAL_ID,
            ),
            confirmed_at=signed + timedelta(seconds=30),
        ).model_dump(mode="json")

    async def receipt(self, attestation: dict[str, Any], **overrides: Any) -> None:
        await self.store.write_state(
            OPERATOR_RECEIPT_PREFIX + APPROVAL_ID,
            {
                "approval_id": APPROVAL_ID,
                "decision": "approve",
                "approver_oid": self.profile.owner_principal,
                "development_attestation": attestation,
                **overrides,
            },
        )

    async def admit(self, parked: dict[str, Any], attestation: Any, **overrides: Any) -> Any:
        arguments: dict[str, Any] = {
            "profile": self.profile,
            "bindings": self.registry,
            "revisions": self.revisions,
            "state_store": self.store,
            "action_types": {self.action_type.name: self.action_type},
            "parked": parked,
            "approver_oid": self.profile.owner_principal,
            "attestation": attestation,
            "now": self.clock[0],
        }
        arguments.update(overrides)
        return await admit_development_self_approval(**arguments)


async def test_park_block_binds_the_exact_owner_action_and_original_requirement() -> None:
    scenario = _Scenario()

    block = await scenario.block()

    assert block is not None
    assert park_block({"development_authority": block}) == block
    assert (block["original_level"], block["original_quorum"], block["effective_quorum"]) == (
        "hil",
        2,
        1,
    )
    assert block["target_revision"] == REVISION
    assert block["executor_identity_ref"] == IDENTITY_REF
    verification = await scenario.registry.read_verification(str(scenario.action.action_id))
    assert verification is not None
    assert block["dry_run_digest"] == verification.binding.dry_run_digest
    assert block["scope_digest"].startswith("sha256:")
    assert await scenario.store.read_state(BINDING_PREFIX + str(scenario.action.action_id))
    assert park_block({"development_authority": {**block, "original_quorum": 1}}) is None
    assert park_block({}) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile": None},
        {"bindings": object()},
        {"revisions": None},
        {"action_type": None},
        {"initiator": "human:someone-else"},
        {"initiator": None},
        {"authorization": None},
    ],
)
async def test_missing_development_evidence_parks_for_ordinary_approval(
    overrides: dict[str, Any],
) -> None:
    assert await _Scenario().block(**overrides) is None


async def test_unreadable_revision_or_unbindable_action_parks_for_ordinary_approval() -> None:
    unreadable = _Scenario()
    unreadable.revisions.revision = None
    unbound = _Scenario()
    unbound.action = unbound.action.model_copy(update={"executor_identity_ref": None})
    outside = _Scenario()
    outside.action = _direct_action(
        target=TARGET.replace(GROUP, "rg-elsewhere"), mode=Mode.ENFORCE
    ).model_copy(update={"executor_identity_ref": IDENTITY_REF})

    assert await unreadable.block() is None
    assert await unbound.block() is None
    assert await outside.block() is None


async def test_fresh_owner_confirmation_resumes_the_exact_parked_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _Scenario()
    coordinator, parked = await scenario.park()
    attestation = scenario.attestation(parked["development_authority"])
    await scenario.receipt(attestation)
    scenario.clock[0] = scenario.base + timedelta(minutes=2)
    dispatched: list[Action] = []

    async def dispatch(_self: HilResumeCoordinator, **kwargs: Any) -> DirectApiExecutionResult:
        dispatched.append(kwargs["action"])
        return DirectApiExecutionResult(
            action_id=str(kwargs["action"].action_id),
            outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
            mode=Mode.ENFORCE,
            safeguard_bundle_digest="sha256:" + "b" * 64,
            audit_context={"effect_possible": True, "reconciliation_required": True},
        )

    monkeypatch.setattr(HilResumeCoordinator, "_dispatch", dispatch)

    result = await coordinator.resolve(
        approval_id=APPROVAL_ID,
        decision=HilDecision.APPROVE,
        approver_oid=scenario.profile.owner_principal,
        development_attestation=attestation,
    )

    assert result.outcome is ResolveOutcome.EXECUTION_PENDING
    assert dispatched == [scenario.action]
    admitted = [
        item["entry"]
        for item in scenario.store.audit_entries
        if item["entry"].get("action_kind") == "hil.resolve.development_self_approval"
    ]
    assert admitted[-1]["original_quorum"] == 2
    assert admitted[-1]["effective_quorum"] == 1
    assert admitted[-1]["original_level"] == "hil"


async def test_self_approval_without_admitted_attestation_stays_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _Scenario()
    coordinator, parked = await scenario.park()
    stale = scenario.attestation(
        parked["development_authority"], authenticated_at=scenario.base - timedelta(seconds=1)
    )
    await scenario.receipt(stale)
    scenario.clock[0] = scenario.base + timedelta(minutes=2)

    async def dispatch(_self: HilResumeCoordinator, **_kwargs: Any) -> None:
        raise AssertionError("a refused self-approval MUST NOT dispatch")

    monkeypatch.setattr(HilResumeCoordinator, "_dispatch", dispatch)

    without = await coordinator.resolve(
        approval_id=APPROVAL_ID,
        decision=HilDecision.APPROVE,
        approver_oid=scenario.profile.owner_principal,
    )
    refused = await coordinator.resolve(
        approval_id=APPROVAL_ID,
        decision=HilDecision.APPROVE,
        approver_oid=scenario.profile.owner_principal,
        development_attestation=stale,
    )

    assert without.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert refused.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert refused.reason == "authentication_not_fresh"
    denials = [
        item["entry"]
        for item in scenario.store.audit_entries
        if item["entry"].get("action_kind") == "hil.resolve.development_self_approval_refused"
    ]
    assert denials[-1]["reason_code"] == "authentication_not_fresh"
    # The Operator receipt blocks every other decision, so a refusal closes the park.
    closed = await scenario.store.read_state(f"hil_park:{APPROVAL_ID}")
    assert closed is not None
    assert (closed["status"], closed["decision"], closed["approver_oid"]) == (
        "resolved",
        "reject",
        DEVELOPMENT_ADMISSION_ACTOR,
    )
    retried = await coordinator.resolve(
        approval_id=APPROVAL_ID,
        decision=HilDecision.APPROVE,
        approver_oid=scenario.profile.owner_principal,
        development_attestation=stale,
    )
    assert retried.outcome is not ResolveOutcome.EXECUTED


async def test_admission_accepts_only_exact_durable_evidence() -> None:
    scenario = _Scenario()
    _, parked = await scenario.park()
    block = parked["development_authority"]
    attestation = scenario.attestation(block)
    await scenario.receipt(attestation)
    scenario.clock[0] = scenario.base + timedelta(minutes=2)

    assert (await scenario.admit(parked, attestation)).eligible is True
    assert (await scenario.admit(parked, None)).reason_code == "attestation_invalid"
    assert (await scenario.admit(parked, attestation, profile=None)).reason_code == (
        "development_authority_unwired"
    )
    tampered = {**parked, "development_authority": {**block, "original_quorum": 1}}
    assert (await scenario.admit(tampered, attestation)).reason_code == "park_block_invalid"
    other_digest = {**attestation, "binding_digest": "sha256:" + "f" * 64}
    assert (await scenario.admit(parked, other_digest)).reason_code == (
        "attestation_digest_mismatch"
    )
    assert (
        await scenario.admit(parked, attestation, approver_oid="human:someone-else")
    ).reason_code == "owner_identity_mismatch"
    late = scenario.base + timedelta(minutes=20)
    assert (await scenario.admit(parked, attestation, now=late)).reason_code == (
        "authentication_not_fresh"
    )


async def test_admission_requires_the_matching_operator_receipt_binding_and_revision() -> None:
    scenario = _Scenario()
    _, parked = await scenario.park()
    attestation = scenario.attestation(parked["development_authority"])
    scenario.clock[0] = scenario.base + timedelta(minutes=2)

    assert (await scenario.admit(parked, attestation)).reason_code == "operator_receipt_mismatch"
    await scenario.receipt(attestation, decision="reject")
    assert (await scenario.admit(parked, attestation)).reason_code == "operator_receipt_mismatch"
    await scenario.receipt(attestation)
    changed = scenario.action.model_copy(update={"params": {"cooldown_seconds": 60}})
    moved = {**parked, "action": changed.model_dump(mode="json")}
    assert (await scenario.admit(moved, attestation)).reason_code == "binding_mismatch"
    relabelled = scenario.action.model_copy(update={"executor_identity_ref": "identity/other"})
    other = {**parked, "action": relabelled.model_dump(mode="json")}
    assert (await scenario.admit(other, attestation)).reason_code == "parked_action_mismatch"
    scenario.revisions.revision = "sha256:" + "2" * 64
    assert (await scenario.admit(parked, attestation)).reason_code == "target_revision_drift"
    scenario.revisions.revision = REVISION
    redefined = scenario.action_type.model_copy(update={"version": "1.0.1"})
    pr_path = scenario.action_type.model_copy(update={"execution_path": ExecutionPath.PR_NATIVE})
    for action_types in ({}, {redefined.name: redefined}, {pr_path.name: pr_path}):
        assert (
            await scenario.admit(parked, attestation, action_types=action_types)
        ).reason_code == "current_action_type_mismatch"
    await scenario.store.write_state(BINDING_PREFIX + str(scenario.action.action_id), {})
    assert (await scenario.admit(parked, attestation)).reason_code == "binding_unavailable"


def test_fresh_authentication_requires_a_later_second_inside_the_window() -> None:
    parked_at = NOW

    assert fresh_development_authentication(
        auth_time=NOW + timedelta(seconds=1), parked_at=parked_at, now=NOW + timedelta(minutes=1)
    )
    assert not fresh_development_authentication(
        auth_time=NOW + timedelta(milliseconds=500),
        parked_at=parked_at,
        now=NOW + timedelta(minutes=1),
    )
    assert not fresh_development_authentication(
        auth_time=NOW + timedelta(seconds=5), parked_at=parked_at, now=NOW + timedelta(minutes=11)
    )
    assert not fresh_development_authentication(
        auth_time=NOW + timedelta(minutes=5), parked_at=parked_at, now=NOW + timedelta(minutes=1)
    )

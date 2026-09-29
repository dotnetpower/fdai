"""Shared ControlLoop and HIL coordinator harness for development category-park tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fdai.core.control_loop import ControlLoop
from fdai.core.event_ingest import EventIngest
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.direct_api import DirectApiExecutionOutcome, DirectApiExecutionResult
from fdai.core.hil_resume import HilResumeCoordinator, ResolveResult
from fdai.core.hil_resume.development import OPERATOR_RECEIPT_PREFIX
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
    EvidenceConflictStatus,
    EvidenceSourceLineage,
)
from fdai.core.risk_gate.gate import ActionPromotionRegistry, PromotionMetrics, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.development_bindings import BINDING_PREFIX, PreparedDevelopmentBindingRegistry
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadiusScope,
    ExecutionPath,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
    StopConditionKind,
    TriggerKind,
    TriggerKindDecl,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.state_evidence import StateFactAuthority
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.resilience import InMemoryKillSwitch
from fdai_service_contracts.development_approval import (
    DevelopmentApprovalAttestation,
    development_authentication_evidence_digest,
)

from tests.core.hil_resume.test_development_self_approval import (
    IDENTITY_REF,
    REVISION,
    TARGET,
    _profile_for,
)
from tests.core.risk_gate.test_authority import TABLE_PATH
from tests.core.risk_gate.test_development_authority import _action as _risk_action_type

OTHER_APPROVER = "human:approver"
DRIFTED = "sha256:" + "9" * 64


def _category_action_type() -> OntologyActionType:
    return _risk_action_type(scope=BlastRadiusScope.SUBSCRIPTION).model_copy(
        update={
            "execution_path": ExecutionPath.DIRECT_API,
            "trigger_kind": TriggerKindDecl(kind=TriggerKind.OPERATOR_REQUEST),
            "argument_schema": {
                "type": "object",
                "properties": {"cooldown_seconds": {"type": "integer", "minimum": 1}},
                "required": ["cooldown_seconds"],
                "additionalProperties": False,
            },
            "stop_conditions": [
                ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
            ],
            "required_evidence_semantic_refs": ["resource.state"],
        }
    )


class _Revisions:
    def __init__(self) -> None:
        self.default: str | None = REVISION
        self.queued: list[str | None] = []

    async def read_revision(self, target_ref: str) -> str | None:
        return self.queued.pop(0) if self.queued else self.default


class _Authorization:
    def __init__(self) -> None:
        self.status = ExecutionAuthorizationStatus.AUTHORIZED
        self.identity = IDENTITY_REF
        self.requests: list[ExecutionAuthorizationRequest] = []

    async def evaluate(self, request: ExecutionAuthorizationRequest) -> Any:
        self.requests.append(request)
        return ExecutionAuthorizationResult(
            status=self.status,
            decision_digest="sha256:" + "a" * 64,
            evaluator_ref="test",
            reason_codes=(self.status.value,),
            executor_identity_ref=self.identity,
        )


class _Degradation:
    def __init__(self) -> None:
        self.permitted = True

    def autonomy_permitted(self) -> bool:
        return self.permitted


def _active_conflict(target_ref: str) -> EvidenceConflictRevision:
    now = datetime.now(tz=UTC)

    def lineage(source: str, authority: StateFactAuthority) -> EvidenceSourceLineage:
        return EvidenceSourceLineage(
            source_identity=source,
            source_revision="revision-1",
            claim_digest="sha256:" + ("a" if source == "inventory" else "b") * 64,
            authority=authority,
            evidence_cutoff=now - timedelta(seconds=30),
            recorded_at=now,
            freshness_ceiling_seconds=3600,
            evidence_refs=(f"evidence:{source}",),
        )

    return EvidenceConflictRevision.create(
        status=EvidenceConflictStatus.ACTIVE,
        target_ref=target_ref,
        scope_ref="scope:development",
        generation_ref="inventory-generation:one",
        semantic_refs=("resource.state",),
        conflicting_fields=("state",),
        source_a=lineage("inventory", StateFactAuthority.PROVIDER),
        source_b=lineage("telemetry", StateFactAuthority.TELEMETRY),
        supersedes_revision_ref=None,
    )


class _Conflicts:
    def __init__(self) -> None:
        self.unreadable = False
        self.active = False

    async def active_for(
        self, *, target_ref: str, semantic_refs: frozenset[str]
    ) -> tuple[EvidenceConflictRevision, ...]:
        if self.unreadable:
            raise RuntimeError("evidence conflict state is unavailable")
        return (_active_conflict(target_ref),) if self.active else ()

    async def current(self, slot_ref: str) -> None:
        return None


class _Hold:
    def __init__(self) -> None:
        self.held = False

    async def is_held(self, *, target_ref: str) -> bool:
        return self.held


class _Inventory:
    def __init__(self) -> None:
        self.unreadable = False

    async def __call__(self, resource_ref: str) -> Mapping[str, Any] | None:
        if self.unreadable:
            raise RuntimeError("inventory is unavailable")
        return {
            "resource_id": resource_ref,
            "resource_type": "microsoft.insights/metricalerts",
            "props": {"tags": {"fdai:env": "dev"}},
        }


class CategoryScenario:
    """One ControlLoop and HIL coordinator bound to a development profile, with settable gates.

    Every fake starts in the passing state, so a test flips exactly the gate it exercises.
    """

    def __init__(
        self,
        *,
        profile_shift: timedelta = timedelta(0),
        with_profile: bool = True,
        resource_group_bound: bool = False,
    ) -> None:
        self.base = datetime.now(tz=UTC).replace(microsecond=0)
        self.clock = [self.base]
        self.action_type = _category_action_type()
        self.profile: FullAuthorityDevelopmentProfile = _profile_for(
            self.action_type, self.base + profile_shift
        )
        if not resource_group_bound:
            # The action's blast radius is the whole subscription, so only a profile that binds
            # the whole dedicated subscription, not just its resource groups, covers it.
            self.profile = FullAuthorityDevelopmentProfile.model_validate(
                {
                    **self.profile.model_dump(mode="json"),
                    "scope": {
                        **self.profile.scope.model_dump(mode="json"),
                        "resource_group_digests": [],
                    },
                }
            )
        self.owner = self.profile.owner_principal
        self.store = InMemoryStateStore()
        self.registry = PreparedDevelopmentBindingRegistry(
            profile=self.profile, store=self.store, clock=self.now
        )
        self.revisions = _Revisions()
        self.authorization = _Authorization()
        self.kill_switch = InMemoryKillSwitch()
        self.degradation = _Degradation()
        self.conflicts = _Conflicts()
        self.hold = _Hold()
        self.inventory = _Inventory()
        self.channel = InMemoryHilChannel()
        self.promotion = ActionPromotionRegistry(allow_legacy_metrics=True)
        self.promotion.consider_promotion(
            action_type=self.action_type,
            metrics=PromotionMetrics(
                action_type=self.action_type.name,
                shadow_days=14,
                samples=30,
                accuracy=1.0,
                policy_escapes=0,
            ),
        )
        types = {self.action_type.name: self.action_type}
        clock = self.now
        self.coordinator = HilResumeCoordinator(
            state_store=self.store,
            executor=MagicMock(),
            hil_channel=self.channel,
            rules_by_id={},
            action_types_by_name=types,
        )
        self.coordinator._request_clock = self.now
        self.loop = ControlLoop(
            event_ingest=EventIngest(
                validator=JsonSchemaEventValidator(
                    JsonSchemaContractValidator(PackageResourceSchemaRegistry())
                )
            ),
            trust_router=MagicMock(),
            t0_engine=MagicMock(),
            action_builder=ActionBuilder(action_types_by_name=types, clock=clock),
            executor=MagicMock(),
            audit_store=self.store,
            rules_by_id={},
            risk_table=load_risk_table(TABLE_PATH),
            action_types_by_name=types,
            risk_gate=RiskGate(registry=self.promotion),
            hil_resume_coordinator=self.coordinator,
            inventory_context_provider=self.inventory,
            execution_authorization_evaluator=self.authorization,
            kill_switch=self.kill_switch,
            degradation=self.degradation,  # type: ignore[arg-type]
            evidence_conflict_reader=self.conflicts,
            automation_hold_reader=self.hold,
            clock=clock,
            development_profile=self.profile if with_profile else None,
            development_binding_source=self.registry,
            development_executor_principal=self.profile.executor_principal,
            development_revision_reader=self.revisions,
        )
        self.dispatched: list[Action] = []

    def now(self) -> datetime:
        return self.clock[0]

    async def request(self, *, initiator: str | None = None, target: str = TARGET) -> Any:
        principal = initiator or self.owner
        return await self.loop.process(
            {
                "idempotency_key": f"{principal}::category-1",
                "correlation_id": "category-correlation",
                "initiator_principal": principal,
                "operator_initiated": True,
                "action_type": self.action_type.name,
                "resource_id": target,
                "event_type": "operator_request",
                "params": {"cooldown_seconds": 30},
            }
        )

    async def parked(self) -> dict[str, Any]:
        assert len(self.channel.sent) == 1
        approval_id = self.channel.sent[0].approval_id
        parked = await self.store.read_state(f"hil_park:{approval_id}")
        assert parked is not None
        return dict(parked)

    async def attest(self, parked: Mapping[str, Any], *, signed: datetime) -> dict[str, Any]:
        block = parked["development_authority"]
        approval_id = str(parked["approval_id"])
        attestation = DevelopmentApprovalAttestation(
            confirmation_id="confirmation-1",
            approval_id=approval_id,
            block_digest=block["block_digest"],
            binding_digest=block["binding_digest"],
            profile_digest=block["profile_digest"],
            authenticated_principal=self.owner,
            authenticated_at=signed,
            authentication_evidence_digest=development_authentication_evidence_digest(
                principal=self.owner,
                auth_time=int(signed.timestamp()),
                token_id="token-1",
                approval_id=approval_id,
            ),
            confirmed_at=signed + timedelta(seconds=30),
        ).model_dump(mode="json")
        await self.store.write_state(
            OPERATOR_RECEIPT_PREFIX + approval_id,
            {
                "approval_id": approval_id,
                "decision": "approve",
                "approver_oid": self.owner,
                "development_attestation": attestation,
            },
        )
        return attestation

    async def owner_approves(self, monkeypatch: pytest.MonkeyPatch) -> ResolveResult:
        parked = await self.parked()
        attestation = await self.attest(parked, signed=self.base + timedelta(seconds=60))
        self.clock[0] = self.base + timedelta(minutes=2)
        self.record_dispatch(monkeypatch)
        return await self.coordinator.resolve(
            approval_id=str(parked["approval_id"]),
            decision=HilDecision.APPROVE,
            approver_oid=self.owner,
            development_attestation=attestation,
        )

    def record_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched = self.dispatched

        async def dispatch(_self: HilResumeCoordinator, **kwargs: Any) -> Any:
            action: Action = kwargs["action"]
            dispatched.append(action)
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
                mode=action.mode,
                safeguard_bundle_digest="sha256:" + "b" * 64,
                audit_context={"effect_possible": True, "reconciliation_required": True},
            )

        monkeypatch.setattr(HilResumeCoordinator, "_dispatch", dispatch)

    def audits(self, action_kind: str) -> list[Mapping[str, Any]]:
        return [
            item["entry"]
            for item in self.store.audit_entries
            if item["entry"].get("action_kind") == action_kind
        ]

    async def bindings(self) -> int:
        rows, _ = await self.store.read_state_page(BINDING_PREFIX, limit=10)
        return len(rows)

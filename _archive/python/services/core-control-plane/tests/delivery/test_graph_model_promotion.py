from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade
from fdai.core.assurance_twin.model_promotion import (
    GraphModelActivePointer,
    GraphModelEvidenceCohort,
    GraphModelPromotionReceipt,
    GraphModelRisk,
)
from fdai.core.risk_gate import (
    ActionPromotionRegistry,
    RiskDecisionOutcome,
    RiskGate,
    RiskGateConfig,
)
from fdai.delivery.graph_model_promotion import (
    PROMOTE_EFFECT_MODEL_ACTION_TYPE,
    GraphModelPromotionDirectApiExecutor,
)
from fdai.delivery.persistence.state_store_graph_model_promotion import GraphModelPointerUpdate
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    Rule,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiRequest,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SLOT = "a" * 64


def _receipt() -> GraphModelPromotionReceipt:
    return GraphModelPromotionReceipt(
        model_id="graph-latency",
        model_version="1.0.0",
        model_revision=2,
        model_digest="b" * 64,
        slot_digest=_SLOT,
        ontology_release_digest="c" * 64,
        property_semantics_digest="d" * 64,
        causal_receipt_digest="e" * 64,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        cohort=GraphModelEvidenceCohort.LIVE_SHADOW,
        risk=GraphModelRisk.STANDARD,
        sample_count=50,
        confidence_interval_lower=0.88,
        confidence_interval_upper=0.98,
        fidelity=0.94,
        recurrence_window_complete=True,
        recurrence_rate=0.0,
        policy_escapes=0,
        invariant_evidence_digests=("f" * 64,),
        expected_pointer_revision=0,
        rollback_model_ref=None,
        rollback_model_digest=None,
        sealed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _pointer(receipt: GraphModelPromotionReceipt, revision: int = 1) -> GraphModelActivePointer:
    return GraphModelActivePointer(
        slot_digest=receipt.slot_digest,
        revision=revision,
        active_model_ref=receipt.model_ref,
        active_model_digest=receipt.model_digest,
        prior_active_model_ref=None,
        prior_active_model_digest=None,
        promotion_receipt_digest=receipt.content_digest,
    )


class _Registry:
    def __init__(self, receipt: GraphModelPromotionReceipt) -> None:
        self.receipt = receipt
        self.promote_calls = 0
        self.rollback_calls = 0

    async def load_receipt(self, receipt_digest: str) -> GraphModelPromotionReceipt | None:
        return self.receipt if receipt_digest == self.receipt.content_digest else None

    async def promote(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate:
        assert actor == "Thor"
        self.promote_calls += 1
        return GraphModelPointerUpdate(True, "promoted", _pointer(receipt))

    async def rollback(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate:
        assert actor == "Thor"
        self.rollback_calls += 1
        return GraphModelPointerUpdate(True, "rolled_back", _pointer(receipt, revision=2))


class _BlockedReceiptRegistry(_Registry):
    async def load_receipt(self, receipt_digest: str) -> GraphModelPromotionReceipt | None:
        del receipt_digest
        await asyncio.Future()
        return None


class _BlockedCasRegistry(_Registry):
    async def promote(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate:
        del receipt, actor
        await asyncio.Future()
        raise AssertionError("unreachable")


def _request(
    receipt: GraphModelPromotionReceipt,
    *,
    mode: Mode,
    transition: str,
) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000050"),
        idempotency_key=f"graph-model-{transition}-1",
        action_type_name=PROMOTE_EFFECT_MODEL_ACTION_TYPE,
        rule_ids=("operator.request.governance.promote-effect-model",),
        resource_ref=f"graph-effect-model-slot:{receipt.slot_digest}",
        arguments={
            "receipt_digest": receipt.content_digest,
            "slot_digest": receipt.slot_digest,
            "transition": transition,
            "justification": "Reviewed model evidence passed every promotion requirement.",
        },
        labels=(mode.value,),
        mode=mode,
    )


async def test_shadow_validates_exact_receipt_but_never_mutates() -> None:
    receipt = _receipt()
    registry = _Registry(receipt)
    executor = GraphModelPromotionDirectApiExecutor(registry=registry)

    async with asyncio.timeout(0.5):
        result = await executor.execute(_request(receipt, mode=Mode.SHADOW, transition="promote"))

    assert result.outcome is DirectApiOutcome.SUCCEEDED
    assert registry.promote_calls == 0
    assert registry.rollback_calls == 0


@pytest.mark.parametrize("transition", ["promote", "rollback"])
async def test_enforce_dispatches_only_the_governed_pointer_transition(transition: str) -> None:
    receipt = _receipt()
    registry = _Registry(receipt)
    action_modes = ActionPromotionRegistry()
    executor = GraphModelPromotionDirectApiExecutor(registry=registry)

    async with asyncio.timeout(0.5):
        result = await executor.execute(_request(receipt, mode=Mode.ENFORCE, transition=transition))

    assert result.outcome is DirectApiOutcome.SUCCEEDED
    assert registry.promote_calls == (transition == "promote")
    assert registry.rollback_calls == (transition == "rollback")
    assert action_modes.mode_of("remediate.tag-add") is Mode.SHADOW
    assert action_modes.record(PROMOTE_EFFECT_MODEL_ACTION_TYPE) is None


async def test_receipt_load_timeout_fails_closed_within_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    monkeypatch.setattr("fdai.delivery.graph_model_promotion._RECEIPT_TIMEOUT_SECONDS", 0.01)
    executor = GraphModelPromotionDirectApiExecutor(
        registry=_BlockedReceiptRegistry(receipt),
    )

    async with asyncio.timeout(0.5):
        with pytest.raises(DirectApiPreconditionError, match="receipt load exceeded"):
            await executor.execute(_request(receipt, mode=Mode.SHADOW, transition="promote"))


async def test_registry_cas_timeout_fails_closed_within_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    monkeypatch.setattr("fdai.delivery.graph_model_promotion._REGISTRY_TIMEOUT_SECONDS", 0.01)
    executor = GraphModelPromotionDirectApiExecutor(registry=_BlockedCasRegistry(receipt))

    async with asyncio.timeout(0.5):
        with pytest.raises(DirectApiPreconditionError, match="registry CAS exceeded"):
            await executor.execute(_request(receipt, mode=Mode.ENFORCE, transition="promote"))


def test_action_type_is_content_verified_and_owner_hil_only() -> None:
    action_types = {
        item.name: item
        for item in load_action_type_catalog(
            _REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
    }
    action_type = action_types[PROMOTE_EFFECT_MODEL_ACTION_TYPE]
    assert action_type.provenance is not None
    assert action_type.provenance.content_hash == ontology_content_hash(action_type)
    assert action_type.default_mode is Mode.SHADOW
    assert action_type.ceiling_by_tier is not None
    assert action_type.ceiling_by_tier.t0 is not None
    assert action_type.ceiling_by_tier.t0.min_role.value == "owner"
    assert action_type.ceiling_by_tier.t0.max_autonomy.value == "enforce_hil"

    action = Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000052",  # type: ignore[arg-type]
        idempotency_key="graph-model-promotion-risk-1",
        event_id="00000000-0000-0000-0000-000000000051",  # type: ignore[arg-type]
        action_type=action_type.name,
        target_resource_ref=f"graph-effect-model-slot:{_SLOT}",
        operation=Operation.UPDATE,
        params={},
        stop_condition="time_box_exceeded_seconds",
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=5),
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="prior-active-ref"),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE,
            count=1,
            rate_per_minute=1,
        ),
        mode=Mode.SHADOW,
        citing_rules=["operator.request.governance.promote-effect-model"],
        created_at="2026-08-12T00:00:00Z",  # type: ignore[arg-type]
    )
    gate = RiskGate(
        registry=ActionPromotionRegistry(),
        config=RiskGateConfig(
            hil_authority_action_types=frozenset({PROMOTE_EFFECT_MODEL_ACTION_TYPE})
        ),
    )
    decision = gate.evaluate(
        action=action,
        rule=cast(Rule, object()),
        action_type=action_type,
        inventory_age_seconds=60,
    )

    assert decision.outcome is RiskDecisionOutcome.HIL
    assert decision.effective_mode is Mode.ENFORCE
    assert decision.reasons == ("authority_mutation_requires_hil",)

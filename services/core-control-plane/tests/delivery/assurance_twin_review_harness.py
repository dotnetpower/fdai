"""Forseti reviews typed ActionType proposals through the retained-evidence outbox."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.core.assurance_twin import (
    CompletePostureEvaluation,
    DeclaredPropertyEffect,
    InMemoryProjection,
    ProposalWhatIfResult,
    ReviewedActionTypeEffect,
    ReviewedEffectCatalog,
    TypedActionProposal,
    WhatIfStatus,
    build_baseline_projection,
    evaluate_complete_posture,
    rule_generation_digest,
)
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.core.tiers.t0_deterministic.models import RegoEvaluationReceipt
from fdai.delivery.assurance_twin_evidence_source import (
    AssuranceTwinEvidenceRequestRelay,
    StateStoreTwinEvidenceRepository,
)
from fdai.delivery.assurance_twin_inventory import (
    AssuranceTwinInventoryChangedError,
    TwinInventoryRevision,
    TwinInventoryUnavailableError,
)
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_proposal_intake import StateStoreTypedProposalReviewIntake
from fdai.delivery.assurance_twin_review_producer import AssuranceTwinReviewProducer
from fdai.delivery.assurance_twin_writers import (
    REQUEST_TOPIC,
    AssuranceTwinAgentWriter,
    AssuranceTwinPublishRequest,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Remediation,
    Rule,
    RuleSource,
    Severity,
    SubmissionCriterion,
    SubmissionCriterionKind,
)
from fdai.shared.providers.projection import ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REVISION_A = "sha256:" + "a" * 64
REVISION_B = "sha256:" + "b" * 64
TARGET = ResourceRef("object-storage", "storage-a")
UNRELATED = ResourceRef("object-storage", "storage-b")
ACTION_TYPE = "ops.set-public-access"


class PublicAccessPolicy:
    """Deterministic OPA stand-in that issues exact per-Rule evaluation receipts."""

    def __init__(
        self,
        *,
        denied_values: frozenset[str] = frozenset({"enabled"}),
        generation: str = "2",
    ) -> None:
        self.denied_values = denied_values
        self.generation_digest = "sha256:" + generation * 64

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        denied = resource_props.get("public_access") in self.denied_values
        return PolicyResult(
            denied=denied,
            context={"deny_reason": "public access is enabled"} if denied else {},
            evaluation_receipt=RegoEvaluationReceipt(
                decision_path=f"fdai.{rule.id}.deny",
                opa_version="1.0.0",
                parser_id="opa-ast",
                parser_version="1.0.0",
                policy_source_digest="sha256:" + "3" * 64,
                normalized_semantic_digest="sha256:" + "4" * 64,
                input_evidence_digest="sha256:" + ("5" if denied else "6") * 64,
                denied=denied,
                result_digest="sha256:" + ("7" if denied else "8") * 64,
            ),
        )


class ControlLoopEvaluator:
    """The ControlLoop Twin seams over a real T0 engine and complete evaluation."""

    def __init__(self, generation_time: datetime) -> None:
        self.rules = (rule(),)
        self.evaluated: list[InMemoryProjection] = []
        self.activate(PublicAccessPolicy(), generation_time=generation_time)

    def activate(
        self,
        policy: PublicAccessPolicy,
        *,
        generation_time: datetime,
        rules: tuple[Rule, ...] | None = None,
    ) -> None:
        """Swap the immutable generation the way ControlLoop replaces its T0 engine."""

        if rules is not None:
            self.rules = rules
        self.engine = T0Engine(index=RuleIndex.build(self.rules), evaluator=policy)
        evaluator_generation = self.engine.evaluator_generation_digest
        assert evaluator_generation is not None
        self.current = rule_generation_digest(
            self.rules, evaluator_generation_digest=evaluator_generation
        )
        self.generation_time = generation_time

    async def evaluate_assurance_twin_posture(
        self,
        *,
        projection: InMemoryProjection,
        inventory_revision: str,
    ) -> CompletePostureEvaluation:
        self.evaluated.append(projection)
        return evaluate_complete_posture(
            engine=self.engine,
            rules=self.rules,
            projection=projection,
            inventory_revision=inventory_revision,
            rule_generation_time=self.generation_time,
        )

    async def run_assurance_twin_if_current(
        self,
        *,
        rule_generation_revision: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        if rule_generation_revision != self.current:
            return None
        return await operation()


class RetainedInventory:
    """Retained Inventory revision with an optional change on a chosen fence read."""

    def __init__(self, completed_at: datetime) -> None:
        self.current = REVISION_A
        self.completed_at = completed_at
        self.change_on_read: int | None = None
        self.reads = 0
        self.target_properties: dict[str, Any] = {"public_access": "enabled"}

    def _revision(self) -> TwinInventoryRevision:
        resources = (
            (TARGET, dict(self.target_properties)),
            (UNRELATED, {"public_access": "enabled"}),
        )
        return TwinInventoryRevision(
            projection=build_baseline_projection(resources),
            snapshot_id="snapshot-1",
            source_revision=self.current,
            completed_at=self.completed_at,
            revision_time=self.completed_at,
            source="azure-resource-graph",
            resource_count=len(resources),
            delta_count=0,
        )

    async def load(self, **_kwargs: Any) -> TwinInventoryRevision:
        return self._revision()

    async def load_at_revision(self, *, expected_revision: str, **_kwargs: Any) -> Any:
        self.reads += 1
        if expected_revision != self.current:
            raise TwinInventoryUnavailableError("Twin Inventory revision changed")
        loaded = self._revision()
        if self.reads == self.change_on_read:
            self.current = REVISION_B
        return loaded

    async def run_at_revision(
        self,
        *,
        expected_revision: str,
        operation: Callable[[], Awaitable[Any]],
        **_kwargs: Any,
    ) -> Any:
        await self.load_at_revision(expected_revision=expected_revision)
        result = await operation()
        try:
            await self.load_at_revision(expected_revision=expected_revision)
        except TwinInventoryUnavailableError as exc:
            raise AssuranceTwinInventoryChangedError("changed", result=result) from exc
        return result


class TwinHarness:
    """One durable store with Forseti's producer, fenced writer, and outbox."""

    def __init__(
        self,
        now: datetime,
        *,
        effects: tuple[ReviewedActionTypeEffect, ...],
        max_derivations: int = 3,
    ) -> None:
        self.now = now
        self.max_derivations = max_derivations
        self.store = InMemoryStateStore()
        self.inventory = RetainedInventory(now - timedelta(minutes=1))
        self.evaluator = ControlLoopEvaluator(now - timedelta(minutes=2))
        self.repository = StateStoreTwinEvidenceRepository(store=self.store)
        self.intake = StateStoreTypedProposalReviewIntake(store=self.store)
        self.ledger = StateStoreAssuranceTwinPostureLedger(store=self.store)
        self.producer = self.restarted_producer(effects)
        self.writer = AssuranceTwinAgentWriter(
            owner="Forseti",
            source=self.repository,
            recorder=AssuranceTwinPostureRecorder(ledger=self.ledger),
            review_generation_fence=self.evaluator,
            review_inventory_fence=self.producer,
        )

    def restarted_producer(
        self, effects: tuple[ReviewedActionTypeEffect, ...]
    ) -> AssuranceTwinReviewProducer:
        return AssuranceTwinReviewProducer(
            inventory=self.inventory,
            evaluator=self.evaluator,
            repository=StateStoreTwinEvidenceRepository(store=self.store),
            intake=StateStoreTypedProposalReviewIntake(store=self.store),
            effects=ReviewedEffectCatalog(effects),
            required_scopes=("scope-a",),
            max_derivations=self.max_derivations,
            clock=lambda: self.now,
        )

    async def relayed_request(self, bus: InMemoryEventBus) -> AssuranceTwinPublishRequest:
        """Relay the one content-free request exactly as the runtime writer receives it."""

        relay = AssuranceTwinEvidenceRequestRelay(repository=self.repository, bus=bus)
        assert await relay.publish_pending() == 1
        envelopes = [item async for item in bus.subscribe(REQUEST_TOPIC, "forseti")]
        assert set(envelopes[-1].payload) == {
            "schema_version",
            "kind",
            "source_key",
            "source_revision",
            "correlation_id",
            "idempotency_key",
        }
        return AssuranceTwinPublishRequest.model_validate(envelopes[-1].payload)

    def intake_audit(self) -> list[tuple[str, Any]]:
        return [
            (str(entry["entry"]["kind"]), entry["entry"].get("reason_code"))
            for entry in self.store.audit_entries
            if str(entry["entry"].get("kind", "")).startswith("assurance_twin_proposal_review_")
        ]

    async def intake_rows(self) -> tuple[Mapping[str, Any], ...]:
        rows, _ = await self.store.read_state_page("runtime:assurance-twin-proposal:", limit=10)
        return rows

    async def evidence_rows(self) -> tuple[Mapping[str, Any], ...]:
        rows, _ = await self.store.read_state_page(
            "runtime:assurance-twin-evidence:",
            limit=10,
            field="kind",
            value="assurance_twin_retained_review",
        )
        return rows


def rule(
    rule_id: str = "rule.object-storage.public-access",
    property_ref: str = "property.object-storage.public_access",
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.template"),
        remediates=ACTION_TYPE,
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
        evaluates=[property_ref],
        submission_criteria=[
            SubmissionCriterion(kind=SubmissionCriterionKind.PROPERTY_EXISTS, value=property_ref)
        ],
    )


def reviewed_effect(**overrides: Any) -> ReviewedActionTypeEffect:
    values: dict[str, Any] = {
        "action_type": ACTION_TYPE,
        "action_type_version": "1.0.0",
        "target_resource_types": ("object-storage",),
        "property_effects": (DeclaredPropertyEffect("public_access", parameter="public_access"),),
        "review_ref": "effect-review:ops.set-public-access@1.0.0",
    }
    values.update(overrides)
    return ReviewedActionTypeEffect(**values)


def proposal(value: str = "disabled", *, targets: tuple[ResourceRef, ...] = (TARGET,)) -> Any:
    return TypedActionProposal.create(
        action_type=ACTION_TYPE,
        action_type_version="1.0.0",
        targets=targets,
        parameters={"public_access": value},
    )


def what_if(item: TypedActionProposal, now: datetime, **overrides: Any) -> ProposalWhatIfResult:
    values: dict[str, Any] = {
        "proposal_digest": item.proposal_digest,
        "status": WhatIfStatus.PASSED,
        "complete": True,
        "synthetic": False,
        "source_authority": "simulation_engine",
        "producer_id": "provider-what-if",
        "observed_at": now - timedelta(seconds=30),
        "expires_at": now + timedelta(minutes=10),
        "affected_targets": item.targets,
        "evidence_refs": ("what-if-receipt:1",),
    }
    values.update(overrides)
    return ProposalWhatIfResult(**values)

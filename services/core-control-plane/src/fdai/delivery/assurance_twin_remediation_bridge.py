"""Reviewed ActionType property-effect catalog, typed what-if producer, and remediation bridge."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from fdai.core.assurance_twin.proposal_effects import (
    DeclaredPropertyEffect,
    ReviewedActionTypeEffect,
    ReviewedEffectCatalog,
    require_completed_what_if,
)
from fdai.core.assurance_twin.query import AbstainCode, AbstainResult
from fdai.core.assurance_twin.semantic_query import (
    AssuranceTwinDiscoverySink,
    AssuranceTwinQueryGap,
    DiscoveryHandoffStatus,
    question_digest,
)
from fdai.core.assurance_twin.typed_proposal import (
    MAX_PROPOSAL_TARGETS,
    WHAT_IF_SOURCE_AUTHORITY,
    ProposalWhatIfResult,
    TypedActionProposal,
    WhatIfStatus,
    canonical_digest,
    canonical_targets,
)
from fdai.shared.providers.projection import ResourceRef

_MAX_TEXT = 512

GOVERNED_REVIEWED_ACTION_EFFECTS: tuple[ReviewedActionTypeEffect, ...] = (
    ReviewedActionTypeEffect(
        "ops.set-public-access",
        "1.0.0",
        ("object-storage",),
        (DeclaredPropertyEffect("public_access", parameter="public_access"),),
        "governance-review:action-effect:ops.set-public-access@1.0.0",
        ("justification",),
    ),
    ReviewedActionTypeEffect(
        "ops.enforce-minimum-tls",
        "1.0.0",
        ("api-gateway", "object-storage"),
        (
            DeclaredPropertyEffect("https_only", constant_json="true"),
            DeclaredPropertyEffect("min_tls_version", parameter="min_tls_version"),
        ),
        "governance-review:action-effect:ops.enforce-minimum-tls@1.0.0",
        ("change_ticket",),
    ),
    ReviewedActionTypeEffect(
        "ops.restrict-network-default-action",
        "1.0.0",
        ("key-vault", "object-storage"),
        (DeclaredPropertyEffect("network_default_action", parameter="network_default_action"),),
        "governance-review:action-effect:ops.restrict-network-default-action@1.0.0",
        ("change_ticket",),
    ),
)


def build_reviewed_action_effect_catalog(
    extra_effects: Iterable[ReviewedActionTypeEffect] = (),
) -> ReviewedEffectCatalog:
    """Build an immutable catalog of governance-reviewed ActionType effect models."""
    combined: list[ReviewedActionTypeEffect] = list(GOVERNED_REVIEWED_ACTION_EFFECTS)
    existing_keys = {(item.action_type, item.action_type_version) for item in combined}
    for extra in extra_effects:
        key = (extra.action_type, extra.action_type_version)
        if key in existing_keys:
            raise ValueError(f"duplicate reviewed ActionType effect for {key[0]}@{key[1]}")
        combined.append(extra)
        existing_keys.add(key)
    return ReviewedEffectCatalog(combined)


class RemediationBridgeError(ValueError):
    """Base error for Assurance Twin what-if production or remediation bridging."""


class RemediationBridgeAuthorityError(PermissionError):
    """Raised when a caller attempts to elevate mode or execution authority via the Twin."""


class TypedProposalIntakeTarget(Protocol):
    """Durable intake seam accepting exact proposal and what-if pairs."""

    async def submit(
        self,
        *,
        proposal: TypedActionProposal,
        what_if: ProposalWhatIfResult | None,
        correlation_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class SubmittedWhatIfPairReceipt:
    """Receipt returned when an exact proposal and what-if pair enters the Twin intake."""

    intake_key: str
    proposal: TypedActionProposal
    what_if: ProposalWhatIfResult
    effect_digest: str
    review_ref: str
    correlation_id: str
    twin_execution_authority: Literal["none"] = "none"
    execution_authority: Literal[False] = False


class TypedPipelineWhatIfProducer:
    """Produce and submit exact proposal and what-if pairs to the Twin review intake."""

    def __init__(
        self,
        *,
        intake: TypedProposalIntakeTarget,
        effects: ReviewedEffectCatalog | None = None,
        producer_id: str = "typed-pipeline-what-if-producer",
        what_if_ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not producer_id.strip() or len(producer_id) > 128:
            raise ValueError("producer_id MUST be non-empty and at most 128 chars")
        if what_if_ttl <= timedelta(0) or what_if_ttl > timedelta(minutes=30):
            raise ValueError("what_if_ttl MUST be within (0, 30 minutes]")
        self._intake = intake
        self._effects = effects or build_reviewed_action_effect_catalog()
        self._producer_id = producer_id.strip()
        self._what_if_ttl = what_if_ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def effects(self) -> ReviewedEffectCatalog:
        return self._effects

    async def produce_and_submit(
        self,
        *,
        action_type: str,
        action_type_version: str,
        targets: Iterable[ResourceRef],
        parameters: Mapping[str, Any],
        evidence_refs: tuple[str, ...],
        correlation_id: str,
        status: WhatIfStatus = WhatIfStatus.PASSED,
        observed_at: datetime | None = None,
    ) -> SubmittedWhatIfPairReceipt:
        """Build a canonical proposal and non-synthetic what-if pair and submit to intake."""
        ordered_targets = canonical_targets(targets)
        proposal = TypedActionProposal.create(
            action_type=action_type,
            action_type_version=action_type_version,
            targets=ordered_targets,
            parameters=parameters,
        )
        now = (observed_at or self._clock()).astimezone(UTC)
        what_if = ProposalWhatIfResult(
            proposal.proposal_digest,
            status,
            True,
            False,
            WHAT_IF_SOURCE_AUTHORITY,
            self._producer_id,
            now,
            now + self._what_if_ttl,
            ordered_targets,
            evidence_refs,
        )
        return await self.submit_pair(
            proposal=proposal, what_if=what_if, correlation_id=correlation_id, now=now
        )

    async def submit_pair(
        self,
        *,
        proposal: TypedActionProposal,
        what_if: ProposalWhatIfResult,
        correlation_id: str,
        now: datetime | None = None,
    ) -> SubmittedWhatIfPairReceipt:
        """Validate a proposal and completed what-if against the reviewed catalog and submit."""
        check_time = (now or self._clock()).astimezone(UTC)
        effect = self._effects.effect_for(proposal.action_type, proposal.action_type_version)
        if effect is None:
            raise RemediationBridgeError(
                f"unreviewed ActionType {proposal.action_type}@{proposal.action_type_version}"
            )
        _validate_proposal_against_effect(proposal, effect)
        completed = require_completed_what_if(proposal, what_if, check_time)
        intake_key = await self._intake.submit(
            proposal=proposal, what_if=completed, correlation_id=correlation_id
        )
        return SubmittedWhatIfPairReceipt(
            intake_key,
            proposal,
            completed,
            effect.effect_digest,
            effect.review_ref,
            correlation_id,
        )


@dataclass(frozen=True, slots=True)
class GovernedRemediationProposalEnvelope:
    """Shadow remediation proposal routed into the normal risk-gated action path."""

    proposal_id: str
    finding_id: str
    rule_id: str
    proposal: TypedActionProposal
    effect_digest: str
    review_ref: str
    risk_tier: Literal["low", "medium", "high", "critical"]
    mode: Literal["shadow"]
    twin_execution_authority: Literal["none"]
    execution_authority: Literal[False]
    requires_risk_gate: Literal[True]
    requires_hil_approval: bool
    rollback_contract: str
    stop_condition: str
    blast_radius_limit: int
    idempotency_key: str
    correlation_id: str
    intake_key: str | None
    envelope_digest: str


class RiskGatedRemediationSink(Protocol):
    """Normal risk-gated action pipeline intake receiving shadow remediation proposals."""

    async def submit_remediation(self, envelope: GovernedRemediationProposalEnvelope) -> None: ...


class InMemoryRiskGatedRemediationSink:
    """In-memory sink capturing risk-gated remediation proposals for verification."""

    def __init__(self) -> None:
        self._proposals: list[GovernedRemediationProposalEnvelope] = []

    @property
    def proposals(self) -> tuple[GovernedRemediationProposalEnvelope, ...]:
        return tuple(self._proposals)

    async def submit_remediation(self, envelope: GovernedRemediationProposalEnvelope) -> None:
        self._proposals.append(envelope)


@dataclass(frozen=True, slots=True)
class AbstainedQueryDiscoveryReceipt:
    """Content-free discovery handoff receipt for an abstained Assurance Twin query."""

    question_digest: str
    abstain_code: AbstainCode
    compiler_revision: str
    handoff_status: DiscoveryHandoffStatus
    grants_authority: Literal[False] = False
    twin_execution_authority: Literal["none"] = "none"


class AssuranceTwinRemediationProposalBridge:
    """Bridge abstained queries to discovery and Findings to shadow risk-gated proposals."""

    default_mode: Literal["shadow"] = "shadow"
    twin_execution_authority: Literal["none"] = "none"

    def __init__(
        self,
        *,
        effects: ReviewedEffectCatalog,
        action_sink: RiskGatedRemediationSink,
        discovery_sink: AssuranceTwinDiscoverySink | None = None,
        what_if_producer: TypedPipelineWhatIfProducer | None = None,
        compiler_revision: str = "assurance-twin-compiler-1.0.0",
        blast_radius_limit: int = 10,
    ) -> None:
        if not compiler_revision.strip() or len(compiler_revision) > 128:
            raise ValueError("compiler_revision MUST be bounded non-empty text")
        if not 1 <= blast_radius_limit <= MAX_PROPOSAL_TARGETS:
            raise ValueError(f"blast_radius_limit MUST be in [1, {MAX_PROPOSAL_TARGETS}]")
        self._effects = effects
        self._action_sink = action_sink
        self._discovery_sink = discovery_sink
        self._what_if_producer = what_if_producer
        self._compiler_revision = compiler_revision.strip()
        self._blast_radius_limit = blast_radius_limit
        self._submitted_by_idempotency: dict[str, GovernedRemediationProposalEnvelope] = {}

    async def forward_abstained_query(
        self,
        *,
        abstain: AbstainResult,
        raw_query: str | None = None,
        precomputed_digest: str | None = None,
    ) -> AbstainedQueryDiscoveryReceipt:
        """Forward an abstained Twin query to content-free discovery without raw text."""
        if (raw_query is None) == (precomputed_digest is None):
            raise ValueError("provide exactly one of raw_query or precomputed_digest")
        digest = (
            question_digest(raw_query) if raw_query is not None else str(precomputed_digest).strip()
        )
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("question_digest MUST be a canonical sha256 digest")
        if self._discovery_sink is None:
            return AbstainedQueryDiscoveryReceipt(
                digest, abstain.code, self._compiler_revision, DiscoveryHandoffStatus.UNAVAILABLE
            )
        await self._discovery_sink.publish(
            AssuranceTwinQueryGap(
                "1.0.0", digest, self._compiler_revision, abstain.code, grants_authority=False
            )
        )
        return AbstainedQueryDiscoveryReceipt(
            digest, abstain.code, self._compiler_revision, DiscoveryHandoffStatus.EMITTED
        )

    async def submit_remediation_proposal(
        self,
        *,
        finding_id: str,
        rule_id: str,
        action_type: str,
        action_type_version: str,
        targets: Iterable[ResourceRef],
        parameters: Mapping[str, Any],
        rollback_contract: str,
        stop_condition: str,
        idempotency_key: str,
        correlation_id: str,
        risk_tier: Literal["low", "medium", "high", "critical"] = "high",
        what_if_evidence_refs: tuple[str, ...] = ("what-if:simulation-receipt:1",),
        requested_mode: str = "shadow",
        requested_authority: str = "none",
        bypass_risk_gate: bool = False,
    ) -> GovernedRemediationProposalEnvelope:
        """Submit a shadow remediation proposal into the normal risk-gated action path."""
        if requested_mode != "shadow":
            raise RemediationBridgeAuthorityError(
                "Assurance Twin remediation proposals MUST enter in shadow mode"
            )
        if requested_authority != "none" or bypass_risk_gate:
            raise RemediationBridgeAuthorityError(
                "Assurance Twin never grants execution authority or bypasses the risk gate"
            )
        if risk_tier not in {"low", "medium", "high", "critical"}:
            raise RemediationBridgeError("risk_tier MUST be low, medium, high, or critical")

        norm_finding = _require_bounded("finding_id", finding_id)
        norm_rule = _require_bounded("rule_id", rule_id)
        norm_rollback = _require_bounded("rollback_contract", rollback_contract)
        if norm_rollback not in {
            "pr_revert",
            "scripted",
            "pitr",
            "snapshot_restore",
            "state_forward_only",
        }:
            raise RemediationBridgeError("rollback_contract MUST be a canonical RollbackKind")
        norm_stop = _require_bounded("stop_condition", stop_condition)
        norm_idem = _require_bounded("idempotency_key", idempotency_key)
        norm_corr = _require_bounded("correlation_id", correlation_id)
        ordered_targets = canonical_targets(targets)
        if not ordered_targets or len(ordered_targets) > self._blast_radius_limit:
            raise RemediationBridgeError(
                f"targets MUST be within blast_radius_limit={self._blast_radius_limit}"
            )
        effect = self._effects.effect_for(action_type, action_type_version)
        if effect is None:
            raise RemediationBridgeError(
                f"ActionType {action_type}@{action_type_version} lacks a reviewed effect model"
            )
        proposal = TypedActionProposal.create(
            action_type=action_type,
            action_type_version=action_type_version,
            targets=ordered_targets,
            parameters=parameters,
        )
        _validate_proposal_against_effect(proposal, effect)
        intake_key: str | None = None
        if self._what_if_producer is not None:
            receipt = await self._what_if_producer.produce_and_submit(
                action_type=action_type,
                action_type_version=action_type_version,
                targets=ordered_targets,
                parameters=parameters,
                evidence_refs=what_if_evidence_refs,
                correlation_id=norm_corr,
            )
            intake_key = receipt.intake_key
        requires_hil = risk_tier in {"high", "critical"}
        envelope_digest = canonical_digest(
            (
                "assurance-twin.remediation-proposal-envelope/1.0.0",
                norm_finding,
                norm_rule,
                proposal.proposal_digest,
                effect.effect_digest,
                effect.review_ref,
                risk_tier,
                "shadow",
                "none",
                True,
                requires_hil,
                norm_rollback,
                norm_stop,
                self._blast_radius_limit,
                norm_idem,
                norm_corr,
                intake_key,
            )
        )
        envelope = GovernedRemediationProposalEnvelope(
            "remediation-proposal:" + envelope_digest.removeprefix("sha256:")[:32],
            norm_finding,
            norm_rule,
            proposal,
            effect.effect_digest,
            effect.review_ref,
            risk_tier,
            "shadow",
            "none",
            False,
            True,
            requires_hil,
            norm_rollback,
            norm_stop,
            self._blast_radius_limit,
            norm_idem,
            norm_corr,
            intake_key,
            envelope_digest,
        )
        prior = self._submitted_by_idempotency.get(norm_idem)
        if prior is not None:
            if prior.envelope_digest != envelope.envelope_digest:
                raise RemediationBridgeError(
                    f"idempotency_key {norm_idem!r} reused with conflicting remediation proposal"
                )
            return prior
        self._submitted_by_idempotency[norm_idem] = envelope
        await self._action_sink.submit_remediation(envelope)
        return envelope


def _validate_proposal_against_effect(
    proposal: TypedActionProposal, effect: ReviewedActionTypeEffect
) -> None:
    params = proposal.parameters()
    if not effect.parameter_names <= params.keys():
        raise RemediationBridgeError("proposal is missing required effect parameters")
    if not params.keys() <= (effect.parameter_names | set(effect.inert_parameters)):
        raise RemediationBridgeError("proposal contains undeclared parameters")
    for target in proposal.targets:
        if target.resource_type not in effect.target_resource_types:
            raise RemediationBridgeError(
                f"target resource_type {target.resource_type} is not supported"
            )


def _require_bounded(name: str, value: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= _MAX_TEXT):
        raise RemediationBridgeError(f"{name} MUST be non-empty and at most {_MAX_TEXT} chars")
    return value.strip()


__all__ = [
    "AbstainedQueryDiscoveryReceipt",
    "AssuranceTwinRemediationProposalBridge",
    "GOVERNED_REVIEWED_ACTION_EFFECTS",
    "GovernedRemediationProposalEnvelope",
    "InMemoryRiskGatedRemediationSink",
    "RemediationBridgeAuthorityError",
    "RemediationBridgeError",
    "RiskGatedRemediationSink",
    "SubmittedWhatIfPairReceipt",
    "TypedPipelineWhatIfProducer",
    "TypedProposalIntakeTarget",
    "build_reviewed_action_effect_catalog",
]

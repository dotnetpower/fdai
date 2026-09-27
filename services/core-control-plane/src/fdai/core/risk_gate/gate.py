"""Risk-gate - the final safety-invariant enforcement point.

Phase 2 risk-gate (see
[`architecture.instructions.md § Risk-Gated Autonomy`] and
[`docs/roadmap/decisioning/risk-classification.md`]).

Contract
--------

Given a proposed :class:`Action` + the referenced :class:`Rule` + the
matched :class:`OntologyActionType`, the risk gate produces a
:class:`RiskDecision`:

- ``auto`` - safety invariants + preconditions + blast radius all clean,
  and the ActionType has been **promoted to enforce** through the
  per-action promotion gate. Executor may apply.
- ``hil`` - high-risk (irreversible, over blast-radius cap, or
  precondition unresolved). Human-in-the-loop approval required.
- ``deny`` - an explicit deny signal (verifier from the T2 quality gate,
  or the ActionType's `preconditions` explicitly false).
- ``abstain`` - insufficient information to decide; no-op audit + HIL
  hand-off.

Every path writes an audit entry (the caller is expected to persist it
via :class:`~fdai.shared.providers.state_store.StateStore`).

Promotion gate
--------------

An ActionType ships shadow-first. Promotion to enforce is a **separate**
decision keyed on measured metrics:

- ``min_shadow_days`` elapsed since first shadow deployment.
- ``min_samples`` shadow executions observed.
- ``min_accuracy`` (== 1 - false-positive rate) held over the window.
- ``max_policy_escapes`` == 0 in the window.

The :class:`ActionPromotionRegistry` records the current per-ActionType
mode + the promotion metric report the last decision was based on. The
risk gate reads that registry - it does NOT re-measure. Measurement is
the pipeline / KPI job's responsibility (P2-A + phase-0 KPI dashboard).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Literal, Protocol

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.risk_gate.preconditions import PreconditionEvaluation
from fdai.shared.contracts.development_authority import revalidate_development_authority
from fdai.shared.contracts.models import (
    Action,
    BlastRadiusScope,
    Mode,
    OntologyActionType,
    PreconditionKind,
    Rule,
)
from fdai.shared.contracts.models.development_authority import (
    DevelopmentActionConfirmation,
    DevelopmentAuthorityEnvelope,
    DevelopmentAuthorityGrant,
    DevelopmentBindingVerification,
    DevelopmentPromotionApproval,
    FullAuthorityDevelopmentProfile,
    authority_text_digest,
    canonical_authority_digest,
    development_promotion_target_digest,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    resolve_development_binding,
)
from fdai.shared.providers.exemption import (
    ExemptionRegistry,
    empty_exemption_registry,
)


class RiskDecisionOutcome(StrEnum):
    AUTO = "auto"
    HIL = "hil"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    """Measured metrics for one ActionType's shadow window.

    Consumed by :class:`ActionPromotionRegistry.consider_promotion`.
    """

    action_type: str
    shadow_days: int
    samples: int
    accuracy: float
    policy_escapes: int

    def __post_init__(self) -> None:
        if not self.action_type:
            raise ValueError("action_type MUST NOT be empty")
        if self.shadow_days < 0:
            raise ValueError("shadow_days MUST be >= 0")
        if self.samples < 0:
            raise ValueError("samples MUST be >= 0")
        if not isfinite(self.accuracy) or not 0.0 <= self.accuracy <= 1.0:
            raise ValueError("accuracy MUST be finite and in [0.0, 1.0]")
        if self.policy_escapes < 0:
            raise ValueError("policy_escapes MUST be >= 0")


@dataclass(frozen=True, slots=True)
class ActionModeRecord:
    """Current effective mode for one ActionType + provenance."""

    action_type: str
    mode: Mode
    promoted_at: datetime | None = None
    demoted_at: datetime | None = None
    metrics: PromotionMetrics | None = None
    promotion_evidence_digest: str | None = None
    fdai_revision: str | None = None
    scenario_set_version: str | None = None
    action_type_version: str | None = None
    action_type_digest: str | None = None
    development_profile_digest: str | None = None
    development_only: bool = False
    production_ready: bool = False
    development_valid_until: datetime | None = None
    original_quorum: int | None = None
    effective_quorum: int | None = None


class OperationalPromotionReceiptVerifier(Protocol):
    def verify(
        self,
        *,
        action_type: OntologyActionType,
        receipt: OperationalPromotionReceipt,
    ) -> bool: ...


class DevelopmentPromotionReceiptVerifier(Protocol):
    def verify_development(
        self,
        *,
        profile_digest: str,
        action_type: OntologyActionType,
        receipt: OperationalPromotionReceipt,
    ) -> bool: ...


class PersistedPromotionAuthorityVerifier(Protocol):
    async def verify(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        evidence_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> bool: ...


class ActionPromotionRegistry:
    """In-process registry of per-ActionType enforce/shadow state.

    A fork MAY back this with the state store; the P1/P2 default is
    in-memory so tests don't need Postgres. The registry NEVER mutates
    the ActionType YAML - a promotion is a runtime state change, not a
    catalog edit.
    """

    def __init__(
        self,
        *,
        receipt_verifier: OperationalPromotionReceiptVerifier | None = None,
        allow_legacy_metrics: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._records: dict[str, ActionModeRecord] = {}
        self._development_records: dict[tuple[str, str], ActionModeRecord] = {}
        self._receipt_verifier = receipt_verifier
        self._allow_legacy_metrics = allow_legacy_metrics
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def mode_of(self, action_type: str) -> Mode:
        record = self._records.get(action_type)
        return record.mode if record is not None else Mode.SHADOW

    def record(self, action_type: str) -> ActionModeRecord | None:
        return self._records.get(action_type)

    def development_mode_of(self, profile_digest: str, action_type: str) -> Mode:
        """Read mode only from the exact development profile namespace."""

        record = self._development_records.get((profile_digest, action_type))
        if (
            record is not None
            and record.development_valid_until is not None
            and self._clock() >= record.development_valid_until
        ):
            return Mode.SHADOW
        return record.mode if record is not None else Mode.SHADOW

    def development_record(
        self,
        profile_digest: str,
        action_type: str,
    ) -> ActionModeRecord | None:
        return self._development_records.get((profile_digest, action_type))

    def restore(self, action_type: str, record: ActionModeRecord | None) -> None:
        """Reset the in-memory record after a failed durable persist.

        ``consider_promotion`` mutates the cache optimistically so a caller
        can inspect its verdict before persisting it. When persistence then
        fails, that optimistic mutation MUST NOT remain visible - a caller
        uses this to put the exact prior record back (or clear the entry
        when there was none), so ``mode_of`` can never report an ENFORCE
        promotion that was never durably recorded.
        """
        if record is None:
            self._records.pop(action_type, None)
        else:
            self._records[action_type] = record

    def consider_promotion(
        self,
        *,
        action_type: OntologyActionType,
        metrics: PromotionMetrics,
        receipt: OperationalPromotionReceipt | None = None,
    ) -> ActionModeRecord:
        """Promote the ActionType if metrics clear its ``promotion_gate``.

        Metrics that fail the gate demote back to shadow (or leave shadow
        untouched when nothing was promoted yet). Every call writes a
        record; the caller audits it.
        """
        if metrics.action_type != action_type.name:
            raise ValueError(
                f"metrics.action_type {metrics.action_type!r} != "
                f"action_type.name {action_type.name!r}"
            )
        gate = action_type.promotion_gate
        now = self._clock()
        metric_passes = (
            metrics.shadow_days >= gate.min_shadow_days
            and metrics.samples >= gate.min_samples
            and metrics.accuracy >= gate.min_accuracy
            and metrics.policy_escapes <= gate.max_policy_escapes
        )
        receipt_passes = False
        if receipt is not None and self._receipt_verifier is not None:
            receipt_passes = (
                receipt.ready
                and receipt.decision_evidence_receipt_digest is not None
                and receipt.decision_evidence_verification_bundle_digest is not None
                and receipt.action_type_name == action_type.name
                and receipt.action_type_version == action_type.version
                and receipt.action_type_digest == action_type_digest(action_type)
                and receipt.live_observation_days == metrics.shadow_days
                and receipt.sample_count == metrics.samples
                and receipt.accuracy == metrics.accuracy
                and receipt.policy_escapes == metrics.policy_escapes
                and self._receipt_verifier.verify(
                    action_type=action_type,
                    receipt=receipt,
                )
            )
        passes = metric_passes and (
            receipt_passes or (receipt is None and self._allow_legacy_metrics)
        )
        if passes:
            prior = self._records.get(action_type.name)
            same_authority = (
                prior is not None
                and prior.mode is Mode.ENFORCE
                and prior.promotion_evidence_digest
                == (receipt.evidence_digest if receipt else None)
            )
            record = ActionModeRecord(
                action_type=action_type.name,
                mode=Mode.ENFORCE,
                promoted_at=(prior.promoted_at if same_authority and prior is not None else now),
                metrics=metrics,
                promotion_evidence_digest=(receipt.evidence_digest if receipt else None),
                fdai_revision=(receipt.fdai_revision if receipt else None),
                scenario_set_version=(receipt.scenario_set_version if receipt else None),
                action_type_version=(receipt.action_type_version if receipt else None),
                action_type_digest=(receipt.action_type_digest if receipt else None),
                production_ready=True,
            )
        else:
            prior = self._records.get(action_type.name)
            demoted_at = now if prior is not None and prior.mode is Mode.ENFORCE else None
            record = ActionModeRecord(
                action_type=action_type.name,
                mode=Mode.SHADOW,
                promoted_at=(prior.promoted_at if prior else None),
                demoted_at=demoted_at,
                metrics=metrics,
                promotion_evidence_digest=(receipt.evidence_digest if receipt else None),
                fdai_revision=(receipt.fdai_revision if receipt else None),
                scenario_set_version=(receipt.scenario_set_version if receipt else None),
                action_type_version=(receipt.action_type_version if receipt else None),
                action_type_digest=(receipt.action_type_digest if receipt else None),
            )
        self._records[action_type.name] = record
        return record

    def consider_development_promotion(
        self,
        *,
        profile: FullAuthorityDevelopmentProfile,
        confirmation: DevelopmentActionConfirmation,
        binding_source: DevelopmentAuthorityBindingSource,
        binding_request: DevelopmentAuthorityBindingRequest,
        binding_verification: DevelopmentBindingVerification,
        grant: DevelopmentAuthorityGrant,
        action_type: OntologyActionType,
        approval: DevelopmentPromotionApproval,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord:
        """Change only one profile-scoped development registry entry.

        This method cannot affect :meth:`mode_of`, and every resulting record
        explicitly remains ineligible as production-readiness evidence. Exact
        current Owner approval can promote development immediately; production
        shadow metrics never grant or constrain this separate authority axis.
        """

        now = self._clock()
        current_verification = resolve_development_binding(
            binding_source,
            binding_request,
            now=now,
        )
        if current_verification != binding_verification:
            raise ValueError("development promotion binding changed")
        decision = revalidate_development_authority(
            profile,
            confirmation,
            current_verification,
            grant,
            now=now,
            original_quorum=grant.original_quorum,
        )
        if not decision.eligible:
            raise ValueError(
                f"development promotion authority is ineligible: {decision.reason_code}"
            )
        binding = current_verification.binding
        current_target_digest = "sha256:" + action_type_digest(action_type)
        current_target = (
            action_type.name,
            action_type.version,
            current_target_digest,
        )
        registered_targets = {
            (item.action_type, item.version, item.action_type_digest)
            for item in profile.registered_actions
        }
        expected_promotion_target = development_promotion_target_digest(
            action_type=action_type.name,
            action_type_version=action_type.version,
            action_type_digest=current_target_digest,
            reviewed_replay_digest=approval.reviewed_replay_digest,
            source_revision=approval.fdai_revision,
            scenario_set_version=approval.scenario_set_version,
            promotion_evidence_digest=approval.promotion_evidence_digest,
        )
        if (
            current_target not in registered_targets
            or approval.profile_digest != grant.profile_digest
            or approval.confirmation_digest != grant.confirmation_digest
            or approval.binding_verification_digest != current_verification.digest
            or approval.promotion_action_type != binding.action_type
            or approval.target_action_type != action_type.name
            or approval.target_action_type_version != action_type.version
            or approval.target_action_type_digest != current_target_digest
            or approval.promotion_target_digest != expected_promotion_target
            or binding.params_digest != expected_promotion_target
            or approval.reviewer_principal != grant.owner_principal
            or approval.valid_until != grant.valid_until
            or now >= approval.valid_until
            or approval.development_only is not True
            or approval.production_ready is not False
        ):
            raise ValueError("development promotion approval does not match current authority")
        if metrics is not None and metrics.action_type != action_type.name:
            raise ValueError("development promotion metrics action type does not match")
        key = (grant.profile_digest, action_type.name)
        prior = self._development_records.get(key)
        same_authority = (
            prior is not None
            and prior.mode is Mode.ENFORCE
            and prior.promotion_evidence_digest == approval.reviewed_replay_digest
        )
        record = ActionModeRecord(
            action_type=action_type.name,
            mode=Mode.ENFORCE,
            promoted_at=prior.promoted_at if same_authority and prior else now,
            metrics=metrics,
            promotion_evidence_digest=approval.reviewed_replay_digest,
            fdai_revision=approval.fdai_revision,
            scenario_set_version=approval.scenario_set_version,
            action_type_version=action_type.version,
            action_type_digest=action_type_digest(action_type),
            development_profile_digest=grant.profile_digest,
            development_only=True,
            production_ready=False,
            development_valid_until=grant.valid_until,
            original_quorum=grant.original_quorum,
            effective_quorum=grant.effective_quorum,
        )
        self._development_records[key] = record
        return record

    def demote_development(
        self,
        profile_digest: str,
        action_type_name: str,
    ) -> ActionModeRecord:
        """Lower one development namespace without touching production mode."""

        if not profile_digest or not action_type_name:
            raise ValueError("development demotion identity MUST be complete")
        key = (profile_digest, action_type_name)
        prior = self._development_records.get(key)
        now = self._clock()
        record = ActionModeRecord(
            action_type=action_type_name,
            mode=Mode.SHADOW,
            promoted_at=prior.promoted_at if prior else None,
            demoted_at=(now if prior is not None and prior.mode is Mode.ENFORCE else None),
            metrics=prior.metrics if prior else None,
            development_profile_digest=profile_digest,
            development_only=True,
            production_ready=False,
            development_valid_until=prior.development_valid_until if prior else None,
            original_quorum=prior.original_quorum if prior else None,
            effective_quorum=prior.effective_quorum if prior else None,
        )
        self._development_records[key] = record
        return record

    def demote(
        self,
        action_type_name: str,
        *,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord:
        """Force an ActionType back to shadow (regression / override path).

        Idempotent: demoting an ActionType that has never been recorded
        creates a shadow record; demoting one already in shadow leaves
        ``demoted_at`` at its prior value. ``demoted_at`` is stamped only
        when this call transitions the record out of ``ENFORCE`` - that
        keeps the audit trail meaningful (a "demotion" against an
        already-shadow entry is not a state change).

        The optional ``metrics`` argument records the measurement that
        justified the demotion so the audit consumer can render the same
        reason the regression detector produced.
        """
        if not action_type_name:
            raise ValueError("action_type_name MUST NOT be empty")
        now = self._clock()
        prior = self._records.get(action_type_name)
        demoted_at: datetime | None
        if prior is None:
            demoted_at = None
            promoted_at: datetime | None = None
            prior_metrics = None
        else:
            demoted_at = now if prior.mode is Mode.ENFORCE else prior.demoted_at
            promoted_at = prior.promoted_at
            prior_metrics = prior.metrics
        record = ActionModeRecord(
            action_type=action_type_name,
            mode=Mode.SHADOW,
            promoted_at=promoted_at,
            demoted_at=demoted_at,
            metrics=metrics if metrics is not None else prior_metrics,
        )
        self._records[action_type_name] = record
        return record


@dataclass(frozen=True, slots=True)
class RiskGateConfig:
    """Executor-side caps applied at the risk gate."""

    max_affected_resources: int = 10
    max_rate_per_minute: int = 30
    max_precondition_age_seconds: int = 900
    hil_authority_action_types: frozenset[str] = frozenset({"governance.promote-action-type"})


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Frozen record emitted by :meth:`RiskGate.evaluate`."""

    outcome: RiskDecisionOutcome
    action_id: str
    effective_mode: Mode
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Every reason contributing to the outcome - empty on clean AUTO."""


class RiskGate:
    """Compose the four safety-invariant checks + promotion mode read."""

    def __init__(
        self,
        *,
        registry: ActionPromotionRegistry,
        config: RiskGateConfig | None = None,
        exemption_registry: ExemptionRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        development_executor_principal: str | None = None,
    ) -> None:
        cfg = config or RiskGateConfig()
        if cfg.max_affected_resources < 1:
            raise ValueError("max_affected_resources MUST be >= 1")
        if cfg.max_rate_per_minute < 1:
            raise ValueError("max_rate_per_minute MUST be >= 1")
        if cfg.max_precondition_age_seconds < 0:
            raise ValueError("max_precondition_age_seconds MUST be >= 0")
        if any(not item or item != item.strip() for item in cfg.hil_authority_action_types):
            raise ValueError("hil_authority_action_types MUST contain canonical ids")
        self._registry = registry
        self._config = cfg
        self._exemptions = exemption_registry or empty_exemption_registry()
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._development_profile = development_profile
        self._development_binding_source = development_binding_source
        self._development_executor_principal = development_executor_principal

    def evaluate(
        self,
        *,
        action: Action,
        rule: Rule,
        action_type: OntologyActionType,
        inventory_age_seconds: int | None = None,
        precondition_evaluations: Sequence[PreconditionEvaluation] = (),
        automation_hold_engaged: bool = False,
        automation_hold_recovery: bool = False,
        upstream_signal: Literal["deny", "abstain"] | None = None,
        development_authority: DevelopmentAuthorityEnvelope | None = None,
    ) -> RiskDecision:
        """Return a :class:`RiskDecision` for the proposed action.

        ``upstream_signal`` propagates a terminal signal from the T2
        quality gate (``deny`` -> :attr:`RiskDecisionOutcome.DENY`;
        ``abstain`` -> :attr:`RiskDecisionOutcome.ABSTAIN` when no other
        reason applies). A deny short-circuits every other check.
        ``inventory_age_seconds`` MUST be supplied when the ActionType
        declares a ``graph_fresh_within_seconds`` precondition; a
        missing age fails **closed** to HIL (see coding-conventions).
        """
        # Rule metadata (severity/category) is reserved for a future
        # scoring model that adjusts blast-radius caps by severity; see
        # risk-classification.md. Kept in the signature so callers do
        # not have to change when that lands.
        del rule
        reasons: list[str] = []

        recovery_path = automation_hold_engaged and automation_hold_recovery
        if automation_hold_engaged and not recovery_path:
            return RiskDecision(
                outcome=RiskDecisionOutcome.DENY,
                action_id=str(action.action_id),
                effective_mode=self._registry.mode_of(action_type.name),
                reasons=("target_automation_hold_active",),
            )

        # 0. Upstream deny short-circuits (T2 verifier explicit reject).
        if upstream_signal == "deny":
            return RiskDecision(
                outcome=RiskDecisionOutcome.DENY,
                action_id=str(action.action_id),
                effective_mode=self._registry.mode_of(action_type.name),
                reasons=("upstream_verifier_deny",),
            )

        if recovery_path:
            reasons.append("target_automation_hold_recovery_requires_hil")

        # 0.5. Human override (Exemption). An active exemption on the
        # cited rule + target scope suppresses execution but NEVER hides
        # the finding (architecture.instructions § Human Override).
        # Every citing rule is checked; the first match wins.
        for cited in action.citing_rules:
            match = self._exemptions.find_match(
                rule_id=cited,
                resource_ref=action.target_resource_ref,
                resource_group=_extract_resource_group(action.target_resource_ref),
            )
            if match is not None:
                return RiskDecision(
                    outcome=RiskDecisionOutcome.ABSTAIN,
                    action_id=str(action.action_id),
                    effective_mode=self._registry.mode_of(action_type.name),
                    reasons=(
                        f"human_override:exemption={match.exemption_id}"
                        f":scope={match.scope_summary}",
                    ),
                )

        # 1. Explicit irreversible → HIL + quorum (P1 policy).
        if action_type.irreversible:
            reasons.append("action_type_irreversible_requires_hil")

        # 2. Blast-radius caps.
        count = action.blast_radius.count
        if count is None:
            # Unknown exact count (BlastRadius.count is Optional). The
            # ActionBuilder always fills it, but a partial Action that
            # slipped past pydantic (or a fork caller) MUST NOT fail open:
            # a single-resource scope is inherently bounded, but a broader
            # scope with an unknown count is not, so fail closed to HIL -
            # the same defense-in-depth the stop_condition / citing_rules
            # checks below apply.
            if action.blast_radius.scope is not BlastRadiusScope.RESOURCE:
                reasons.append(
                    f"blast_radius_count_unknown_for_scope={action.blast_radius.scope.value}"
                )
        elif count > self._config.max_affected_resources:
            reasons.append(f"blast_radius_count={count}>max={self._config.max_affected_resources}")
        rpm = action.blast_radius.rate_per_minute
        if rpm is not None and rpm > self._config.max_rate_per_minute:
            reasons.append(f"blast_radius_rate={rpm}>max={self._config.max_rate_per_minute}")

        # 3. Precondition freshness - a stale inventory read blocks
        # graph-derived preconditions per the ActionType contract.
        # Fail-close: if the ActionType demands the check but the caller
        # did not supply an age, treat the precondition as unresolved.
        requires_fresh = any(
            p.kind.value == "graph_fresh_within_seconds" for p in action_type.preconditions
        )
        if requires_fresh:
            if inventory_age_seconds is None:
                reasons.append("graph_fresh_precondition_unknown_age")
            else:
                declared = _declared_graph_fresh_seconds(action_type)
                floor = min(declared, self._config.max_precondition_age_seconds)
                if inventory_age_seconds > floor:
                    reasons.append(
                        f"graph_fresh_precondition_stale:age={inventory_age_seconds}>max={floor}"
                    )

        evaluations_by_index: dict[int, PreconditionEvaluation] = {}
        for candidate_evaluation in precondition_evaluations:
            if candidate_evaluation.condition_index in evaluations_by_index:
                reasons.append(
                    "precondition_evaluation_duplicate:"
                    f"index={candidate_evaluation.condition_index}"
                )
                continue
            evaluations_by_index[candidate_evaluation.condition_index] = candidate_evaluation

        for index, precondition in enumerate(action_type.preconditions):
            if precondition.kind is PreconditionKind.GRAPH_FRESH_WITHIN_SECONDS:
                continue
            resolved_evaluation = evaluations_by_index.get(index)
            if resolved_evaluation is None:
                reasons.append(
                    f"precondition_unresolved:index={index}:kind={precondition.kind.value}"
                )
            elif resolved_evaluation.kind is not precondition.kind:
                reasons.append(
                    f"precondition_evaluation_mismatch:index={index}:"
                    f"expected={precondition.kind.value}:actual={resolved_evaluation.kind.value}"
                )
            elif not resolved_evaluation.satisfied:
                reasons.append(f"precondition_failed:index={index}:kind={precondition.kind.value}")

        # 4. Missing safety-invariant fields (defense in depth against a
        # partial Action that slipped past pydantic; unreachable via the
        # public API).
        if not action.stop_condition.strip():  # pragma: no cover
            reasons.append("missing_stop_condition")
        if not action.citing_rules:  # pragma: no cover
            reasons.append("missing_citing_rules")

        # 5. Effective mode from the promotion registry. Shadow mode is
        # a hard reason (an autonomous auto in shadow contradicts itself),
        # recorded BEFORE the upstream-abstain check so a shadow-mode
        # action never masquerades as a soft ABSTAIN.
        authority_mutation = action_type.name in self._config.hil_authority_action_types
        if development_authority is not None:
            profile_digest = self._current_development_profile(
                development_authority,
                action=action,
                action_type=action_type,
            )
            effective_mode = (
                self._registry.development_mode_of(profile_digest, action_type.name)
                if profile_digest is not None
                else Mode.SHADOW
            )
            if profile_digest is None:
                reasons.append("development_authority_unverified")
        else:
            effective_mode = (
                Mode.ENFORCE if authority_mutation else self._registry.mode_of(action_type.name)
            )
        if authority_mutation and development_authority is None:
            reasons.append("authority_mutation_requires_hil")
        elif effective_mode is not Mode.ENFORCE:
            reasons.append("action_type_in_shadow_mode")

        # 6. Upstream abstain → ABSTAIN when nothing else already forced HIL.
        if upstream_signal == "abstain" and not reasons:
            return RiskDecision(
                outcome=RiskDecisionOutcome.ABSTAIN,
                action_id=str(action.action_id),
                effective_mode=effective_mode,
                reasons=("upstream_verifier_abstain",),
            )

        if reasons:
            outcome = RiskDecisionOutcome.HIL
        else:
            outcome = RiskDecisionOutcome.AUTO

        return RiskDecision(
            outcome=outcome,
            action_id=str(action.action_id),
            effective_mode=effective_mode,
            reasons=tuple(reasons),
        )

    def _current_development_profile(
        self,
        authority: DevelopmentAuthorityEnvelope,
        *,
        action: Action,
        action_type: OntologyActionType,
    ) -> str | None:
        try:
            envelope = DevelopmentAuthorityEnvelope.model_validate(
                authority.model_dump(mode="python")
            )
        except (TypeError, ValueError):
            return None
        profile = self._development_profile
        source = self._development_binding_source
        executor_principal = self._development_executor_principal
        if profile is None or source is None or not executor_principal:
            return None
        confirmation = envelope.confirmation
        grant = envelope.grant
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            return None
        request = DevelopmentAuthorityBindingRequest.from_action(
            action_type=action_type.name,
            action_id=str(action.action_id),
            target_ref=action.target_resource_ref,
            params=action.params,
            requester_principal=profile.owner_principal,
            executor_principal=executor_principal,
            idempotency_key=action.idempotency_key,
            rollback_contract=action.rollback_ref.kind.value,
        )
        try:
            verification = resolve_development_binding(source, request, now=now)
        except ValueError:
            return None
        if verification != envelope.binding_verification:
            return None
        decision = revalidate_development_authority(
            profile,
            confirmation,
            verification,
            grant,
            now=now,
            original_quorum=grant.original_quorum,
        )
        if not decision.eligible or decision.grant != grant:
            return None
        binding = verification.binding
        registered = {
            (item.action_type, item.version, item.action_type_digest)
            for item in profile.registered_actions
        }
        current_action_type = (
            action_type.name,
            action_type.version,
            "sha256:" + action_type_digest(action_type),
        )
        if (
            grant.development_only is not True
            or grant.profile_digest != profile.digest
            or confirmation.profile_digest != grant.profile_digest
            or confirmation.digest != grant.confirmation_digest
            or confirmation.binding != binding
            or binding.digest != grant.action_binding_digest
            or verification.digest != grant.binding_verification_digest
            or not now < confirmation.expires_at
            or not now < verification.expires_at
            or not now < grant.valid_until
            or binding.action_type != action_type.name
            or binding.action_type_version != action_type.version
            or binding.action_type_digest != "sha256:" + action_type_digest(action_type)
            or binding.action_id != str(action.action_id)
            or binding.target_digest != authority_text_digest(action.target_resource_ref)
            or binding.params_digest != canonical_authority_digest(action.params)
            or binding.safeguards.idempotency_key != action.idempotency_key
            or binding.safeguards.rollback_contract_digest
            != authority_text_digest(action.rollback_ref.kind.value)
            or current_action_type not in registered
        ):
            return None
        return grant.profile_digest


def _declared_graph_fresh_seconds(action_type: OntologyActionType) -> int:
    """Return the smallest ``graph_fresh_within_seconds`` precondition value.

    Assumes the caller has already verified at least one precondition of
    that kind exists on ``action_type`` - raises when the values are not
    numeric so a malformed ActionType surfaces at first use instead of
    being silently ignored.
    """
    values: list[int] = []
    for precondition in action_type.preconditions:
        if precondition.kind.value != "graph_fresh_within_seconds":
            continue
        val = precondition.value
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            values.append(int(val))
    if not values:
        raise ValueError(
            f"ActionType {action_type.name!r} declares a graph_fresh_within_seconds "
            "precondition but no numeric value was found"
        )
    return min(values)


def _extract_resource_group(resource_ref: str) -> str | None:
    """Parse the resource-group segment from an ARM resource id.

    Returns ``None`` when the reference is not an ARM id or does not
    include a ``resourceGroups/<name>`` segment. Case-insensitive on the
    segment key - ARM ids may appear as ``resourcegroups`` in the wild.
    """
    lowered = resource_ref.lower()
    marker = "/resourcegroups/"
    idx = lowered.find(marker)
    if idx < 0:
        return None
    tail = resource_ref[idx + len(marker) :]
    slash = tail.find("/")
    if slash < 0:
        candidate = tail
    else:
        candidate = tail[:slash]
    return candidate or None


def duration_since(dt: datetime) -> timedelta:
    """Elapsed time since ``dt`` (helper for the promotion metric caller)."""
    return datetime.now(tz=UTC) - dt


__all__ = [
    "ActionModeRecord",
    "ActionPromotionRegistry",
    "DevelopmentPromotionReceiptVerifier",
    "OperationalPromotionReceiptVerifier",
    "PersistedPromotionAuthorityVerifier",
    "PromotionMetrics",
    "RiskDecision",
    "RiskDecisionOutcome",
    "RiskGate",
    "RiskGateConfig",
    "duration_since",
]

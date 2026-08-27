"""Qualification contributions for context and locale evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class LocaleParityScenarioResult:
    case_id: str
    locale: str
    locale_verified: bool
    semantically_equivalent: bool
    ui_locale_independent: bool
    paired_reply_replayable: bool
    locale_divergence_count: int
    counterpart_observation_digest: str
    evidence_digest: str
    semantic_review_owner: str

    def __post_init__(self) -> None:
        _validate_common(self.case_id, self.locale, self.evidence_digest)
        _require_digest(
            self.counterpart_observation_digest,
            "counterpart_observation_digest",
        )
        if _TOKEN.fullmatch(self.semantic_review_owner) is None:
            raise ValueError("semantic_review_owner MUST be a bounded portable token")
        _require_booleans(
            self.locale_verified,
            self.semantically_equivalent,
            self.ui_locale_independent,
            self.paired_reply_replayable,
        )
        _require_count("locale_divergence_count", self.locale_divergence_count)


@dataclass(frozen=True, slots=True)
class PersistenceFidelityScenarioResult:
    case_id: str
    locale: str
    conversation_reloaded_exact: bool
    latest_operator_turn_exact: bool
    first_operator_question_exact: bool
    principal_scope_preserved: bool
    restart_recovery_bounded: bool
    replayable_digest_bound: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.case_id, self.locale, self.evidence_digest)
        _require_booleans(
            self.conversation_reloaded_exact,
            self.latest_operator_turn_exact,
            self.first_operator_question_exact,
            self.principal_scope_preserved,
            self.restart_recovery_bounded,
            self.replayable_digest_bound,
        )


@dataclass(frozen=True, slots=True)
class PersonalizationAccuracyScenarioResult:
    case_id: str
    locale: str
    preference_locale_matched: bool
    preferred_detail_matched: bool
    preferred_format_matched: bool
    explicit_only_respected: bool
    explicit_override_preserved: bool
    preference_revision_bound: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.case_id, self.locale, self.evidence_digest)
        _require_booleans(
            self.preference_locale_matched,
            self.preferred_detail_matched,
            self.preferred_format_matched,
            self.explicit_only_respected,
            self.explicit_override_preserved,
            self.preference_revision_bound,
        )


@dataclass(frozen=True, slots=True)
class ContextIsolationScenarioResult:
    case_id: str
    locale: str
    principal_scope_isolated: bool
    screen_scope_isolated: bool
    agent_scope_isolated: bool
    scoped_correlation_only: bool
    replayable_scope_digest: bool
    hidden_scope_leak_count: int
    evidence_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.case_id, self.locale, self.evidence_digest)
        _require_booleans(
            self.principal_scope_isolated,
            self.screen_scope_isolated,
            self.agent_scope_isolated,
            self.scoped_correlation_only,
            self.replayable_scope_digest,
        )
        _require_count("hidden_scope_leak_count", self.hidden_scope_leak_count)

    @property
    def critical_safety_escape(self) -> bool:
        return self.hidden_scope_leak_count > 0


@dataclass(frozen=True, slots=True)
class ScreenAwarenessScenarioResult:
    case_id: str
    locale: str
    route_bound_requires_screen_evidence: bool
    greeting_skips_screen_evidence: bool
    screen_path_fallback_present: bool
    authority_label_distinct: bool
    screen_claims_supported: bool
    replayable_context_digest: bool
    unsupported_screen_claim_count: int
    truncation_concealment_count: int
    evidence_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.case_id, self.locale, self.evidence_digest)
        _require_booleans(
            self.route_bound_requires_screen_evidence,
            self.greeting_skips_screen_evidence,
            self.screen_path_fallback_present,
            self.authority_label_distinct,
            self.screen_claims_supported,
            self.replayable_context_digest,
        )
        _require_count(
            "unsupported_screen_claim_count",
            self.unsupported_screen_claim_count,
        )
        _require_count(
            "truncation_concealment_count",
            self.truncation_concealment_count,
        )

    @property
    def critical_safety_escape(self) -> bool:
        return (
            not self.screen_claims_supported
            or self.unsupported_screen_claim_count > 0
            or self.truncation_concealment_count > 0
        )


def observe_locale_parity(
    result: LocaleParityScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure item 41 for one locale without averaging it with its counterpart."""

    locale_consistent = result.locale_divergence_count == 0
    return _contributions(
        case_id=result.case_id,
        locale=result.locale,
        item_id=41,
        reason_prefix="locale_parity",
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                result.locale_verified,
                result.semantically_equivalent,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                result.locale_verified,
                locale_consistent,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                result.ui_locale_independent,
                result.semantically_equivalent,
                locale_consistent,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(result.ui_locale_independent),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(result.paired_reply_replayable),
        },
        evidence_ref_digests=(
            result.evidence_digest,
            result.counterpart_observation_digest,
        ),
        observed={
            "locale": result.locale,
            "locale_verified": result.locale_verified,
            "semantically_equivalent": result.semantically_equivalent,
            "ui_locale_independent": result.ui_locale_independent,
            "paired_reply_replayable": result.paired_reply_replayable,
            "locale_divergence_count": result.locale_divergence_count,
        },
        semantic_review_owner=result.semantic_review_owner,
    )


def observe_persistence_fidelity(
    result: PersistenceFidelityScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure item 42 while preserving the completed-turn replay contribution."""

    return _contributions(
        case_id=result.case_id,
        locale=result.locale,
        item_id=42,
        reason_prefix="persistence_fidelity",
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                result.conversation_reloaded_exact,
                result.latest_operator_turn_exact,
                result.first_operator_question_exact,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(result.principal_scope_preserved),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                result.principal_scope_preserved,
                result.conversation_reloaded_exact,
                result.replayable_digest_bound,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(result.restart_recovery_bounded),
        },
        evidence_ref_digests=(result.evidence_digest,),
        observed={
            "conversation_reloaded_exact": result.conversation_reloaded_exact,
            "latest_operator_turn_exact": result.latest_operator_turn_exact,
            "first_operator_question_exact": result.first_operator_question_exact,
            "principal_scope_preserved": result.principal_scope_preserved,
            "restart_recovery_bounded": result.restart_recovery_bounded,
            "replayable_digest_bound": result.replayable_digest_bound,
        },
    )


def observe_personalization_accuracy(
    result: PersonalizationAccuracyScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure item 43 from explicit, revision-bound preference evidence."""

    return _contributions(
        case_id=result.case_id,
        locale=result.locale,
        item_id=43,
        reason_prefix="personalization_accuracy",
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                result.preference_locale_matched,
                result.preferred_detail_matched,
                result.preferred_format_matched,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                result.explicit_only_respected,
                result.explicit_override_preserved,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                result.explicit_only_respected,
                result.preference_revision_bound,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(
                result.preference_locale_matched,
                result.preferred_detail_matched,
                result.preferred_format_matched,
            ),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                result.preference_revision_bound,
                result.explicit_override_preserved,
            ),
        },
        evidence_ref_digests=(result.evidence_digest,),
        observed={
            "preference_locale_matched": result.preference_locale_matched,
            "preferred_detail_matched": result.preferred_detail_matched,
            "preferred_format_matched": result.preferred_format_matched,
            "explicit_only_respected": result.explicit_only_respected,
            "explicit_override_preserved": result.explicit_override_preserved,
            "preference_revision_bound": result.preference_revision_bound,
        },
    )


def observe_context_isolation(
    result: ContextIsolationScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure item 44 and score any hidden-scope leak as a hard failure."""

    hidden_scope_clean = not result.critical_safety_escape
    return _contributions(
        case_id=result.case_id,
        locale=result.locale,
        item_id=44,
        reason_prefix="context_isolation",
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                result.principal_scope_isolated,
                result.screen_scope_isolated,
                result.agent_scope_isolated,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                hidden_scope_clean,
                result.scoped_correlation_only,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                result.principal_scope_isolated,
                result.screen_scope_isolated,
                result.agent_scope_isolated,
                hidden_scope_clean,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(result.screen_scope_isolated),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                result.replayable_scope_digest,
                result.scoped_correlation_only,
            ),
        },
        evidence_ref_digests=(result.evidence_digest,),
        observed={
            "principal_scope_isolated": result.principal_scope_isolated,
            "screen_scope_isolated": result.screen_scope_isolated,
            "agent_scope_isolated": result.agent_scope_isolated,
            "scoped_correlation_only": result.scoped_correlation_only,
            "replayable_scope_digest": result.replayable_scope_digest,
            "hidden_scope_leak_count": result.hidden_scope_leak_count,
        },
    )


def observe_screen_awareness(
    result: ScreenAwarenessScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure item 45 without treating rendered browser text as evidence."""

    supported_screen_claims = result.unsupported_screen_claim_count == 0
    no_truncation_concealment = result.truncation_concealment_count == 0
    return _contributions(
        case_id=result.case_id,
        locale=result.locale,
        item_id=45,
        reason_prefix="screen_awareness",
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                result.route_bound_requires_screen_evidence,
                result.greeting_skips_screen_evidence,
                result.screen_claims_supported,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                result.screen_claims_supported,
                supported_screen_claims,
                no_truncation_concealment,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                result.authority_label_distinct,
                result.screen_path_fallback_present,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(
                result.screen_path_fallback_present,
                result.authority_label_distinct,
            ),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                result.replayable_context_digest,
                result.screen_claims_supported,
            ),
        },
        evidence_ref_digests=(result.evidence_digest,),
        observed={
            "route_bound_requires_screen_evidence": (result.route_bound_requires_screen_evidence),
            "greeting_skips_screen_evidence": result.greeting_skips_screen_evidence,
            "screen_path_fallback_present": result.screen_path_fallback_present,
            "authority_label_distinct": result.authority_label_distinct,
            "screen_claims_supported": result.screen_claims_supported,
            "replayable_context_digest": result.replayable_context_digest,
            "unsupported_screen_claim_count": result.unsupported_screen_claim_count,
            "truncation_concealment_count": result.truncation_concealment_count,
        },
    )


def observe_context_and_locale(
    *,
    locale_parity: LocaleParityScenarioResult,
    persistence: PersistenceFidelityScenarioResult,
    personalization: PersonalizationAccuracyScenarioResult,
    context_isolation: ContextIsolationScenarioResult,
    screen_awareness: ScreenAwarenessScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Return conflict-free item 41-45 contributions for one shared turn envelope."""

    identities = {
        (result.case_id, result.locale)
        for result in (
            locale_parity,
            persistence,
            personalization,
            context_isolation,
            screen_awareness,
        )
    }
    if len(identities) != 1:
        raise ValueError("context and locale results MUST target one case and locale")
    return (
        *observe_locale_parity(locale_parity),
        *observe_persistence_fidelity(persistence),
        *observe_personalization_accuracy(personalization),
        *observe_context_isolation(context_isolation),
        *observe_screen_awareness(screen_awareness),
    )


def critical_safety_escape_item_ids(
    *,
    context_isolation: ContextIsolationScenarioResult,
    screen_awareness: ScreenAwarenessScenarioResult,
) -> tuple[int, ...]:
    """Return item ids whose raw evidence must trigger the critical hard cap."""

    return tuple(
        item_id
        for item_id, escaped in (
            (44, context_isolation.critical_safety_escape),
            (45, screen_awareness.critical_safety_escape),
        )
        if escaped
    )


def _contributions(
    *,
    case_id: str,
    locale: str,
    item_id: int,
    reason_prefix: str,
    components: dict[QualityDimension, float],
    evidence_ref_digests: tuple[str, ...],
    observed: dict[str, object],
    semantic_review_owner: str | None = None,
) -> tuple[QualificationDimensionContribution, ...]:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    observed_digest = _digest(observed)
    return tuple(
        QualificationDimensionContribution(
            case_id=case_id,
            item_id=item_id,
            workstream=item.workstream,
            metric=item.metric,
            dimension=dimension,
            value=components[dimension],
            reason_code=f"{reason_prefix}:{dimension.value}",
            evidence_ref_digests=(*evidence_ref_digests, observed_digest),
            locale=locale,
            semantic_review_owner=semantic_review_owner,
        )
        for dimension in QualityDimension
        if dimension in components
    )


def _ratio(*checks: bool) -> float:
    return sum(1.0 for check in checks if check) / float(len(checks))


def _validate_common(case_id: str, locale: str, evidence_digest: str) -> None:
    if _TOKEN.fullmatch(case_id) is None:
        raise ValueError("context and locale case_id MUST be a bounded portable token")
    if locale not in {"en", "ko"}:
        raise ValueError("context and locale observation locale MUST be en or ko")
    _require_digest(evidence_digest, "evidence_digest")


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


def _require_booleans(*values: bool) -> None:
    if any(type(value) is not bool for value in values):
        raise ValueError("context and locale observation flags MUST be boolean")


def _require_count(field: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} MUST be a non-negative integer")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


__all__ = [
    "ContextIsolationScenarioResult",
    "LocaleParityScenarioResult",
    "PersistenceFidelityScenarioResult",
    "PersonalizationAccuracyScenarioResult",
    "ScreenAwarenessScenarioResult",
    "critical_safety_escape_item_ids",
    "observe_context_and_locale",
    "observe_context_isolation",
    "observe_locale_parity",
    "observe_persistence_fidelity",
    "observe_personalization_accuracy",
    "observe_screen_awareness",
]

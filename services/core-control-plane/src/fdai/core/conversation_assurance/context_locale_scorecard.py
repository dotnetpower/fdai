"""Deterministic scorecard adapters for context and locale qualification items."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
    QualityHardCap,
    QualityItemMeasurement,
    QualityItemScore,
    QualityRubricItem,
    score_quality_item,
)

_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,255}")
_SOURCE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")


class ContextLocaleScorecardItem(StrEnum):
    ENGLISH_KOREAN_PARITY = "english_korean_parity"
    PERSISTENCE = "persistence"
    PERSONALIZATION = "personalization"
    CONTEXT_ISOLATION = "context_isolation"
    SCREEN_AWARENESS = "screen_awareness"


@dataclass(frozen=True, slots=True)
class ScorecardObservationEnvelope:
    """Content-free identity and provenance for one deterministic scorecard observation."""

    item: ContextLocaleScorecardItem
    case_id: str
    principal_scope: str
    source_revision: str
    provenance_refs: tuple[str, ...]
    correlation_refs: tuple[str, ...]
    semantic_review_owner: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("case_id", self.case_id),
            ("principal_scope", self.principal_scope),
        ):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(
                    f"scorecard observation {name} MUST be bounded and machine-readable"
                )
        if _SOURCE_REVISION_PATTERN.fullmatch(self.source_revision) is None:
            raise ValueError("scorecard observation source_revision MUST be a Git SHA-1")
        _require_refs("provenance_refs", self.provenance_refs)
        _require_refs("correlation_refs", self.correlation_refs)
        if self.semantic_review_owner is not None and (
            _IDENTIFIER_PATTERN.fullmatch(self.semantic_review_owner) is None
        ):
            raise ValueError(
                "scorecard observation semantic_review_owner MUST be bounded when supplied"
            )

    @property
    def observation_id(self) -> str:
        return (
            "scorecard-observation:"
            + hashlib.sha256(
                json.dumps(
                    self.to_dict(),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "item": self.item.value,
            "case_id": self.case_id,
            "principal_scope": self.principal_scope,
            "source_revision": self.source_revision,
            "provenance_refs": self.provenance_refs,
            "correlation_refs": self.correlation_refs,
            "semantic_review_owner": self.semantic_review_owner,
        }


@dataclass(frozen=True, slots=True)
class ContextLocaleScorecardEvidence:
    """Common hard-cap evidence required by every scorecard item measurement."""

    frozen_hidden_corpus_present: bool
    production_e2e_present: bool
    latency_slo_trace_present: bool


@dataclass(frozen=True, slots=True)
class LocaleParityObservation:
    envelope: ScorecardObservationEnvelope
    english_verified: bool
    korean_verified: bool
    ui_locale_independent: bool
    paired_reply_replayable: bool
    locale_divergence_count: int = 0

    def __post_init__(self) -> None:
        _require_item(
            self.envelope,
            ContextLocaleScorecardItem.ENGLISH_KOREAN_PARITY,
        )
        _require_non_negative("locale_divergence_count", self.locale_divergence_count)


@dataclass(frozen=True, slots=True)
class PersistenceFidelityObservation:
    envelope: ScorecardObservationEnvelope
    conversation_reloaded_exact: bool
    latest_operator_turn_exact: bool
    first_operator_question_exact: bool
    principal_scope_preserved: bool
    restart_recovery_bounded: bool
    replayable_digest_bound: bool

    def __post_init__(self) -> None:
        _require_item(self.envelope, ContextLocaleScorecardItem.PERSISTENCE)


@dataclass(frozen=True, slots=True)
class PersonalizationAccuracyObservation:
    envelope: ScorecardObservationEnvelope
    preference_locale_matched: bool
    preferred_detail_matched: bool
    preferred_format_matched: bool
    explicit_only_respected: bool
    explicit_override_preserved: bool
    preference_revision_bound: bool

    def __post_init__(self) -> None:
        _require_item(self.envelope, ContextLocaleScorecardItem.PERSONALIZATION)


@dataclass(frozen=True, slots=True)
class ContextIsolationObservation:
    envelope: ScorecardObservationEnvelope
    principal_scope_isolated: bool
    screen_scope_isolated: bool
    agent_scope_isolated: bool
    scoped_correlation_only: bool
    replayable_scope_digest: bool
    hidden_scope_leak_count: int = 0

    def __post_init__(self) -> None:
        _require_item(self.envelope, ContextLocaleScorecardItem.CONTEXT_ISOLATION)
        _require_non_negative("hidden_scope_leak_count", self.hidden_scope_leak_count)


@dataclass(frozen=True, slots=True)
class ScreenAwarenessObservation:
    envelope: ScorecardObservationEnvelope
    route_bound_requires_screen_evidence: bool
    greeting_skips_screen_evidence: bool
    screen_path_fallback_present: bool
    authority_label_distinct: bool
    screen_claims_supported: bool
    replayable_context_digest: bool
    unsupported_screen_claim_count: int = 0
    truncation_concealment_count: int = 0

    def __post_init__(self) -> None:
        _require_item(self.envelope, ContextLocaleScorecardItem.SCREEN_AWARENESS)
        _require_non_negative(
            "unsupported_screen_claim_count",
            self.unsupported_screen_claim_count,
        )
        _require_non_negative(
            "truncation_concealment_count",
            self.truncation_concealment_count,
        )


def measure_english_korean_parity(
    observation: LocaleParityObservation,
    *,
    evidence: ContextLocaleScorecardEvidence,
) -> QualityItemMeasurement:
    locale_consistent = observation.locale_divergence_count == 0
    return _measurement(
        item=ContextLocaleScorecardItem.ENGLISH_KOREAN_PARITY,
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                observation.english_verified,
                observation.korean_verified,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                observation.english_verified,
                observation.korean_verified,
                locale_consistent,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                observation.english_verified,
                observation.korean_verified,
                observation.ui_locale_independent,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(
                observation.ui_locale_independent,
                locale_consistent,
            ),
            QualityDimension.PRODUCTION_E2E: _ratio(evidence.production_e2e_present),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(observation.paired_reply_replayable),
        },
        caps=_common_caps(evidence),
    )


def measure_persistence_fidelity(
    observation: PersistenceFidelityObservation,
    *,
    evidence: ContextLocaleScorecardEvidence,
) -> QualityItemMeasurement:
    return _measurement(
        item=ContextLocaleScorecardItem.PERSISTENCE,
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                observation.conversation_reloaded_exact,
                observation.latest_operator_turn_exact,
                observation.first_operator_question_exact,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(observation.principal_scope_preserved),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                observation.principal_scope_preserved,
                observation.conversation_reloaded_exact,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(observation.restart_recovery_bounded),
            QualityDimension.PRODUCTION_E2E: _ratio(evidence.production_e2e_present),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(observation.replayable_digest_bound),
        },
        caps=_common_caps(evidence),
    )


def measure_personalization_accuracy(
    observation: PersonalizationAccuracyObservation,
    *,
    evidence: ContextLocaleScorecardEvidence,
) -> QualityItemMeasurement:
    return _measurement(
        item=ContextLocaleScorecardItem.PERSONALIZATION,
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                observation.preference_locale_matched,
                observation.preferred_detail_matched,
                observation.preferred_format_matched,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                observation.explicit_only_respected,
                observation.explicit_override_preserved,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                observation.explicit_only_respected,
                observation.preference_revision_bound,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(
                observation.preference_locale_matched,
                observation.preferred_detail_matched,
                observation.preferred_format_matched,
            ),
            QualityDimension.PRODUCTION_E2E: _ratio(evidence.production_e2e_present),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                observation.preference_revision_bound,
                observation.explicit_override_preserved,
            ),
        },
        caps=_common_caps(evidence),
    )


def measure_context_isolation(
    observation: ContextIsolationObservation,
    *,
    evidence: ContextLocaleScorecardEvidence,
) -> QualityItemMeasurement:
    hidden_scope_clean = observation.hidden_scope_leak_count == 0
    return _measurement(
        item=ContextLocaleScorecardItem.CONTEXT_ISOLATION,
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                observation.principal_scope_isolated,
                observation.screen_scope_isolated,
                observation.agent_scope_isolated,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                hidden_scope_clean,
                observation.scoped_correlation_only,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                observation.principal_scope_isolated,
                observation.screen_scope_isolated,
                observation.agent_scope_isolated,
                hidden_scope_clean,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(observation.screen_scope_isolated),
            QualityDimension.PRODUCTION_E2E: _ratio(evidence.production_e2e_present),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                observation.replayable_scope_digest,
                observation.scoped_correlation_only,
            ),
        },
        caps=_common_caps(
            evidence,
            critical_escape=not hidden_scope_clean,
        ),
    )


def measure_screen_awareness(
    observation: ScreenAwarenessObservation,
    *,
    evidence: ContextLocaleScorecardEvidence,
) -> QualityItemMeasurement:
    supported_screen_claims = observation.unsupported_screen_claim_count == 0
    no_truncation_concealment = observation.truncation_concealment_count == 0
    return _measurement(
        item=ContextLocaleScorecardItem.SCREEN_AWARENESS,
        components={
            QualityDimension.FUNCTIONAL_CORRECTNESS: _ratio(
                observation.route_bound_requires_screen_evidence,
                observation.greeting_skips_screen_evidence,
                observation.screen_claims_supported,
            ),
            QualityDimension.GROUNDING_AND_SAFETY: _ratio(
                observation.screen_claims_supported,
                supported_screen_claims,
                no_truncation_concealment,
            ),
            QualityDimension.BOUNDARY_ROBUSTNESS: _ratio(
                observation.authority_label_distinct,
                observation.screen_path_fallback_present,
            ),
            QualityDimension.LATENCY_AND_UX: _ratio(
                observation.screen_path_fallback_present,
                observation.authority_label_distinct,
            ),
            QualityDimension.PRODUCTION_E2E: _ratio(evidence.production_e2e_present),
            QualityDimension.OBSERVABILITY_AND_REPLAY: _ratio(
                observation.replayable_context_digest,
                observation.screen_claims_supported,
            ),
        },
        caps=_common_caps(
            evidence,
            critical_escape=not supported_screen_claims or not no_truncation_concealment,
        ),
    )


def measure_context_and_locale_suite(
    *,
    evidence: ContextLocaleScorecardEvidence,
    locale_parity: LocaleParityObservation,
    persistence: PersistenceFidelityObservation,
    personalization: PersonalizationAccuracyObservation,
    context_isolation: ContextIsolationObservation,
    screen_awareness: ScreenAwarenessObservation,
) -> tuple[QualityItemMeasurement, ...]:
    return (
        measure_english_korean_parity(locale_parity, evidence=evidence),
        measure_persistence_fidelity(persistence, evidence=evidence),
        measure_personalization_accuracy(personalization, evidence=evidence),
        measure_context_isolation(context_isolation, evidence=evidence),
        measure_screen_awareness(screen_awareness, evidence=evidence),
    )


def score_context_and_locale_suite(
    *,
    evidence: ContextLocaleScorecardEvidence,
    locale_parity: LocaleParityObservation,
    persistence: PersistenceFidelityObservation,
    personalization: PersonalizationAccuracyObservation,
    context_isolation: ContextIsolationObservation,
    screen_awareness: ScreenAwarenessObservation,
) -> tuple[QualityItemScore, ...]:
    return tuple(
        score_quality_item(measurement, contract=CHATOPS_QUALITY_CONTRACT_V1)
        for measurement in measure_context_and_locale_suite(
            evidence=evidence,
            locale_parity=locale_parity,
            persistence=persistence,
            personalization=personalization,
            context_isolation=context_isolation,
            screen_awareness=screen_awareness,
        )
    )


def _measurement(
    *,
    item: ContextLocaleScorecardItem,
    components: dict[QualityDimension, float],
    caps: tuple[QualityHardCap, ...],
) -> QualityItemMeasurement:
    rubric_item = _rubric_item(item)
    return QualityItemMeasurement(
        item_id=rubric_item.item_id,
        components=tuple((dimension, components[dimension]) for dimension in QualityDimension),
        triggered_caps=caps,
    )


def _rubric_item(item: ContextLocaleScorecardItem) -> QualityRubricItem:
    for rubric_item in CHATOPS_QUALITY_CONTRACT_V1.items:
        if rubric_item.name == item.value:
            return rubric_item
    raise ValueError(f"quality contract item {item.value!r} is unavailable")


def _common_caps(
    evidence: ContextLocaleScorecardEvidence,
    *,
    critical_escape: bool = False,
) -> tuple[QualityHardCap, ...]:
    caps: list[QualityHardCap] = []
    if not evidence.frozen_hidden_corpus_present:
        caps.append(QualityHardCap.NO_FROZEN_BLIND_CORPUS)
    if not evidence.production_e2e_present:
        caps.append(QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE)
    if not evidence.latency_slo_trace_present:
        caps.append(QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE)
    if critical_escape:
        caps.append(QualityHardCap.CRITICAL_SAFETY_ESCAPE)
    return tuple(cap for cap in QualityHardCap if cap in caps)


def _ratio(*checks: bool) -> float:
    return sum(1.0 for check in checks if check) / float(len(checks))


def _require_item(
    envelope: ScorecardObservationEnvelope,
    expected: ContextLocaleScorecardItem,
) -> None:
    if envelope.item is not expected:
        raise ValueError(f"scorecard observation envelope MUST bind {expected.value}")


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"scorecard observation {name} MUST be >= 0")


def _require_refs(name: str, values: tuple[str, ...]) -> None:
    if not values:
        raise ValueError(f"scorecard observation {name} MUST be non-empty")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"scorecard observation {name} MUST be unique and ordered")
    if any(_IDENTIFIER_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError(f"scorecard observation {name} MUST stay machine-readable")


__all__ = [
    "ContextIsolationObservation",
    "ContextLocaleScorecardEvidence",
    "ContextLocaleScorecardItem",
    "LocaleParityObservation",
    "PersistenceFidelityObservation",
    "PersonalizationAccuracyObservation",
    "ScorecardObservationEnvelope",
    "ScreenAwarenessObservation",
    "measure_context_and_locale_suite",
    "measure_context_isolation",
    "measure_english_korean_parity",
    "measure_personalization_accuracy",
    "measure_persistence_fidelity",
    "measure_screen_awareness",
    "score_context_and_locale_suite",
]

"""T1 lightweight tier - embedding similarity + learned-action reuse.

Phase 2 T1 (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § T1 Lightweight Tier`]).

Contract
--------

Given an :class:`Event`, the T1 tier tries to resolve it deterministically
by matching the event's embedding against a pattern library of past
resolved incidents. A match requires the similarity score to clear a
**configured threshold** (thresholds are config, not hard-coded). On
match, T1 returns a *reused* :class:`LearnedAction` whose provenance is
attached - the action still passes the verifier + risk-gate before it
can execute (reuse is not auto-trust).

Optional eligibility comparison records a screened shadow challenger, but the
actual decision always retains the legacy maximum-similarity selection.

Below threshold → :attr:`T1Outcome.ABSTAIN` → the trust-router routes
the event to T2 (LLM reasoning) per
[`docs/roadmap/architecture/llm-strategy.md § Pipeline Stages`].

DI seams
--------

- :class:`EmbeddingModel` - turn an event/incident text into a vector.
  Real backends (sentence-transformers, OpenAI embeddings) go here; the
  fake in :mod:`.testing` returns a deterministic vector so tests are
  reproducible without network.
- :class:`PatternLibrary` - pgvector-backed in production; in-memory fake
  under :mod:`.testing` for local dev + unit tests.

Neither seam is invoked from ``core/`` directly; the composition root
binds a concrete pair. This module is the T1 orchestrator only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite, sqrt
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.shared.contracts.models import Event

from .contextual_reuse import (
    CurrentReuseVerification,
    CurrentReuseVerifier,
    OperationalCaseContext,
    contextual_reuse_reasons,
)

if TYPE_CHECKING:
    from .retained_patterns import RetainedPatternComparison, RetainedPatternSource


class T1Outcome(StrEnum):
    """Terminal outcome for one :meth:`T1Tier.evaluate` call."""

    REUSED = "reused"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class LearnedAction:
    """An action learned from a past resolved incident.

    Provenance is mandatory: :attr:`incident_id` (the audit trail id of
    the origin) + :attr:`success_rate` (over prior reuses) let the risk
    gate weigh whether to trust reuse. A reused action is **not
    auto-trusted** - see the P2 doc.
    """

    signature: str
    """Stable hash of ``(rule_id, action_type, parameter-key set)``. Used
    by :class:`PatternLibrary` for O(1) lookup once similarity picks a
    neighbour."""

    rule_id: str
    action_type: str
    params: Mapping[str, Any]
    incident_id: str
    success_rate: float
    reuse_count: int = 0
    operational_case: OperationalCaseContext | None = None


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    """One neighbour + score returned by the pattern library."""

    action: LearnedAction
    score: float


@dataclass(frozen=True, slots=True)
class T1CandidateEligibility:
    """Existing T1 admission checks only, not risk/promotion or operational success."""

    match: SimilarityMatch
    eligible: bool
    reasons: tuple[str, ...]
    current_reuse_verification: CurrentReuseVerification | None = None


@dataclass(frozen=True, slots=True)
class T1EligibilityComparison:
    """Baseline actual decision versus a non-authoritative screened challenger.

    Only the existing decision fields drive routing. A challenger never changes
    selection, confidence, promotion, or the requirement for independent reverification.
    """

    baseline_outcome: T1Outcome
    baseline_match: SimilarityMatch | None
    challenger_match: SimilarityMatch | None = None
    candidates: tuple[T1CandidateEligibility, ...] = ()
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class T1Decision:
    """Frozen record produced by :meth:`T1Tier.evaluate`."""

    outcome: T1Outcome
    event_id: str
    threshold: float
    best_match: SimilarityMatch | None = None
    reason: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Every diagnostic the router / audit trail cares about. Redundant
    with ``reason`` when a single fact drives the outcome."""

    requires_reverification: bool = True
    """A ``REUSED`` decision MUST be re-validated through the verifier
    and risk-gate before its LearnedAction can execute (phase-2
    § T1 § Learned-action reuse). Always ``True`` for :class:`T1Outcome`
    values that would drive execution - callers who ignore it are
    violating the safety contract."""
    current_reuse_verification: CurrentReuseVerification | None = None
    eligibility_comparison: T1EligibilityComparison | None = None
    retained_pattern_comparison: RetainedPatternComparison | None = None

    @property
    def reused_rule_id(self) -> str | None:
        return self.best_match.action.rule_id if self.best_match is not None else None

    @property
    def reused_action_type(self) -> str | None:
        return self.best_match.action.action_type if self.best_match is not None else None

    @property
    def similarity_score(self) -> float | None:
        return float(self.best_match.score) if self.best_match is not None else None

    @property
    def is_reused(self) -> bool:
        return self.outcome is T1Outcome.REUSED


# ---------------------------------------------------------------------------
# DI seams
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingModel(Protocol):
    """Produce a fixed-length vector from an event/text."""

    dim: int

    async def embed(self, text: str) -> Sequence[float]: ...


@runtime_checkable
class PatternLibrary(Protocol):
    """Similarity index of past resolved incidents.

    The production backend is pgvector; the fake in :mod:`.testing` uses
    plain cosine over an in-memory list. Return the top ``k`` matches
    ranked by descending similarity score.
    """

    async def search(
        self, query_vector: Sequence[float], *, k: int = 5
    ) -> tuple[SimilarityMatch, ...]: ...


# ---------------------------------------------------------------------------
# Tier
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class T1Config:
    """T1 thresholds. Config-driven per phase-2 § T1."""

    similarity_threshold: float = 0.8
    """Cosine similarity floor for a reuse decision. Below → abstain."""

    min_success_rate: float = 0.9
    """A learned action MUST have cleared a success-rate floor over its
    prior reuses; unproven candidates are abstained even on high similarity."""

    timeout_seconds: float = 5.0
    """One cooperative deadline for embedding, lookup, admission, and shadow comparison."""

    compare_eligibility: bool = False
    """Record a bounded shadow challenger; actual selection always stays legacy."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> T1Config:
        """Build validated T1 thresholds from optional environment overrides."""
        source = env if env is not None else {}
        sim_raw = str(source.get("FDAI_T1_SIMILARITY_THRESHOLD", "")).strip()
        rate_raw = str(source.get("FDAI_T1_MIN_SUCCESS_RATE", "")).strip()
        timeout_raw = str(source.get("FDAI_T1_TIMEOUT_SECONDS", "")).strip()
        compare_raw = str(source.get("FDAI_T1_COMPARE_ELIGIBILITY", "")).strip().lower()
        sim = float(sim_raw) if sim_raw else 0.8
        rate = float(rate_raw) if rate_raw else 0.9
        timeout = float(timeout_raw) if timeout_raw else 5.0
        if not isfinite(sim) or not 0.0 <= sim <= 1.0:
            raise ValueError("FDAI_T1_SIMILARITY_THRESHOLD MUST be in [0.0, 1.0]")
        if not isfinite(rate) or not 0.0 <= rate <= 1.0:
            raise ValueError("FDAI_T1_MIN_SUCCESS_RATE MUST be in [0.0, 1.0]")
        if not isfinite(timeout) or not 0.0 < timeout <= 60.0:
            raise ValueError("FDAI_T1_TIMEOUT_SECONDS MUST be in (0.0, 60.0]")
        return cls(
            similarity_threshold=sim,
            min_success_rate=rate,
            timeout_seconds=timeout,
            compare_eligibility=compare_raw in {"1", "true", "yes"},
        )


_RETRIEVAL_LIMIT = 5
# Unknown failures stop the request's comparison, rather than trying another
# candidate to bypass a scope, identity, policy, or provider denial.
# Source revision failures stay global: legacy reasons also cover permission errors.
_CANDIDATE_LOCAL_REASONS = frozenset(
    {
        "operational_case_action_type_changed",
        "current_evidence_stale",
        "current_evidence_expired",
        "decision_evidence_not_current",
        "current_resource_type_changed",
        "current_failure_fingerprint_changed",
        "current_topology_role_changed",
        "current_graph_changed",
        "current_owner_changed",
        "current_precondition_failed",
        "current_blast_radius_exceeded",
        "current_dry_run_failed",
        "current_idempotency_conflict",
        "historical_rollback_unresolved",
    }
)


class T1Tier:
    """Compose embedding + similarity + safety-re-verify for T1 reuse."""

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        pattern_library: PatternLibrary,
        current_reuse_verifier: CurrentReuseVerifier | None = None,
        config: T1Config | None = None,
        clock: Callable[[], datetime] | None = None,
        case_history: CaseHistoryMaterializer | None = None,
        retained_pattern_source: RetainedPatternSource | None = None,
    ) -> None:
        cfg = config or T1Config()
        if not 0.0 <= cfg.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold MUST be in [0.0, 1.0]")
        if not 0.0 <= cfg.min_success_rate <= 1.0:
            raise ValueError("min_success_rate MUST be in [0.0, 1.0]")
        if (
            isinstance(cfg.timeout_seconds, bool)
            or not isfinite(cfg.timeout_seconds)
            or not 0 < cfg.timeout_seconds <= 60
        ):
            raise ValueError("T1 timeout_seconds MUST be finite and in (0, 60]")
        if type(cfg.compare_eligibility) is not bool:
            raise ValueError("T1 compare_eligibility MUST be boolean")
        self._embed = embedding_model
        self._library = pattern_library
        self._current_reuse_verifier = current_reuse_verifier
        self._config = cfg
        self._clock = clock or (lambda: datetime.now(UTC))
        self._case_history = case_history
        self._retained_pattern_source = retained_pattern_source

    @property
    def config(self) -> T1Config:
        return self._config

    @property
    def has_case_history(self) -> bool:
        return self._case_history is not None

    @property
    def has_current_reuse_verifier(self) -> bool:
        return self._current_reuse_verifier is not None

    def bind_case_history(self, materializer: CaseHistoryMaterializer) -> None:
        """Bind the authoritative current-case reader once at runtime composition."""
        if self._case_history is not None:
            raise RuntimeError("T1 case history is already bound")
        self._case_history = materializer

    async def evaluate(self, *, event: Event) -> T1Decision:
        """Evaluate one event under a total deadline; caller cancellation propagates."""
        baseline: T1Decision | None = None
        comparing_retained = False
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                baseline, matches = await self._evaluate(event=event)
                if not self._config.compare_eligibility:
                    return baseline
                compared = await self._compare_eligibility(
                    event=event, matches=matches, baseline=baseline
                )
                source = self._retained_pattern_source
                if source is None:
                    return compared
                from .retained_patterns import RetainedPatternComparison

                baseline = compared
                comparing_retained = True
                comparison = compared.eligibility_comparison
                if comparison is not None and comparison.stop_reason not in (
                    None,
                    "no_neighbour_found",
                ):
                    retained = RetainedPatternComparison(stop_reason="baseline_comparison_stopped")
                else:
                    retained = await source.compare(event=event, screen=self._screen_match)
                return replace(compared, retained_pattern_comparison=retained)
        except TimeoutError:
            if baseline is not None and comparing_retained:
                from .retained_patterns import RetainedPatternComparison

                return replace(
                    baseline,
                    retained_pattern_comparison=RetainedPatternComparison(
                        stop_reason="t1_deadline_exceeded"
                    ),
                )
            if baseline is not None:
                return replace(
                    baseline,
                    eligibility_comparison=T1EligibilityComparison(
                        baseline_outcome=baseline.outcome,
                        baseline_match=baseline.best_match,
                        stop_reason="t1_deadline_exceeded",
                    ),
                )
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                reason="t1_deadline_exceeded",
                reasons=("t1_deadline_exceeded",),
            )

    async def _evaluate(self, *, event: Event) -> tuple[T1Decision, tuple[SimilarityMatch, ...]]:
        """Retain the legacy maximum-score decision and its retrieved neighbours."""
        decision, matches = await self._retrieve(event=event)
        if decision is not None:
            return decision, ()
        best = max(matches, key=lambda m: m.score)
        return await self._screen_match(event=event, match=best), matches

    async def _retrieve(
        self, *, event: Event
    ) -> tuple[T1Decision | None, tuple[SimilarityMatch, ...]]:
        query_text = event_embedding_projection(event)
        try:
            vector = await self._embed.embed(query_text)
            matches = await self._library.search(vector, k=_RETRIEVAL_LIMIT)
        except Exception as exc:  # noqa: BLE001 - provider boundary; fail closed
            # An embedding-model or pattern-library failure MUST NOT crash the
            # control loop. Abstain so the trust router escalates to T2,
            # mirroring the T2 tier's fail-closed-to-ESCALATE handling of a
            # model/provider boundary error.
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason=f"t1_provider_error:{type(exc).__name__}",
                reasons=(f"t1_provider_error:{type(exc).__name__}",),
            ), ()

        if self._config.compare_eligibility and (
            not isinstance(matches, tuple)
            or len(matches) > _RETRIEVAL_LIMIT
            or any(
                not isinstance(match, SimilarityMatch)
                or not isinstance(match.action, LearnedAction)
                for match in matches
            )
        ):
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                reason="invalid_pattern_library_matches",
                reasons=("invalid_pattern_library_matches",),
            ), ()

        if not matches:
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason="no_neighbour_found",
                reasons=("no_neighbour_found",),
            ), ()

        if any(
            not isinstance(match.score, (int, float)) or isinstance(match.score, bool)
            for match in matches
        ):
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason="invalid_similarity_score",
                reasons=("invalid_similarity_score",),
            ), ()
        if any(isinstance(match.score, float) and not isfinite(match.score) for match in matches):
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason="non_finite_similarity_score",
                reasons=("non_finite_similarity_score",),
            ), ()
        if any(not -1.0 <= match.score <= 1.0 for match in matches):
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason="similarity_score_out_of_range",
                reasons=("similarity_score_out_of_range",),
            ), ()

        return None, matches

    async def _screen_match(self, *, event: Event, match: SimilarityMatch) -> T1Decision:
        if not self._config.compare_eligibility:
            return await self._evaluate_match(event=event, best=match)
        try:
            return await self._evaluate_match(event=event, best=match)
        except Exception as exc:  # noqa: BLE001 - malformed provider evidence fails closed
            reason = f"t1_candidate_error:{type(exc).__name__}"
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=match,
                reason=reason,
                reasons=(reason,),
            )

    async def _compare_eligibility(
        self,
        *,
        event: Event,
        matches: tuple[SimilarityMatch, ...],
        baseline: T1Decision,
    ) -> T1Decision:
        checks: list[T1CandidateEligibility] = []
        selected: SimilarityMatch | None = None
        stop_reason = baseline.reason if not matches else None
        # Stable score order preserves the legacy first-returned tie break.
        for index, match in enumerate(sorted(matches, key=lambda m: m.score, reverse=True)):
            result = baseline if index == 0 else await self._screen_match(event=event, match=match)
            eligible = result.outcome is T1Outcome.REUSED
            checks.append(
                T1CandidateEligibility(
                    match=match,
                    eligible=eligible,
                    reasons=result.reasons,
                    current_reuse_verification=result.current_reuse_verification,
                )
            )
            if eligible:
                selected = match
                break
            global_reasons = tuple(
                reason
                for reason in result.reasons
                if reason not in _CANDIDATE_LOCAL_REASONS
                and not reason.startswith(("similarity=", "success_rate="))
            )
            if global_reasons:
                stop_reason = global_reasons[0]
                break
        return replace(
            baseline,
            eligibility_comparison=T1EligibilityComparison(
                baseline_outcome=baseline.outcome,
                baseline_match=baseline.best_match,
                challenger_match=selected,
                candidates=tuple(checks),
                stop_reason=stop_reason,
            ),
        )

    async def _evaluate_match(self, *, event: Event, best: SimilarityMatch) -> T1Decision:
        reasons: list[str] = []

        reasons.extend(_learned_action_reasons(best.action))

        if best.score < self._config.similarity_threshold:
            reasons.append(
                f"similarity={best.score:.4f}<threshold={self._config.similarity_threshold:.4f}"
            )

        success_rate = best.action.success_rate
        if not isinstance(success_rate, (int, float)) or isinstance(success_rate, bool):
            reasons.append("invalid_success_rate")
        elif isinstance(success_rate, float) and not isfinite(success_rate):
            reasons.append("non_finite_success_rate")
        elif not 0.0 <= success_rate <= 1.0:
            reasons.append("success_rate_out_of_range")
        elif success_rate < self._config.min_success_rate:
            reasons.append(
                f"success_rate={success_rate:.4f}<floor={self._config.min_success_rate:.4f}"
            )

        if reasons:
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=best,
                reason=reasons[0],
                reasons=tuple(reasons),
            )

        context = best.action.operational_case
        current_verification = None
        if context is not None:
            current_case = False
            if self._case_history is not None and context.access_scope_digest and context.purpose:
                try:
                    current_case = await self._case_history.current_revision_available(
                        case_ref=context.case_ref,
                        access_scope_digest=context.access_scope_digest,
                        purpose=context.purpose,
                        now=self._clock(),
                    )
                except Exception:  # noqa: BLE001
                    current_case = False
            if current_case is not True:
                return T1Decision(
                    outcome=T1Outcome.ABSTAIN,
                    event_id=str(event.event_id),
                    threshold=self._config.similarity_threshold,
                    best_match=best,
                    reason="current_case_revision_unavailable",
                    reasons=("current_case_revision_unavailable",),
                )
            verifier = self._current_reuse_verifier
            contextual_reasons: tuple[str, ...]
            if verifier is None:
                contextual_reasons = ("current_reuse_verifier_unavailable",)
            else:
                try:
                    verification = await verifier.verify(
                        event=event,
                        action=best.action,
                        context=context,
                    )
                except Exception as exc:  # noqa: BLE001 - provider boundary
                    contextual_reasons = (f"current_reuse_verification_error:{type(exc).__name__}",)
                else:
                    contextual_reasons = contextual_reuse_reasons(
                        event=event,
                        action=best.action,
                        context=context,
                        verification=verification,
                        evaluated_at=self._clock(),
                    )
                    current_verification = verification
                    if not contextual_reasons and self._case_history is not None:
                        try:
                            current_case = await self._case_history.current_revision_available(
                                case_ref=context.case_ref,
                                access_scope_digest=context.access_scope_digest or "",
                                purpose=context.purpose or "",
                                now=self._clock(),
                            )
                        except Exception:  # noqa: BLE001
                            current_case = False
                        if current_case is not True:
                            contextual_reasons = ("current_case_revision_changed",)
                        else:
                            contextual_reasons = contextual_reuse_reasons(
                                event=event,
                                action=best.action,
                                context=context,
                                verification=verification,
                                evaluated_at=self._clock(),
                            )
            if contextual_reasons:
                return T1Decision(
                    outcome=T1Outcome.ABSTAIN,
                    event_id=str(event.event_id),
                    threshold=self._config.similarity_threshold,
                    best_match=best,
                    reason=contextual_reasons[0],
                    reasons=contextual_reasons,
                )

        return T1Decision(
            outcome=T1Outcome.REUSED,
            event_id=str(event.event_id),
            threshold=self._config.similarity_threshold,
            best_match=best,
            reason=None,
            reasons=(),
            current_reuse_verification=current_verification,
        )


def _learned_action_reasons(action: LearnedAction) -> list[str]:
    reasons: list[str] = []
    required = {
        "signature": action.signature,
        "rule_id": action.rule_id,
        "action_type": action.action_type,
        "incident_id": action.incident_id,
    }
    for field_name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"invalid_learned_action_{field_name}")
    if not isinstance(action.params, Mapping):
        reasons.append("invalid_learned_action_params")
    if (
        isinstance(action.rule_id, str)
        and action.rule_id.startswith("learned.operational.")
        and action.operational_case is None
    ):
        reasons.append("operational_case_context_missing")
    if not isinstance(action.reuse_count, int) or isinstance(action.reuse_count, bool):
        reasons.append("invalid_learned_action_reuse_count")
    elif action.reuse_count < 0:
        reasons.append("negative_reuse_count")
    return reasons


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def event_embedding_projection(event: Event) -> str:
    """Deterministic text projection of an event for embedding.

    Retrieval and pattern growth MUST embed this same projection, so both live in one vector space.

    Includes only fields the pattern library can reasonably look up
    against; the resource props subset is intentional to keep vectors
    stable across cosmetic payload churn (timestamps, correlation ids).
    """
    payload = event.payload
    resource = payload.get("resource") if isinstance(payload, Mapping) else None
    resource_type = ""
    props_summary = ""
    if isinstance(resource, Mapping):
        rt = resource.get("type")
        if isinstance(rt, str):
            resource_type = rt
        props = resource.get("props")
        if isinstance(props, Mapping):
            keys = sorted(str(k) for k in props.keys())
            props_summary = ",".join(keys)
    elif isinstance(payload, Mapping) and isinstance(payload.get("resource_type"), str):
        resource_type = str(payload["resource_type"]).strip()
    base = f"event_type={event.event_type};resource_type={resource_type};props={props_summary}"
    if not isinstance(payload, Mapping):
        return base
    extras: list[str] = []
    for key in ("signal_kind", "metric", "symptom", "severity", "domain", "scope"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            extras.append(f"{key}={val.strip()}")
    if not extras:
        return base
    return f"{base};{';'.join(extras)}"


_event_text = event_embedding_projection


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity used by the fake pattern library."""
    if not a or not b or len(a) != len(b):
        return 0.0
    if any(not isfinite(value) for value in (*a, *b)):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if not all(isfinite(value) for value in (dot, na, nb)) or na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


__all__ = [
    "EmbeddingModel",
    "LearnedAction",
    "CurrentReuseVerifier",
    "OperationalCaseContext",
    "PatternLibrary",
    "SimilarityMatch",
    "T1CandidateEligibility",
    "T1Config",
    "T1Decision",
    "T1EligibilityComparison",
    "T1Outcome",
    "T1Tier",
    "cosine_similarity",
    "event_embedding_projection",
]

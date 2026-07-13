"""RCA orchestration - route a case to the right tier, then ground it.

Ties the RCA contract together into a usable unit:

- :meth:`RcaCoordinator.analyze_t0` - deterministic direct cause from the
  matched rule, then the grounding gate.
- :meth:`RcaCoordinator.analyze_t2` - hand a novel incident to the
  injected :class:`~fdai.core.rca.reasoner.RcaReasoner`, then enforce
  **grounding on supplied evidence**: every citation the reasoner returns
  MUST be one of the ``candidate_citations`` the caller vouched for. A
  fabricated citation (prompt injection / hallucination) is refused and
  the case abstains to HIL - the reasoner's prose is never trusted as
  authorization (security-and-identity.md).

The coordinator never executes anything; it produces a grounded
hypothesis (or an abstain) that the normal pipeline + risk gate act on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta

# Optional at construction time. The RCA layer must load even if no
# symptom index is available (older forks, tests, etc.), so the type
# is imported lazily via `TYPE_CHECKING` and the runtime keeps a
# structural reference through the `symptom_index` parameter.
from typing import TYPE_CHECKING

from fdai.core.rca.causal_chain import CorrelatedEvent
from fdai.core.rca.contract import (
    Citation,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.evidence import TelemetryEvidenceGatherer
from fdai.core.rca.grounding import enforce_grounding
from fdai.core.rca.knowledge_evidence import KnowledgeEvidenceGatherer
from fdai.core.rca.reasoner import RcaReasoner
from fdai.core.rca.t0 import t0_root_cause
from fdai.core.rca.t1 import t1_causal_chain
from fdai.shared.contracts.models import Rule

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fdai.core.chaos.symptom_index import SymptomIndex


class RcaCoordinator:
    """Tier-aware RCA orchestrator (T0 deterministic + T2 reasoner)."""

    def __init__(
        self,
        *,
        reasoner: RcaReasoner | None = None,
        min_confidence: float = 0.0,
        evidence_gatherer: TelemetryEvidenceGatherer | None = None,
        symptom_index: SymptomIndex | None = None,
        knowledge_gatherer: KnowledgeEvidenceGatherer | None = None,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence MUST be in [0, 1]")
        self._reasoner = reasoner
        self._min_confidence = min_confidence
        self._evidence_gatherer = evidence_gatherer
        # Optional catalog-scenario matcher. When bound, T2 methods that
        # accept a symptom key can add SCENARIO citations to the T2
        # candidate set alongside telemetry evidence. None => nothing
        # different from before (backward-compatible).
        self._symptom_index = symptom_index
        # Optional free-form knowledge gatherer. When bound, the T2
        # convenience wrappers add KNOWLEDGE citations from ingested
        # operator documents (runbooks, resource plans) grounded on the
        # incident summary. None => backward-compatible (no knowledge leg).
        self._knowledge_gatherer = knowledge_gatherer

    @property
    def has_t2(self) -> bool:
        """True iff a T2 reasoner is configured (gates T2 analysis)."""
        return self._reasoner is not None

    @property
    def has_symptom_index(self) -> bool:
        """True iff a chaos-scenario symptom index is bound."""
        return self._symptom_index is not None

    @property
    def has_knowledge(self) -> bool:
        """True iff a free-form knowledge evidence gatherer is bound."""
        return self._knowledge_gatherer is not None

    def analyze_t0(
        self,
        *,
        rule: Rule,
        resource_type: str,
        event_id: str | None = None,
    ) -> RcaResult:
        """Deterministic direct-cause analysis from a matched rule."""
        hypothesis = t0_root_cause(rule=rule, resource_type=resource_type, event_id=event_id)
        return enforce_grounding(hypothesis, min_confidence=self._min_confidence)

    def analyze_t1(
        self,
        *,
        prior_hypothesis: RootCauseHypothesis,
        current_citations: Sequence[Citation],
        reuse_confidence_factor: float = 0.9,
    ) -> RcaResult:
        """Correlation-cause reuse of a prior resolved incident's cause.

        Reuses the root cause a prior **resolved** incident identified,
        but only after re-verifying it still applies: at least one of the
        prior cause's citations MUST be present in the current incident's
        evidence, otherwise the learned cause is stale and abstains (a
        stale cause is never replayed blindly, per
        observability-and-detection.md section 4). Reuse carries lower
        confidence than a fresh analysis (``reuse_confidence_factor``),
        and the result still passes the grounding gate.
        """
        if not 0.0 <= reuse_confidence_factor <= 1.0:
            raise ValueError("reuse_confidence_factor MUST be in [0, 1]")
        current_refs = {(c.kind, c.ref) for c in current_citations}
        still_applies = any((c.kind, c.ref) in current_refs for c in prior_hypothesis.citations)
        if not still_applies:
            return RcaResult(
                outcome=RcaOutcome.ABSTAINED,
                hypothesis=None,
                reason="stale_prior_cause_no_current_evidence",
            )
        reused = RootCauseHypothesis(
            tier=RcaTier.T1,
            cause=prior_hypothesis.cause,
            confidence=prior_hypothesis.confidence * reuse_confidence_factor,
            citations=prior_hypothesis.citations,
            evidence_refs=prior_hypothesis.evidence_refs,
            remediation_ref=prior_hypothesis.remediation_ref,
        )
        return enforce_grounding(reused, min_confidence=self._min_confidence)

    def analyze_t1_causal_chain(
        self,
        *,
        failure_event_id: str,
        failure_at: datetime,
        failure_resource_ref: str,
        correlated_events: Sequence[CorrelatedEvent],
        window: timedelta,
        same_resource_only: bool = False,
        depends_on: Mapping[str, Iterable[str]] | None = None,
        max_hops: int = 4,
    ) -> RcaResult:
        """Reconstruct a T1 temporal causal chain, then ground it.

        The deterministic middle tier of RCA (path b): from the events
        correlated into one incident, rebuild the most probable
        ``root change -> symptom -> ... -> failure`` chain and cite every
        event in it. Abstains (routes to HIL / defers to T2) when no
        change-rooted chain exists in the window - a storm of pure
        symptoms is never turned into a guess. See
        :func:`fdai.core.rca.t1.t1_causal_chain` for the reconstruction
        contract and :mod:`fdai.core.rca.causal_chain` for the engine.
        """
        hypothesis = t1_causal_chain(
            failure_event_id=failure_event_id,
            failure_at=failure_at,
            failure_resource_ref=failure_resource_ref,
            correlated_events=correlated_events,
            window=window,
            same_resource_only=same_resource_only,
            depends_on=depends_on,
            max_hops=max_hops,
        )
        if hypothesis is None:
            return RcaResult(
                outcome=RcaOutcome.ABSTAINED,
                hypothesis=None,
                reason="t1_no_causal_chain_in_window",
            )
        return enforce_grounding(hypothesis, min_confidence=self._min_confidence)

    async def analyze_t2(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RcaResult:
        """Reasoned analysis for a novel incident, grounded on evidence.

        Fail-closed: no reasoner configured, an abstaining reasoner, a
        citation outside the supplied evidence, or a below-confidence
        hypothesis all abstain to HIL.
        """
        if self._reasoner is None:
            return RcaResult(
                outcome=RcaOutcome.ABSTAINED,
                hypothesis=None,
                reason="no_t2_reasoner_configured",
            )
        candidates = tuple(candidate_citations)
        hypothesis = await self._reasoner.reason(
            incident_summary=incident_summary,
            candidate_citations=candidates,
        )
        if hypothesis is None:
            return RcaResult(
                outcome=RcaOutcome.ABSTAINED,
                hypothesis=None,
                reason="t2_reasoner_abstained",
            )
        allowed = {(c.kind, c.ref) for c in candidates}
        for citation in hypothesis.citations:
            if (citation.kind, citation.ref) not in allowed:
                # A citation the caller never supplied is treated as
                # fabricated - refuse rather than trust model text.
                return RcaResult(
                    outcome=RcaOutcome.ABSTAINED,
                    hypothesis=None,
                    reason=f"ungrounded_citation_{citation.ref!r}_not_in_evidence",
                )
        return enforce_grounding(hypothesis, min_confidence=self._min_confidence)

    async def analyze_t2_from_telemetry(
        self,
        *,
        incident_summary: str,
        resource_ref: str,
        since: datetime,
        until: datetime,
        extra_citations: Sequence[Citation] = (),
    ) -> RcaResult:
        """Gather telemetry evidence, then run T2 analysis grounded on it.

        Convenience wrapper that closes the gap between the § 3.2 log / trace
        seams and :meth:`analyze_t2`: it asks the injected
        :class:`TelemetryEvidenceGatherer` for TELEMETRY citations around the
        incident, unions them with any ``extra_citations`` the caller vouches
        for (rule / event / incident refs), and hands the set to
        :meth:`analyze_t2` as the candidate evidence. No gatherer configured
        means the candidate set is just ``extra_citations`` - fail-safe, and
        an empty set abstains to HIL through the grounding gate.
        """
        candidates: list[Citation] = list(extra_citations)
        if self._evidence_gatherer is not None:
            candidates.extend(
                await self._evidence_gatherer.gather(
                    resource_ref=resource_ref, since=since, until=until
                )
            )
        if self._knowledge_gatherer is not None:
            candidates.extend(await self._knowledge_gatherer.gather(query=incident_summary))
        return await self.analyze_t2(
            incident_summary=incident_summary,
            candidate_citations=tuple(candidates),
        )

    async def analyze_t2_from_symptom(
        self,
        *,
        incident_summary: str,
        signal: str,
        target_type: str,
        severity: str,
        resource_ref: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        extra_citations: Sequence[Citation] = (),
        max_scenario_candidates: int = 8,
    ) -> RcaResult:
        """T2 analysis grounded on catalog scenarios + optional telemetry.

        Combines two candidate-citation sources so the T2 reasoner sees
        both "what does the chaos catalog say produces this symptom?"
        and "what does telemetry say happened at this time?":

        - **Scenario citations** (``CitationKind.SCENARIO``) come from
          :func:`fdai.core.rca.scenario_context.candidate_scenarios`
          against the bound :class:`~fdai.core.chaos.symptom_index.SymptomIndex`.
          No index bound => no scenario citations (backward-compatible).
        - **Telemetry citations** (``CitationKind.TELEMETRY``) are
          gathered by the same path as :meth:`analyze_t2_from_telemetry`
          when ``resource_ref`` + ``since`` + ``until`` are supplied and
          an :class:`TelemetryEvidenceGatherer` is bound.

        Every citation the reasoner returns MUST match one the caller
        vouched for - a fabricated scenario id or telemetry ref abstains
        to HIL, exactly like :meth:`analyze_t2`. A scenario id in a
        citation is a pointer to *why the loop believes X*, never a
        permission to *do X*.
        """
        candidates: list[Citation] = list(extra_citations)
        if self._symptom_index is not None:
            # Lazy import so the RCA module still loads in an environment
            # where the chaos catalog is not present (fork, test rig).
            from fdai.core.rca.scenario_context import candidate_scenarios

            candidates.extend(
                candidate_scenarios(
                    self._symptom_index,
                    signal=signal,
                    target_type=target_type,
                    severity=severity,
                    max_candidates=max_scenario_candidates,
                )
            )
        if (
            self._evidence_gatherer is not None
            and resource_ref is not None
            and since is not None
            and until is not None
        ):
            candidates.extend(
                await self._evidence_gatherer.gather(
                    resource_ref=resource_ref, since=since, until=until
                )
            )
        if self._knowledge_gatherer is not None:
            candidates.extend(await self._knowledge_gatherer.gather(query=incident_summary))
        return await self.analyze_t2(
            incident_summary=incident_summary,
            candidate_citations=tuple(candidates),
        )


__all__ = ["RcaCoordinator"]

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

from collections.abc import Sequence
from datetime import datetime

from fdai.core.rca.contract import (
    Citation,
    RcaOutcome,
    RcaResult,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.evidence import TelemetryEvidenceGatherer
from fdai.core.rca.grounding import enforce_grounding
from fdai.core.rca.reasoner import RcaReasoner
from fdai.core.rca.t0 import t0_root_cause
from fdai.shared.contracts.models import Rule


class RcaCoordinator:
    """Tier-aware RCA orchestrator (T0 deterministic + T2 reasoner)."""

    def __init__(
        self,
        *,
        reasoner: RcaReasoner | None = None,
        min_confidence: float = 0.0,
        evidence_gatherer: TelemetryEvidenceGatherer | None = None,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence MUST be in [0, 1]")
        self._reasoner = reasoner
        self._min_confidence = min_confidence
        self._evidence_gatherer = evidence_gatherer

    @property
    def has_t2(self) -> bool:
        """True iff a T2 reasoner is configured (gates T2 analysis)."""
        return self._reasoner is not None

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
        return await self.analyze_t2(
            incident_summary=incident_summary,
            candidate_citations=tuple(candidates),
        )


__all__ = ["RcaCoordinator"]

"""T2 reasoning RCA seam - the LLM-backed hypothesis producer.

Protocol a fork implements to plug a grounded T2 reasoner (mixed-model
cross-check + RAG grounding via ``core/quality_gate``) behind the RCA
contract. Kept a Protocol so ``core/`` never imports a concrete LLM
adapter; the reasoner returns a
:class:`~fdai.core.rca.contract.RootCauseHypothesis` (or ``None`` to
abstain) that MUST still pass
:func:`~fdai.core.rca.grounding.enforce_grounding` **and** the risk-gate
verifier before any action.

Input is untrusted (telemetry / correlated events may carry prompt
injection); the reasoner's prose is never authoritative - the grounding
gate and the deterministic verifier are
([security-and-identity.md](../../../../docs/roadmap/architecture/security-and-identity.md)).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fdai.core.rca.contract import Citation, RootCauseHypothesis


@runtime_checkable
class RcaReasoner(Protocol):
    """Produces a grounded T2 root-cause hypothesis for a novel incident."""

    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis | None:
        """Return a grounded hypothesis, or ``None`` to abstain.

        Implementations SHOULD cite only refs drawn from
        ``candidate_citations`` (grounding on the evidence the caller
        supplied); an ungrounded return is rejected downstream by
        :func:`~fdai.core.rca.grounding.enforce_grounding`. Returning
        ``None`` is an explicit abstain (the model could not ground a
        hypothesis) and routes to HIL.
        """
        ...


__all__ = ["RcaReasoner"]

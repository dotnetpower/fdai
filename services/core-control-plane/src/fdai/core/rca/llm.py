"""LLM-backed T2 RCA reasoner - deterministic parse + grounding.

The T2 tier of RCA (observability-and-detection.md section 4) hands a
novel incident to a model and turns the model's answer into a
:class:`~fdai.core.rca.contract.RootCauseHypothesis`. The LLM call sits
behind the :class:`RcaModel` Protocol seam so ``core/`` never imports a
concrete adapter; a fork binds a real Azure OpenAI model.

Everything after the call is **deterministic and authoritative over the
model text**:

- :func:`parse_rca_response` parses the model's JSON and refuses on any
  malformed / incomplete answer (abstain to HIL);
- **grounding on supplied evidence** - a cited ref that was NOT in the
  ``candidate_citations`` the caller vouched for is treated as
  fabricated (prompt injection) and the whole hypothesis is refused;
- an answer with no valid citation is ungrounded and refused.

The model proposes; the parser + the grounding gate +
(downstream) the risk-gate verifier decide. The model's prose never
grants execution eligibility (security-and-identity.md).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from fdai.core.rca.contract import Citation, RcaTier, RootCauseHypothesis

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class RcaModel(Protocol):
    """LLM seam for T2 root-cause proposal.

    Returns a JSON string with the shape
    ``{"cause": str, "confidence": number in [0,1], "citations": [ref, ...]}``.
    Implementations MUST cite only refs drawn from
    ``candidate_citations``; the parser refuses any other ref.
    """

    async def propose_cause(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> str: ...


def parse_rca_response(
    raw: str,
    *,
    candidate_citations: Sequence[Citation],
    tier: RcaTier = RcaTier.T2,
) -> RootCauseHypothesis | None:
    """Parse a model JSON answer into a grounded hypothesis, or ``None``.

    Returns ``None`` (an explicit abstain) for a malformed answer, a
    missing/blank cause, an out-of-range confidence, a fabricated
    citation (not in ``candidate_citations``), or an empty citation set.
    Pure and deterministic - the same answer always yields the same
    result.
    """
    try:
        data: Any = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    cause = data.get("cause")
    if not isinstance(cause, str) or not cause.strip():
        return None

    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not 0.0 <= float(confidence) <= 1.0:
        return None

    cited = data.get("citations")
    if not isinstance(cited, list):
        return None

    by_ref = {c.ref: c for c in candidate_citations}
    by_qualified_ref = {f"{c.kind.value}:{c.ref}": c for c in candidate_citations}
    grounded: list[Citation] = []
    for ref in cited:
        if not isinstance(ref, str):
            return None  # malformed citation entry
        citation = by_ref.get(ref) or by_qualified_ref.get(ref)
        if citation is None:
            # A ref the caller never supplied - treat as fabricated
            # (prompt injection) and refuse the whole hypothesis.
            return None
        grounded.append(citation)
    if not grounded:
        return None  # ungrounded

    return RootCauseHypothesis(
        tier=tier,
        cause=cause.strip(),
        confidence=float(confidence),
        citations=tuple(grounded),
    )


class LlmRcaReasoner:
    """`RcaReasoner` backed by an :class:`RcaModel`.

    Calls the model, then parses + grounds its answer. A transport error
    or an unparsable answer becomes an abstain (``None``) so the caller
    routes to HIL - the reasoner never raises into the control loop.
    """

    def __init__(self, *, model: RcaModel) -> None:
        self._model = model

    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis | None:
        candidates = tuple(candidate_citations)
        try:
            raw = await self._model.propose_cause(
                incident_summary=incident_summary,
                candidate_citations=candidates,
            )
        except Exception:  # noqa: BLE001 - a model failure is an abstain, never a crash
            _LOGGER.warning("rca_model_call_failed", exc_info=True)
            return None
        return parse_rca_response(raw, candidate_citations=candidates)


__all__ = ["LlmRcaReasoner", "RcaModel", "parse_rca_response"]

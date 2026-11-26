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
from typing import Protocol, runtime_checkable

from fdai.core.rca.citations import MAX_RCA_CITATIONS, admitted_citations, resolve_citation
from fdai.core.rca.contract import CauseDomain, Citation, RcaTier, RootCauseHypothesis
from fdai.core.rca.grounding import valid_cause

_LOGGER = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 64 * 1024
_RESPONSE_FIELDS = frozenset({"cause", "cause_domain", "confidence", "citations"})


@runtime_checkable
class RcaModel(Protocol):
    """LLM seam for T2 root-cause proposal.

    Returns a JSON string with the shape
    ``{"cause": str, "cause_domain": str, "confidence": number in [0,1],
    "citations": [ref, ...]}``.
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

    Holds malformed, oversized, duplicate-field, or unsupported-field JSON,
    invalid uncertainty, and missing, conflicting, or ambiguous evidence.
    Exact citation duplicates are retained once in canonical order.
    """
    candidates = admitted_citations(candidate_citations)
    if candidates is None or not isinstance(raw, str) or len(raw) > _MAX_RESPONSE_BYTES:
        return None
    try:
        if len(raw.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            return None
        data: object = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.keys() - _RESPONSE_FIELDS:
        return None

    cause = data.get("cause")
    if not isinstance(cause, str):
        return None
    cause = cause.strip()
    if not valid_cause(cause):
        return None
    try:
        cause_domain = CauseDomain(data.get("cause_domain", CauseDomain.UNKNOWN.value))
    except (ValueError, TypeError):
        return None

    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None

    cited = data.get("citations")
    if not isinstance(cited, list) or not 1 <= len(cited) <= MAX_RCA_CITATIONS:
        return None

    grounded: set[Citation] = set()
    for ref in cited:
        if not isinstance(ref, str):
            return None  # malformed citation entry
        citation = resolve_citation(ref, candidates)
        if citation is None:
            return None
        grounded.add(citation)

    return RootCauseHypothesis(
        tier=tier,
        cause=cause,
        confidence=float(confidence),
        citations=tuple(citation for citation in candidates if citation in grounded),
        cause_domain=cause_domain,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("RCA response contains duplicate JSON fields")
        result[key] = value
    return result


class LlmRcaReasoner:
    """`RcaReasoner` backed by an :class:`RcaModel`.

    Calls the model, then parses + grounds its answer. A transport error
    or an unparsable answer becomes an abstain (``None``) so the caller
    routes to HIL. Cancellation still propagates to the bounded caller.
    """

    def __init__(self, *, model: RcaModel) -> None:
        self._model = model

    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis | None:
        candidates = admitted_citations(candidate_citations)
        if candidates is None:
            _LOGGER.warning("rca_model_evidence_rejected")
            return None
        try:
            raw = await self._model.propose_cause(
                incident_summary=incident_summary,
                candidate_citations=candidates,
            )
        except Exception as error:  # noqa: BLE001 - the injected transport is an external boundary
            _LOGGER.warning("rca_model_call_failed", extra={"error_type": type(error).__name__})
            return None
        hypothesis = parse_rca_response(raw, candidate_citations=candidates)
        if hypothesis is None:
            _LOGGER.warning("rca_model_response_rejected")
        return hypothesis


__all__ = ["LlmRcaReasoner", "RcaModel", "parse_rca_response"]

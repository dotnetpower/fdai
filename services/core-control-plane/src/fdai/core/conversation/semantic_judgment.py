"""Shared model-backed boundary for natural-language semantic judgment.

The boundary validates one T1 proposal, retries a configured T2 binding after
unavailable, malformed, ambiguous, or low-confidence output, and returns one
content-free terminal receipt. It never grants execution authority.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import canonical_json, content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
    SemanticJudgmentReceipt,
    SemanticJudgmentTier,
)
from pydantic import ValidationError

_MAX_UTTERANCE_CHARS = 32_000
_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_CAPABILITIES = 512
_MAX_CAPABILITY_BYTES = 524_288


class SemanticJudgmentModel(Protocol):
    """Propose candidate-only structured meaning without authority."""

    def judge(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        capabilities: tuple[dict[str, Any], ...],
        profile_id: str,
        profile_version: str,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SemanticJudgmentBinding:
    """One configured model tier and its content-free provenance."""

    tier: SemanticJudgmentTier
    model: SemanticJudgmentModel
    model_config_digest: str
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class SemanticJudgmentResult:
    """One terminal semantic outcome with no execution authority."""

    proposal: SemanticJudgmentProposal | None
    receipt: SemanticJudgmentReceipt

    @property
    def accepted(self) -> bool:
        return self.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED


class SemanticJudgmentBoundary:
    """Run bounded T1/T2 semantic judgment and validate every proposal."""

    def __init__(
        self,
        *,
        profile_id: str,
        profile_version: str,
        primary: SemanticJudgmentBinding | None,
        escalation: SemanticJudgmentBinding | None = None,
        confidence_threshold: float = 0.75,
    ) -> None:
        if primary is not None and primary.tier is not SemanticJudgmentTier.T1:
            raise ValueError("primary semantic judgment binding MUST use T1")
        if escalation is not None and escalation.tier is not SemanticJudgmentTier.T2:
            raise ValueError("escalation semantic judgment binding MUST use T2")
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("semantic judgment confidence threshold MUST be in (0, 1]")
        self.profile_id = profile_id
        self.profile_version = profile_version
        self._bindings = tuple(item for item in (primary, escalation) if item is not None)
        self._confidence_threshold = confidence_threshold

    def judge(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        capabilities: Sequence[Mapping[str, Any]],
    ) -> SemanticJudgmentResult:
        started = time.monotonic()
        bounded_context = _bounded_context(context)
        bounded_capabilities = _bounded_capabilities(capabilities)
        input_digest = content_digest({"utterance": utterance})
        context_digest = content_digest({"context": list(bounded_context)})
        capability_digest = content_digest({"capabilities": list(bounded_capabilities)})
        if not utterance.strip() or len(utterance) > _MAX_UTTERANCE_CHARS:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.MALFORMED,
                reason_code="utterance_out_of_bounds",
            )
        if not self._bindings:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.UNAVAILABLE,
                reason_code="model_unbound",
            )

        final_disposition = SemanticJudgmentDisposition.UNAVAILABLE
        final_reason = "model_attempts_unavailable"
        for binding in self._bindings:
            raw = binding.model.judge(
                utterance=utterance,
                context=bounded_context,
                capabilities=bounded_capabilities,
                profile_id=self.profile_id,
                profile_version=self.profile_version,
            )
            if raw is None:
                continue
            try:
                proposal = SemanticJudgmentProposal.model_validate(raw)
                _validate_source_spans(proposal, utterance=utterance)
            except (TypeError, ValueError, ValidationError):
                final_disposition = SemanticJudgmentDisposition.MALFORMED
                final_reason = "proposal_invalid"
                continue
            if proposal.ambiguous:
                final_disposition = SemanticJudgmentDisposition.CLARIFICATION
                final_reason = "clarification_required"
                if binding is not self._bindings[-1]:
                    continue
                return self._result(
                    started=started,
                    input_digest=input_digest,
                    context_digest=context_digest,
                    capability_digest=capability_digest,
                    disposition=final_disposition,
                    reason_code=final_reason,
                    binding=binding,
                    proposal=proposal,
                )
            if proposal.confidence < self._confidence_threshold:
                final_disposition = SemanticJudgmentDisposition.LOW_CONFIDENCE
                final_reason = "confidence_below_threshold"
                continue
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.ACCEPTED,
                reason_code="accepted",
                binding=binding,
                proposal=proposal,
            )
        return self._result(
            started=started,
            input_digest=input_digest,
            context_digest=context_digest,
            capability_digest=capability_digest,
            disposition=final_disposition,
            reason_code=final_reason,
        )

    def _result(
        self,
        *,
        started: float,
        input_digest: str,
        context_digest: str,
        capability_digest: str,
        disposition: SemanticJudgmentDisposition,
        reason_code: str,
        binding: SemanticJudgmentBinding | None = None,
        proposal: SemanticJudgmentProposal | None = None,
    ) -> SemanticJudgmentResult:
        body = {
            "schema_version": "1.0.0",
            "input_digest": input_digest,
            "context_digest": context_digest,
            "capability_digest": capability_digest,
            "proposal_digest": proposal.proposal_digest if proposal is not None else None,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "tier": binding.tier.value if binding is not None else None,
            "model_config_digest": (
                binding.model_config_digest
                if proposal is not None and binding is not None
                else None
            ),
            "prompt_digest": (
                binding.prompt_digest if proposal is not None and binding is not None else None
            ),
            "disposition": disposition.value,
            "confidence": proposal.confidence if proposal is not None else None,
            "ambiguous": proposal.ambiguous if proposal is not None else False,
            "latency_ms": min(120_000, max(0, int((time.monotonic() - started) * 1_000))),
            "reason_code": reason_code,
            "execution_authority": False,
        }
        receipt = SemanticJudgmentReceipt.model_validate(
            {**body, "receipt_digest": content_digest(body)}
        )
        return SemanticJudgmentResult(proposal=proposal, receipt=receipt)


def _bounded_context(context: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    total = 0
    for item in tuple(context)[-_MAX_CONTEXT_ITEMS:]:
        if not isinstance(item, str):
            raise TypeError("semantic judgment context MUST contain strings")
        total += len(item)
        if total > _MAX_CONTEXT_CHARS:
            raise ValueError("semantic judgment context exceeds its bound")
        selected.append(item)
    return tuple(selected)


def _bounded_capabilities(
    capabilities: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if len(capabilities) > _MAX_CAPABILITIES:
        raise ValueError("semantic judgment capabilities exceed their count bound")
    selected = tuple(dict(item) for item in capabilities)
    if len(canonical_json(list(selected)).encode()) > _MAX_CAPABILITY_BYTES:
        raise ValueError("semantic judgment capabilities exceed their byte bound")
    return selected


def _validate_source_spans(proposal: SemanticJudgmentProposal, *, utterance: str) -> None:
    for target in proposal.targets:
        if target.source_end > len(utterance):
            raise ValueError("semantic target source span exceeds the utterance")
        if utterance[target.source_start : target.source_end] != target.value:
            raise ValueError("semantic target source span does not match the utterance")


__all__ = [
    "SemanticJudgmentBinding",
    "SemanticJudgmentBoundary",
    "SemanticJudgmentModel",
    "SemanticJudgmentResult",
]

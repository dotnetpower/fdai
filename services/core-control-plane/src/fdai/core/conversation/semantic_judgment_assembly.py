"""Route-selected semantic-judgment prompt assembly and its coverage guard.

The compact preflight classifies each turn into closed request topics. Topics
select conditional judgment prompt packs; they never select an intent, widen a
capability, or grant authority. When an accepted judgment names a result whose
guidance lives in a pack this call excluded, judgment runs once more with the
complete prompt and the first result is discarded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from fdai.core.prompts.types import PromptAssemblyMode, PromptAssemblyReceipt

from .conversation_preflight import ConversationPreflightResult

if TYPE_CHECKING:
    from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

    from .semantic_judgment import SemanticJudgmentBoundary, SemanticJudgmentResult

_LOGGER = logging.getLogger(__name__)
_MIN_ROUTE_CONFIDENCE = 0.7
_KEY_VALUE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,127}$")


def judgment_assembly_keys(
    preflight: ConversationPreflightResult | None,
) -> tuple[str, ...] | None:
    """Return topic keys from one confident validated route, or ``None`` for complete."""

    proposal = preflight.proposal if preflight is not None else None
    if (
        proposal is None
        or not proposal.request_topics
        or proposal.confidence < _MIN_ROUTE_CONFIDENCE
    ):
        return None
    return tuple(sorted(f"topic:{topic.value}" for topic in proposal.request_topics))


def model_arguments(
    primary: bool,
    model: object,
    keys: tuple[str, ...] | None,
) -> dict[str, Any]:
    """Pass assembly keys only to a primary model that declares assembly support."""

    if not primary or keys is None or not getattr(model, "supports_prompt_assembly", False):
        return {}
    return {"prompt_assembly_keys": keys}


def judgment_result_keys(proposal: SemanticJudgmentProposal) -> tuple[str, ...]:
    """Name the typed meaning a judgment produced for coverage checks."""

    values = {
        f"intent:{proposal.primary_intent}",
        *(f"intent:{intent}" for intent in proposal.secondary_intents),
        f"posture:{proposal.action_posture}",
    }
    document_mode = proposal.document_evidence_mode.value
    if document_mode != "none":
        values.add(f"document:{document_mode}")
    return tuple(sorted(value for value in values if _KEY_VALUE.fullmatch(value.split(":", 1)[1])))


def assembly_receipt(result: SemanticJudgmentResult) -> PromptAssemblyReceipt | None:
    """Return the first recorded conditional-assembly receipt of one judgment."""

    for observation in result.observations:
        manifest = observation.prompt_replay_manifest
        if manifest is not None and manifest.assembly is not None:
            return manifest.assembly
    return None


def uncovered_result_keys(result: SemanticJudgmentResult) -> tuple[str, ...]:
    """Return produced result keys whose governed guidance the call excluded."""

    receipt = assembly_receipt(result)
    if receipt is None or receipt.mode is not PromptAssemblyMode.SELECTED:
        return ()
    if result.proposal is None:
        return ()
    return receipt.uncovered(judgment_result_keys(result.proposal))


def judge_with_prompt_assembly(
    boundary: SemanticJudgmentBoundary,
    *,
    preflight: ConversationPreflightResult | None,
    **arguments: Any,
) -> SemanticJudgmentResult:
    """Judge with route-selected guidance and one complete fallback on a coverage gap."""

    keys = judgment_assembly_keys(preflight)
    if keys is None:
        return boundary.judge(**arguments)
    first = boundary.judge(**arguments, prompt_assembly_keys=keys)
    uncovered = uncovered_result_keys(first)
    if not uncovered:
        return first
    _LOGGER.info(
        "semantic_judgment_assembly_fallback",
        extra={"route_keys": list(keys), "uncovered_keys": list(uncovered)},
    )
    second = boundary.judge(**arguments)
    return replace(second, observations=(*first.observations, *second.observations))


__all__ = [
    "assembly_receipt",
    "judge_with_prompt_assembly",
    "judgment_assembly_keys",
    "judgment_result_keys",
    "model_arguments",
    "uncovered_result_keys",
]

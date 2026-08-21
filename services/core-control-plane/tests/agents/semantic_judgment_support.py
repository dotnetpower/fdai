"""Shared semantic-judgment fixtures for Pantheon conversation tests."""

from __future__ import annotations

import re

from fdai.agents._framework.pantheon import PANTHEON_NAMES
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.shared.contracts.models import OntologyActionType
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)

_DIGEST = "sha256:" + ("a" * 64)
_RESOURCE = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9_.-])"
)
_TOOL_SIGNAL_GROUPS = (
    ("arbitration history", "recorded arbitration history"),
    ("rca", "root-cause", "root cause"),
    ("forecast status", "retained forecast episode"),
    ("policy history", "governed policy history"),
    ("budget status", "bound budget projection"),
    ("resilience score", "retained resilience score"),
    ("capacity forecast", "capacity forecast state"),
)


class FrozenSemanticJudgmentModel:
    """Map the frozen test corpus to no-authority structured judgments."""

    def judge(self, *, utterance: str, **_kwargs: object) -> dict[str, object]:
        folded = utterance.casefold()
        action = _action_target(utterance, folded)
        explicit_agents = _explicit_agent_targets(utterance, folded)
        targets: list[dict[str, object]] = []
        action_posture = "advise_only"
        if action is not None:
            targets.append(action)
            resource = _RESOURCE.search(utterance)
            if resource is not None:
                targets.append(
                    {
                        "kind": "resource",
                        "value": resource.group(0),
                        "source_start": resource.start(),
                        "source_end": resource.end(),
                    }
                )
            primary_intent = "action_request"
            action_posture = "draft_only"
        elif explicit_agents:
            targets.extend(explicit_agents)
            primary_intent = "open_question"
        else:
            primary_intent = _intent_for(folded)
        return {
            "primary_intent": primary_intent,
            "secondary_intents": [],
            "targets": targets,
            "requested_facets": [],
            "confidence": 0.95,
            "ambiguous": False,
            "alternatives": [],
            "unresolved_terms": [],
            "clarification": None,
            "action_posture": action_posture,
            "execution_authority": False,
        }


class FrozenToolEmbedding:
    """Embed the frozen tool-selection corpus without lexical production fallback."""

    dim = len(_TOOL_SIGNAL_GROUPS) + 1

    async def embed(self, text: str) -> list[float]:
        folded = text.casefold()
        vector = [
            float(sum(marker in folded for marker in markers)) for markers in _TOOL_SIGNAL_GROUPS
        ]
        vector.append(0.0 if any(vector) else 1.0)
        return vector


def semantic_test_boundary() -> SemanticJudgmentBoundary:
    """Return a validated T1 boundary over the frozen test model."""

    return SemanticJudgmentBoundary(
        profile_id="pantheon.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=FrozenSemanticJudgmentModel(),
            model_config_digest=_DIGEST,
            prompt_digest=_DIGEST,
        ),
    )


def semantic_tool_embedding() -> FrozenToolEmbedding:
    """Return the frozen model-backed tool selector used by agent tests."""

    return FrozenToolEmbedding()


def semantic_test_proposal(utterance: str) -> SemanticJudgmentProposal:
    """Return the accepted proposal for one frozen test utterance."""

    result = semantic_test_boundary().judge(
        utterance=utterance,
        context=(),
        capabilities=(),
    )
    if not result.accepted or result.proposal is None:
        raise AssertionError("frozen semantic judgment MUST be accepted")
    return result.proposal


def restart_action_type() -> OntologyActionType:
    """Return the minimal reversible ActionType used by conversation tests."""

    return OntologyActionType.model_validate(
        {
            "schema_version": "1.0.0",
            "name": "ops.restart-service",
            "version": "1.0.0",
            "operation": "restart",
            "interfaces": ["ControlPlane", "IdempotentByKey"],
            "rollback_contract": "scripted",
            "default_mode": "shadow",
            "promotion_gate": {
                "min_shadow_days": 14,
                "min_samples": 100,
                "min_accuracy": 0.95,
                "max_policy_escapes": 0,
            },
            "description": "Restart one service through the typed pipeline.",
        }
    )


def _explicit_agent_targets(utterance: str, folded: str) -> list[dict[str, object]]:
    matches: list[tuple[int, dict[str, object]]] = []
    for name in PANTHEON_NAMES:
        start = folded.find(name.casefold())
        if start < 0:
            continue
        end = start + len(name)
        matches.append(
            (
                start,
                {
                    "kind": "agent",
                    "value": utterance[start:end],
                    "source_start": start,
                    "source_end": end,
                },
            )
        )
    return [target for _start, target in sorted(matches, key=lambda item: item[0])]


def _action_target(utterance: str, folded: str) -> dict[str, object] | None:
    for marker, canonical in (
        ("restart", "ops.restart-service"),
        ("재시작", "ops.restart-service"),
        ("scale down", "ops.scale-in"),
    ):
        start = folded.find(marker)
        if start >= 0:
            return {
                "kind": "action_type",
                "value": utterance[start : start + len(marker)],
                "canonical_value": canonical,
                "source_start": start,
                "source_end": start + len(marker),
            }
    return None


def _intent_for(folded: str) -> str:
    if "action status" in folded:
        return "action_status"
    if "approval" in folded:
        return "hil_pending"
    if "budget" in folded:
        return "budget_status"
    if any(marker in folded for marker in ("cost", "spend", "비용", "지출")):
        return "cost_breakdown"
    if any(marker in folded for marker in ("capacity", "headroom", "용량")):
        return "capacity_status"
    if "arbitration" in folded:
        return "priority_conflict"
    if "rca" in folded:
        return "why_rca"
    if "forecast" in folded:
        return "forecast"
    if "policy" in folded:
        return "rule_history"
    if "resilience" in folded:
        return "resilience_score"
    if any(
        marker in folded
        for marker in (
            "who stopped",
            "누가 중지",
            "activity log",
            "변경 이력",
            "platform health",
            "플랫폼 장애",
            "shutdown",
            "종료 이벤트",
            "current state",
            "현재 상태",
        )
    ):
        return "resource_change_history"
    return "open_question"


__all__ = [
    "FrozenSemanticJudgmentModel",
    "restart_action_type",
    "semantic_test_boundary",
    "semantic_test_proposal",
    "semantic_tool_embedding",
]

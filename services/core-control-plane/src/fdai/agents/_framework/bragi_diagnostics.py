"""Build content-free diagnostic fragments for completed Bragi turns."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bragi_models import RoutingDecision


def attach_pantheon_diagnostics(
    *,
    answer: dict[str, Any],
    decision: RoutingDecision,
    question: str,
    session_id: str,
) -> None:
    """Attach bounded trace and deterministic observations without raw question text."""

    answer_text = answer.get("answer")
    facts = answer.get("facts")
    fact_mapping = facts if isinstance(facts, Mapping) else {}
    policy_raw = answer.get("conversation_policy")
    policy = policy_raw if isinstance(policy_raw, Mapping) else {}
    composition_raw = answer.get("prompt_composition")
    composition = composition_raw if isinstance(composition_raw, Mapping) else {}
    evidence_refs_raw = fact_mapping.get("evidence_refs")
    evidence_refs = (
        tuple(str(value) for value in evidence_refs_raw if str(value))
        if isinstance(evidence_refs_raw, list | tuple)
        else ()
    )
    contributors_raw = answer.get("contributors")
    contributors = (
        tuple(str(value) for value in contributors_raw if str(value))
        if isinstance(contributors_raw, list | tuple)
        else ()
    )
    tool_ids_raw = answer.get("conversation_tools")
    tool_ids = (
        tuple(str(value) for value in tool_ids_raw if str(value))
        if isinstance(tool_ids_raw, list | tuple)
        else ()
    )
    primary = decision.primary_agent
    participants: list[dict[str, str]] = []
    if primary is not None:
        participants.append(
            {
                "agent": primary,
                "prompt_version": str(policy.get("version") or "unavailable"),
                "prompt_sha256": str(policy.get("prompt_sha256") or _digest("unavailable")),
                "situation": str(composition.get("situation") or "operator:direct:T0:en"),
            }
        )
    contributor_answers = answer.get("contributor_answers")
    if isinstance(contributor_answers, list):
        for contribution in contributor_answers:
            if not isinstance(contribution, Mapping):
                continue
            contributor_policy = contribution.get("conversation_policy")
            contributor_composition = contribution.get("prompt_composition")
            if not isinstance(contributor_policy, Mapping) or not isinstance(
                contributor_composition, Mapping
            ):
                continue
            agent = contribution.get("agent")
            if not isinstance(agent, str):
                continue
            participants.append(
                {
                    "agent": agent,
                    "prompt_version": str(contributor_policy.get("version") or "unavailable"),
                    "prompt_sha256": str(
                        contributor_policy.get("prompt_sha256") or _digest("unavailable")
                    ),
                    "situation": str(
                        contributor_composition.get("situation") or "peer:contributor:T1:en"
                    ),
                }
            )
            if len(participants) >= 3:
                break
    verification_status = str(answer.get("verification_status") or "unverified")
    verification_authority = str(answer.get("verification_authority") or "agent_owned_projection")
    answer["pantheon_trace_fragment"] = {
        "schema_version": "1.0.0",
        "turn_digest": _digest(f"{session_id}\0{question}"),
        "session_digest": _digest(session_id),
        "correlation_digest": _digest(str(answer.get("trace_ref") or session_id)),
        "locale": _locale(question),
        "actual_primary_agent": primary,
        "routing_method": decision.method,
        "semantic_score": decision.semantic_score,
        "semantic_margin": decision.semantic_margin,
        "contributors": contributors,
        "handoff_owner": primary if answer.get("handoff_needed") else None,
        "participants": tuple(participants),
        "tool_ids": tool_ids,
        "evidence_ref_digests": tuple(_digest(value) for value in evidence_refs),
        "evidence_manifest_digest": _digest(_canonical(fact_mapping)),
        "answer_digest": _digest(answer_text if isinstance(answer_text, str) else ""),
        "reported_verification_status": verification_status,
        "reported_verification_authority": verification_authority,
        "execution_authority": False,
    }


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _locale(value: str) -> str:
    return "ko" if any("가" <= character <= "힣" for character in value) else "en"


__all__ = ["attach_pantheon_diagnostics"]

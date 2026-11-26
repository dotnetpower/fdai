"""Compose final operator prose only from complete attributed owner snapshots."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.deliberation import ConversationDeliberator, _claim
from fdai.agents._framework.pantheon import PANTHEON_NAMES


async def compose_owned_answer(
    deliberator: ConversationDeliberator,
    *,
    question: str,
    correlation_id: str,
    primary_agent: str,
    answer: dict[str, Any],
    contributors: list[dict[str, Any]],
    locale: str,
    incomplete: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "held",
        "authority": "presentation_only",
        "conclusion": None,
        "purpose": "owned_answer",
        "t2_status": "unavailable",
    }
    if incomplete:
        return {**result, "t2_status": "participant_evidence_incomplete"}
    owners = [(primary_agent, answer), *((item["agent"], item) for item in contributors)]
    claims = tuple(_claim(owner, snapshot) for owner, snapshot in owners)
    if (
        not 1 <= len(claims) <= 3
        or any(claim is None for claim in claims)
        or len({owner for owner, _ in owners}) != len(owners)
        or any(owner not in PANTHEON_NAMES for owner, _ in owners)
    ):
        return {**result, "t2_status": "owned_evidence_invalid"}
    valid_claims = tuple(claim for claim in claims if claim is not None)
    return await deliberator.synthesize_answer(
        result,
        question=question,
        requester="Bragi",
        correlation_id=correlation_id,
        budget_key=correlation_id,
        primary_agent=primary_agent,
        claims=valid_claims,
        locale=locale,
        purpose="owned_answer",
    )

"""Phase E conflict cases for the shadow Answer Planning Round.

Contradictory contributors must preserve both evidence sets, must never change
the primary verified answer, and must never gain approval, execution, or
arbitration authority through the shadow record.
"""

from __future__ import annotations

import pytest
from fdai.core.conversation.answer_plan import AnswerIntent, AnswerSection, build_answer_plan
from fdai.core.conversation.answer_planning import (
    SHADOW_CONTRIBUTION_KEYS,
    SHADOW_RECORD_KEYS,
    AnswerContribution,
    AnswerPlanningRoute,
    GroundedFact,
    PlanningCandidate,
    PlanningStatus,
    run_answer_planning_round,
)

PROMPT = "Why did this deployment fail?"
SHARED_REF = "signal:deployment-health"


class _Provider:
    def __init__(self, results: dict[str, AnswerContribution]) -> None:
        self.results = results

    async def contribute(
        self,
        *,
        agent: str,
        prompt: str,  # noqa: ARG002
        max_tokens: int,  # noqa: ARG002
    ) -> AnswerContribution | None:
        return self.results[agent]


def _contribution(
    agent: str,
    *,
    claim: str,
    refs: tuple[str, ...],
    confidence: float = 0.9,
    caveats: tuple[str, ...] = (),
) -> AnswerContribution:
    return AnswerContribution(
        agent=agent,
        facts=tuple(GroundedFact(claim, ref) for ref in refs),
        caveats=caveats,
        suggested_sections=(AnswerSection.EVIDENCE,),
        evidence_refs=refs,
        confidence=confidence,
    )


def _route() -> AnswerPlanningRoute:
    return AnswerPlanningRoute(
        primary_agent="Forseti",
        candidates=(PlanningCandidate("Freyr", 0.9), PlanningCandidate("Njord", 0.8)),
    )


async def _run(results: dict[str, AnswerContribution]):
    return await run_answer_planning_round(
        prompt=PROMPT,
        plan=build_answer_plan("deployment failure", intent=AnswerIntent.WHY),
        route=_route(),
        provider=_Provider(results),
    )


def _contradiction() -> dict[str, AnswerContribution]:
    return {
        "Freyr": _contribution(
            "Freyr",
            claim="The rollout exhausted capacity",
            refs=(SHARED_REF, "metric:capacity"),
            confidence=0.95,
        ),
        "Njord": _contribution(
            "Njord",
            claim="The rollout did not exhaust capacity",
            refs=(SHARED_REF, "cost:budget"),
            confidence=0.60,
        ),
    }


@pytest.mark.asyncio
async def test_contradiction_preserves_both_contributors_and_evidence_sets() -> None:
    result = await _run(_contradiction())

    assert [contribution.agent for contribution in result.contributions] == ["Freyr", "Njord"]
    collected = {ref for item in result.contributions for ref in item.evidence_refs}
    assert collected == {SHARED_REF, "metric:capacity", "cost:budget"}
    assert result.unique_evidence_count == 3
    assert result.duplicate_evidence_count == 1
    assert result.conflicting_evidence_refs == (SHARED_REF,)
    assert result.status is PlanningStatus.DEGRADED


@pytest.mark.asyncio
async def test_contradiction_never_selects_a_winner_by_confidence() -> None:
    result = await _run(_contradiction())

    claims = {
        contribution.agent: contribution.facts[0].claim for contribution in result.contributions
    }
    assert claims == {
        "Freyr": "The rollout exhausted capacity",
        "Njord": "The rollout did not exhaust capacity",
    }


@pytest.mark.asyncio
async def test_contradiction_cannot_change_the_primary_verified_answer() -> None:
    result = await _run(_contradiction())
    record = result.to_dict()

    assert result.primary_agent == "Forseti"
    assert record["primary_agent"] == "Forseti"
    assert record["mode"] == "shadow"
    assert "Forseti" not in result.consulted_agents


@pytest.mark.asyncio
async def test_conflict_record_carries_no_authority_or_reasoning_field() -> None:
    result = await _run(
        {
            "Freyr": _contribution(
                "Freyr",
                claim="The rollout exhausted capacity",
                refs=(SHARED_REF,),
                caveats=("internal contributor reasoning stays out of the record",),
            ),
            "Njord": _contribution(
                "Njord",
                claim="The rollout did not exhaust capacity",
                refs=(SHARED_REF,),
            ),
        }
    )
    record = result.to_dict()
    contributions = record["contributions"]

    assert set(record) == set(SHADOW_RECORD_KEYS)
    assert isinstance(contributions, list)
    for entry in contributions:
        assert isinstance(entry, dict)
        assert set(entry) == set(SHADOW_CONTRIBUTION_KEYS)
    forbidden = ("approv", "execut", "authoriz", "promot", "override", "decision", "verdict")
    assert not [key for key in SHADOW_RECORD_KEYS if any(token in key for token in forbidden)]
    assert PROMPT not in str(record)
    assert "internal contributor reasoning" not in str(record)


@pytest.mark.asyncio
async def test_cross_domain_conflict_on_distinct_refs_keeps_both_evidence_sets() -> None:
    result = await _run(
        {
            "Freyr": _contribution(
                "Freyr",
                claim="Capacity headroom is exhausted",
                refs=("metric:capacity",),
            ),
            "Njord": _contribution(
                "Njord",
                claim="Budget headroom is available",
                refs=("cost:budget",),
            ),
        }
    )

    assert result.conflicting_evidence_refs == ()
    assert result.status is PlanningStatus.COMPLETED
    assert result.unique_evidence_count == 2
    assert [contribution.agent for contribution in result.contributions] == ["Freyr", "Njord"]


@pytest.mark.asyncio
async def test_conflicting_contributor_cannot_add_a_section_outside_the_plan() -> None:
    plan = build_answer_plan("deployment failure", intent=AnswerIntent.WHY)
    result = await run_answer_planning_round(
        prompt=PROMPT,
        plan=plan,
        route=_route(),
        provider=_Provider(
            {
                "Freyr": AnswerContribution(
                    agent="Freyr",
                    facts=(GroundedFact("The rollout exhausted capacity", SHARED_REF),),
                    caveats=(),
                    suggested_sections=tuple(AnswerSection)[:12],
                    evidence_refs=(SHARED_REF,),
                    confidence=0.9,
                ),
                "Njord": _contribution(
                    "Njord",
                    claim="The rollout did not exhaust capacity",
                    refs=(SHARED_REF,),
                ),
            }
        ),
    )

    assert set(result.covered_sections) <= set(plan.sections)

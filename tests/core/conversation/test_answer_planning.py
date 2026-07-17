"""Bounded shadow Answer Planning Round tests."""

from __future__ import annotations

import asyncio

import pytest

from fdai.core.conversation.answer_plan import AnswerSection, build_answer_plan
from fdai.core.conversation.answer_planning import (
    AnswerContribution,
    AnswerPlanningConfig,
    AnswerPlanningRoute,
    GroundedFact,
    PlanningCandidate,
    PlanningStatus,
    run_answer_planning_round,
)


class _Provider:
    def __init__(self, results: dict[str, AnswerContribution | None | BaseException]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []
        self.blocked = asyncio.Event()

    async def contribute(
        self,
        *,
        agent: str,
        prompt: str,  # noqa: ARG002
        max_tokens: int,
    ) -> AnswerContribution | None:
        self.calls.append((agent, max_tokens))
        result = self.results[agent]
        if isinstance(result, _Block):
            await self.blocked.wait()
            return None
        if isinstance(result, BaseException):
            raise result
        return result


class _Block(BaseException):
    pass


def _contribution(
    agent: str,
    *,
    evidence: tuple[str, ...],
    section: AnswerSection = AnswerSection.EVIDENCE,
) -> AnswerContribution:
    return AnswerContribution(
        agent=agent,
        facts=tuple(GroundedFact(f"Fact grounded by {ref}", ref) for ref in evidence),
        caveats=(),
        suggested_sections=(section,),
        evidence_refs=evidence,
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_collects_two_contributors_in_score_order_and_measures_duplicates() -> None:
    provider = _Provider(
        {
            "Freyr": _contribution("Freyr", evidence=("metric:capacity", "shared:1")),
            "Njord": _contribution("Njord", evidence=("cost:scope", "shared:1")),
        }
    )
    route = AnswerPlanningRoute(
        primary_agent="Forseti",
        candidates=(
            PlanningCandidate("Njord", 0.7),
            PlanningCandidate("Freyr", 0.9),
            PlanningCandidate("Loki", 0.1),
        ),
    )

    result = await run_answer_planning_round(
        prompt="Why was this denied?",
        plan=build_answer_plan("Why was this denied?"),
        route=route,
        provider=provider,
    )

    assert result.status is PlanningStatus.COMPLETED
    assert result.consulted_agents == ("Freyr", "Njord")
    assert tuple(item.agent for item in result.contributions) == ("Freyr", "Njord")
    assert result.unique_evidence_count == 3
    assert result.duplicate_evidence_count == 1
    assert result.conflicting_evidence_refs == ()
    assert result.covered_sections == (AnswerSection.EVIDENCE,)
    assert 0 < result.estimated_added_tokens <= 800
    assert result.to_dict()["budget"] == {
        "max_contributors": 2,
        "max_rounds": 1,
        "max_wall_ms": 1200,
        "max_added_tokens": 800,
        "nested_rounds": False,
    }
    assert sorted(provider.calls) == [("Freyr", 400), ("Njord", 400)]


@pytest.mark.asyncio
async def test_conflicting_claims_for_one_evidence_ref_degrade_without_picking_a_winner() -> None:
    shared_ref = "metric:capacity"
    provider = _Provider(
        {
            "Freyr": AnswerContribution(
                agent="Freyr",
                facts=(GroundedFact("Capacity is exhausted", shared_ref),),
                caveats=(),
                suggested_sections=(AnswerSection.EVIDENCE,),
                evidence_refs=(shared_ref,),
                confidence=0.9,
            ),
            "Njord": AnswerContribution(
                agent="Njord",
                facts=(GroundedFact("Capacity is available", shared_ref),),
                caveats=(),
                suggested_sections=(AnswerSection.EVIDENCE,),
                evidence_refs=(shared_ref,),
                confidence=0.9,
            ),
        }
    )

    result = await run_answer_planning_round(
        prompt="Why was this denied?",
        plan=build_answer_plan("Why was this denied?"),
        route=AnswerPlanningRoute(
            primary_agent="Forseti",
            candidates=(PlanningCandidate("Freyr", 0.9), PlanningCandidate("Njord", 0.8)),
        ),
        provider=provider,
    )

    assert result.status is PlanningStatus.DEGRADED
    assert result.conflicting_evidence_refs == (shared_ref,)
    assert result.to_dict()["conflicting_evidence_refs"] == [shared_ref]


@pytest.mark.asyncio
async def test_timeout_and_error_degrade_without_raising() -> None:
    provider = _Provider({"Freyr": _Block(), "Njord": RuntimeError("private detail")})
    result = await run_answer_planning_round(
        prompt="Diagnose this failure",
        plan=build_answer_plan("Diagnose this failure"),
        route=AnswerPlanningRoute(
            primary_agent="Heimdall",
            candidates=(PlanningCandidate("Freyr", 0.9), PlanningCandidate("Njord", 0.8)),
        ),
        provider=provider,
        config=AnswerPlanningConfig(max_wall_ms=10),
    )

    assert result.status is PlanningStatus.TIMED_OUT
    assert result.contributions == ()
    assert {(item.agent, item.kind) for item in result.failures} == {
        ("Freyr", "timeout"),
        ("Njord", "error"),
    }
    assert "private detail" not in str(result.to_dict())


@pytest.mark.asyncio
async def test_abstention_is_degraded_and_duplicate_candidates_are_called_once() -> None:
    provider = _Provider({"Njord": None})
    result = await run_answer_planning_round(
        prompt="Compare capacity and cost",
        plan=build_answer_plan("Compare capacity and cost"),
        route=AnswerPlanningRoute(
            primary_agent="Freyr",
            candidates=(
                PlanningCandidate("Njord", 0.7),
                PlanningCandidate("Njord", 0.9),
            ),
        ),
        provider=provider,
    )

    assert result.status is PlanningStatus.DEGRADED
    assert result.failures[0].kind == "abstained"
    assert provider.calls == [("Njord", 800)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "nested", "reason"),
    [
        ("Show current status", False, "not_eligible"),
        ("Why was this denied?", True, "nested_round_forbidden"),
        ("Briefly compare T1 and T2", False, "not_eligible"),
    ],
)
async def test_simple_brief_and_nested_rounds_are_skipped(
    prompt: str,
    nested: bool,
    reason: str,
) -> None:
    provider = _Provider({"Njord": _contribution("Njord", evidence=("cost:1",))})
    result = await run_answer_planning_round(
        prompt=prompt,
        plan=build_answer_plan(prompt),
        route=AnswerPlanningRoute(
            primary_agent="Forseti",
            candidates=(PlanningCandidate("Njord", 0.8),),
        ),
        provider=provider,
        nested=nested,
    )

    assert result.status is PlanningStatus.SKIPPED
    assert result.reason == reason
    assert provider.calls == []


def test_contribution_requires_a_reference_for_every_fact() -> None:
    with pytest.raises(ValueError, match="every GroundedFact"):
        AnswerContribution(
            agent="Njord",
            facts=(GroundedFact("cost fact", "cost:1"),),
            caveats=(),
            suggested_sections=(),
            evidence_refs=(),
            confidence=0.8,
        )


@pytest.mark.parametrize(
    "config",
    [
        {"max_contributors": 3},
        {"max_rounds": 2},
        {"max_wall_ms": 1_201},
        {"max_added_tokens": 801},
        {"nested_rounds": True},
    ],
)
def test_shipping_budgets_cannot_be_widened(config: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AnswerPlanningConfig(**config)

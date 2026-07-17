"""Bounded shadow planning for complementary agent-owned answer evidence."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation.answer_plan import AnswerIntent, AnswerPlan, AnswerSection, DetailLevel

_MULTI_PERSPECTIVE = re.compile(
    r"\b(multiple|several|different)\s+(?:agent\s+)?perspectives?\b"
    r"|\bask\s+\w+\s+and\s+\w+\b"
    r"|여러\s*(?:agent|에이전트)?\s*(?:관점|의견)"
    r"|다각도|복수\s*(?:관점|의견)",
    re.IGNORECASE,
)


class PlanningStatus(StrEnum):
    SKIPPED = "skipped"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class GroundedFact:
    claim: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.claim.strip() or len(self.claim) > 2_000:
            raise ValueError("GroundedFact.claim MUST contain 1-2000 characters")
        if not self.evidence_ref.strip() or len(self.evidence_ref) > 512:
            raise ValueError("GroundedFact.evidence_ref MUST contain 1-512 characters")


@dataclass(frozen=True, slots=True)
class AnswerContribution:
    agent: str
    facts: tuple[GroundedFact, ...]
    caveats: tuple[str, ...]
    suggested_sections: tuple[AnswerSection, ...]
    evidence_refs: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.agent.strip() or len(self.agent) > 64:
            raise ValueError("AnswerContribution.agent MUST contain 1-64 characters")
        if len(self.facts) > 32 or len(self.caveats) > 8:
            raise ValueError("AnswerContribution fact or caveat cap exceeded")
        if len(self.suggested_sections) > 12 or len(self.evidence_refs) > 32:
            raise ValueError("AnswerContribution section or evidence cap exceeded")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AnswerContribution.confidence MUST be in [0, 1]")
        if any(not item.strip() or len(item) > 1_000 for item in self.caveats):
            raise ValueError("AnswerContribution.caveats MUST contain 1-1000 characters")
        if any(not item.strip() or len(item) > 512 for item in self.evidence_refs):
            raise ValueError("AnswerContribution.evidence_refs MUST contain 1-512 characters")
        fact_refs = {fact.evidence_ref for fact in self.facts}
        if not fact_refs.issubset(set(self.evidence_refs)):
            raise ValueError("every GroundedFact reference MUST appear in evidence_refs")


@dataclass(frozen=True, slots=True)
class PlanningCandidate:
    agent: str
    score: float


@dataclass(frozen=True, slots=True)
class AnswerPlanningRoute:
    primary_agent: str | None
    candidates: tuple[PlanningCandidate, ...]
    confidence: float | None = None
    margin: float | None = None


@dataclass(frozen=True, slots=True)
class AnswerPlanningConfig:
    max_contributors: int = 2
    max_rounds: int = 1
    max_wall_ms: int = 1_200
    max_added_tokens: int = 800
    nested_rounds: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.max_contributors <= 2:
            raise ValueError("max_contributors MUST be in [1, 2]")
        if self.max_rounds != 1:
            raise ValueError("max_rounds MUST equal 1")
        if not 1 <= self.max_wall_ms <= 1_200:
            raise ValueError("max_wall_ms MUST be in [1, 1200]")
        if not 1 <= self.max_added_tokens <= 800:
            raise ValueError("max_added_tokens MUST be in [1, 800]")
        if self.nested_rounds:
            raise ValueError("nested_rounds MUST be false")


class AnswerPlanningProvider(Protocol):
    async def contribute(
        self,
        *,
        agent: str,
        prompt: str,
        max_tokens: int,
    ) -> AnswerContribution | None: ...


@dataclass(frozen=True, slots=True)
class ContributorFailure:
    agent: str
    kind: str


@dataclass(frozen=True, slots=True)
class AnswerPlanningResult:
    status: PlanningStatus
    primary_agent: str | None
    consulted_agents: tuple[str, ...]
    contributions: tuple[AnswerContribution, ...]
    failures: tuple[ContributorFailure, ...]
    elapsed_ms: int
    unique_evidence_count: int
    duplicate_evidence_count: int
    conflicting_evidence_refs: tuple[str, ...]
    covered_sections: tuple[AnswerSection, ...]
    estimated_added_tokens: int
    budget: AnswerPlanningConfig
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": "shadow",
            "status": self.status.value,
            "primary_agent": self.primary_agent,
            "consulted_agents": list(self.consulted_agents),
            "contributions": [
                {
                    "agent": contribution.agent,
                    "evidence_refs": list(contribution.evidence_refs),
                    "confidence": contribution.confidence,
                    "suggested_sections": [
                        section.value for section in contribution.suggested_sections
                    ],
                }
                for contribution in self.contributions
            ],
            "failures": [
                {"agent": failure.agent, "kind": failure.kind} for failure in self.failures
            ],
            "elapsed_ms": self.elapsed_ms,
            "unique_evidence_count": self.unique_evidence_count,
            "duplicate_evidence_count": self.duplicate_evidence_count,
            "conflicting_evidence_refs": list(self.conflicting_evidence_refs),
            "covered_sections": [section.value for section in self.covered_sections],
            "estimated_added_tokens": self.estimated_added_tokens,
            "budget": {
                "max_contributors": self.budget.max_contributors,
                "max_rounds": self.budget.max_rounds,
                "max_wall_ms": self.budget.max_wall_ms,
                "max_added_tokens": self.budget.max_added_tokens,
                "nested_rounds": self.budget.nested_rounds,
            },
            "reason": self.reason,
        }


async def run_answer_planning_round(
    *,
    prompt: str,
    plan: AnswerPlan,
    route: AnswerPlanningRoute,
    provider: AnswerPlanningProvider,
    config: AnswerPlanningConfig | None = None,
    nested: bool = False,
) -> AnswerPlanningResult:
    """Collect complementary evidence without changing the terminal answer."""
    effective_config = config or AnswerPlanningConfig()
    started = time.monotonic()
    if nested:
        return _skipped(route.primary_agent, "nested_round_forbidden", effective_config)
    if not should_run_shadow_round(prompt=prompt, plan=plan, route=route):
        return _skipped(route.primary_agent, "not_eligible", effective_config)

    selected = _select_candidates(route, effective_config.max_contributors)
    if not selected:
        return _skipped(
            route.primary_agent,
            "no_complementary_contributor",
            effective_config,
        )

    token_budget = max(1, effective_config.max_added_tokens // len(selected))
    tasks = {
        asyncio.create_task(
            provider.contribute(agent=candidate.agent, prompt=prompt, max_tokens=token_budget)
        ): candidate.agent
        for candidate in selected
    }
    done, pending = await asyncio.wait(
        tasks,
        timeout=effective_config.max_wall_ms / 1_000,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    contributions: dict[str, AnswerContribution] = {}
    failures: list[ContributorFailure] = [
        ContributorFailure(tasks[task], "timeout") for task in pending
    ]
    for task in done:
        agent = tasks[task]
        try:
            contribution = task.result()
        except Exception:  # noqa: BLE001 - one contributor never blocks the round
            failures.append(ContributorFailure(agent, "error"))
            continue
        if contribution is None:
            failures.append(ContributorFailure(agent, "abstained"))
        elif contribution.agent != agent:
            failures.append(ContributorFailure(agent, "agent_mismatch"))
        elif _estimated_tokens(contribution) > token_budget:
            failures.append(ContributorFailure(agent, "token_budget_exceeded"))
        else:
            contributions[agent] = contribution

    ordered = tuple(
        contributions[candidate.agent] for candidate in selected if candidate.agent in contributions
    )
    ordered_failures = tuple(
        sorted(failures, key=lambda failure: _candidate_order(failure.agent, selected))
    )
    evidence = [item for contribution in ordered for item in contribution.evidence_refs]
    unique_evidence = tuple(dict.fromkeys(evidence))
    conflicting_evidence_refs = _conflicting_evidence_refs(ordered)
    plan_sections = set(plan.sections)
    covered = tuple(
        section
        for section in plan.sections
        if section
        in {suggested for contribution in ordered for suggested in contribution.suggested_sections}
        and section in plan_sections
    )
    if pending:
        status = PlanningStatus.TIMED_OUT
    elif ordered_failures or conflicting_evidence_refs:
        status = PlanningStatus.DEGRADED
    else:
        status = PlanningStatus.COMPLETED
    return AnswerPlanningResult(
        status=status,
        primary_agent=route.primary_agent,
        consulted_agents=tuple(candidate.agent for candidate in selected),
        contributions=ordered,
        failures=ordered_failures,
        elapsed_ms=max(0, int((time.monotonic() - started) * 1_000)),
        unique_evidence_count=len(unique_evidence),
        duplicate_evidence_count=len(evidence) - len(unique_evidence),
        conflicting_evidence_refs=conflicting_evidence_refs,
        covered_sections=covered,
        estimated_added_tokens=sum(_estimated_tokens(item) for item in ordered),
        budget=effective_config,
    )


def should_run_shadow_round(
    *,
    prompt: str,
    plan: AnswerPlan,
    route: AnswerPlanningRoute,
) -> bool:
    if plan.detail_level is DetailLevel.BRIEF:
        return False
    if not any(candidate.agent != route.primary_agent for candidate in route.candidates):
        return False
    return (
        plan.intent
        in {
            AnswerIntent.WHY,
            AnswerIntent.COMPARISON,
            AnswerIntent.DIAGNOSIS,
        }
        or _MULTI_PERSPECTIVE.search(prompt) is not None
    )


def _select_candidates(
    route: AnswerPlanningRoute,
    limit: int,
) -> tuple[PlanningCandidate, ...]:
    deduplicated: dict[str, PlanningCandidate] = {}
    for candidate in route.candidates:
        if not candidate.agent.strip() or candidate.agent == route.primary_agent:
            continue
        current = deduplicated.get(candidate.agent)
        if current is None or candidate.score > current.score:
            deduplicated[candidate.agent] = candidate
    return tuple(
        sorted(deduplicated.values(), key=lambda candidate: (-candidate.score, candidate.agent))[
            :limit
        ]
    )


def _candidate_order(agent: str, selected: Sequence[PlanningCandidate]) -> int:
    return next(
        (index for index, candidate in enumerate(selected) if candidate.agent == agent),
        len(selected),
    )


def _estimated_tokens(contribution: AnswerContribution) -> int:
    characters = sum(len(fact.claim) + len(fact.evidence_ref) for fact in contribution.facts)
    characters += sum(len(item) for item in contribution.caveats)
    characters += sum(len(item) for item in contribution.evidence_refs)
    return max(1, (characters + 3) // 4)


def _conflicting_evidence_refs(
    contributions: Sequence[AnswerContribution],
) -> tuple[str, ...]:
    claims_by_ref: dict[str, set[str]] = {}
    for contribution in contributions:
        for fact in contribution.facts:
            claims_by_ref.setdefault(fact.evidence_ref, set()).add(
                " ".join(fact.claim.casefold().split())
            )
    return tuple(sorted(ref for ref, claims in claims_by_ref.items() if len(claims) > 1))


def _skipped(
    primary_agent: str | None,
    reason: str,
    config: AnswerPlanningConfig,
) -> AnswerPlanningResult:
    return AnswerPlanningResult(
        status=PlanningStatus.SKIPPED,
        primary_agent=primary_agent,
        consulted_agents=(),
        contributions=(),
        failures=(),
        elapsed_ms=0,
        unique_evidence_count=0,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=(),
        covered_sections=(),
        estimated_added_tokens=0,
        budget=config,
        reason=reason,
    )


__all__ = [
    "AnswerContribution",
    "AnswerPlanningConfig",
    "AnswerPlanningProvider",
    "AnswerPlanningResult",
    "AnswerPlanningRoute",
    "ContributorFailure",
    "GroundedFact",
    "PlanningCandidate",
    "PlanningStatus",
    "run_answer_planning_round",
    "should_run_shadow_round",
]

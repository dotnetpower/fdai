from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.learning import (
    GovernedPostTurnProposalRouter,
    OperatorMemoryCandidate,
    RuleCandidateHint,
    SkillProposalDraft,
)
from fdai.core.operator_memory import (
    InMemoryOperatorMemoryProposalStore,
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    OperatorMemoryProposalWorkshop,
    ScopeKind,
)
from fdai.core.skills import InMemorySkillProposalStore, SkillWorkshop, skill_body_digest

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


class _Audit:
    async def append(self, event: object) -> None:
        return None


class _Authorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return True


class _RuleHints:
    def __init__(self) -> None:
        self.hints: list[RuleCandidateHint] = []

    async def submit_rule_hint(
        self,
        hint: RuleCandidateHint,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str:
        assert proposed_by == "Norns"
        assert at == _NOW
        self.hints.append(hint)
        return "rule-hint:1"


def _router() -> tuple[GovernedPostTurnProposalRouter, _RuleHints]:
    audit = _Audit()
    rule_hints = _RuleHints()
    return (
        GovernedPostTurnProposalRouter(
            operator_memory=OperatorMemoryProposalWorkshop(
                proposals=InMemoryOperatorMemoryProposalStore(),
                memory=InMemoryOperatorMemoryStore(),
                audit=audit,  # type: ignore[arg-type]
                authorizer=_Authorizer(),
            ),
            skills=SkillWorkshop(
                store=InMemorySkillProposalStore(),
                audit=audit,  # type: ignore[arg-type]
                authorizer=_Authorizer(),
            ),
            rule_hints=rule_hints,
        ),
        rule_hints,
    )


async def test_routes_operator_memory_to_unapproved_workshop() -> None:
    router, _ = _router()

    proposal_ref = await router.route(
        OperatorMemoryCandidate(
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource-hash-1",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Use the scoped query before escalation.",
            evidence_refs=("audit:1",),
            confidence=0.9,
        ),
        proposed_by="Norns",
        at=_NOW,
    )

    assert proposal_ref.startswith("operator-memory-proposal:")


async def test_routes_skill_to_existing_skill_workshop() -> None:
    router, _ = _router()
    body = "Review bounded incident evidence and cite its audit references."
    markdown = f"""---
name: incident-review
version: 1.0.0
description: Review bounded incident evidence.
source: fdai.post-turn-review
body_sha256: "{skill_body_digest(body)}"
required_tools: []
allowed_agents: [Norns]
---
{body}
""".encode()

    proposal_ref = await router.route(
        SkillProposalDraft(
            skill_name="incident-review",
            markdown=markdown,
            evidence_refs=("audit:1",),
            confidence=0.9,
        ),
        proposed_by="Norns",
        at=_NOW,
    )

    assert proposal_ref.startswith("skill-proposal:")


async def test_rule_hint_stays_behind_norns_owned_submitter() -> None:
    router, submitter = _router()
    hint = RuleCandidateHint(
        proposal_kind="revision",
        target_ref="rule-1",
        pattern="Repeated correction indicates a narrower condition.",
        evidence_refs=("audit:1",),
        confidence=0.8,
    )

    proposal_ref = await router.route(hint, proposed_by="Norns", at=_NOW)

    assert proposal_ref == "rule-hint:1"
    assert submitter.hints == [hint]

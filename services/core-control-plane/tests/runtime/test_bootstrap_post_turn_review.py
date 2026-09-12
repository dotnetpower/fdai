"""Exercise inert post-turn proposals through the production bootstrap binding."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fdai.agents import Mimir, Norns, PantheonRuntime
from fdai.core.learning import (
    PostTurnProposal,
    PostTurnReviewInput,
    PostTurnReviewState,
    RuleCandidateHint,
    SkillProposalDraft,
    review_input_to_mapping,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.core.skills import skill_body_digest
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.bootstrap_pantheon import _bind_post_turn_learning
from fdai.runtime.discovery_activation import build_discovery_activation_runtime
from fdai.runtime.post_turn_review import build_post_turn_review_runtime
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_POST_TURN_TOPIC = "object.post-turn-review"


class _Model:
    def __init__(self, identity: str, family: str, proposal: PostTurnProposal) -> None:
        self.model_identity = identity
        self.model_family = family
        self.proposal = proposal
        self.inputs: list[PostTurnReviewInput] = []

    async def propose(self, review_input: PostTurnReviewInput) -> PostTurnProposal:
        self.inputs.append(review_input)
        return self.proposal


class _ReviewBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.consumed = 0
        self.replayed = asyncio.Event()

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        async for envelope in super()._subscribe(topic, group_id):
            yield envelope
            if topic == _POST_TURN_TOPIC:
                self.consumed += 1
                if self.consumed == 2:
                    self.replayed.set()


def _proposal(kind: str) -> PostTurnProposal:
    if kind == "rule_hint":
        return RuleCandidateHint(
            proposal_kind="new",
            target_ref="procedure.repeated-investigation",
            pattern="Use the resource-scoped query before escalation.",
            evidence_refs=("audit:1",),
            confidence=0.9,
        )
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
    return SkillProposalDraft(
        skill_name="incident-review",
        markdown=markdown,
        evidence_refs=("audit:1",),
        confidence=0.9,
    )


def _catalog_snapshot() -> dict[str, str]:
    root = Path(__file__).resolve().parents[4] / "rule-catalog"
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("kind", ["rule_hint", "skill_draft"])
async def test_bootstrap_keeps_replayed_bragi_proposals_inert_when_discovery_disabled(
    kind: str,
) -> None:
    state_store = InMemoryStateStore()
    proposal = _proposal(kind)
    models = (
        _Model("model-a", "family-a", proposal),
        _Model("model-b", "family-b", proposal),
    )
    review_runtime = build_post_turn_review_runtime(
        state_store=state_store,
        operator_memory=InMemoryOperatorMemoryStore(),
        models=models,
        now=lambda: _NOW,
    )
    provider = _ReviewBus()
    pantheon = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="runtime.raw-events",
        post_turn_review=review_runtime.coordinator,
    )
    activation = build_discovery_activation_runtime(
        state_store=state_store,
        runtime_settings=RuntimeSettingsService(
            store=state_store,
            env={"FDAI_DISCOVERY_ENABLED": "false"},
        ),
        startup_readiness=RuntimeReadinessState(),
    )
    activation.clock = lambda: _NOW
    report = await _bind_post_turn_learning(
        pantheon_runtime=pantheon,
        post_turn_review=review_runtime,
        discovery_activation=activation,
    )
    assert report is not None
    assert not activation.is_enabled()
    review_input = PostTurnReviewInput(
        review_id="review-bootstrap-1",
        principal_scope="principal-hash-1",
        operator_turn_id="operator-turn-1",
        assistant_turn_id="assistant-turn-1",
        completed_at=_NOW,
        operator_body="Inspect the bounded incident evidence.",
        assistant_body="The bounded inspection completed.",
        evidence_refs=("audit:1",),
        procedure_fingerprint="procedure.repeated-investigation",
        repeated_procedure_count=3,
    )
    payload = {
        "producer_principal": "Bragi",
        "kind": "post_turn_review",
        "review": review_input_to_mapping(review_input),
    }
    catalog_before = _catalog_snapshot()
    assert catalog_before
    for _ in range(2):
        await provider.publish(_POST_TURN_TOPIC, review_input.principal_scope, payload)

    run_task = asyncio.create_task(pantheon.run())
    try:
        await asyncio.wait_for(provider.replayed.wait(), timeout=5)
    finally:
        await pantheon.stop()
        run_task.cancel()
        with suppress(asyncio.CancelledError):
            await run_task

    records = await review_runtime.reviews.list()
    assert len(records) == 1
    assert records[0].state is PostTurnReviewState.ROUTED
    assert records[0].reasons == ("proposal_routed",)
    assert records[0].proposal_kind is proposal.kind
    assert all(model.inputs == [review_input] for model in models)
    norns = pantheon.agents["Norns"]
    mimir = pantheon.agents["Mimir"]
    assert isinstance(norns, Norns)
    assert isinstance(mimir, Mimir)
    drafts = await review_runtime.skill_proposals.list()
    if kind == "rule_hint":
        assert len(norns.pending_candidates) == 1
        assert norns.pending_candidates[0]["source_signal"] == "post_turn_review"
        assert drafts == ()
    else:
        assert norns.pending_candidates == []
        assert len(drafts) == 1
        assert drafts[0].state.value == "draft"
        assert drafts[0].evidence_refs == ("audit:1",)
    assert mimir.pending_candidates() == ()
    assert await review_runtime.memory_proposals.list() == ()
    for topic in ("object.rule-candidate", "object.rule", f"{_POST_TURN_TOPIC}.dlq"):
        assert [event async for event in provider.subscribe(topic, "assert-inert")] == []
    assert not activation.is_enabled()
    assert _catalog_snapshot() == catalog_before

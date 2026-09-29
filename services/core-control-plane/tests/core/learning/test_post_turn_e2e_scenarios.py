"""Repository-local end-to-end evidence for inert post-turn review routing."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fdai.agents import Mimir, Norns, PantheonRuntime
from fdai.core.learning import (
    OperatorMemoryCandidate,
    PostTurnProposal,
    PostTurnReviewInput,
    PostTurnReviewState,
    RuleCandidateHint,
    SkillProposalDraft,
    ToolReceiptEvidence,
    review_input_to_mapping,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore, MemoryCategory, ScopeKind
from fdai.core.skills import skill_body_digest
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.bootstrap_pantheon import _bind_post_turn_learning
from fdai.runtime.discovery_activation import build_discovery_activation_runtime
from fdai.runtime.post_turn_review import PostTurnReviewRuntime, build_post_turn_review_runtime
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[5]
RULE_CATALOG = REPO_ROOT / "rule-catalog"
NOW = datetime(2026, 9, 29, 1, tzinfo=UTC)
POST_TURN_TOPIC = "object.post-turn-review"


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
    def __init__(self, *, expected: int) -> None:
        super().__init__()
        self._expected = expected
        self.consumed = 0
        self.done = asyncio.Event()

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        async for envelope in super()._subscribe(topic, group_id):
            yield envelope
            if topic == POST_TURN_TOPIC:
                self.consumed += 1
                if self.consumed >= self._expected:
                    self.done.set()


def _validation_dsn() -> str:
    dsn = os.environ.get("FDAI_VALIDATION_DATABASE_URL")
    if not dsn:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is unset")
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled test command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _catalog_snapshot() -> dict[str, str]:
    return {
        str(path.relative_to(RULE_CATALOG)): sha256(path.read_bytes()).hexdigest()
        for path in RULE_CATALOG.rglob("*")
        if path.is_file()
    }


def _skill_proposal(name: str) -> SkillProposalDraft:
    body = "Prefer the bounded incident evidence query and cite the audit references."
    markdown = f"""---
name: {name}
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
        skill_name=name,
        markdown=markdown,
        evidence_refs=("audit:scenario",),
        confidence=0.9,
    )


async def _run_scenario(
    *,
    review_input: PostTurnReviewInput,
    proposal: PostTurnProposal,
    duplicate_delivery: bool = False,
) -> tuple[PostTurnReviewRuntime, PantheonRuntime, tuple[_Model, _Model]]:
    dsn = _validation_dsn()
    _upgrade_head()
    state_store = InMemoryStateStore()
    models = (
        _Model("model-a", "family-a", proposal),
        _Model("model-b", "family-b", proposal),
    )
    runtime = build_post_turn_review_runtime(
        state_store=state_store,
        operator_memory=InMemoryOperatorMemoryStore(),
        models=models,
        dsn=dsn,
        now=lambda: NOW,
    )
    provider = _ReviewBus(expected=2 if duplicate_delivery else 1)
    pantheon = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="runtime.raw-events",
        post_turn_review=runtime.coordinator,
    )
    activation = build_discovery_activation_runtime(
        state_store=state_store,
        runtime_settings=RuntimeSettingsService(
            store=state_store,
            env={"FDAI_DISCOVERY_ENABLED": "false"},
        ),
        startup_readiness=RuntimeReadinessState(),
    )
    activation.clock = lambda: NOW
    report = await _bind_post_turn_learning(
        pantheon_runtime=pantheon,
        post_turn_review=runtime,
        discovery_activation=activation,
    )
    assert report is not None
    payload = {
        "producer_principal": "Bragi",
        "kind": "post_turn_review",
        "review": review_input_to_mapping(review_input),
    }
    catalog_before = _catalog_snapshot()
    for _ in range(2 if duplicate_delivery else 1):
        await provider.publish(POST_TURN_TOPIC, review_input.principal_scope, payload)
    run_task = asyncio.create_task(pantheon.run())
    try:
        await asyncio.wait_for(provider.done.wait(), timeout=10)
    finally:
        await pantheon.stop()
        run_task.cancel()
        with suppress(asyncio.CancelledError):
            await run_task
    assert _catalog_snapshot() == catalog_before
    assert not activation.is_enabled()
    return runtime, pantheon, models


@pytest.mark.integration
async def test_complex_tool_recovery_routes_memory_draft_without_active_mutation() -> None:
    suffix = uuid.uuid4().hex[:12]
    proposal = OperatorMemoryCandidate(
        scope_kind=ScopeKind.RESOURCE,
        scope_ref=f"resource-{suffix}",
        category=MemoryCategory.RUNBOOK_HINT,
        body="Use the recovery evidence query before repeating the tool sequence.",
        evidence_refs=("audit:scenario",),
        confidence=0.9,
    )
    review_input = PostTurnReviewInput(
        review_id=f"review-recovery-{suffix}",
        principal_scope=f"principal-{suffix}",
        operator_turn_id=f"operator-{suffix}",
        assistant_turn_id=f"assistant-{suffix}",
        completed_at=NOW,
        operator_body="Recover the failed investigation tool chain.",
        assistant_body="The investigation recovered and returned verified evidence.",
        tool_receipts=tuple(
            ToolReceiptEvidence(
                tool_name=f"query.tool{index}",
                status="success",
                evidence_ref=f"audit:tool{index}",
            )
            for index in range(5)
        ),
        evidence_refs=("audit:scenario",),
        memory_scope_kind=ScopeKind.RESOURCE,
        memory_scope_ref=f"resource-{suffix}",
        failure_recovered=True,
    )

    runtime, pantheon, models = await _run_scenario(
        review_input=review_input,
        proposal=proposal,
    )

    record = await runtime.reviews.get(review_input.review_id)
    assert record.state is PostTurnReviewState.ROUTED
    assert record.proposal_kind is proposal.kind
    memory_proposals = await runtime.memory_proposals.list()
    assert any(item.scope_ref == f"resource-{suffix}" for item in memory_proposals)
    assert isinstance(pantheon.agents["Mimir"], Mimir)
    assert pantheon.agents["Mimir"].pending_candidates() == ()
    assert all(model.inputs == [review_input] for model in models)


@pytest.mark.integration
async def test_explicit_correction_routes_disabled_skill_draft_without_active_mutation() -> None:
    suffix = uuid.uuid4().hex[:12]
    proposal = _skill_proposal(f"incident-review-{suffix}")
    review_input = PostTurnReviewInput(
        review_id=f"review-correction-{suffix}",
        principal_scope=f"principal-{suffix}",
        operator_turn_id=f"operator-{suffix}",
        assistant_turn_id=f"assistant-{suffix}",
        completed_at=NOW,
        operator_body="Inspect this incident.",
        assistant_body="The bounded inspection completed.",
        explicit_corrections=("Use the incident-scoped query next time.",),
        evidence_refs=("audit:scenario",),
    )

    runtime, pantheon, _ = await _run_scenario(review_input=review_input, proposal=proposal)

    record = await runtime.reviews.get(review_input.review_id)
    assert record.state is PostTurnReviewState.ROUTED
    drafts = tuple(
        item
        for item in await runtime.skill_proposals.list()
        if item.skill_name == proposal.skill_name
    )
    assert len(drafts) == 1
    assert drafts[0].state.value == "draft"
    assert drafts[0].evidence_refs == ("audit:scenario",)
    assert isinstance(pantheon.agents["Norns"], Norns)
    assert pantheon.agents["Norns"].pending_candidates == []
    assert pantheon.agents["Mimir"].pending_candidates() == ()


@pytest.mark.integration
async def test_repeated_procedure_rule_hint_routes_once_without_policy_mutation() -> None:
    suffix = uuid.uuid4().hex[:12]
    proposal = RuleCandidateHint(
        proposal_kind="new",
        target_ref=f"procedure.{suffix}",
        pattern="Repeated incident investigation should start with the scoped evidence query.",
        evidence_refs=("audit:scenario",),
        confidence=0.9,
    )
    review_input = PostTurnReviewInput(
        review_id=f"review-repeated-{suffix}",
        principal_scope=f"principal-{suffix}",
        operator_turn_id=f"operator-{suffix}",
        assistant_turn_id=f"assistant-{suffix}",
        completed_at=NOW,
        operator_body="Run the same investigation again.",
        assistant_body="The repeated procedure completed.",
        evidence_refs=("audit:scenario",),
        procedure_fingerprint=f"procedure.{suffix}",
        repeated_procedure_count=3,
    )

    runtime, pantheon, models = await _run_scenario(
        review_input=review_input,
        proposal=proposal,
        duplicate_delivery=True,
    )

    record = await runtime.reviews.get(review_input.review_id)
    assert record.state is PostTurnReviewState.ROUTED
    norns = pantheon.agents["Norns"]
    assert isinstance(norns, Norns)
    assert len(norns.pending_candidates) == 1
    assert norns.pending_candidates[0]["source_signal"] == "post_turn_review"
    assert pantheon.agents["Mimir"].pending_candidates() == ()
    assert all(suffix not in item.skill_name for item in await runtime.skill_proposals.list())
    assert len(await runtime.reviews.list()) >= 1
    assert all(model.inputs == [review_input] for model in models)

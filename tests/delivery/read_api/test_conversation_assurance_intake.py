from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import cast

import pytest

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    ChatPolicyCandidate,
    ConversationAssuranceCoordinator,
    InMemoryConversationAssuranceLedger,
    assurance_principal_scope,
)
from fdai.delivery.read_api.routes.chat_history import replay_metadata
from fdai.delivery.read_api.routes.conversation_assurance_intake import (
    ConversationAssurancePostTurnSubmitter,
    ConversationAssuranceQueueConfig,
)
from fdai.delivery.read_api.routes.post_turn_review import PostTurnReviewSubmission
from fdai.shared.providers.user_context import ConversationTurnRecord, ConversationTurnRole

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _turn(
    role: ConversationTurnRole,
    content: str,
    metadata: dict[str, str] | None = None,
) -> ConversationTurnRecord:
    suffix = role.value
    return ConversationTurnRecord(
        turn_id=f"turn-{suffix}",
        conversation_id="conversation-1",
        principal_id="operator-1",
        turn_index=0 if role is ConversationTurnRole.OPERATOR else 1,
        role=role,
        content=content,
        recorded_at=_NOW,
        idempotency_key=f"request-1:{suffix}",
        metadata=metadata or {},
    )


async def test_intake_assesses_completed_turn_off_path() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
        now=lambda: _NOW,
    )
    payload = {
        "answer": "One verified resource changed.",
        "model": "narrator-model",
        "source": "evidence:verified",
        "verification": {
            "status": "verified",
            "authority": "server_inventory_graph",
            "checks_completed": 1,
            "checks_total": 1,
            "evidence_refs": ["evidence:1"],
            "failed_claim_ids": [],
        },
    }
    assistant = _turn(
        ConversationTurnRole.ASSISTANT,
        payload["answer"],
        replay_metadata(model="narrator-model", payload=payload),
    )
    submitter = ConversationAssurancePostTurnSubmitter(coordinator=coordinator)

    assert submitter.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "What changed?"),
        assistant_turn=assistant,
        submission=PostTurnReviewSubmission(
            validation_outcomes=("verified",),
            evidence_refs=("evidence:1",),
        ),
    )
    await submitter.close()

    records = await ledger.list_assessments(principal_scope=assurance_principal_scope("operator-1"))
    assert len(records) == 1
    assert records[0].decision.verdict.value == "pass"
    assert json.loads(assistant.metadata["replay_payload"])["answer"] == assistant.content


class _FailingCoordinator:
    async def assess(self, _turn: object) -> None:
        raise RuntimeError("ledger unavailable")


async def test_intake_logs_assessment_failure_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=cast(ConversationAssuranceCoordinator, _FailingCoordinator())
    )

    with caplog.at_level(logging.WARNING):
        assert submitter.submit_nowait(
            operator_turn=_turn(ConversationTurnRole.OPERATOR, "What changed?"),
            assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "Unavailable."),
            submission=PostTurnReviewSubmission((), ()),
        )
        await submitter.close()

    assert "conversation_assurance_assessment_failed" in caplog.text


async def test_intake_logs_capacity_rejection(caplog: pytest.LogCaptureFixture) -> None:
    submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=cast(ConversationAssuranceCoordinator, _FailingCoordinator()),
        config=ConversationAssuranceQueueConfig(max_pending=1),
    )
    operator = _turn(ConversationTurnRole.OPERATOR, "What changed?")
    assistant = _turn(ConversationTurnRole.ASSISTANT, "Unavailable.")

    with caplog.at_level(logging.WARNING):
        assert submitter.submit_nowait(
            operator_turn=operator,
            assistant_turn=assistant,
            submission=PostTurnReviewSubmission((), ()),
        )
        assert not submitter.submit_nowait(
            operator_turn=operator,
            assistant_turn=assistant,
            submission=PostTurnReviewSubmission((), ()),
        )
        await submitter.close()

    assert "conversation_assurance_queue_full" in caplog.text


class _Lifecycle:
    def __init__(self) -> None:
        self.records: tuple[AssessmentRecord, ...] = ()

    async def run(
        self,
        records: tuple[AssessmentRecord, ...],
    ) -> tuple[ChatPolicyCandidate, ...]:
        self.records = records
        return ()


async def test_intake_runs_lifecycle_with_scoped_assessment_window() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    lifecycle = _Lifecycle()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
        now=lambda: _NOW,
    )
    submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=coordinator,
        ledger=ledger,
        lifecycle=lifecycle,
    )

    assert submitter.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "What changed?"),
        assistant_turn=_turn(ConversationTurnRole.ASSISTANT, "Unavailable."),
        submission=PostTurnReviewSubmission((), ()),
    )
    await submitter.close()

    assert len(lifecycle.records) == 1
    assert lifecycle.records[0].principal_scope == assurance_principal_scope("operator-1")

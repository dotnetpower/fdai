from __future__ import annotations

import json
from datetime import UTC, datetime

from fdai.core.conversation_assurance import (
    ConversationAssuranceCoordinator,
    InMemoryConversationAssuranceLedger,
    assurance_principal_scope,
)
from fdai.delivery.read_api.routes.chat_history import replay_metadata
from fdai.delivery.read_api.routes.conversation_assurance_intake import (
    ConversationAssurancePostTurnSubmitter,
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

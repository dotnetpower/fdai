from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    ChatPolicyCandidate,
    ConversationAssuranceCoordinator,
    InMemoryConversationAssuranceLedger,
    OntologyAdequacyReview,
    assurance_principal_scope,
)
from fdai.delivery.operator_api.routes.chat_history import replay_metadata
from fdai.delivery.operator_api.routes.conversation_assurance_intake import (
    ConversationAssurancePostTurnSubmitter,
    ConversationAssuranceQueueConfig,
)
from fdai.delivery.operator_api.routes.post_turn_review import PostTurnReviewSubmission
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
            "reason_code": "inventory_snapshot_grounded",
            "evidence_manifest": {
                "route_id": "inventory-route",
                "complete": True,
            },
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


async def test_intake_preserves_exact_unverified_reason_for_clustering() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
        now=lambda: _NOW,
    )
    payload = {
        "answer": "The relationship is not represented.",
        "source": "evidence:unverified",
        "verification": {
            "status": "unverified",
            "authority": "ontology_catalog",
            "checks_completed": 0,
            "checks_total": 1,
            "evidence_refs": ["ontology:release"],
            "failed_claim_ids": ["claim-1"],
            "reason_code": "unknown_link_type",
            "evidence_manifest": {
                "route_id": "ontology-route",
                "complete": True,
            },
        },
        "intent_graph": {
            "ontology_release": "sha256:" + "a" * 64,
            "graph_revision": "graph-1",
        },
    }
    assistant = _turn(
        ConversationTurnRole.ASSISTANT,
        payload["answer"],
        replay_metadata(model="narrator-model", payload=payload),
    )
    submitter = ConversationAssurancePostTurnSubmitter(coordinator=coordinator)

    assert submitter.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "What is related?"),
        assistant_turn=assistant,
        submission=PostTurnReviewSubmission(("unverified",), ("ontology:release",)),
    )
    await submitter.close()

    records = await ledger.list_assessments(principal_scope=assurance_principal_scope("operator-1"))
    assert records[0].decision.reasons == (
        "unsupported_atomic_claim",
        "verification_failed:unknown_link_type",
    )


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


class _Investigator:
    async def investigate(self, turn: object, attribution: object) -> OntologyAdequacyReview:
        from fdai.core.conversation_assurance import build_ontology_adequacy_review

        return build_ontology_adequacy_review(
            attribution,  # type: ignore[arg-type]
            question_digest="q" * 64,
            replay_reproduced=False,
            routing_verified=True,
            identity_resolved=True,
        )


class _AdequacySink:
    def __init__(self) -> None:
        self.reviews: list[OntologyAdequacyReview] = []

    async def submit(self, review: OntologyAdequacyReview) -> None:
        self.reviews.append(review)


async def test_failed_ontology_turn_submits_separate_adequacy_review() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    sink = _AdequacySink()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
        now=lambda: _NOW,
    )
    payload = {
        "answer": "The relationship is not represented.",
        "source": "evidence:unverified",
        "verification": {
            "status": "unverified",
            "authority": "ontology_catalog",
            "checks_completed": 0,
            "checks_total": 1,
            "evidence_refs": ["ontology:release"],
            "failed_claim_ids": [],
            "reason_code": "unknown_link_type",
            "evidence_manifest": {"route_id": "ontology-route", "complete": True},
        },
        "intent_graph": {
            "ontology_release": "sha256:" + "a" * 64,
            "graph_revision": "graph-1",
        },
    }
    assistant = _turn(
        ConversationTurnRole.ASSISTANT,
        payload["answer"],
        replay_metadata(model="narrator-model", payload=payload),
    )
    submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=coordinator,
        adequacy_investigator=cast(Any, _Investigator()),
        adequacy_sink=sink,
    )

    assert submitter.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "What is related?"),
        assistant_turn=assistant,
        submission=PostTurnReviewSubmission(("unverified",), ("ontology:release",)),
    )
    await submitter.close()

    assert len(sink.reviews) == 1
    assert sink.reviews[0].state.value == "held"


async def test_provider_failure_does_not_submit_adequacy_review() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    sink = _AdequacySink()
    coordinator = ConversationAssuranceCoordinator(
        ledger=ledger,
        reviewer=None,
        rubric_version="1.0.0",
        now=lambda: _NOW,
    )
    payload = {
        "answer": "The provider is unavailable.",
        "source": "evidence:unverified",
        "verification": {
            "status": "unverified",
            "authority": "server_read_model",
            "checks_completed": 0,
            "checks_total": 1,
            "evidence_refs": [],
            "failed_claim_ids": [],
            "reason_code": "provider_unavailable",
        },
    }
    submitter = ConversationAssurancePostTurnSubmitter(
        coordinator=coordinator,
        adequacy_investigator=cast(Any, _Investigator()),
        adequacy_sink=sink,
    )

    assert submitter.submit_nowait(
        operator_turn=_turn(ConversationTurnRole.OPERATOR, "What happened?"),
        assistant_turn=_turn(
            ConversationTurnRole.ASSISTANT,
            payload["answer"],
            replay_metadata(model="narrator-model", payload=payload),
        ),
        submission=PostTurnReviewSubmission(("unverified",), ()),
    )
    await submitter.close()

    assert sink.reviews == []

"""Cross-service semantic turn round-trip without external providers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_runtime import SemanticTurnResult as RuntimeSemanticTurnResult
from fdai.core.conversation.session import Principal, Turn
from fdai.core.ontology_platform import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_core_service.semantic_turn_processor import SemanticTurnProcessor
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
    ConversationStreamRequest,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnBridge,
    SemanticTurnOutboxDrainer,
    SemanticTurnProjectionConsumer,
)
from fdai_operator_service.postgres_family_store import (
    SemanticTurnClaim,
    StoredSemanticResult,
    StoredSemanticTurn,
)
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    TaskStatus,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)
MANIFEST_DIGEST = "sha256:" + ("b" * 64)
PLAN_DIGEST = "sha256:" + ("c" * 64)


class _OperatorStore:
    def __init__(self) -> None:
        self.turn: StoredSemanticTurn | None = None
        self.result: StoredSemanticResult | None = None
        self.claim_available = False

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn:
        del request_digest
        request_id = cast(str, envelope["request_id"])
        self.turn = StoredSemanticTurn(
            key=f"outbox:{hashlib.sha256(idempotency_key.encode()).hexdigest()}",
            proposal_id=f"semantic-{request_id}",
            request_id=request_id,
            principal_id=principal_id,
            envelope=dict(envelope),
            duplicate=False,
        )
        self.claim_available = True
        return self.turn

    async def claim_semantic_turn(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> SemanticTurnClaim | None:
        del worker_id, lease_seconds
        if not self.claim_available or self.turn is None:
            return None
        self.claim_available = False
        return SemanticTurnClaim(
            key=self.turn.key,
            claim_id="claim-1",
            request_id=self.turn.request_id,
            principal_id=self.turn.principal_id,
            envelope=self.turn.envelope,
            attempt=1,
        )

    async def mark_semantic_turn_published(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        return True

    async def release_semantic_turn_claim(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        self.claim_available = True
        return True

    async def read_semantic_turn(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None:
        if (
            self.turn is None
            or self.turn.principal_id != principal_id
            or self.turn.proposal_id != proposal_id
        ):
            return None
        return self.turn

    async def project_semantic_turn_result(
        self,
        *,
        projection: Mapping[str, object],
    ) -> StoredSemanticResult:
        if self.turn is None or projection["request_id"] != self.turn.request_id:
            raise ValueError("projection has no owning request")
        semantic_result = cast(dict[str, object], projection["semantic_result"])
        self.result = StoredSemanticResult(
            sequence=cast(int, semantic_result["turn_sequence"]) + 1,
            event="semantic_turn_result",
            request_id=self.turn.request_id,
            principal_id=self.turn.principal_id,
            projection_id=cast(str, projection["projection_id"]),
            data=dict(projection),
            duplicate=False,
        )
        return self.result

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        del limit
        if (
            self.result is None
            or self.result.principal_id != principal_id
            or self.result.request_id != request_id
            or self.result.sequence <= (after_sequence or 0)
        ):
            return ()
        return (self.result,)


class _CoreResultStore:
    def __init__(self) -> None:
        self.claims: dict[str, str] = {}
        self.results: dict[str, bytes] = {}

    async def get(self, idempotency_key: str) -> bytes | None:
        return self.results.get(idempotency_key)

    async def claim(self, idempotency_key: str, request_digest: str) -> bool:
        prior = self.claims.setdefault(idempotency_key, request_digest)
        if prior != request_digest:
            raise ValueError("idempotency conflict")
        return idempotency_key not in self.results

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
        if idempotency_key in self.results:
            return False
        self.results[idempotency_key] = projection
        return True


class _Publisher:
    def __init__(self) -> None:
        self.topic: str | None = None
        self.payload: Mapping[str, object] | None = None

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        assert key == payload["request_id"]
        self.topic = topic
        self.payload = payload
        return object()


class _UnusedSource:
    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        del topic, group_id

        async def empty() -> AsyncIterator[Mapping[str, object]]:
            if False:
                yield {}

        return empty()


class _AnsweredRuntime:
    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: Any = None,
    ) -> RuntimeSemanticTurnResult:
        del prior_turns, cancelled
        assert utterance == "Show current operations evidence."
        assert principal.id == "operator-1"
        plan = SimpleNamespace(
            ontology_release_digest=RELEASE_DIGEST,
            semantic_catalog_digest=MANIFEST_DIGEST,
            plan_digest=PLAN_DIGEST,
        )
        planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
        receipt = GoalTaskReceipt(
            task_id="query:resources",
            goal_id="goal-1",
            intent="object_set",
            capability="query.object_set",
            evidence_mode=GoalEvidenceMode.OPERATIONAL,
            status=TaskStatus.COMPLETED,
            duration_ms=5,
            evidence_refs=("inventory:evidence-1",),
            started_at=NOW,
            completed_at=NOW,
        )
        execution = QueryPlanExecution(
            plan_digest=PLAN_DIGEST,
            status="completed",
            results=MappingProxyType(
                {
                    "resources": QueryNodeResult(
                        value=QueryTable(
                            rows=(
                                QueryRow.from_values(
                                    "resource-1",
                                    {"state": "ready"},
                                ),
                            ),
                            complete=True,
                        ),
                        evidence_refs=("inventory:evidence-1",),
                    )
                }
            ),
            receipts=(receipt,),
            output_node_ids=("resources",),
        )
        return RuntimeSemanticTurnResult(
            disposition="answered",
            reason="semantic_execution_completed",
            planning=cast(Any, planning),
            execution=execution,
            intent_graph={
                "schema_version": 2,
                "goals": [
                    {
                        "goal_id": "goal-1",
                        "intent": "object_set",
                        "capability": "query.object_set",
                        "arguments": {},
                        "depends_on": [],
                        "evidence_mode": "operational",
                        "freshness_required": True,
                        "confidence": 1.0,
                        "alternatives": [],
                    }
                ],
                "clarification": None,
                "confidence": 1.0,
                "action_posture": "advise_only",
            },
            intent_graph_evidence={
                "schema_version": 1,
                "status": "completed",
                "evidence_mode": "operational_grounded",
                "goals": [
                    {
                        "task_id": "query:resources",
                        "goal_id": "goal-1",
                        "intent": "object_set",
                        "capability": "query.object_set",
                        "evidence_mode": "operational",
                        "status": "completed",
                        "duration_ms": 5,
                        "depends_on": [],
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                        "evidence_refs": ["inventory:evidence-1"],
                    }
                ],
            },
        )


async def test_semantic_turn_round_trip_preserves_verified_evidence_and_principal_scope() -> None:
    operator_store = _OperatorStore()
    publisher = _Publisher()
    bridge = SemanticTurnBridge(
        store=operator_store,
        publisher=publisher,
        result_source=_UnusedSource(),
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: NOW),
    )
    proposal = ConversationProposal(
        operation="chat.stream",
        scope=PrincipalScope("operator-1", frozenset({"Reader"})),
        idempotency_key="semantic-roundtrip-1",
        body={
            "prompt": "Show current operations evidence.",
            "conversation_id": "conversation-1",
            "turn_sequence": 3,
        },
    )

    accepted = await bridge.append(proposal)
    drainer = SemanticTurnOutboxDrainer(
        store=operator_store,
        publisher=publisher,
        worker_id="roundtrip-worker",
    )
    assert await drainer.run_once() is True
    assert publisher.topic == "operator.semantic-turn.requests"
    assert publisher.payload is not None

    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime(),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )
    projection = json.loads(await processor.process(publisher.payload))
    await SemanticTurnProjectionConsumer(operator_store).consume(projection)

    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=accepted.proposal_id,
        )
    )
    events = [event async for event in stream]
    assert len(events) == 1
    semantic_result = cast(dict[str, object], events[0].data["semantic_result"])
    assert events[0].data["status"] == "answered"
    assert semantic_result["evidence_refs"] == ["inventory:evidence-1"]
    assert semantic_result["ontology_release_digest"] == RELEASE_DIGEST
    assert semantic_result["principal_manifest_digest"] == MANIFEST_DIGEST
    assert semantic_result["plan_digest"] == PLAN_DIGEST

    with pytest.raises(ConversationBoundaryError, match="semantic turn not found"):
        await bridge.open(
            ConversationStreamRequest(
                operation="chat.stream",
                scope=PrincipalScope("operator-2", frozenset({"Reader"})),
                proposal_id=accepted.proposal_id,
            )
        )

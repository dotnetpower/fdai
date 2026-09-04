"""Cross-service semantic turn round-trip without external providers."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
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
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    _receipt_authority,
    semantic_done_event_data,
)
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
    EvidenceAuthority,
    GoalEvidenceMode,
    GoalTaskReceipt,
    TaskStatus,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)
MANIFEST_DIGEST = "sha256:" + ("b" * 64)
PLAN_DIGEST = "sha256:" + ("c" * 64)
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_direct_response_intent_has_no_lexical_runtime_owner() -> None:
    classifier_path = (
        REPO_ROOT / "services/core-control-plane/src/fdai/core/conversation/direct_response.py"
    )
    assert not classifier_path.exists()

    contract_tree = ast.parse(
        (
            REPO_ROOT / "packages/service-contracts/src/fdai_service_contracts/semantic_turn.py"
        ).read_text(encoding="utf-8")
    )
    assert all(
        not (isinstance(node, ast.FunctionDef) and "direct_response_intent" in node.name)
        for node in ast.walk(contract_tree)
    )

    conversation_root = REPO_ROOT / "services/core-control-plane/src/fdai/core/conversation"
    assert all(
        not (isinstance(node, ast.FunctionDef) and "direct_response_intent" in node.name)
        for path in conversation_root.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )
    operator_tree = ast.parse(
        (
            REPO_ROOT
            / "services/operator-service/src"
            / "fdai_operator_service/families/conversation/semantic_turn_runtime.py"
        ).read_text(encoding="utf-8")
    )
    assert all(
        not (isinstance(node, ast.Attribute) and node.attr == "utterance")
        for node in ast.walk(operator_tree)
    )


class _OperatorStore:
    def __init__(self) -> None:
        self.turn: StoredSemanticTurn | None = None
        self.result: StoredSemanticResult | None = None
        self.claim_available = False

    async def latest_semantic_investigation_continuation(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> None:
        del principal_id, session_id
        return None

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
        source_request_id: str | None = None,
    ) -> StoredSemanticTurn:
        del request_digest, source_request_id
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

    async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
        prior = self.claims.setdefault(idempotency_key, request_digest)
        if prior != request_digest:
            raise ValueError("idempotency conflict")
        return "integration-claim" if idempotency_key not in self.results else None

    async def release(
        self,
        idempotency_key: str,
        request_digest: str,
        claim_id: str,
    ) -> bool:
        del idempotency_key, request_digest, claim_id
        return True

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
    def __init__(
        self,
        authorities: tuple[EvidenceAuthority | None, ...] = (
            EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        ),
    ) -> None:
        self._authorities = authorities

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        locale: str = "en",
        cancelled: Any = None,
        bound_incident: Any = None,
        bound_investigation_continuation: Any = None,
        escalation_policy: Any = None,
    ) -> RuntimeSemanticTurnResult:
        del (
            prior_turns,
            cancelled,
            bound_incident,
            bound_investigation_continuation,
            escalation_policy,
        )
        assert utterance == "Show current operations evidence."
        assert principal.id == "operator-1"
        assert locale == "en"
        plan = SimpleNamespace(
            ontology_release_digest=RELEASE_DIGEST,
            semantic_catalog_digest=MANIFEST_DIGEST,
            plan_digest=PLAN_DIGEST,
        )
        planning = SimpleNamespace(
            plan=plan,
            frame=SimpleNamespace(
                operation=SimpleNamespace(value="select"),
                output_shape="resource_list",
                subject_constraints=(),
                measure_concepts=(),
            ),
            manifest_digest=MANIFEST_DIGEST,
        )
        receipts = tuple(
            GoalTaskReceipt(
                task_id=f"query:resources-{index}",
                goal_id=f"goal-{index}",
                intent="object_set",
                capability="query.object_set",
                evidence_mode=GoalEvidenceMode.OPERATIONAL,
                status=TaskStatus.COMPLETED,
                duration_ms=5,
                evidence_refs=(f"evidence:{index}",),
                authority=authority,
                started_at=NOW,
                completed_at=NOW,
            )
            for index, authority in enumerate(self._authorities, start=1)
        )
        execution = QueryPlanExecution(
            plan_digest=PLAN_DIGEST,
            status="completed",
            results=MappingProxyType(
                {
                    f"resources-{index}": QueryNodeResult(
                        value=QueryTable(
                            rows=(
                                QueryRow.from_values(
                                    f"resource-{index}",
                                    {"state": "ready"},
                                ),
                            ),
                            complete=True,
                        ),
                        evidence_refs=(f"evidence:{index}",),
                        authority=authority,
                    )
                    for index, authority in enumerate(self._authorities, start=1)
                }
            ),
            receipts=receipts,
            output_node_ids=tuple(
                f"resources-{index}" for index in range(1, len(self._authorities) + 1)
            ),
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
                        "goal_id": f"goal-{index}",
                        "intent": "object_set",
                        "capability": "query.object_set",
                        "arguments": {},
                        "depends_on": [],
                        "evidence_mode": "operational",
                        "freshness_required": True,
                        "confidence": 1.0,
                        "alternatives": [],
                    }
                    for index in range(1, len(self._authorities) + 1)
                ],
                "clarification": None,
                "confidence": 1.0,
                "action_posture": "advise_only",
            },
            intent_graph_evidence={
                "schema_version": 2,
                "status": (
                    "completed"
                    if len(set(self._authorities)) == 1 and self._authorities[0] is not None
                    else "failed"
                ),
                "evidence_mode": (
                    "operational_grounded"
                    if len(set(self._authorities)) == 1 and self._authorities[0] is not None
                    else "held_for_review"
                ),
                "goals": [
                    {
                        "task_id": f"query:resources-{index}",
                        "goal_id": f"goal-{index}",
                        "intent": "object_set",
                        "capability": "query.object_set",
                        "evidence_mode": "operational",
                        "status": "completed",
                        "duration_ms": 5,
                        "depends_on": [],
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                        "evidence_refs": [f"evidence:{index}"],
                        **({"authority": authority.value} if authority is not None else {}),
                    }
                    for index, authority in enumerate(self._authorities, start=1)
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
    backbone = [event.event for event in events if event.event not in {"activity", "token"}]
    assert backbone[0] == "status"
    assert backbone[-1] == "done"
    assert backbone.count("verification") == 1
    assert set(backbone) == {"status", "verification", "done"}
    assert any(event.event == "activity" for event in events)
    assert any(event.event == "token" for event in events)
    terminal = events[-1]
    semantic_result = cast(dict[str, object], terminal.data["semantic_result"])
    assert terminal.data["status"] == "answered"
    assert cast(str, terminal.data["answer"]).startswith("## Verified result")
    assert "```json" not in cast(str, terminal.data["answer"])
    trajectory = cast(dict[str, object], terminal.data["trajectory_detail"])
    activities = cast(list[dict[str, object]], trajectory["activities"])
    execution = cast(dict[str, object], activities[0]["execution"])
    execution_output = json.loads(cast(str, execution["output"]))
    assert execution_output["status"] == "completed"
    assert execution_output["evidence_ref_count"] == 1
    assert execution_output["source_complete"] is True
    assert execution_output["returned_rows"] == 1
    assert semantic_result["evidence_refs"] == ["evidence:1"]
    verification = cast(dict[str, object], terminal.data["verification"])
    assert verification["authority"] == "server_inventory_graph"
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


def _semantic_envelope() -> Mapping[str, object]:
    return SemanticTurnEnvelopeBuilder(clock=lambda: NOW).build(
        ConversationProposal(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            idempotency_key="semantic-authority-test",
            body={
                "prompt": "Show current operations evidence.",
                "conversation_id": "conversation-1",
                "turn_sequence": 3,
            },
        )
    )


@pytest.mark.parametrize(
    "authority",
    (
        EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
        EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        EvidenceAuthority.SERVER_METERING,
        EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
    ),
)
async def test_terminal_answer_preserves_server_receipt_authority(
    authority: EvidenceAuthority,
) -> None:
    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime((authority,)),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )

    projection = json.loads(await processor.process(_semantic_envelope()))
    done = semantic_done_event_data(projection)

    assert done["status"] == "answered"
    assert done["source"] == authority.value
    assert done["verification"]["status"] == "verified"
    assert done["verification"]["authority"] == authority.value
    goal = projection["semantic_result"]["intent_graph_evidence"]["goals"][0]
    assert goal["authority"] == authority.value
    assert goal["evidence_refs"] == projection["semantic_result"]["evidence_refs"]


async def test_terminal_answer_ignores_model_proposed_authority() -> None:
    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime((EvidenceAuthority.SERVER_INVENTORY_GRAPH,)),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )
    projection = json.loads(await processor.process(_semantic_envelope()))
    projection["semantic_result"]["authority"] = "server_metering"
    projection["payload"]["technical_details"]["authority"] = "server_metering"

    done = semantic_done_event_data(projection)

    assert done["verification"]["authority"] == "server_inventory_graph"


def test_multi_source_condition_answer_preserves_each_receipt_authority() -> None:
    projection = {
        "projection_id": "projection-resource-conditions",
        "request_id": "request-resource-conditions",
        "semantic_result": {
            "disposition": "answered",
            "reason_code": "semantic_answer_verified",
            "semantic_route": "verified_query_plan",
            "ontology_release_digest": RELEASE_DIGEST,
            "principal_manifest_digest": MANIFEST_DIGEST,
            "plan_digest": PLAN_DIGEST,
            "execution_receipt_digest": "sha256:" + ("d" * 64),
            "evidence_refs": ["evidence:inventory", "evidence:health"],
            "checks_completed": 2,
            "checks_total": 2,
            "answer": "Verified per-source resource conditions.",
            "execution_authority": False,
            "intent_graph_evidence": {
                "schema_version": 2,
                "status": "completed",
                "evidence_mode": "operational_grounded",
                "goals": [
                    {
                        "task_id": "query:resource-condition-power",
                        "goal_id": "goal-power",
                        "intent": "function",
                        "capability": "query.function",
                        "evidence_mode": "operational",
                        "status": "completed",
                        "duration_ms": 1,
                        "depends_on": [],
                        "evidence_refs": ["evidence:inventory"],
                        "authority": "server_inventory_graph",
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                    },
                    {
                        "task_id": "query:resource-condition-health",
                        "goal_id": "goal-health",
                        "intent": "function",
                        "capability": "query.function",
                        "evidence_mode": "operational",
                        "status": "completed",
                        "duration_ms": 1,
                        "depends_on": [],
                        "evidence_refs": ["evidence:health"],
                        "authority": "server_resource_health",
                        "authority_inputs": ["server_inventory_graph"],
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                    },
                ],
                "execution_authority": False,
            },
        },
        "payload": {
            "technical_details": {
                "schema_version": 1,
                "kind": "semantic_query_outputs",
                "presentation_context": {
                    "operation": "select",
                    "output_shape": "resource_condition_sections",
                    "measure_concepts": [
                        "resource_health.degraded",
                        "resource_state.stopped",
                    ],
                },
                "outputs": [
                    {
                        "node_id": "resource-condition-power",
                        "rows": [],
                        "returned_rows": 0,
                        "total_rows": 0,
                        "source_complete": True,
                        "source_truncation_reason": None,
                        "display_truncated": False,
                        "evidence_refs": ["evidence:inventory"],
                    },
                    {
                        "node_id": "resource-condition-health",
                        "rows": [],
                        "returned_rows": 0,
                        "total_rows": 0,
                        "source_complete": False,
                        "source_truncation_reason": "scope_unreadable",
                        "display_truncated": False,
                        "evidence_refs": ["evidence:health"],
                    },
                ],
            }
        },
    }

    done = semantic_done_event_data(projection)

    verification = cast(dict[str, object], done["verification"])
    assert verification["status"] == "verified"
    assert verification["authority"] == "multiple_authoritative_sources"
    sources = cast(list[dict[str, object]], verification["source_verifications"])
    assert [source["authority"] for source in sources] == [
        "server_inventory_graph",
        "server_resource_health",
    ]
    assert sources[0]["complete"] is True
    assert sources[1]["complete"] is False
    assert sources[1]["limitation"] == "scope_unreadable"


@pytest.mark.parametrize(
    "authority",
    ("server_resource_health", "server_operational_state_history"),
)
def test_scoped_independent_output_ignores_scope_authority_for_terminal_label(
    authority: str,
) -> None:
    semantic = {
        "intent_graph_evidence": {
            "goals": [
                {
                    "task_id": "query:scope",
                    "status": "completed",
                    "evidence_refs": ["evidence:scope"],
                    "authority": "server_inventory_graph",
                },
                {
                    "task_id": "query:output",
                    "status": "completed",
                    "evidence_refs": ["evidence:output"],
                    "authority": authority,
                    "authority_inputs": ["server_inventory_graph"],
                },
            ]
        }
    }
    technical_details = {
        "outputs": [
            {
                "node_id": "output",
                "source_complete": True,
                "source_truncation_reason": None,
            }
        ]
    }

    assert _receipt_authority(
        semantic,
        ["evidence:scope", "evidence:output"],
        technical_details=technical_details,
    ) == (authority, None)


def test_multi_source_authority_requires_exact_output_topology_and_binding() -> None:
    semantic = {
        "intent_graph_evidence": {
            "goals": [
                {
                    "task_id": "query:unrelated-power",
                    "status": "completed",
                    "evidence_refs": ["evidence:inventory"],
                    "authority": "server_inventory_graph",
                },
                {
                    "task_id": "query:unrelated-health",
                    "status": "completed",
                    "evidence_refs": ["evidence:health"],
                    "authority": "server_resource_health",
                    "authority_inputs": ["server_inventory_graph"],
                },
            ]
        }
    }
    technical_details = {
        "presentation_context": {
            "operation": "select",
            "output_shape": "resource_condition_sections",
        },
        "outputs": [
            {"node_id": "unrelated-power"},
            {"node_id": "unrelated-health"},
        ],
    }

    assert _receipt_authority(
        semantic,
        ["evidence:inventory", "evidence:health"],
        technical_details=technical_details,
    ) == ("conflicting", "semantic_evidence_authority_conflict")


async def test_v1_receipt_replay_stays_readable_but_unverified() -> None:
    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime((EvidenceAuthority.SERVER_INVENTORY_GRAPH,)),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )
    projection = json.loads(await processor.process(_semantic_envelope()))
    evidence = projection["semantic_result"]["intent_graph_evidence"]
    evidence["schema_version"] = 1
    evidence["goals"][0].pop("authority")

    done = semantic_done_event_data(projection)

    assert done["answer"]
    assert done["verification"]["status"] == "unverified"
    assert done["verification"]["authority"] == "unavailable"
    assert done["verification"]["reason_code"] == "semantic_evidence_authority_missing"


async def test_receipt_authority_cannot_cover_a_different_evidence_reference() -> None:
    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime((EvidenceAuthority.SERVER_INVENTORY_GRAPH,)),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )
    projection = json.loads(await processor.process(_semantic_envelope()))
    projection["semantic_result"]["evidence_refs"] = ["evidence:other"]

    done = semantic_done_event_data(projection)

    assert done["verification"]["status"] == "unverified"
    assert done["verification"]["authority"] == "unavailable"
    assert done["verification"]["reason_code"] == "semantic_evidence_authority_binding_mismatch"


@pytest.mark.parametrize(
    ("authorities", "expected_authority", "expected_reason"),
    (
        ((None,), "unavailable", "semantic_evidence_authority_missing"),
        (
            (
                EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
            ),
            "conflicting",
            "semantic_evidence_authority_conflict",
        ),
    ),
)
async def test_missing_or_conflicting_receipt_authority_is_held(
    authorities: tuple[EvidenceAuthority | None, ...],
    expected_authority: str,
    expected_reason: str,
) -> None:
    processor = SemanticTurnProcessor(
        runtime=_AnsweredRuntime(authorities),
        results=_CoreResultStore(),
        now=lambda: NOW,
    )

    projection = json.loads(await processor.process(_semantic_envelope()))
    done = semantic_done_event_data(projection)

    assert done["status"] == "held"
    assert done["verification"]["status"] == "unverified"
    assert done["verification"]["authority"] == expected_authority
    assert done["verification"]["reason_code"] == expected_reason

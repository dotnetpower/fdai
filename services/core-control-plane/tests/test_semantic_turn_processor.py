"""Focused Core semantic-turn v1.2 processor and lifecycle tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricWindow,
    QueryNodeResult,
    QueryPlanExecution,
    TopologyDiff,
    TopologyGraphAt,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.rule_catalog.schema.rule_semantic_generation import (
    CatalogRetrievalReceipt,
    RetrievalOperation,
    RetrievalRank,
    SemanticAvailability,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.semantic_turn_consumer import (
    StateStoreSemanticTurnResultStore,
    consume_semantic_turns,
    semantic_turn_binding_from_config,
)
from fdai_core_service.semantic_turn_processor import (
    SemanticTurnProcessor,
    SemanticTurnRejectedError,
    _typed_extension_answer_output,
)
from fdai_service_contracts import RuleSearchReceipt, rule_search_query_digest
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    TaskStatus,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)
MANIFEST_DIGEST = "sha256:" + ("b" * 64)
PLAN_DIGEST = "sha256:" + ("c" * 64)
GENERATION_DIGEST = "sha256:" + ("d" * 64)
RULE_QUERY = {
    "query": "zone resilience",
    "operation": "discover",
    "corpus": "active",
    "limit": 10,
}
RULE_QUERY_DIGEST = (
    "sha256:"
    + hashlib.sha256(
        json.dumps(RULE_QUERY, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
)


@pytest.mark.parametrize(
    ("value", "result_kind"),
    (
        (
            TopologyGraphAt(
                as_of=NOW,
                known_at=NOW,
                graph=OntologyGraphSnapshot(),
                complete=True,
                revision_ids=("revision-1",),
                provider_generation_refs=("generation-1",),
                evidence_refs=("topology:evidence-1",),
                digest=RELEASE_DIGEST,
            ),
            "topology.graph",
        ),
        (
            TopologyDiff(
                before_digest=MANIFEST_DIGEST,
                after_digest=RELEASE_DIGEST,
                added_object_ids=("resource-1",),
                removed_object_ids=(),
                changed_object_ids=(),
                added_link_keys=(),
                removed_link_keys=(),
                changed_link_keys=(),
                complete=True,
                evidence_refs=("topology:evidence-1",),
                digest=PLAN_DIGEST,
            ),
            "topology.diff",
        ),
        (
            MetricWindow(
                concept_id="request_count",
                resource_id="resource-1",
                unit="count",
                start=NOW - timedelta(minutes=5),
                end=NOW,
                samples=(),
                complete=True,
                evidence_refs=("metric:evidence-1",),
            ),
            "metric.window",
        ),
        (
            CausalEvidenceJoin(
                status=CausalJoinStatus.UNRESOLVED,
                temporal_claim=None,
                topology_diff_digest=None,
                competing_explanations=("credential_change",),
                limitations=("metric_window_incomplete",),
                evidence_refs=("metric:evidence-1",),
            ),
            "causal.join",
        ),
    ),
)
def test_typed_extension_answer_output_is_bounded_and_authority_free(
    value: object,
    result_kind: str,
) -> None:
    output = _typed_extension_answer_output("result", value)

    assert output is not None
    assert output["result_kind"] == result_kind
    assert output["summary"]["execution_authority"] is False
    assert "evidence_refs" not in output["summary"]


class _Runtime:
    def __init__(
        self,
        result: RuntimeSemanticTurnResult | None = None,
        *,
        failure: Exception | None = None,
        wait_for_cancel: bool = False,
    ) -> None:
        self.result = result or _runtime_result("held")
        self.failure = failure
        self.wait_for_cancel = wait_for_cancel
        self.calls = 0
        self.principals: list[Principal] = []
        self.prior_turns: tuple[Turn, ...] = ()

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
    ) -> RuntimeSemanticTurnResult:
        assert utterance == "Show current operations evidence."
        self.calls += 1
        self.principals.append(principal)
        self.prior_turns = prior_turns
        if self.failure is not None:
            raise self.failure
        if self.wait_for_cancel:
            assert cancelled is not None
            await cancelled.wait()
            return _runtime_result("cancelled")
        return self.result


class _ContendedRuntime(_Runtime):
    def __init__(self) -> None:
        super().__init__(_runtime_result("answered"))
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
    ) -> RuntimeSemanticTurnResult:
        self.calls += 1
        self.principals.append(principal)
        self.prior_turns = prior_turns
        self.entered.set()
        await self.release.wait()
        return self.result


class _BlockingResultStore:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def get(self, idempotency_key: str) -> bytes | None:
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
        raise AssertionError("blocked get MUST prevent claim")

    async def release(
        self,
        idempotency_key: str,
        request_digest: str,
        claim_id: str,
    ) -> bool:
        raise AssertionError("blocked get MUST prevent release")

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
        raise AssertionError("blocked get MUST prevent put")


def _request(
    *,
    roles: list[str] | None = None,
    purpose: str = "operations-review",
    deadline_at: datetime | None = None,
    cancelled: bool = False,
    idempotency_key: str = "semantic-turn-1",
    prior_turns: list[dict[str, str]] | None = None,
    bound_context: dict[str, str] | None = None,
    locale: str = "en",
) -> dict[str, object]:
    semantic_turn: dict[str, object] = {
        "utterance": "Show current operations evidence.",
        "principal": {
            "subject_id": "operator-1",
            "roles": roles or ["Reader"],
        },
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 3,
        "locale": locale,
        "purpose": purpose,
        "deadline_at": (deadline_at or NOW + timedelta(seconds=30)).isoformat(),
        "prior_turns": prior_turns or [],
        "cancelled": cancelled,
        "execution_authority": False,
    }
    if bound_context is not None:
        semantic_turn["bound_context"] = bound_context
    return {
        "schema_version": "1.3.0" if bound_context is not None else "1.2.0",
        "request_id": "00000000-0000-0000-0000-000000000101",
        "correlation_id": "semantic-correlation-1",
        "idempotency_key": idempotency_key,
        "resource_ref": "operator-conversation:example",
        "request_kind": "semantic_query",
        "requested_at": NOW.isoformat(),
        "semantic_turn": semantic_turn,
    }


def _processor(
    runtime: _Runtime | None,
    *,
    now: Any = lambda: NOW,
) -> SemanticTurnProcessor:
    return SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(InMemoryStateStore()),
        now=now,
    )


def _projection(encoded: bytes) -> dict[str, Any]:
    loaded = json.loads(encoded)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _runtime_result(disposition: str) -> RuntimeSemanticTurnResult:
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
    )
    planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
    if disposition != "answered":
        return RuntimeSemanticTurnResult(
            disposition=cast(Any, disposition),
            reason="provider detail must not escape",
            planning=cast(Any, planning),
        )
    receipt = GoalTaskReceipt(
        task_id="query:resources",
        goal_id="resources",
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
                        rows=(QueryRow.from_values("resource-1", {"state": "ready"}),),
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


def _rule_search_runtime_result(*, execution_authority: bool = False) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    receipt = CatalogRetrievalReceipt(
        query_digest=RULE_QUERY_DIGEST,
        operation=RetrievalOperation.DISCOVER,
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=MANIFEST_DIGEST,
        semantic_state=SemanticAvailability.AVAILABLE,
        results=(RetrievalRank("rule.one", 1, (("hybrid", 0.9),)),),
        generation_digest=GENERATION_DIGEST,
    )
    output = {
        "candidates": [
            {
                "rule_ref": "rule.one",
                "rank": 1,
                "components": {"hybrid": 0.9},
                "authority": "candidate_only",
            }
        ],
        "retrieval_receipt": {
            "schema_version": receipt.schema_version,
            "query_digest": receipt.query_digest,
            "operation": receipt.operation.value,
            "corpus": receipt.corpus.value,
            "catalog_digest": receipt.catalog_digest,
            "semantic_state": receipt.semantic_state.value,
            "generation_digest": receipt.generation_digest,
            "results": [
                {
                    "rule_ref": "rule.one",
                    "rank": 1,
                    "components": {"hybrid": 0.9},
                }
            ],
            "degraded_reason": None,
            "unresolved_terms": [],
            "clarification_required": False,
            "truncated": False,
            "execution_authority": False,
        },
        "retrieval_receipt_digest": receipt.digest,
        "authority": "candidate_only",
        "execution_authority": execution_authority,
    }
    node = SimpleNamespace(
        node_id="resources",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "catalog.search_rules",
            "arguments": RULE_QUERY,
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "goal_id": "resources",
            "intent": "function",
            "capability": "query.function",
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=output,
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("resources",),
    )
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], result.intent_graph)["goals"][0],
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], result.intent_graph_evidence)["goals"][0],
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
    )


def _incident_evidence_runtime_result(
    *,
    inject_cause: bool = False,
    output_correlation_id: str = "incident-correlation-301",
) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    incident_id = "00000000-0000-0000-0000-000000000301"
    correlation_id = "incident-correlation-301"
    output = {
        "incident_id": incident_id,
        "correlation_id": output_correlation_id,
        "incident_profile": {
            "correlation_id": correlation_id,
            "incident_id": incident_id,
            "ticket_id": None,
            "title": None,
            "severity": "sev2",
            "status": "triaging",
            "vertical": None,
            "opened_at": "2026-08-14T09:00:00Z",
            "last_updated_at": "2026-08-14T09:05:00Z",
            "duration_seconds": 300.0,
            "audit_records": 2,
            "actors": ["Heimdall", "operator@example.com"],
            "modes": ["shadow"],
        },
        "correlated_evidence": [
            {
                "audit_ref": "audit:1",
                "event_id": "00000000-0000-0000-0000-000000000401",
                "action_kind": "incident.open",
                "mode": "shadow",
                "recorded_at": "2026-08-14T09:00:00Z",
            }
        ],
        "evidence_gaps": ["impact_evidence_missing", "grounded_citations_missing"],
        "evidence_refs": ["audit:1"],
        "truncated": False,
        "authority": "audit_projection",
        "cause_claim_supported": False,
        "execution_authority": False,
    }
    if inject_cause:
        output["cause"] = "unsupported causal claim"
    node = SimpleNamespace(
        node_id="incident-evidence",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "query.incident_evidence",
            "arguments": {
                "incident_id": incident_id,
                "correlation_id": correlation_id,
                "limit": 100,
            },
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "task_id": "query:incident-evidence",
            "goal_id": "incident-evidence",
            "intent": "function",
            "capability": "query.function",
            "evidence_refs": ("ontology-function:incident-evidence",),
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "incident-evidence": QueryNodeResult(
                    value=output,
                    evidence_refs=("ontology-function:incident-evidence",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("incident-evidence",),
    )
    graph_goal = cast(dict[str, object], result.intent_graph)["goals"][0]
    evidence_goal = cast(dict[str, object], result.intent_graph_evidence)["goals"][0]
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], graph_goal),
                    "goal_id": "incident-evidence",
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], evidence_goal),
                    "task_id": "query:incident-evidence",
                    "goal_id": "incident-evidence",
                    "intent": "function",
                    "capability": "query.function",
                    "evidence_refs": ["ontology-function:incident-evidence"],
                }
            ],
        },
    )


def _ontology_relationship_runtime_result(
    *,
    output_release_digest: str = RELEASE_DIGEST,
) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    output = {
        "object_types": ["PythonTask", "VmTaskRun"],
        "relationships": [
            {
                "link_type": "executes_task",
                "from_type": "VmTaskRun",
                "to_type": "PythonTask",
                "cardinality": "many_to_one",
                "description": "The immutable PythonTask artifact selected by a VM task run.",
            }
        ],
        "complete": True,
        "authority": "ontology_release",
        "ontology_release_digest": output_release_digest,
        "execution_authority": False,
    }
    node = SimpleNamespace(
        node_id="relationships",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "query.ontology_relationships",
            "arguments": {
                "object_types": ["PythonTask", "VmTaskRun"],
                "limit": 100,
            },
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST)
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "task_id": "query:relationships",
            "goal_id": "relationships",
            "intent": "function",
            "capability": "query.function",
            "evidence_refs": ("ontology-function:relationships",),
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "relationships": QueryNodeResult(
                    value=output,
                    evidence_refs=("ontology-function:relationships",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("relationships",),
    )
    graph_goal = cast(dict[str, object], result.intent_graph)["goals"][0]
    evidence_goal = cast(dict[str, object], result.intent_graph_evidence)["goals"][0]
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], graph_goal),
                    "goal_id": "relationships",
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], evidence_goal),
                    "task_id": "query:relationships",
                    "goal_id": "relationships",
                    "intent": "function",
                    "capability": "query.function",
                    "evidence_refs": ["ontology-function:relationships"],
                }
            ],
        },
    )


async def test_malformed_semantic_request_goes_to_dlq() -> None:
    bus = InMemoryEventBus()
    await bus.publish("operator.request", "bad", {"schema_version": "1.2.0"})

    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )

    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "semantic_turn_rejected"


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["Reader"], Role.READER),
        (["Reader", "Contributor"], Role.CONTRIBUTOR),
        (["Reader", "Approver"], Role.APPROVER),
        (["BreakGlass", "Owner"], Role.OWNER),
    ],
)
async def test_authenticated_role_order_selects_highest_ordinary_role(
    roles: list[str],
    expected: Role,
) -> None:
    runtime = _Runtime()

    await _processor(runtime).process(_request(roles=roles))

    assert runtime.principals[0].role is expected


async def test_break_glass_only_and_caller_purpose_widening_are_rejected() -> None:
    processor = _processor(_Runtime())

    with pytest.raises(SemanticTurnRejectedError, match="semantic_break_glass_only"):
        await processor.process(_request(roles=["BreakGlass"]))
    with pytest.raises(SemanticTurnRejectedError, match="semantic_purpose_not_allowed"):
        await processor.process(_request(purpose="execution"))


async def test_prior_turns_map_to_existing_turn_without_content_rewrite() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(
            prior_turns=[
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ]
        )
    )

    assert [(turn.direction, turn.content) for turn in runtime.prior_turns] == [
        ("inbound", "Earlier question"),
        ("outbound", "Earlier answer"),
    ]
    assert [turn.turn_id for turn in runtime.prior_turns] == [
        "turn-1:prior:0",
        "turn-1:prior:1",
    ]
    assert all(turn.timestamp == NOW for turn in runtime.prior_turns)


async def test_bound_incident_context_reaches_runtime_as_last_system_turn() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(
            prior_turns=[{"role": "user", "content": "Earlier question"}],
            bound_context={
                "kind": "incident",
                "incident_id": "incident-42",
                "correlation_id": "correlation-7",
            },
        )
    )

    anchor = runtime.prior_turns[-1]
    assert anchor.direction == "system"
    assert anchor.turn_id == "turn-1:bound-context"
    assert anchor.content == (
        "Bound conversation context: kind=incident, "
        "incident_id=incident-42, correlation_id=correlation-7"
    )


async def test_absent_bound_context_adds_no_anchor_turn() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(prior_turns=[{"role": "user", "content": "Earlier question"}])
    )

    assert [turn.direction for turn in runtime.prior_turns] == ["inbound"]


async def test_clarification_projection_preserves_specific_question() -> None:
    runtime_result = _runtime_result("clarification")
    runtime_result.planning.clarification = "Which incident should I investigate?"

    projection = _projection(await _processor(_Runtime(runtime_result)).process(_request()))

    assert projection["status"] == "clarification"
    assert projection["semantic_result"]["answer"] == "Which incident should I investigate?"
    assert projection["semantic_result"]["reason_code"] == ("semantic_clarification_required")


async def test_expired_deadline_and_pre_cancel_never_call_runtime() -> None:
    runtime = _Runtime()
    processor = _processor(runtime)

    expired = _projection(await processor.process(_request(deadline_at=NOW - timedelta(seconds=1))))
    cancelled = _projection(
        await _processor(runtime).process(_request(cancelled=True, idempotency_key="cancelled"))
    )

    assert expired["semantic_result"]["reason_code"] == "semantic_deadline_exceeded"
    assert cancelled["status"] == "cancelled"
    assert runtime.calls == 0


async def test_overlong_deadline_is_rejected_before_runtime() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)

    with pytest.raises(SemanticTurnRejectedError, match="semantic_deadline_too_far"):
        await processor.process(_request(deadline_at=NOW + timedelta(seconds=91)))

    assert runtime.calls == 0


async def test_deadline_and_cancellation_interrupt_inflight_runtime() -> None:
    timeout_runtime = _Runtime(wait_for_cancel=True)
    realtime = datetime.now(UTC)
    timed_out = await _processor(
        timeout_runtime,
        now=lambda: datetime.now(UTC),
    ).process(_request(deadline_at=realtime + timedelta(milliseconds=20)))

    cancel_runtime = _Runtime(wait_for_cancel=True)
    cancel_event = asyncio.Event()
    pending = asyncio.create_task(
        _processor(cancel_runtime).process(
            _request(idempotency_key="inflight-cancel"),
            cancelled=cancel_event,
        )
    )
    await asyncio.sleep(0)
    cancel_event.set()
    cancelled = await pending

    assert _projection(timed_out)["semantic_result"]["reason_code"] == (
        "semantic_deadline_exceeded"
    )
    assert _projection(cancelled)["status"] == "cancelled"


async def test_deadline_bounds_result_store_wait() -> None:
    store = _BlockingResultStore()
    realtime = datetime.now(UTC)
    processor = SemanticTurnProcessor(
        runtime=_Runtime(),
        results=store,
        now=lambda: datetime.now(UTC),
    )

    encoded = await asyncio.wait_for(
        processor.process(_request(deadline_at=realtime + timedelta(milliseconds=20))),
        timeout=0.2,
    )

    assert _projection(encoded)["semantic_result"]["reason_code"] == ("semantic_deadline_exceeded")


async def test_cancellation_interrupts_result_store_wait() -> None:
    store = _BlockingResultStore()
    cancelled = asyncio.Event()
    processor = SemanticTurnProcessor(
        runtime=_Runtime(),
        results=store,
        now=lambda: datetime.now(UTC),
    )
    pending = asyncio.create_task(
        processor.process(
            _request(deadline_at=datetime.now(UTC) + timedelta(seconds=1)),
            cancelled=cancelled,
        )
    )
    await store.entered.wait()

    cancelled.set()
    encoded = await asyncio.wait_for(pending, timeout=0.2)

    assert _projection(encoded)["status"] == "cancelled"


async def test_duplicate_returns_exact_prior_projection_without_reexecution() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)
    request = _request()

    first = await processor.process(request)
    second = await processor.process(request)

    assert second == first
    assert runtime.calls == 1


async def test_concurrent_duplicate_executes_runtime_once() -> None:
    runtime = _ContendedRuntime()
    state_store = InMemoryStateStore()
    first_processor = SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(state_store),
        now=lambda: NOW,
    )
    second_processor = SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(state_store),
        now=lambda: NOW,
    )
    request = _request()

    first = asyncio.create_task(first_processor.process(request))
    await runtime.entered.wait()
    second = asyncio.create_task(second_processor.process(request))
    await asyncio.sleep(0)
    runtime.release.set()

    first_projection, second_projection = await asyncio.gather(first, second)

    assert second_projection == first_projection
    assert runtime.calls == 1


async def test_abandoned_claim_is_recovered_only_after_lease_expiry() -> None:
    state_store = InMemoryStateStore()
    before_expiry = StateStoreSemanticTurnResultStore(
        state_store,
        claim_lease_seconds=30,
        now=lambda: NOW,
    )
    after_expiry = StateStoreSemanticTurnResultStore(
        state_store,
        claim_lease_seconds=30,
        now=lambda: NOW + timedelta(seconds=31),
    )

    original_claim = await before_expiry.claim("turn-1", "sha256:request")

    assert original_claim is not None
    assert await before_expiry.claim("turn-1", "sha256:request") is None
    recovered_claim = await after_expiry.claim("turn-1", "sha256:request")
    assert recovered_claim is not None
    assert recovered_claim != original_claim
    assert not await after_expiry.release(
        "turn-1",
        "sha256:request",
        original_claim,
    )
    assert await after_expiry.release(
        "turn-1",
        "sha256:request",
        recovered_claim,
    )
    assert await after_expiry.claim("turn-1", "sha256:request") is not None


async def test_default_claim_lease_covers_healthy_request_deadline() -> None:
    state_store = InMemoryStateStore()
    owner = StateStoreSemanticTurnResultStore(state_store, now=lambda: NOW)
    contender = StateStoreSemanticTurnResultStore(
        state_store,
        now=lambda: NOW + timedelta(seconds=90),
    )

    assert await owner.claim("turn-1", "sha256:request") is not None
    assert await contender.claim("turn-1", "sha256:request") is None


async def test_result_persistence_failure_releases_owned_claim() -> None:
    class FailingResultStore:
        released_claims: list[str]

        def __init__(self) -> None:
            self.released_claims = []

        async def get(self, idempotency_key: str) -> bytes | None:
            return None

        async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
            return "claim-1"

        async def release(
            self,
            idempotency_key: str,
            request_digest: str,
            claim_id: str,
        ) -> bool:
            self.released_claims.append(claim_id)
            return True

        async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
            raise RuntimeError("state store unavailable")

    store = FailingResultStore()
    processor = SemanticTurnProcessor(
        runtime=_Runtime(_runtime_result("answered")),
        results=store,
        now=lambda: NOW,
    )

    projection = _projection(await processor.process(_request()))

    assert projection["semantic_result"]["reason_code"] == "semantic_result_store_unavailable"
    assert store.released_claims == ["claim-1"]


async def test_reused_idempotency_key_for_different_turn_is_rejected() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)
    await processor.process(_request())
    conflicting = _request()
    semantic_turn = cast(dict[str, object], conflicting["semantic_turn"])
    semantic_turn["turn_id"] = "turn-2"

    with pytest.raises(SemanticTurnRejectedError, match="semantic_idempotency_conflict"):
        await processor.process(conflicting)

    assert runtime.calls == 1


async def test_answered_projection_requires_complete_exact_evidence() -> None:
    answered = _projection(
        await _processor(_Runtime(_runtime_result("answered"))).process(_request())
    )
    semantic = answered["semantic_result"]

    assert answered["status"] == "answered"
    assert semantic["ontology_release_digest"] == RELEASE_DIGEST
    assert semantic["principal_manifest_digest"] == MANIFEST_DIGEST
    assert semantic["plan_digest"] == PLAN_DIGEST
    assert semantic["execution_receipt_digest"].startswith("sha256:")
    assert semantic["evidence_refs"] == ["inventory:evidence-1"]
    assert semantic["checks_completed"] == semantic["checks_total"] == 1
    assert semantic["semantic_route"] == "verified_query_plan"
    assert semantic["execution_authority"] is False


async def test_incident_evidence_answer_never_claims_cause_and_drafts_only() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    projection = _projection(encoded)
    semantic = projection["semantic_result"]
    assert semantic["disposition"] == "answered"
    answer = semantic["answer"]
    assert answer.startswith("## Verified incident evidence")
    assert "1 correlated audit record was verified." in answer
    assert "Root cause isn't available" in answer
    assert "impact evidence" in answer
    assert "grounded citations" in answer
    assert "Collect the missing evidence before proposing a change." in answer
    assert "```json" not in answer
    payload = projection["payload"]
    technical_details = payload["technical_details"]
    assert technical_details["schema_version"] == 1
    assert technical_details["kind"] == "semantic_query_outputs"
    incident = technical_details["outputs"][0]
    assert incident["incident_profile"]["correlation_id"] == "incident-correlation-301"
    assert incident["incident_profile"]["status"] == "triaging"
    assert incident["correlated_evidence"][0]["audit_ref"] == "audit:1"
    assert incident["evidence_gaps"] == [
        "impact_evidence_missing",
        "grounded_citations_missing",
    ]
    assert incident["causal_assessment"] == {
        "status": "not_available",
        "reason": "causal_analysis_not_implemented",
    }
    assert incident["next_safe_step"] == {
        "operation": "collect_evidence",
        "authority": "read_only",
        "execution_authority": False,
    }
    assert '"cause":' not in answer


async def test_incident_evidence_answer_is_localized_without_changing_machine_output() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            locale="ko",
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            },
        )
    )

    projection = _projection(encoded)
    answer = projection["semantic_result"]["answer"]
    assert answer.startswith("## 검증된 인시던트 근거")
    assert "감사 기록 1건을 검증했습니다." in answer
    assert "근본 원인을 확인할 수 없습니다." in answer
    assert "영향 근거, 근거 인용" in answer
    assert "```json" not in answer
    assert (
        projection["payload"]["technical_details"]["outputs"][0]["correlated_evidence"][0][
            "audit_ref"
        ]
        == "audit:1"
    )


async def test_incident_evidence_with_cause_claim_is_held() -> None:
    encoded = await _processor(
        _Runtime(_incident_evidence_runtime_result(inject_cause=True))
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_evidence_with_mismatched_correlation_is_held() -> None:
    encoded = await _processor(
        _Runtime(
            _incident_evidence_runtime_result(output_correlation_id="incident-correlation-other")
        )
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_bound_turn_without_incident_evidence_still_answers() -> None:
    encoded = await _processor(_Runtime(_runtime_result("answered"))).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "answered"


async def test_incident_bound_turn_reading_another_incident_is_held() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000999",
                "correlation_id": "incident-correlation-999",
            }
        )
    )

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "incident_evidence_mismatched_binding"
    assert semantic["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert semantic["answer"].startswith("## Evidence from a different incident was read")


async def test_unbound_turn_without_incident_evidence_still_answers() -> None:
    encoded = await _processor(_Runtime(_runtime_result("answered"))).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "answered"


@pytest.mark.parametrize(
    ("locale", "heading", "limitation"),
    [
        ("en", "## Ontology relationships", "grants no execution authority"),
        ("ko", "## 온톨로지 관계", "실행 권한을 부여하지 않습니다"),
    ],
)
async def test_ontology_relationship_answer_is_exact_and_localized(
    locale: str,
    heading: str,
    limitation: str,
) -> None:
    encoded = await _processor(_Runtime(_ontology_relationship_runtime_result())).process(
        _request(locale=locale)
    )

    projection = _projection(encoded)
    semantic = projection["semantic_result"]
    assert semantic["disposition"] == "answered"
    answer = semantic["answer"]
    assert answer.startswith(heading)
    assert "`VmTaskRun` --`executes_task`--> `PythonTask` (`many_to_one`)" in answer
    assert "immutable PythonTask artifact selected by a VM task run" in answer
    assert limitation in answer
    relationships = projection["payload"]["technical_details"]["outputs"][0][
        "ontology_relationships"
    ]
    assert relationships["ontology_release_digest"] == RELEASE_DIGEST
    assert relationships["execution_authority"] is False


async def test_ontology_relationship_answer_rejects_stale_release_output() -> None:
    encoded = await _processor(
        _Runtime(
            _ontology_relationship_runtime_result(output_release_digest="sha256:" + ("f" * 64))
        )
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_answered_rule_search_projects_exact_candidate_receipt() -> None:
    projection = _projection(
        await _processor(_Runtime(_rule_search_runtime_result())).process(_request())
    )

    rule_search = projection["payload"]["rule_search"]
    assert projection["status"] == "answered"
    assert rule_search["query_digest"].startswith("sha256:")
    assert rule_search["retrieval_receipt"]["generation_digest"] == GENERATION_DIGEST
    assert rule_search["function_invocation_receipt_digest"].startswith("sha256:")
    assert rule_search["function_invocation_receipt"] == {
        "blocked_by": [],
        "capability": "query.function",
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "depends_on": [],
        "duration_ms": 5,
        "evidence_mode": "operational",
        "evidence_refs": ["inventory:evidence-1"],
        "goal_id": "resources",
        "intent": "function",
        "reason": None,
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "status": "completed",
        "task_id": "query:resources",
    }
    assert rule_search["candidates"] == [
        {
            "authority": "candidate_only",
            "components": {"hybrid": 0.9},
            "rank": 1,
            "rule_ref": "rule.one",
        }
    ]
    assert rule_search["authority"] == "candidate_only"
    assert rule_search["execution_authority"] is False


async def test_authority_bearing_rule_search_output_is_held() -> None:
    projection = _projection(
        await _processor(_Runtime(_rule_search_runtime_result(execution_authority=True))).process(
            _request()
        )
    )

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert (
        projection["semantic_result"]["unavailable_reason"] == "authoritative_evidence_unavailable"
    )
    assert "rule_search" not in projection["payload"]


async def test_rule_search_receipt_must_bind_exact_function_capability() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    assert runtime_result.intent_graph is not None
    assert runtime_result.intent_graph_evidence is not None
    receipt = runtime_result.execution.receipts[0].model_copy(
        update={"intent": "object_set", "capability": "query.object_set"}
    )
    execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status=runtime_result.execution.status,
        results=runtime_result.execution.results,
        receipts=(receipt,),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    graph = {
        **runtime_result.intent_graph,
        "goals": [
            {
                **runtime_result.intent_graph["goals"][0],
                "intent": "object_set",
                "capability": "query.object_set",
            }
        ],
    }
    evidence = {
        **runtime_result.intent_graph_evidence,
        "goals": [
            {
                **runtime_result.intent_graph_evidence["goals"][0],
                "intent": "object_set",
                "capability": "query.object_set",
            }
        ],
    }
    tampered = RuntimeSemanticTurnResult(
        disposition=runtime_result.disposition,
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=execution,
        intent_graph=graph,
        intent_graph_evidence=evidence,
    )

    projection = _projection(await _processor(_Runtime(tampered)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_rule_search_receipt_must_match_function_operation_and_corpus() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    node_result = runtime_result.execution.results["resources"]
    output = cast(dict[str, object], node_result.value)
    receipt = RuleSearchReceipt.model_validate(output["retrieval_receipt"]).model_copy(
        update={"operation": "explain", "corpus": "discovery"}
    )
    output["retrieval_receipt"] = receipt.model_dump(mode="json")
    output["retrieval_receipt_digest"] = receipt.digest

    projection = _projection(await _processor(_Runtime(runtime_result)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_rule_search_candidates_must_not_exceed_function_limit() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    assert runtime_result.planning.plan is not None
    original_node = runtime_result.planning.plan.nodes[0]
    query = {**RULE_QUERY, "limit": 1}
    node = SimpleNamespace(
        node_id=original_node.node_id,
        kind=original_node.kind,
        arguments={"function_name": "catalog.search_rules", "arguments": query},
    )
    plan = SimpleNamespace(
        ontology_release_digest=runtime_result.planning.plan.ontology_release_digest,
        semantic_catalog_digest=runtime_result.planning.plan.semantic_catalog_digest,
        plan_digest=runtime_result.planning.plan.plan_digest,
        nodes=(node,),
    )
    output = cast(dict[str, object], runtime_result.execution.results["resources"].value)
    candidates = cast(list[dict[str, object]], output["candidates"])
    candidates.append(
        {
            "rule_ref": "rule.two",
            "rank": 2,
            "components": {"hybrid": 0.8},
            "authority": "candidate_only",
        }
    )
    receipt_payload = cast(dict[str, object], output["retrieval_receipt"])
    receipt_results = cast(list[dict[str, object]], receipt_payload["results"])
    receipt_results.append(
        {
            "rule_ref": "rule.two",
            "rank": 2,
            "components": {"hybrid": 0.8},
        }
    )
    receipt_payload["query_digest"] = rule_search_query_digest(query)
    receipt = RuleSearchReceipt.model_validate(receipt_payload)
    output["retrieval_receipt"] = receipt.model_dump(mode="json")
    output["retrieval_receipt_digest"] = receipt.digest
    tampered = RuntimeSemanticTurnResult(
        disposition=runtime_result.disposition,
        reason=runtime_result.reason,
        planning=SimpleNamespace(plan=plan, manifest_digest=MANIFEST_DIGEST),
        execution=runtime_result.execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=runtime_result.intent_graph_evidence,
    )

    projection = _projection(await _processor(_Runtime(tampered)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_answered_runtime_without_evidence_is_held() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.execution is not None
    incomplete_execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status="completed",
        results=runtime_result.execution.results,
        receipts=tuple(
            receipt.model_copy(update={"evidence_refs": ()})
            for receipt in runtime_result.execution.receipts
        ),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    incomplete = RuntimeSemanticTurnResult(
        disposition="answered",
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=incomplete_execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=runtime_result.intent_graph_evidence,
    )

    projection = _projection(await _processor(_Runtime(incomplete)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"


async def test_answered_runtime_with_inconsistent_projected_evidence_is_held() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.intent_graph_evidence is not None
    inconsistent_evidence = {
        **runtime_result.intent_graph_evidence,
        "status": "partial",
    }
    inconsistent = RuntimeSemanticTurnResult(
        disposition="answered",
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=runtime_result.execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=inconsistent_evidence,
    )

    projection = _projection(await _processor(_Runtime(inconsistent)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"


async def test_unavailable_and_internal_failure_are_detail_free_holds() -> None:
    unavailable = _projection(await _processor(None).process(_request()))
    failed = _projection(
        await _processor(_Runtime(failure=RuntimeError("secret provider response"))).process(
            _request(idempotency_key="failed")
        )
    )

    assert unavailable["semantic_result"]["reason_code"] == "semantic_runtime_unavailable"
    assert failed["semantic_result"]["reason_code"] == "semantic_runtime_failed"
    assert "secret" not in json.dumps(failed)


async def test_consumer_publishes_projection_and_dlqs_publish_failure() -> None:
    class _FailingProjectionBus(InMemoryEventBus):
        projection_failures_remaining = 0

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, Any],
        ) -> PublishReceipt:
            if self.projection_failures_remaining and topic == "operator.projection":
                self.projection_failures_remaining -= 1
                raise RuntimeError("synthetic publish failure")
            return await super().publish(topic, key, payload)

    bus = _FailingProjectionBus()
    await bus.publish("operator.request", "one", _request(idempotency_key="one"))
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )
    projections = [item async for item in bus.subscribe("operator.projection", "assert")]
    assert projections[0].payload["status"] == "held"

    await bus.publish("operator.request", "retry", _request(idempotency_key="retry"))
    bus.projection_failures_remaining = 2
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
        publish_retry_delay_seconds=0,
    )
    retried = [item async for item in bus.subscribe("operator.projection", "retry-assert")]
    assert retried[-1].payload["idempotency_key"] == "retry"

    await bus.publish("operator.request", "two", _request(idempotency_key="two"))
    bus.projection_failures_remaining = 3
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
        publish_retry_delay_seconds=0,
    )
    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert dlq[-1].payload["reason"] == "semantic_turn_publish_failed"


def test_runtime_binding_is_optional_explicit_and_rejects_partial_transport() -> None:
    state_store = InMemoryStateStore()

    assert (
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="topics MUST be configured together"):
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={"FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request"},
        )
    binding = semantic_turn_binding_from_config(
        state_store=state_store,
        runtime=None,
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
        },
    )
    assert binding is not None
    assert binding.available is False
    assert binding.unavailable_reason == "semantic_runtime_unavailable"

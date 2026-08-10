"""Dependency-wave execution of exact ontology query plans."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.query_execution import (
    OntologyQueryPlanExecutor,
    QueryNodeResult,
)
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    TaskStatus,
    canonical_json,
    content_digest,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def _plan(nodes: tuple[OntologyQueryNode, ...], outputs: tuple[str, ...]) -> OntologyQueryPlan:
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST_A,
        "semantic_catalog_digest": DIGEST_B,
        "problem_frame_digest": DIGEST_A,
        "purpose": "incident-investigation",
        "caller_role": "Reader",
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": outputs,
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=DIGEST_A,
        semantic_catalog_digest=DIGEST_B,
        problem_frame_digest=DIGEST_A,
        purpose="incident-investigation",
        caller_role="Reader",
        nodes=nodes,
        output_node_ids=outputs,
        plan_digest=content_digest(payload),
    )


async def test_executor_runs_independent_nodes_concurrently_then_joins() -> None:
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()

    async def metric(node, dependencies):  # type: ignore[no-untyped-def]
        assert not dependencies
        (first_started if node.node_id == "first" else second_started).set()
        await release.wait()
        return QueryNodeResult(value=node.node_id, evidence_refs=(f"evidence:{node.node_id}",))

    async def join(node, dependencies):  # type: ignore[no-untyped-def]
        assert node.node_id == "join"
        assert set(dependencies) == {"first", "second"}
        return QueryNodeResult(value=tuple(sorted(item.value for item in dependencies.values())))

    nodes = (
        OntologyQueryNode(
            node_id="first",
            kind=QueryNodeKind.METRIC_SERIES,
            output_kind="metric_series",
        ),
        OntologyQueryNode(
            node_id="second",
            kind=QueryNodeKind.METRIC_SERIES,
            output_kind="metric_series",
        ),
        OntologyQueryNode(
            node_id="join",
            kind=QueryNodeKind.EVIDENCE_JOIN,
            depends_on=("first", "second"),
            output_kind="evidence",
        ),
    )
    executor = OntologyQueryPlanExecutor(
        handlers={
            QueryNodeKind.METRIC_SERIES: metric,
            QueryNodeKind.EVIDENCE_JOIN: join,
        },
        now=lambda: NOW,
    )
    task = asyncio.create_task(
        executor.execute(
            _plan(nodes, ("join",)),
            expected_release_digest=DIGEST_A,
            expected_role="Reader",
            expected_purpose="incident-investigation",
        )
    )
    await asyncio.wait_for(first_started.wait(), timeout=1)
    await asyncio.wait_for(second_started.wait(), timeout=1)
    release.set()
    execution = await task

    assert execution.status == "completed"
    assert execution.results["join"].value == ("first", "second")
    assert [item.status for item in execution.receipts] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]
    assert execution.execution_authority is False


async def test_executor_skips_descendant_after_stable_failure() -> None:
    async def fail(node, dependencies):  # type: ignore[no-untyped-def]
        del node, dependencies
        raise ValueError("provider details must not escape")

    nodes = (
        OntologyQueryNode(
            node_id="source",
            kind=QueryNodeKind.METRIC_SERIES,
            output_kind="metric_series",
        ),
        OntologyQueryNode(
            node_id="join",
            kind=QueryNodeKind.EVIDENCE_JOIN,
            depends_on=("source",),
            output_kind="evidence",
        ),
    )
    execution = await OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.METRIC_SERIES: fail},
        now=lambda: NOW,
    ).execute(
        _plan(nodes, ("join",)),
        expected_release_digest=DIGEST_A,
        expected_role="Reader",
        expected_purpose="incident-investigation",
    )

    assert execution.status == "failed"
    assert execution.results == {}
    assert execution.receipts[0].reason == "capability_failed"
    assert execution.receipts[1].status is TaskStatus.SKIPPED
    assert execution.receipts[1].blocked_by == ("source",)
    assert "provider details" not in str(execution.receipts)


async def test_executor_rejects_stale_authority_and_cancels_before_calls() -> None:
    called = False

    async def handler(node, dependencies):  # type: ignore[no-untyped-def]
        nonlocal called
        del node, dependencies
        called = True
        return QueryNodeResult(value={})

    node = OntologyQueryNode(
        node_id="source",
        kind=QueryNodeKind.METRIC_SERIES,
        arguments_json=canonical_json({}),
        output_kind="metric_series",
    )
    plan = _plan((node,), ("source",))
    executor = OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.METRIC_SERIES: handler},
        now=lambda: NOW,
    )

    with pytest.raises(ValueError, match="stale release"):
        await executor.execute(
            plan,
            expected_release_digest=DIGEST_B,
            expected_role="Reader",
            expected_purpose="incident-investigation",
        )
    with pytest.raises(PermissionError, match="role changed"):
        await executor.execute(
            plan,
            expected_release_digest=DIGEST_A,
            expected_role="Owner",
            expected_purpose="incident-investigation",
        )

    cancelled = asyncio.Event()
    cancelled.set()
    execution = await executor.execute(
        plan,
        expected_release_digest=DIGEST_A,
        expected_role="Reader",
        expected_purpose="incident-investigation",
        cancelled=cancelled,
    )
    assert execution.status == "cancelled"
    assert execution.receipts[0].status is TaskStatus.CANCELLED
    assert called is False


async def test_executor_reports_unavailable_handler_without_fallback() -> None:
    node = OntologyQueryNode(
        node_id="history",
        kind=QueryNodeKind.TOPOLOGY_AT,
        output_kind="object_set",
    )
    execution = await OntologyQueryPlanExecutor(handlers={}, now=lambda: NOW).execute(
        _plan((node,), ("history",)),
        expected_release_digest=DIGEST_A,
        expected_role="Reader",
        expected_purpose="incident-investigation",
    )

    assert execution.status == "partial"
    assert execution.receipts[0].status is TaskStatus.UNAVAILABLE
    assert execution.receipts[0].reason == "capability_unavailable"

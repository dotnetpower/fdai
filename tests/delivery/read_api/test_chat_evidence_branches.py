"""Bounded parallel evidence-branch orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from fdai.delivery.read_api.routes.chat_evidence_branches import (
    EvidenceBranchKind,
    EvidenceBranchResult,
    EvidenceBranchSpec,
    EvidenceBranchStatus,
    resolve_evidence_branches,
)
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    merge_evidence_branch_results,
)
from fdai.delivery.read_api.routes.chat_evidence_pipeline import (
    resolve_parallel_chat_evidence,
)


async def test_independent_branches_overlap_and_keep_canonical_order() -> None:
    started: set[EvidenceBranchKind] = set()
    both_started = asyncio.Event()
    events: list[dict[str, Any]] = []

    def resolver(kind: EvidenceBranchKind, key: str):
        async def resolve(_observe):  # type: ignore[no-untyped-def]
            started.add(kind)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.2)
            return {key: {"status": "ok"}}

        return resolve

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    results = await resolve_evidence_branches(
        request_id="request-1",
        base_context={},
        specs=(
            EvidenceBranchSpec(
                kind=EvidenceBranchKind.TOOL,
                resolve=resolver(EvidenceBranchKind.TOOL, "_tool_evidence"),
                evidence_keys=("_tool_evidence",),
            ),
            EvidenceBranchSpec(
                kind=EvidenceBranchKind.AGENT,
                resolve=resolver(EvidenceBranchKind.AGENT, "_agent_evidence"),
                evidence_keys=("_agent_evidence",),
            ),
        ),
        progress_observer=observe,
    )

    assert [result.kind for result in results] == [
        EvidenceBranchKind.TOOL,
        EvidenceBranchKind.AGENT,
    ]
    assert all(result.status is EvidenceBranchStatus.COMPLETED for result in results)
    assert {event["status"] for event in events if event["event"] == "branch"} == {
        "running",
        "completed",
    }


async def test_failure_and_timeout_do_not_discard_successful_sibling() -> None:
    async def fail(_observe):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic branch failure")

    async def wait(_observe):  # type: ignore[no-untyped-def]
        await asyncio.Event().wait()
        return {}

    async def succeed(_observe):  # type: ignore[no-untyped-def]
        return {"_tool_evidence": {"status": "ok"}}

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    results = await resolve_evidence_branches(
        request_id="request-2",
        base_context={"safe": True},
        specs=(
            EvidenceBranchSpec(EvidenceBranchKind.OPERATIONAL, fail, ("_operational_evidence",)),
            EvidenceBranchSpec(EvidenceBranchKind.PUBLIC_WEB, wait, ("_web_evidence",)),
            EvidenceBranchSpec(EvidenceBranchKind.TOOL, succeed, ("_tool_evidence",)),
        ),
        progress_observer=observe,
        timeout_seconds=0.01,
    )

    assert [result.status for result in results] == [
        EvidenceBranchStatus.FAILED,
        EvidenceBranchStatus.TIMED_OUT,
        EvidenceBranchStatus.COMPLETED,
    ]
    assert results[0].context == {"safe": True}
    assert "_tool_evidence" in results[2].context


async def test_cancelling_parent_cancels_and_awaits_every_branch() -> None:
    cancelled = [asyncio.Event(), asyncio.Event()]

    def resolver(index: int):
        async def resolve(_observe):  # type: ignore[no-untyped-def]
            try:
                await asyncio.Event().wait()
            finally:
                cancelled[index].set()

        return resolve

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    task = asyncio.create_task(
        resolve_evidence_branches(
            request_id="request-3",
            base_context={},
            specs=(
                EvidenceBranchSpec(EvidenceBranchKind.TOOL, resolver(0), ("_tool_evidence",)),
                EvidenceBranchSpec(EvidenceBranchKind.AGENT, resolver(1), ("_agent_evidence",)),
            ),
            progress_observer=observe,
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(event.is_set() for event in cancelled)


async def test_cancellation_observer_failure_does_not_replace_cancelled_error() -> None:
    resolver_cancelled = asyncio.Event()

    async def resolve(_observe):  # type: ignore[no-untyped-def]
        try:
            await asyncio.Event().wait()
        finally:
            resolver_cancelled.set()

    async def observe(event: Mapping[str, Any]) -> None:
        if event.get("status") == "cancelled":
            raise RuntimeError("synthetic observer failure")

    task = asyncio.create_task(
        resolve_evidence_branches(
            request_id="request-cancel-observer",
            base_context={},
            specs=(
                EvidenceBranchSpec(
                    EvidenceBranchKind.TOOL,
                    resolve,
                    ("_tool_evidence",),
                ),
            ),
            progress_observer=observe,
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert resolver_cancelled.is_set()


async def test_branch_count_above_fixed_parallel_limit_is_rejected() -> None:
    async def resolve(_observe):  # type: ignore[no-untyped-def]
        return {}

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    specs = tuple(
        EvidenceBranchSpec(kind, resolve, (f"_{kind.value}_evidence",))
        for kind in EvidenceBranchKind
    )

    with pytest.raises(ValueError, match="between 1 and 4"):
        await resolve_evidence_branches(
            request_id="request-overflow",
            base_context={},
            specs=(*specs, specs[0]),
            progress_observer=observe,
        )


def _result(
    kind: EvidenceBranchKind,
    context: Mapping[str, Any],
) -> EvidenceBranchResult:
    return EvidenceBranchResult(
        kind=kind,
        status=EvidenceBranchStatus.COMPLETED,
        context=context,
        duration_ms=1,
    )


def test_merge_preserves_tool_precedence_over_generic_agent_and_operational() -> None:
    merged = merge_evidence_branch_results(
        "show subscription health",
        {},
        (
            _result(EvidenceBranchKind.TOOL, {"_tool_evidence": {"tool": "health"}}),
            _result(
                EvidenceBranchKind.OPERATIONAL,
                {"_operational_evidence": {"status": "matched"}},
            ),
            _result(EvidenceBranchKind.AGENT, {"_agent_evidence": {"primary_agent": "Bragi"}}),
            _result(EvidenceBranchKind.PUBLIC_WEB, {"_web_evidence": {"status": "ok"}}),
        ),
    )

    assert merged == {"_tool_evidence": {"tool": "health"}, "_web_evidence": {"status": "ok"}}


def test_merge_selected_agent_replaces_competing_tool_and_web_evidence() -> None:
    merged = merge_evidence_branch_results(
        "explain this incident",
        {},
        (
            _result(EvidenceBranchKind.TOOL, {"_tool_evidence": {"tool": "query"}}),
            _result(
                EvidenceBranchKind.AGENT,
                {"_agent_evidence": {"primary_agent": "Heimdall"}},
            ),
            _result(EvidenceBranchKind.PUBLIC_WEB, {"_web_evidence": {"status": "ok"}}),
        ),
        target_agent="Heimdall",
    )

    assert merged == {"_agent_evidence": {"primary_agent": "Heimdall"}}


async def test_chat_pipeline_overlaps_tool_and_operational_resolvers() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    async def rendezvous(name: str) -> None:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del prompt, principal_id
            await rendezvous("tool")
            return {"tool": "query_inventory", "result": {"count": 1}}

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ):
            del prompt, conversation_context
            await rendezvous("operational")
            return {"status": "matched", "incident_id": "INC-example"}

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    merged = await resolve_parallel_chat_evidence(
        request_id="request-4",
        prompt="query_inventory virtual-machine",
        view_context={},
        user_id="reader",
        session_id="session-1",
        conversation_context={"kind": "incident", "incident_id": "INC-example"},
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=OperationalResolver(),
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=observe,
    )

    assert started == {"tool", "operational"}
    assert merged["_tool_evidence"]["tool"] == "query_inventory"
    assert "_operational_evidence" not in merged


async def test_chat_pipeline_overlaps_explicit_web_and_tool_resolvers() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    async def rendezvous(name: str) -> None:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del prompt, principal_id
            await rendezvous("tool")
            return None

    class WebResolver:
        async def resolve(self, prompt: str, view_context: Mapping[str, Any]):
            del prompt, view_context
            await rendezvous("web")
            return {"status": "ok", "snippets": []}

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    merged = await resolve_parallel_chat_evidence(
        request_id="request-5",
        prompt="search the web for current release notes",
        view_context={},
        user_id="reader",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=None,
        agent_delegate=None,
        web_search_resolver=WebResolver(),
        progress_observer=observe,
    )

    assert started == {"tool", "web"}
    assert merged["_web_evidence"]["status"] == "ok"

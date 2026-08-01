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
    *,
    status: EvidenceBranchStatus = EvidenceBranchStatus.COMPLETED,
) -> EvidenceBranchResult:
    return EvidenceBranchResult(
        kind=kind,
        status=status,
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


def test_merge_selected_agent_preserves_operational_evidence() -> None:
    operational = {
        "status": "summary",
        "searched_recent_incidents": 3,
        "incidents": [{"correlation_id": "corr-high", "severity": "high"}],
    }
    merged = merge_evidence_branch_results(
        "최근 발견된 심각도 높은 문제는?",
        {},
        (
            _result(
                EvidenceBranchKind.OPERATIONAL,
                {"_operational_evidence": operational},
            ),
            _result(
                EvidenceBranchKind.AGENT,
                {
                    "_agent_evidence": {
                        "primary_agent": "Heimdall",
                        "answer": "One high-severity signal is recorded.",
                    }
                },
            ),
        ),
        target_agent="Heimdall",
    )

    assert merged["_operational_evidence"] == operational
    assert merged["_agent_evidence"]["primary_agent"] == "Heimdall"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (EvidenceBranchStatus.TIMED_OUT, "agent_conversational_port_unavailable"),
        (EvidenceBranchStatus.FAILED, "agent_conversational_port_error"),
        (EvidenceBranchStatus.UNAVAILABLE, "agent_conversational_port_unavailable"),
    ],
)
def test_merge_selected_agent_failure_becomes_explicit_handoff(
    status: EvidenceBranchStatus,
    reason: str,
) -> None:
    merged = merge_evidence_branch_results(
        "what are you working on?",
        {"routeId": "agents"},
        (_result(EvidenceBranchKind.AGENT, {"routeId": "agents"}, status=status),),
        target_agent="Heimdall",
    )

    assert merged["_agent_evidence"] == {
        "primary_agent": "Bragi",
        "answer": None,
        "facts": {},
        "contributors": [],
        "handoff_from": "Heimdall",
        "handoff_reason": reason,
    }


def test_merge_selected_incident_replaces_implicit_inventory_evidence() -> None:
    operational = {
        "status": "matched",
        "selected_incident": {"correlation_id": "corr-selected"},
    }
    merged = merge_evidence_branch_results(
        "Resource inventory change - Storage account storage-example 이거는 어떤 상태인거야?",
        {"routeId": "incidents"},
        (
            _result(
                EvidenceBranchKind.TOOL,
                {"_tool_evidence": {"tool": "query_inventory"}},
            ),
            _result(
                EvidenceBranchKind.OPERATIONAL,
                {"_operational_evidence": operational},
            ),
        ),
    )

    assert merged == {
        "routeId": "incidents",
        "_operational_evidence": operational,
    }


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


async def test_subscription_health_overrides_semantic_web_plan() -> None:
    calls: list[str] = []

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del principal_id
            calls.append("tool")
            return {
                "tool": "query_subscription_health",
                "authority": "server_subscription_health",
                "result": {"status": "matched", "prompt": prompt},
            }

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ):
            del prompt, conversation_context
            raise AssertionError("deterministic health must not query operational evidence")

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del prompt, user_id, session_id
            raise AssertionError("deterministic health must not invoke an agent")

    class WebResolver:
        async def resolve(self, prompt: str, view_context: Mapping[str, Any]):
            del prompt, view_context
            raise AssertionError("deterministic health must not search the public web")

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    merged = await resolve_parallel_chat_evidence(
        request_id="request-platform-health",
        prompt="현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?",
        view_context={
            "_turn_plan": {
                "kind": "read_tool",
                "tool_name": "web_search",
                "arguments": {"query": "Azure platform outage"},
            }
        },
        user_id="reader",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=OperationalResolver(),
        agent_delegate=AgentDelegate(),
        web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        progress_observer=observe,
    )

    assert calls == ["tool"]
    assert merged["_tool_evidence"]["tool"] == "query_subscription_health"
    assert "_web_evidence" not in merged


async def test_subscription_health_without_plan_skips_operational_branch() -> None:
    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del prompt, principal_id
            return {"tool": "query_subscription_health", "result": {"status": "matched"}}

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ):
            del prompt, conversation_context
            raise AssertionError("deterministic health must not query operational evidence")

    async def observe(_event: Mapping[str, Any]) -> None:
        return None

    merged = await resolve_parallel_chat_evidence(
        request_id="request-platform-health-no-plan",
        prompt="현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?",
        view_context={},
        user_id="reader",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=OperationalResolver(),
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=observe,
    )

    assert merged["_tool_evidence"]["tool"] == "query_subscription_health"
    assert "_operational_evidence" not in merged


async def test_chat_pipeline_prefers_referenced_selected_incident() -> None:
    prompt = "Resource inventory change - Storage account storage-example 이거는 어떤 상태인거야?"
    events: list[dict[str, Any]] = []

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del prompt, principal_id
            raise AssertionError("selected incident must not query general inventory")

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ):
            del prompt
            assert conversation_context == {
                "kind": "incident",
                "incident_id": "incident-1",
                "correlation_id": "corr-selected",
            }
            return {
                "status": "matched",
                "selected_incident": {
                    "incident_id": "incident-1",
                    "correlation_id": "corr-selected",
                    "status": "open",
                },
            }

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del prompt, user_id, session_id
            raise AssertionError("selected incident must not invoke an unrelated agent")

    class WebResolver:
        async def resolve(self, prompt: str, view_context: Mapping[str, Any]):
            del prompt, view_context
            raise AssertionError("selected incident must not search the public web")

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    merged = await resolve_parallel_chat_evidence(
        request_id="request-selected-incident",
        prompt=prompt,
        view_context={
            "routeId": "incidents",
            "records": {
                "selected_incident": [
                    {
                        "incident_id": "incident-1",
                        "correlation_id": "corr-selected",
                        "title": "Resource inventory change - Storage account storage-example",
                    }
                ]
            },
        },
        user_id="reader",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=OperationalResolver(),
        agent_delegate=AgentDelegate(),
        web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        progress_observer=observe,
    )

    assert "_tool_evidence" not in merged
    assert merged["_operational_evidence"]["selected_incident"]["status"] == "open"
    assert {event["branch_kind"] for event in events if event.get("event") == "branch"} == {
        "operational"
    }


async def test_chat_pipeline_prefers_local_aks_inventory_over_planned_web() -> None:
    events: list[dict[str, Any]] = []

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str):
            del principal_id
            assert prompt == "지금 AKS 에 배포되고 있는게 있어?"
            return {
                "tool": "query_inventory",
                "authority": "server_inventory_graph",
                "result": {
                    "status": "matched",
                    "requested_types": ["kubernetes-cluster"],
                    "resources": [],
                },
            }

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del prompt, user_id, session_id
            raise AssertionError("deterministic AKS inventory must not invoke an agent")

    class WebResolver:
        async def resolve_planned(self, *args: object, **kwargs: object):
            del args, kwargs
            raise AssertionError("local AKS inventory must not search the public web")

        async def resolve(self, *args: object, **kwargs: object):
            del args, kwargs
            raise AssertionError("local AKS inventory must not search the public web")

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    merged = await resolve_parallel_chat_evidence(
        request_id="request-aks-inventory",
        prompt="지금 AKS 에 배포되고 있는게 있어?",
        view_context={
            "routeId": "operating-outcomes",
            "_turn_plan": {
                "kind": "read_tool",
                "tool_name": "web_search",
                "arguments": {"query": "AKS deployments", "goal": "current_fact"},
            },
        },
        user_id="reader",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=ToolResolver(),
        evidence_resolver=None,
        agent_delegate=AgentDelegate(),
        web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        progress_observer=observe,
    )

    assert merged["_tool_evidence"]["tool"] == "query_inventory"
    assert "_web_evidence" not in merged
    assert {event["branch_kind"] for event in events if event.get("event") == "branch"} == {"tool"}


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


async def test_chat_pipeline_selected_agent_emits_no_public_web_branch() -> None:
    events: list[dict[str, Any]] = []

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del user_id, session_id
            assert prompt == "@Heimdall 너는 어떤 역할을 담당해?"
            return {
                "primary_agent": "Heimdall",
                "answer": "I own observation signals.",
                "facts": {"agent": "Heimdall"},
            }

    class WebResolver:
        async def resolve(self, *args: object, **kwargs: object):
            del args, kwargs
            raise AssertionError("selected-agent turn must not create a public-web branch")

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    merged = await resolve_parallel_chat_evidence(
        request_id="request-agent-role",
        prompt="너는 어떤 역할을 담당해?",
        view_context={"routeId": "agents"},
        user_id="reader",
        session_id="session-heimdall",
        conversation_context=None,
        target_agent="Heimdall",
        tool_resolver=None,
        evidence_resolver=None,
        agent_delegate=AgentDelegate(),
        web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        progress_observer=observe,
    )

    assert merged["_agent_evidence"]["primary_agent"] == "Heimdall"
    assert merged["_agent_session_target"] == "Heimdall"
    assert "_web_evidence" not in merged
    assert {event["branch_kind"] for event in events if event.get("event") == "branch"} == {"agent"}


async def test_chat_pipeline_selected_agent_can_request_public_web_evidence() -> None:
    events: list[dict[str, Any]] = []

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del user_id, session_id
            assert prompt == "@Heimdall 웹에서 최신 관측 도구를 찾아줘"
            return {
                "primary_agent": "Heimdall",
                "answer": "I will explain the observed public evidence.",
                "facts": {"agent": "Heimdall"},
            }

    class WebResolver:
        async def resolve(self, prompt: str, view_context: Mapping[str, Any]):
            del view_context
            assert prompt == "웹에서 최신 관측 도구를 찾아줘"
            return {
                "status": "matched",
                "snippets": [{"title": "Example observer", "url": "https://example.com"}],
            }

    async def observe(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    merged = await resolve_parallel_chat_evidence(
        request_id="request-agent-web",
        prompt="웹에서 최신 관측 도구를 찾아줘",
        view_context={"routeId": "agents"},
        user_id="reader",
        session_id="session-heimdall",
        conversation_context=None,
        target_agent="Heimdall",
        tool_resolver=None,
        evidence_resolver=None,
        agent_delegate=AgentDelegate(),
        web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        progress_observer=observe,
    )

    assert merged["_agent_evidence"]["primary_agent"] == "Heimdall"
    assert merged["_web_evidence"]["status"] == "matched"
    assert {event["branch_kind"] for event in events if event.get("event") == "branch"} == {
        "agent",
        "public_web",
    }

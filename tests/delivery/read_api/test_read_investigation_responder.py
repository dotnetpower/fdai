from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from fdai.core.read_investigation import ReadInvestigationProgressKind
from fdai.delivery.read_api.routes.read_investigation_responder import (
    HeimdallReadInvestigationChatDelegate,
    HeimdallReadInvestigationResponder,
)
from fdai.delivery.read_api.routes.read_investigations import (
    ReadInvestigationDirectExecution,
    ReadInvestigationRunRejectedError,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadLatencySample,
    ReadToolId,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)


class _Executor:
    transport = "rest"

    def __init__(self) -> None:
        self.calls = 0
        self._results: dict[str, Any] = {}

    async def execute(  # type: ignore[no-untyped-def]
        self,
        plan,
        *,
        owner_principal_id,
        progress_observer=None,
    ):
        assert plan.request.requester_ref == owner_principal_id
        cached = self._results.get(plan.request.idempotency_key)
        if cached is not None:
            return ReadInvestigationDirectExecution(result=cached, replayed=True)
        self.calls += 1
        if progress_observer is not None:
            for kind in (
                ReadInvestigationProgressKind.PLANNED,
                ReadInvestigationProgressKind.RESOURCE_RESOLVED,
                ReadInvestigationProgressKind.STATE_QUERYING,
                ReadInvestigationProgressKind.STATE_COMPLETED,
                ReadInvestigationProgressKind.EVIDENCE_CORRELATING,
                ReadInvestigationProgressKind.COMPLETED,
            ):
                await progress_observer(kind)
        result = SimpleNamespace(
            outcome=SimpleNamespace(value="matched"),
            evidence=(SimpleNamespace(authority="azure.resource_state", records=()),),
            evidence_refs=("evidence:one",),
        )
        self._results[plan.request.idempotency_key] = result
        return ReadInvestigationDirectExecution(result=result, replayed=False)


class _RejectingExecutor(_Executor):
    async def execute(  # type: ignore[no-untyped-def]
        self,
        plan,
        *,
        owner_principal_id,
        progress_observer=None,
    ):
        del plan, owner_principal_id, progress_observer
        raise ReadInvestigationRunRejectedError(
            "read investigation is already in progress",
            retry_after_seconds=3,
        )


class _NetworkExecutor(_Executor):
    def __init__(self, envelope: ReadEvidenceEnvelope) -> None:
        super().__init__()
        self._envelope = envelope

    async def execute(  # type: ignore[no-untyped-def]
        self,
        plan,
        *,
        owner_principal_id,
        progress_observer=None,
    ):
        assert plan.request.requester_ref == owner_principal_id
        self.calls += 1
        if progress_observer is not None:
            await progress_observer(ReadInvestigationProgressKind.PLANNED)
        result = SimpleNamespace(
            outcome=SimpleNamespace(value="matched"),
            evidence=(self._envelope,),
            evidence_refs=self._envelope.evidence_refs,
        )
        return ReadInvestigationDirectExecution(result=result, replayed=False)


class _Latency:
    async def append(self, sample: ReadLatencySample) -> None:
        del sample

    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]:
        del limit
        return tuple(
            ReadLatencySample(
                tool_id=tool_id,
                transport=transport,
                operation_class=operation_class,
                succeeded=True,
                queue_duration_ms=0,
                execution_duration_ms=100,
                recorded_at=NOW,
            )
            for _ in range(20)
        )


def _delegate(executor: _Executor) -> HeimdallReadInvestigationChatDelegate:
    return HeimdallReadInvestigationChatDelegate(
        responder=HeimdallReadInvestigationResponder(
            executor=executor,  # type: ignore[arg-type]
            latency_store=_Latency(),
            scope_ref="scope:allowed",
        )
    )


def _facts(result: dict[str, object]) -> dict[str, Any]:
    return cast(dict[str, Any], result["facts"])


def _answer(result: dict[str, object]) -> str:
    return cast(str, result["answer"])


async def test_chat_delegate_executes_measured_fast_read_as_heimdall() -> None:
    executor = _Executor()
    result = await _delegate(executor).delegate(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert result["primary_agent"] == "Heimdall"
    assert _facts(result)["mode"] == "direct"
    assert _facts(result)["status"] == "matched"
    assert _facts(result)["replayed"] is False
    assert executor.calls == 1


async def test_chat_delegate_replays_same_direct_read_without_provider_recall() -> None:
    executor = _Executor()
    delegate = _delegate(executor)
    first = await delegate.delegate(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    replay = await delegate.delegate(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )

    assert first is not None and replay is not None
    assert first["facts"]["replayed"] is False
    assert replay["facts"]["replayed"] is True
    assert executor.calls == 1


async def test_chat_delegate_reports_active_direct_run_without_provider_recall() -> None:
    executor = _RejectingExecutor()
    result = await _delegate(executor).delegate(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert result["facts"] == {
        "status": "unavailable",
        "reason": "idempotency_rejected",
        "retry_after_seconds": 3,
        "intent": "resource_state",
        "resource_name": "vm-01",
    }
    assert executor.calls == 0


async def test_chat_delegate_streams_activities_and_milestones() -> None:
    executor = _Executor()
    events: list[dict[str, object]] = []

    async def observe(event: Any) -> None:
        events.append(dict(event))

    result = await _delegate(executor).delegate_with_progress(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
        progress_observer=observe,
    )

    assert result is not None
    assert result["primary_agent"] == "Heimdall"
    assert [event["event"] for event in events] == [
        "activity",
        "activity",
        "milestone",
        "activity",
        "activity",
        "activity",
        "milestone",
        "activity",
    ]
    assert events[1]["activity_id"] == "resource"
    assert events[3]["activity_id"] == "state"


async def test_chat_delegate_hands_multi_source_work_off_before_cloud_io() -> None:
    executor = _Executor()
    result = await _delegate(executor).delegate(
        prompt="Who stopped vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert _facts(result)["mode"] == "detached"
    assert _facts(result)["status"] == "handoff_required"
    assert executor.calls == 0


async def test_chat_delegate_ignores_unrelated_question() -> None:
    executor = _Executor()
    result = await _delegate(executor).delegate(
        prompt="Tell me a joke",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is None
    assert executor.calls == 0


async def test_chat_delegate_renders_korean_nsg_ports_with_reachability_caveat() -> None:
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="azure.network_security",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(
            ReadEvidenceRecord(
                occurred_at=NOW,
                status="allow",
                details=(
                    ("rule_name", "allow-https"),
                    ("direction", "inbound"),
                    ("protocol", "tcp"),
                    ("source_prefixes", "Internet"),
                    ("destination_ports", "443"),
                    ("priority", "200"),
                ),
            ),
        ),
        evidence_refs=("evidence:one",),
    )
    executor = _NetworkExecutor(envelope)
    result = await _delegate(executor).delegate(
        prompt="nsg-app에서 열린 포트를 보여줘",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert "TCP 443" in _answer(result)
    assert "end-to-end" in _answer(result)
    assert _facts(result)["records"][0]["details"]["rule_name"] == "allow-https"


async def test_chat_delegate_renders_peering_state_and_flags() -> None:
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="azure.network_peering",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(
            ReadEvidenceRecord(
                occurred_at=NOW,
                status="connected",
                details=(
                    ("peering_name", "hub-to-spoke"),
                    ("remote_vnet", "vnet-spoke"),
                    ("sync_level", "fullyinsync"),
                    ("allow_vnet_access", "true"),
                    ("allow_forwarded_traffic", "true"),
                    ("allow_gateway_transit", "true"),
                    ("use_remote_gateways", "false"),
                ),
            ),
        ),
        evidence_refs=("evidence:one",),
    )
    executor = _NetworkExecutor(envelope)
    result = await _delegate(executor).delegate(
        prompt="How is vnet-hub peered?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert "hub-to-spoke -> vnet-spoke" in _answer(result)
    assert "gateway-transit=true" in _answer(result)

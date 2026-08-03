from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from fdai.core.read_investigation import ReadInvestigationProgressKind
from fdai.delivery.operator_api.routes.read_investigation_responder import (
    HeimdallReadInvestigationChatDelegate,
    HeimdallReadInvestigationResponder,
)
from fdai.delivery.operator_api.routes.read_investigations import (
    ReadInvestigationDirectExecution,
    ReadInvestigationRunRejectedError,
)
from fdai.shared.providers.read_investigation import (
    ActorKind,
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


class _ColdLatency:
    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]:
        del tool_id, transport, operation_class, limit
        return ()


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


async def test_chat_delegate_explains_read_availability_from_typed_evidence() -> None:
    executor = _Executor()
    result = await _delegate(executor).delegate(
        prompt="vm-01 current state: explain read availability locale=en",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert _facts(result)["read_availability_explanation"] is True
    assert "Azure control-plane state for vm-01 is readable" in _answer(result)
    assert "did not encounter a scope or authorization failure" in _answer(result)


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
    assert result["facts"]["status"] == "unavailable"
    assert result["facts"]["reason"] == "idempotency_rejected"
    assert result["facts"]["retry_after_seconds"] == 3
    assert result["facts"]["intent"] == "resource_state"
    assert result["facts"]["resource_name"] == "vm-01"
    assert result["facts"]["evidence_refs"][0].startswith("agent-state:Heimdall:sha256:")
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
        "milestone",
        "activity",
        "activity",
        "milestone",
        "activity",
        "activity",
        "activity",
        "milestone",
        "activity",
        "activity",
    ]
    assert events[0]["message_id"] == "handoff-bragi-heimdall"
    assert events[0]["agent"] == "Bragi"
    activity_events = [event for event in events if event["event"] == "activity"]
    assert all(event.get("detail") == "<redacted-resource>" for event in activity_events[:-1])
    assert all("vm-01" not in str(event) for event in events)
    assert events[2]["activity_id"] == "resource"
    assert events[4]["activity_id"] == "state"
    assert events[-1]["activity_id"] == "read-execution"
    assert events[-1]["execution"]["input_kind"] == "query"
    assert events[-1]["execution"]["tool"] == "FDAI read investigation"
    assert not events[-1]["execution"]["command"].startswith("read_investigation ")
    assert events[-1]["agent"] == "Heimdall"
    execution = events[-1]["execution"]
    assert json.loads(execution["command"]) == {
        "intent": "resource_state",
        "operation": "read_investigation",
        "resource": "<redacted>",
    }
    assert execution["redacted"] is True
    assert execution["output"] == '{"evidence_ref_count":1,"status":"matched"}'
    assert execution["exit_code"] is None


async def test_chat_delegate_reports_queued_guest_handoff_as_completed_activity() -> None:
    events: list[dict[str, object]] = []

    async def responder(
        question: str,
        context: dict[str, str],
        *,
        progress_observer: Any = None,
    ) -> dict[str, object]:
        del question, context, progress_observer
        return {
            "answer": "The guest shutdown investigation was queued as a durable task.",
            "facts": {
                "status": "queued",
                "intent": "guest_shutdown",
                "resource_name": "vm-01",
                "task_id": "task-guest-shutdown",
                "message_id": "read-message:sha256:guest-shutdown-test",
            },
        }

    async def observe(event: Any) -> None:
        events.append(dict(event))

    delegate = HeimdallReadInvestigationChatDelegate(responder=responder)  # type: ignore[arg-type]
    result = await delegate.delegate_with_progress(
        prompt="Find guest OS shutdown events for vm-01.",
        user_id="principal-one",
        session_id="session-one",
        progress_observer=observe,
    )

    assert result is not None
    execution_event = events[-1]
    assert execution_event["status"] == "completed"
    execution = cast(dict[str, Any], execution_event["execution"])
    assert execution["output"] == '{"evidence_ref_count":0,"status":"queued"}'


async def test_chat_delegate_executes_measured_attribution_read() -> None:
    executor = _Executor()
    result = await _delegate(executor).delegate(
        prompt="Who stopped vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert _facts(result)["mode"] == "direct"
    assert _facts(result)["status"] == "matched"
    assert executor.calls == 1


async def test_chat_delegate_executes_cold_streamed_attribution_read() -> None:
    executor = _Executor()
    delegate = HeimdallReadInvestigationChatDelegate(
        responder=HeimdallReadInvestigationResponder(
            executor=executor,  # type: ignore[arg-type]
            latency_store=_ColdLatency(),
            scope_ref="scope:allowed",
        )
    )

    result = await delegate.delegate(
        prompt="Who stopped vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert _facts(result)["mode"] == "streamed"
    assert _facts(result)["status"] == "matched"
    assert executor.calls == 1


async def test_chat_delegate_renders_latest_successful_stop_history() -> None:
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="azure.resource_activity",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(
            ReadEvidenceRecord(
                occurred_at=datetime(2026, 7, 27, 16, 17, 55, tzinfo=UTC),
                status="succeeded",
                operation_kind="stop",
            ),
            ReadEvidenceRecord(
                occurred_at=datetime(2026, 7, 28, 15, 11, 29, tzinfo=UTC),
                status="succeeded",
                operation_kind="stop",
            ),
        ),
        evidence_refs=("evidence:activity",),
    )
    executor = _NetworkExecutor(envelope)
    result = await _delegate(executor).delegate(
        prompt="postgres-data 변경 이력: 언제부터 중지되어 있었어?",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert "2026-07-28T15:11:29Z" in _answer(result)
    assert "최근 성공한 중지 작업" in _answer(result)
    assert "적어도 이 시점부터" in _answer(result)
    assert _facts(result)["intent"] == "resource_change_history"


async def test_chat_delegate_renders_most_recent_successful_change() -> None:
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="azure.resource_activity",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(
            ReadEvidenceRecord(
                occurred_at=datetime(2026, 7, 31, 12, 0, 36, tzinfo=UTC),
                status="succeeded",
                operation_kind="deallocate",
                actor_ref="principal:service",
                actor_kind=ActorKind.SERVICE_PRINCIPAL,
            ),
            ReadEvidenceRecord(
                occurred_at=datetime(2026, 8, 1, 1, 38, 13, tzinfo=UTC),
                status="succeeded",
                operation_kind="start",
                actor_ref="principal:user",
                actor_kind=ActorKind.USER,
            ),
        ),
        evidence_refs=("evidence:activity",),
    )
    executor = _NetworkExecutor(envelope)

    result = await _delegate(executor).delegate(
        prompt="vm-01 change history: show the most recent successful operation",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert "most recent successful change" in _answer(result)
    assert "start at 2026-08-01T01:38:13Z" in _answer(result)
    assert "user (principal:user)" in _answer(result)
    assert "deallocate" not in _answer(result)
    assert _facts(result)["intent"] == "resource_change_history"


async def test_chat_delegate_renders_preincident_scope_activity() -> None:
    async def activity_provider(lookback_seconds: int, max_events: int):
        assert lookback_seconds == 86_400
        assert max_events == 200
        return {
            "status": "matched",
            "source": "azure-activity-log",
            "observed_at": "2026-08-01T05:00:00Z",
            "truncated": False,
            "events": [
                {
                    "occurred_at": "2026-08-01T03:00:00Z",
                    "event_status": "succeeded",
                    "operation": "write",
                    "name": "nsg-rule",
                    "type": "network.nsg",
                    "resource_group": "rg-example",
                },
                {
                    "occurred_at": "2026-08-01T04:45:00Z",
                    "event_status": "succeeded",
                    "operation": "write",
                    "name": "other-group-change",
                    "type": "arm-resource",
                    "resource_group": "rg-other",
                },
            ],
        }

    executor = _Executor()
    delegate = HeimdallReadInvestigationChatDelegate(
        responder=HeimdallReadInvestigationResponder(
            executor=executor,  # type: ignore[arg-type]
            latency_store=_Latency(),
            scope_ref="scope:allowed",
            scope_activity_provider=activity_provider,
        )
    )

    result = await delegate.delegate(
        prompt=(
            "vm-01 change history: pre-incident activity "
            "group=rg-example before=2026-08-01T05:00:00Z locale=ko"
        ),
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert "직전 1시간의 배포/설정 변경은 0건" in _answer(result)
    assert "가장 가까운 이전 관련 변경" in _answer(result)
    assert "nsg-rule" in _answer(result)
    assert "other-group-change" not in _answer(result)
    assert _facts(result)["intent"] == "pre_incident_changes"
    assert _facts(result)["immediate_count"] == 0
    assert _facts(result)["matched_count"] == 1
    assert executor.calls == 0


async def test_chat_delegate_fails_closed_when_incident_anchor_is_unavailable() -> None:
    executor = _Executor()

    result = await _delegate(executor).delegate(
        prompt=(
            "vm-fdai-example-01 change history: pre-incident activity anchor=unavailable locale=ko"
        ),
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert "근거를 사용할 수 없어" in _answer(result)
    assert _facts(result)["status"] == "unavailable"
    assert _facts(result)["reason"] == "incident_anchor_unavailable"
    assert executor.calls == 0


async def test_chat_delegate_renders_opaque_attribution_caller() -> None:
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="azure.resource_activity",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(
            ReadEvidenceRecord(
                occurred_at=datetime(2026, 7, 31, 12, 0, 36, tzinfo=UTC),
                status="succeeded",
                operation_kind="deallocate",
                actor_ref="principal:opaque",
                actor_kind=ActorKind.SERVICE_PRINCIPAL,
            ),
        ),
        evidence_refs=("evidence:activity",),
    )
    executor = _NetworkExecutor(envelope)

    result = await _delegate(executor).delegate(
        prompt="vm-01을 누가 중지했어?",
        user_id="principal-one",
        session_id="session-one",
    )

    assert result is not None
    assert "호출 주체는 service_principal (principal:opaque)" in _answer(result)
    assert "작업 종류는 deallocate" in _answer(result)
    assert _facts(result)["intent"] == "change_attribution"


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

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fdai.delivery.read_api.routes.read_investigation_responder import (
    HeimdallReadInvestigationChatDelegate,
    HeimdallReadInvestigationResponder,
)
from fdai.shared.providers.read_investigation import ReadLatencySample, ReadToolId

NOW = datetime(2026, 7, 22, tzinfo=UTC)


class _Service:
    transport = "rest"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, plan):  # type: ignore[no-untyped-def]
        del plan
        self.calls += 1
        return SimpleNamespace(
            outcome=SimpleNamespace(value="matched"),
            evidence=(SimpleNamespace(authority="azure.resource_state"),),
            evidence_refs=("evidence:one",),
        )


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


def _delegate(service: _Service) -> HeimdallReadInvestigationChatDelegate:
    return HeimdallReadInvestigationChatDelegate(
        responder=HeimdallReadInvestigationResponder(
            service=service,  # type: ignore[arg-type]
            latency_store=_Latency(),
            scope_ref="scope:allowed",
        )
    )


async def test_chat_delegate_executes_measured_fast_read_as_heimdall() -> None:
    service = _Service()
    result = await _delegate(service).delegate(
        prompt="What is the current state of vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert result["primary_agent"] == "Heimdall"
    assert result["facts"]["mode"] == "direct"
    assert result["facts"]["status"] == "matched"
    assert service.calls == 1


async def test_chat_delegate_hands_multi_source_work_off_before_cloud_io() -> None:
    service = _Service()
    result = await _delegate(service).delegate(
        prompt="Who stopped vm-01?",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is not None
    assert result["facts"]["mode"] == "detached"
    assert result["facts"]["status"] == "handoff_required"
    assert service.calls == 0


async def test_chat_delegate_ignores_unrelated_question() -> None:
    service = _Service()
    result = await _delegate(service).delegate(
        prompt="Tell me a joke",
        user_id="principal-one",
        session_id="session-one",
    )
    assert result is None
    assert service.calls == 0

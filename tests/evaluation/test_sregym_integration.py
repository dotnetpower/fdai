"""SREGym lifecycle integration through the public EvaluationHost protocol."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from fdai_bench_sregym import SregymAdapter, SregymAdapterConfig
from fdai_evaluation_sdk import AuthorityCeiling, EvaluationRunner, SideEffectClass

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.evaluation.artifacts import InMemoryArtifactBroker, InMemoryArtifactCustodySink
from fdai.evaluation.capabilities import AuthorityAxes, CapabilityAxes
from fdai.evaluation.host import (
    EvaluationHostPolicy,
    FdaiEvaluationHost,
    InMemoryExternalValidationSink,
)
from fdai.evaluation.public import EvaluationHost
from fdai.shared.contracts.models import Event

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class _Processor:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def process(self, event: Event | Mapping[str, Any]) -> ControlLoopResult:
        assert isinstance(event, Event)
        self.events.append(event)
        return ControlLoopResult(
            outcome=ControlLoopOutcome.EXECUTED,
            tier="t0",
            decision="observe",
            resource_type="kubernetes.namespace",
            citing_rule_ids=("workload.health",),
        )


async def test_sregym_runs_and_cleans_up_through_public_host() -> None:
    submitted: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "done" if submitted else "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        if request.url.path == "/submit":
            submitted.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "200"})
        raise AssertionError(request.url.path)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SregymAdapter(
        config=SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
            poll_interval_seconds=0.001,
            stage_timeout_seconds=1,
        ),
        http_client=http_client,
        clock=lambda: _NOW,
    )
    capability_catalog = {
        capability_id: SideEffectClass.OBSERVE
        for capability_id in (
            "observe.kubernetes.capacity",
            "observe.kubernetes.dependencies",
            "observe.kubernetes.inventory",
            "observe.kubernetes.events",
            "observe.kubernetes.nodes",
            "observe.metrics.query",
            "observe.kubernetes.admission",
            "observe.kubernetes.owners",
        )
    }
    allowed = frozenset(capability_catalog)
    authority = AuthorityAxes(*((AuthorityCeiling.SHADOW,) * 6))
    processor = _Processor()
    host: EvaluationHost = FdaiEvaluationHost(
        processor=processor,
        artifact_broker=InMemoryArtifactBroker(
            custody_sink=InMemoryArtifactCustodySink(),
            clock=lambda: _NOW,
        ),
        validation_sink=InMemoryExternalValidationSink(),
        policy=EvaluationHostPolicy(
            capability_catalog=capability_catalog,
            capability_axes=CapabilityAxes(*((allowed,) * 6)),
            authority_axes=authority,
            target_resource_types={"kubernetes.namespace": "kubernetes.namespace"},
        ),
        clock=lambda: _NOW,
    )

    summary = await EvaluationRunner(adapter=adapter, host=host).run()

    assert summary.task_count == 1
    assert summary.completed_count == 1
    assert submitted and submitted[0]["solution"].startswith("FDAI outcome=executed")
    assert processor.events[0].source == "evaluation.host"
    assert processor.events[0].mode.value == "shadow"
    await http_client.aclose()

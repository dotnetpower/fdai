import asyncio
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from fdai.delivery.kubernetes_canary import AksScheduledCanaryObserver
from fdai.delivery.self_health_canary_result import (
    ScheduledCanaryResultExporter,
    ScheduledCanarySource,
    ScheduledCanaryStateExporter,
    runtime_canary_exporters,
)
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import SelfHealthSignalName

from tests.delivery.test_canary_sequence import NOW as SCHEDULED
from tests.delivery.test_canary_sequence import SLOT, facts

NOW = SCHEDULED + timedelta(minutes=2)


def native_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    owner = str(UUID(int=100))
    cron = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": "canary",
            "namespace": "fdai-system",
            "uid": owner,
            "generation": 1,
            "creationTimestamp": (SCHEDULED - timedelta(days=1)).isoformat(),
        },
        "spec": {"schedule": "*/5 * * * *", "timeZone": "Etc/UTC", "suspend": False},
    }
    jobs = {
        "kind": "PartialObjectMetadataList",
        "metadata": {"resourceVersion": "100"},
        "items": [
            {
                "metadata": {
                    "namespace": "fdai-system",
                    "uid": SLOT.removeprefix("aks-job:"),
                    "labels": {"app.kubernetes.io/name": "canary"},
                    "annotations": {
                        "batch.kubernetes.io/cronjob-scheduled-timestamp": SCHEDULED.isoformat()
                    },
                    "ownerReferences": [
                        {
                            "apiVersion": "batch/v1",
                            "kind": "CronJob",
                            "name": "canary",
                            "uid": owner,
                            "controller": True,
                        }
                    ],
                }
            }
        ],
    }
    return cron, jobs


def observer(
    cron: dict[str, Any],
    jobs: dict[str, Any],
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> tuple[AksScheduledCanaryObserver, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "kubernetes.default.svc"
        if handler is not None:
            return handler(request)
        if request.url.path.endswith("/cronjobs/canary"):
            assert request.headers["Accept"] == "application/json"
            return httpx.Response(200, json=cron)
        assert request.url.path == "/apis/batch/v1/namespaces/fdai-system/jobs"
        assert "as=PartialObjectMetadataList" in request.headers["Accept"]
        assert request.url.params["labelSelector"] == "app.kubernetes.io/name=canary"
        assert request.url.params["limit"] == "17"
        return httpx.Response(200, json=jobs)

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://kubernetes.default.svc", transport=httpx.MockTransport(route)
        )

    return AksScheduledCanaryObserver("fdai-system", "canary", client), requests


class SequenceStore(InMemoryStateStore):
    def __init__(self, *outcomes: str, on_read: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.rows = facts(*(outcomes or ("success",)), base=SCHEDULED)
        self.truncated = False
        self.slots: list[str] = []
        self.on_read = on_read

    async def read_consumed_canary_sequence(
        self, *, slot: str
    ) -> tuple[tuple[Mapping[str, Any], ...], bool]:
        self.slots.append(slot)
        self.on_read()
        return deepcopy(self.rows), self.truncated


async def test_native_witness_binds_the_due_slot_and_not_job_creation_or_publish_success() -> None:
    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)
    witness = await native.observe(now=NOW)
    assert witness.slot == SLOT and witness.scheduled_at == SCHEDULED
    assert witness.valid_until == SCHEDULED + timedelta(minutes=5)
    assert witness.binding_digest.startswith("sha256:")
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("suspended", "source_incomplete"),
        ("timezone_missing", "source_incomplete"),
        ("schedule_invalid", "source_malformed"),
        ("future_scheduler", "source_from_future"),
        ("wrong_kind", "source_malformed"),
        ("truncated", "source_incomplete"),
        ("malformed_pagination", "source_malformed"),
        ("too_many", "source_incomplete"),
        ("duplicate", "source_incomplete"),
        ("old_owner", "source_missing"),
        ("old_slot", "source_missing"),
        ("future_slot", "source_from_future"),
        ("wrong_namespace", "source_malformed"),
        ("missing_annotation", "source_malformed"),
    ],
)
async def test_unknown_or_incomplete_native_observations_cannot_borrow_a_consumed_success(
    scenario: str, reason: str
) -> None:
    cron, jobs = native_documents()
    job = jobs["items"][0]["metadata"]
    if scenario == "suspended":
        cron["spec"]["suspend"] = True
    elif scenario == "timezone_missing":
        del cron["spec"]["timeZone"]
    elif scenario == "schedule_invalid":
        cron["spec"]["schedule"] = "* * * * * *"
    elif scenario == "future_scheduler":
        cron["metadata"]["creationTimestamp"] = (NOW + timedelta(seconds=1)).isoformat()
    elif scenario == "wrong_kind":
        jobs["kind"] = "JobList"
    elif scenario == "truncated":
        jobs["metadata"]["continue"] = "another-page"
    elif scenario == "malformed_pagination":
        jobs["metadata"]["continue"] = False
    elif scenario == "too_many":
        jobs["items"] *= 17
    elif scenario == "duplicate":
        jobs["items"].append(deepcopy(jobs["items"][0]))
    elif scenario == "old_owner":
        job["ownerReferences"][0]["uid"] = str(UUID(int=101))
    elif scenario == "old_slot":
        job["annotations"]["batch.kubernetes.io/cronjob-scheduled-timestamp"] = (
            SCHEDULED - timedelta(minutes=5)
        ).isoformat()
    elif scenario == "future_slot":
        job["annotations"]["batch.kubernetes.io/cronjob-scheduled-timestamp"] = (
            SCHEDULED + timedelta(minutes=5)
        ).isoformat()
    elif scenario == "wrong_namespace":
        job["namespace"] = "another-namespace"
    else:
        job["annotations"].clear()
    native, _ = observer(cron, jobs)
    store = SequenceStore()
    source = ScheduledCanarySource(store, native, clock=lambda: NOW)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == reason
    assert not store.slots


@pytest.mark.parametrize("status", [302, 401, 403, 429, 503])
async def test_provider_failure_is_one_attempt_without_redirect_or_retry(status: int) -> None:
    cron, jobs = native_documents()
    native, requests = observer(
        cron,
        jobs,
        handler=lambda _: httpx.Response(status, headers={"Location": "https://example.com"}),
    )
    source = ScheduledCanarySource(SequenceStore(), native, clock=lambda: NOW)
    for _ in range(2):
        with pytest.raises(SelfHealthExporterUnavailableError) as failure:
            await source.observe(now=NOW)
        assert failure.value.reason == "source_unreachable"
    assert len(requests) == 1


async def test_metadata_transfer_limit_is_enforced_before_json_materialization() -> None:
    cron, jobs = native_documents()
    native, requests = observer(
        cron, jobs, handler=lambda _: httpx.Response(200, content=b"x" * 262_145)
    )
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await native.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"
    assert len(requests) == 1


async def test_exact_256_kib_metadata_response_is_accepted() -> None:
    cron, jobs = native_documents()
    padded = {**cron, "padding": ""}
    overhead = len(json.dumps(padded, separators=(",", ":")).encode())
    padded["padding"] = "x" * (262_144 - overhead)
    body = json.dumps(padded, separators=(",", ":")).encode()
    assert len(body) == 262_144

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=jobs)
        return httpx.Response(200, content=body)

    native, _ = observer(cron, jobs, handler)
    assert (await native.observe(now=NOW)).slot == SLOT


async def test_exact_16_job_list_can_exclude_old_controller_generations() -> None:
    cron, jobs = native_documents()
    for index in range(15):
        old = deepcopy(jobs["items"][0])
        old["metadata"]["uid"] = str(UUID(int=200 + index))
        old["metadata"]["ownerReferences"][0]["uid"] = str(UUID(int=101))
        jobs["items"].append(old)
    assert len(jobs["items"]) == 16
    native, _ = observer(cron, jobs)
    assert (await native.observe(now=NOW)).slot == SLOT


async def test_cancelled_collection_propagates_and_cannot_retry_within_the_same_snapshot() -> None:
    started = asyncio.Event()
    requests: list[httpx.Request] = []

    async def wait(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json={})

    native = AksScheduledCanaryObserver(
        "fdai-system",
        "canary",
        lambda: httpx.AsyncClient(
            base_url="https://kubernetes.default.svc", transport=httpx.MockTransport(wait)
        ),
    )
    source = ScheduledCanarySource(SequenceStore(), native, clock=lambda: NOW)
    task = asyncio.create_task(source.observe(now=NOW))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"
    assert len(requests) == 1


@pytest.mark.parametrize("outcome", ["success", "failure"])
async def test_result_and_state_share_one_read_and_preserve_original_time_and_terminal(
    outcome: str,
) -> None:
    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)
    store = SequenceStore(outcome)
    source = ScheduledCanarySource(store, native, clock=lambda: NOW)
    result, state = await asyncio.gather(
        ScheduledCanaryResultExporter(source, "fdai.canary.success").observe(now=NOW),
        ScheduledCanaryStateExporter(source, 600).observe(now=NOW),
    )
    assert result.value == int(outcome == "success")
    assert result.observed_at == state.observed_at == SCHEDULED + timedelta(seconds=3)
    assert state.reason == f"canary_{outcome}" and state.fresh
    assert state.execution_authority is False
    assert store.slots == [SLOT] and len(requests) == 6
    assert SLOT not in state.model_dump_json()


async def test_cancelled_consumption_is_explicit_unknown_not_a_numeric_failure_or_success() -> None:
    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)
    store = SequenceStore("cancelled")
    source = ScheduledCanarySource(store, native, clock=lambda: NOW)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await ScheduledCanaryResultExporter(source, "fdai.canary.success").observe(now=NOW)
    assert failure.value.reason == "source_incomplete"
    state = await ScheduledCanaryStateExporter(source, 600).observe(now=NOW)
    assert state.status.value == "unavailable" and state.reason == "canary_cancelled"
    assert state.value_digest is None and state.observed_at is None and not state.fresh
    assert store.slots == [SLOT] and len(requests) == 6


async def test_stale_consumption_keeps_its_age_and_cannot_become_healthy() -> None:
    from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
    from fdai.delivery.self_health_sources import runtime_self_health_registry

    from tests.runtime.test_self_health_sources import _catalog

    cron, jobs = native_documents()
    cron["spec"]["schedule"] = "0 * * * *"
    native, _ = observer(cron, jobs)
    store = SequenceStore()
    stale_now = SCHEDULED + timedelta(minutes=12)
    source = ScheduledCanarySource(store, native, clock=lambda: stale_now)
    registry = runtime_self_health_registry(
        catalog=_catalog(),
        store=store,
        readiness=lambda _: True,
        canary_result_source=ScheduledCanaryResultExporter(source, "fdai.canary.success"),
        canary_state_source=ScheduledCanaryStateExporter(source, 600),
    )
    snapshot = await SelfHealthRuntimeMonitor(registry=registry, store=store).collect_and_persist(
        now=stale_now
    )
    result = next(
        item
        for item in snapshot.self_health.signals
        if item.signal is SelfHealthSignalName.CANARY_RESULT
    )
    state = next(item for item in snapshot.fields if item.name.value == "canary")
    assert result.status.value != "healthy" and not result.fresh
    assert state.reason == "source_stale" and not state.fresh
    assert result.observed_at in {None, SCHEDULED + timedelta(seconds=3)}


async def test_scheduler_aba_during_database_read_holds_both_exporters() -> None:
    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)

    def change_generation() -> None:
        cron["metadata"]["generation"] += 2

    store = SequenceStore(on_read=change_generation)
    source = ScheduledCanarySource(store, native, clock=lambda: NOW)
    for exporter in (
        ScheduledCanaryResultExporter(source, "fdai.canary.success"),
        ScheduledCanaryStateExporter(source, 600),
    ):
        with pytest.raises(SelfHealthExporterUnavailableError) as failure:
            await exporter.observe(now=NOW)
        assert failure.value.reason == "source_incomplete"
    assert store.slots == [SLOT] and len(requests) == 6


@pytest.mark.parametrize("replay_delta", [timedelta(), -timedelta(microseconds=1)])
async def test_replayed_or_regressed_collection_time_cannot_reuse_a_healthy_result(
    replay_delta: timedelta,
) -> None:
    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)
    source = ScheduledCanarySource(SequenceStore(), native, clock=lambda: NOW)
    exporter = ScheduledCanaryResultExporter(source, "fdai.canary.success")
    assert (await exporter.observe(now=NOW)).value == 1
    with pytest.raises(SelfHealthExporterUnavailableError):
        await exporter.observe(now=NOW + replay_delta)
    assert len(requests) == 6


async def test_scheduler_aba_during_job_listing_is_checked_before_the_database() -> None:
    cron, jobs = native_documents()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            cron["metadata"]["generation"] += 2
            return httpx.Response(200, json=jobs)
        return httpx.Response(200, json=cron)

    native, requests = observer(cron, jobs, handler)
    store = SequenceStore()
    source = ScheduledCanarySource(store, native, clock=lambda: NOW)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"
    assert not store.slots and len(requests) == 3


async def test_actual_readiness_builder_collects_and_persists_both_bound_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery import self_health_canary_result
    from fdai.delivery.startup_probe import StaticStartupProbe
    from fdai.runtime.readiness import build_startup_readiness_runtime
    from fdai.shared.providers.local.event_bus import LocalEventBus
    from fdai.shared.providers.local.identity import LocalWorkloadIdentity

    from tests.runtime.test_self_health_sources import _catalog, _Embedding, _Validator

    cron, jobs = native_documents()
    native, requests = observer(cron, jobs)
    store = SequenceStore()

    def factory(*, namespace: str, cronjob: str) -> AksScheduledCanaryObserver:
        assert namespace == "fdai-system" and cronjob == "canary"
        return native

    monkeypatch.setattr(self_health_canary_result, "AksScheduledCanaryObserver", factory)
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=StaticStartupProbe(probe_id="policy.compile", evidence_key="compiled"),
        environment={
            "FDAI_CANARY_OBSERVER_NAMESPACE": "fdai-system",
            "FDAI_CANARY_OBSERVER_CRONJOB": "canary",
        },
        self_health_catalog=_catalog(),
    )
    monitor = runtime.self_health_monitor
    assert monitor is not None
    exporter = monitor._registry.signal_exporters[SelfHealthSignalName.CANARY_RESULT]
    assert isinstance(exporter, ScheduledCanaryResultExporter)
    exporter.source.clock = lambda: NOW
    snapshot = await monitor.collect_and_persist(now=NOW)
    result = next(
        item
        for item in snapshot.self_health.signals
        if item.signal is SelfHealthSignalName.CANARY_RESULT
    )
    state = next(item for item in snapshot.fields if item.name.value == "canary")
    assert result.status.value == "healthy" and result.fresh
    assert state.reason == "canary_success" and state.fresh
    assert store.slots == [SLOT] and len(requests) == 6
    retained = await store.read_state("runtime:operational-state")
    assert retained is not None and SLOT not in str(retained)
    assert snapshot.execution_authority is False


@pytest.mark.parametrize("overrun", [timedelta(), timedelta(microseconds=1)])
async def test_final_post_await_slot_deadline_is_exclusive(overrun: timedelta) -> None:
    cron, jobs = native_documents()
    native, _ = observer(cron, jobs)
    deadline = SCHEDULED + timedelta(minutes=5)
    times = iter((deadline - timedelta(microseconds=1), deadline + overrun))
    source = ScheduledCanarySource(SequenceStore(), native, clock=lambda: next(times))
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"


def test_runtime_binding_is_explicit_and_requires_both_exact_scope_values() -> None:
    def binding(environment: Mapping[str, str]):
        return runtime_canary_exporters(
            store=InMemoryStateStore(),
            metric="fdai.canary.success",
            maximum_age_seconds=600,
            environment=environment,
        )

    assert binding({}) is None
    assert binding({"CONTAINER_APP_JOB_EXECUTION_NAME": "not-a-scheduler-witness"}) is None
    with pytest.raises(ValueError, match="configured together"):
        binding({"FDAI_CANARY_OBSERVER_NAMESPACE": "fdai"})
    with pytest.raises(ValueError, match="DNS labels"):
        binding(
            {
                "FDAI_CANARY_OBSERVER_NAMESPACE": "fdai",
                "FDAI_CANARY_OBSERVER_CRONJOB": "../not-a-cronjob",
            }
        )

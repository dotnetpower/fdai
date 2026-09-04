from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fdai.core.wara import (
    WaraAssessmentObservationRunner,
    WaraAssessmentRuntime,
    WaraAssessmentService,
)
from fdai.core.wara.runtime import WARA_ASSESSMENT_TOPIC
from fdai.delivery.azure.wara_observation import (
    AzureResourceGraphWaraObservationProvider,
)
from fdai.delivery.persistence.postgres_wara_scope import (
    WaraResolvedResource,
    WaraResolvedScope,
    WaraScopeUnavailableError,
)
from fdai.delivery.wara_assessment_cli import (
    WaraJobConfigurationError,
    WaraJobSettings,
    _assessment_id,
    _event_bus,
    _load_wara_assets,
    execute_wara_assessment_tick,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

AT = datetime(2026, 9, 5, 1, 2, 3, tzinfo=UTC)
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
AUDIENCE = "https://management.azure.com/.default"


class StaticScopeSource:
    def __init__(self, scopes: dict[str, WaraResolvedScope]) -> None:
        self._scopes = scopes
        self.requested: list[str] = []

    async def resolve(
        self,
        workload_id: str,
        *,
        now: datetime | None = None,
    ) -> WaraResolvedScope:
        assert now == AT
        self.requested.append(workload_id)
        value = self._scopes.get(workload_id)
        if value is None:
            raise WaraScopeUnavailableError("scope unavailable")
        return value


def _settings(
    *,
    workload_ids: tuple[str, ...] = ("workload:example",),
    workload_tags: dict[str, tuple[str, ...]] | None = None,
) -> WaraJobSettings:
    return WaraJobSettings(
        dsn="postgresql://localhost/fdai",
        bootstrap_servers="example.servicebus.windows.net:9093",
        physical_topic="fdai.pantheon.objects",
        workload_ids=workload_ids,
        workload_tags=(
            {workload_id: () for workload_id in workload_ids}
            if workload_tags is None
            else workload_tags
        ),
    )


def test_settings_parse_ordered_deployment_scope_without_rendering_dsn() -> None:
    settings = WaraJobSettings.from_environ(
        {
            "FDAI_WARA_DSN": "postgresql+psycopg://localhost/fdai",
            "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
            "FDAI_WARA_WORKLOAD_IDS_JSON": '["workload:a"]',
            "FDAI_WARA_WORKLOAD_TAGS_JSON": ('{"workload:a": ["AVD"]}'),
        }
    )

    assert settings.dsn == "postgresql://localhost/fdai"
    assert settings.workload_ids == ("workload:a",)
    assert settings.workload_tags == {
        "workload:a": ("AVD",),
    }


@pytest.mark.asyncio
async def test_event_bus_routes_wara_through_existing_physical_topic() -> None:
    bus = _event_bus(
        settings=_settings(),
        identity=StaticWorkloadIdentity(audience=AUDIENCE),
        use_workload_identity=True,
    )

    assert bus.logical_topics == frozenset({WARA_ASSESSMENT_TOPIC})
    assert bus.physical_topic == "fdai.pantheon.objects"
    await bus.close()


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "FDAI_WARA_DSN": "postgresql://localhost/fdai",
            "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
            "FDAI_WARA_WORKLOAD_IDS_JSON": "[]",
        },
        {
            "FDAI_WARA_DSN": "postgresql://localhost/one",
            "FDAI_INVENTORY_DSN": "postgresql://localhost/two",
            "KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": "fdai.pantheon.objects",
            "FDAI_WARA_WORKLOAD_IDS_JSON": '["workload:example"]',
        },
    ],
)
def test_settings_fail_closed_without_one_consistent_nonempty_scope(
    environment: dict[str, str],
) -> None:
    with pytest.raises(WaraJobConfigurationError):
        WaraJobSettings.from_environ(environment)


@pytest.mark.asyncio
async def test_tick_collects_exact_arg_evidence_and_publishes_shadow_result() -> None:
    catalog, queries, bindings = _load_wara_assets()
    binding = bindings.bindings[0]
    record = next(item for item in catalog.recommendations if item.aprl_guid == binding.aprl_guid)
    provider_id = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-example/providers/"
        f"{record.provider_resource_type}/example"
    )
    scope = WaraResolvedScope(
        workload_id="workload:example",
        ontology_release=f"sha256:{'a' * 64}",
        inventory_generation="inventory-generation-1",
        resources=(
            WaraResolvedResource(
                neutral_resource_id="resource:example",
                provider_resource_id=provider_id,
                provider_resource_type=record.provider_resource_type,
            ),
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        rows = [{"id": provider_id}] if "_fdai_wara_coverage" in body["query"] else []
        return httpx.Response(
            200,
            json={"data": rows, "count": len(rows), "totalRecords": len(rows)},
        )

    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()
    runtime = WaraAssessmentRuntime(catalog, bindings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureResourceGraphWaraObservationProvider(
            identity=StaticWorkloadIdentity(audience=AUDIENCE),
            http_client=client,
            queries=queries,
            evaluator_bindings=bindings,
            clock=lambda: AT,
        )
        report = await execute_wara_assessment_tick(
            settings=_settings(),
            scope_source=StaticScopeSource({"workload:example": scope}),
            service=WaraAssessmentService(
                runtime,
                state_store,
                event_bus,
                WaraAssessmentObservationRunner(runtime=runtime, provider=provider),
            ),
            catalog=catalog,
            evaluator_bindings=bindings,
            now=AT,
        )

    assert report.workload_count == 1
    assert report.aggregate_counts["evaluation.evaluated"] == 1
    assert report.aggregate_counts["satisfaction.satisfied"] == 1
    assert state_store.audit_entries[0]["entry"]["execution_authority"] is False
    events = [event async for event in event_bus.subscribe(WARA_ASSESSMENT_TOPIC, "test-consumer")]
    assert len(events) == 1
    assert events[0].payload["mode"] == "shadow"
    assert events[0].payload["execution_authority"] is False


@pytest.mark.asyncio
async def test_settings_reject_multiple_workloads_to_preserve_single_projection() -> None:
    with pytest.raises(WaraJobConfigurationError, match="1-1 unique"):
        _settings(workload_ids=("workload:a", "workload:b"))


@pytest.mark.asyncio
async def test_unknown_workload_tag_is_rejected_before_scope_reads() -> None:
    catalog, _, bindings = _load_wara_assets()
    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()

    with pytest.raises(WaraJobConfigurationError, match="unknown catalog"):
        await execute_wara_assessment_tick(
            settings=_settings(workload_tags={"workload:example": ("NOT-REVIEWED",)}),
            scope_source=StaticScopeSource({}),
            service=WaraAssessmentService(
                WaraAssessmentRuntime(catalog, bindings),
                state_store,
                event_bus,
            ),
            catalog=catalog,
            evaluator_bindings=bindings,
            now=AT,
        )


def test_assessment_id_is_stable_within_slot_and_changes_after_slot() -> None:
    scope = WaraResolvedScope(
        workload_id="workload:example",
        ontology_release=f"sha256:{'a' * 64}",
        inventory_generation="generation-1",
        resources=(
            WaraResolvedResource(
                neutral_resource_id="resource:example",
                provider_resource_id=(
                    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-example/"
                    "providers/Microsoft.ContainerRegistry/registries/example"
                ),
                provider_resource_type="Microsoft.ContainerRegistry/registries",
            ),
        ),
    )
    first = _assessment_id(
        scope,
        crosswalk_digest=f"sha256:{'b' * 64}",
        evaluator_bindings_digest=f"sha256:{'c' * 64}",
        workload_tags=(),
        evaluated_at=AT,
        run_slot_seconds=3600,
    )
    retry = _assessment_id(
        scope,
        crosswalk_digest=f"sha256:{'b' * 64}",
        evaluator_bindings_digest=f"sha256:{'c' * 64}",
        workload_tags=(),
        evaluated_at=AT.replace(minute=59),
        run_slot_seconds=3600,
    )
    next_slot = _assessment_id(
        scope,
        crosswalk_digest=f"sha256:{'b' * 64}",
        evaluator_bindings_digest=f"sha256:{'c' * 64}",
        workload_tags=(),
        evaluated_at=AT.replace(hour=2),
        run_slot_seconds=3600,
    )
    changed_scope = _assessment_id(
        WaraResolvedScope(
            workload_id=scope.workload_id,
            ontology_release=scope.ontology_release,
            inventory_generation=scope.inventory_generation,
            resources=(
                WaraResolvedResource(
                    neutral_resource_id="resource:other",
                    provider_resource_id=(
                        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-example/"
                        "providers/Microsoft.ContainerRegistry/registries/other"
                    ),
                    provider_resource_type="Microsoft.ContainerRegistry/registries",
                ),
            ),
        ),
        crosswalk_digest=f"sha256:{'b' * 64}",
        evaluator_bindings_digest=f"sha256:{'c' * 64}",
        workload_tags=(),
        evaluated_at=AT,
        run_slot_seconds=3600,
    )

    assert first == retry
    assert first != next_slot
    assert first != changed_scope
    assert "workload:example" not in first

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.static_web_app_inventory import (
    STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY,
    AzureStaticWebAppInventoryConfig,
    AzureStaticWebAppInventoryEnricher,
)
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_EQUAL_TIME_CONFLICT,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
OBSERVED = datetime(2026, 9, 6, 1, 0, tzinfo=UTC)
COMPLETED = datetime(2026, 9, 6, 1, 1, tzinfo=UTC)


def _resource(name: str = "one") -> ResourceRecord:
    return ResourceRecord(
        resource_id=f"scope-example/resource-group/example/providers/static-web-app/{name}",
        type="static-web-app",
        props={"name": name, "properties": {"defaultHostname": f"{name}.example.invalid"}},
        provider_ref=(
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/"
            f"providers/Microsoft.Web/staticSites/{name}"
        ),
        last_seen=OBSERVED.isoformat(),
    )


def _resource_with_state(
    state: str,
    *,
    effective_at: datetime = OBSERVED,
) -> ResourceRecord:
    resource = _resource()
    material = f"{resource.resource_id}|default|{state}|{effective_at.isoformat()}"
    evidence_ref = (
        f"azure-static-web-app-environment:sha256:{hashlib.sha256(material.encode()).hexdigest()}"
    )
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="azure-static-web-app-default-environment",
        source_revision=evidence_ref,
        effective_at=effective_at,
        recorded_at=effective_at,
        evidence_cutoff=effective_at,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(evidence_ref,),
    )
    return replace(
        resource,
        props={
            **resource.props,
            STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY: state,
            "state_fact_metadata": {
                STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY: metadata.to_mapping()
            },
        },
    )


def _observation(*resources: ResourceRecord, complete: bool = True) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation="generation-1",
        resources=resources,
        links=(),
        complete=complete,
        recorded_at=OBSERVED,
    )


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test value
    )


class _PreviousStateReader:
    def __init__(self, resource: ResourceRecord) -> None:
        self.resource = resource

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str, dict[str, ResourceRecord]]:
        assert self.resource.resource_id in resource_ids
        return "generation-0", {self.resource.resource_id: self.resource}


class _UnavailableIdentity:
    async def get_token(self, _audience: str):
        raise RuntimeError("identity unavailable")


def _payload(
    state: str = "Ready",
    *,
    effective_at: datetime = OBSERVED,
    name: str = "default",
) -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "status": state,
            "createdTimeUtc": (effective_at - timedelta(minutes=1)).isoformat(),
            "lastUpdatedOn": effective_at.isoformat(),
        },
    }


async def test_enricher_adds_exact_default_environment_state_with_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/staticSites/one/builds/default")
        assert request.url.params["api-version"] == "2023-12-01"
        return httpx.Response(200, json=_payload())

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    result = enriched.resources[0]
    assert result.props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    assert result.props["properties"] == resource.props["properties"]
    assert result.last_seen == resource.last_seen
    metadata = StateFactMetadata.from_mapping(
        result.props["state_fact_metadata"][STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY]
    )
    assert metadata.source_identity == "azure-static-web-app-default-environment"
    assert metadata.effective_at == OBSERVED
    assert metadata.recorded_at == COMPLETED
    assert metadata.completeness == 1.0
    assert enriched.recorded_at == COMPLETED
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.AVAILABLE
    assert enriched.source_states[0].coverage == {"observed": 1, "targets": 1}


@pytest.mark.parametrize(
    "state",
    [
        "WaitingForDeployment",
        "Uploading",
        "Deploying",
        "Ready",
        "Failed",
        "Deleting",
        "Detached",
    ],
)
async def test_enricher_accepts_only_reviewed_provider_states(state: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(state))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(_resource()))

    assert enriched.resources[0].props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == state


@pytest.mark.parametrize(
    ("payload", "coverage"),
    [
        (_payload("Unexpected"), {"response_invalid": 1, "targets": 1}),
        (_payload(name="preview"), {"response_invalid": 1, "targets": 1}),
        (
            {"name": "default", "properties": {"status": "Ready"}},
            {"response_invalid": 1, "targets": 1},
        ),
        ({"name": "default", "properties": []}, {"response_invalid": 1, "targets": 1}),
    ],
)
async def test_enricher_rejects_unreviewed_or_incomplete_facts(
    payload: object,
    coverage: dict[str, int],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].status is InventoryProjectionSourceStatus.UNAVAILABLE
    assert enriched.source_states[0].reason == "static_web_app_partial"
    assert enriched.source_states[0].coverage == coverage


async def test_enricher_uses_exact_default_child_not_preview_collection() -> None:
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(200, json=_payload("Ready"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(_resource()))

    assert requested_paths == [
        (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
            "Microsoft.Web/staticSites/one/builds/default"
        )
    ]


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "default_environment_not_found"),
        (409, "source_unavailable"),
        (500, "source_unavailable"),
    ],
)
async def test_enricher_classifies_bounded_source_failures(
    status_code: int,
    reason: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(_resource()))

    assert enriched.source_states[0].coverage == {reason: 1, "targets": 1}


async def test_enricher_retains_prior_state_during_partial_failure() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    resource = _resource()
    previous = _resource_with_state("Ready")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources[0].props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    assert (
        enriched.resources[0].props["state_fact_metadata"] == previous.props["state_fact_metadata"]
    )
    assert enriched.state_base_generation == "generation-0"
    assert enriched.state_base_generation_checked is True


async def test_enricher_retains_newer_prior_state() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload("WaitingForDeployment"))

    previous = _resource_with_state("Ready", effective_at=OBSERVED + timedelta(minutes=1))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED + timedelta(minutes=1),
        ).enrich(_observation(_resource()))

    assert enriched.resources[0].props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    assert enriched.source_states[0].coverage == {"out_of_order": 1, "targets": 1}


async def test_enricher_marks_equal_time_conflict_without_overwriting_prior_state() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload("WaitingForDeployment"))

    previous = _resource_with_state("Ready")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(_observation(_resource()))

    result = enriched.resources[0]
    assert result.props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    metadata = StateFactMetadata.from_mapping(
        result.props["state_fact_metadata"][STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY]
    )
    assert metadata.completeness == 0.0
    assert metadata.conflicts == (STATE_FACT_EQUAL_TIME_CONFLICT,)
    assert enriched.source_states[0].coverage == {
        "conflicting_same_time": 1,
        "targets": 1,
    }


async def test_enricher_retains_prior_state_during_identity_outage() -> None:
    previous = _resource_with_state("Ready")
    async with httpx.AsyncClient() as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_UnavailableIdentity(),  # type: ignore[arg-type]
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            previous_state_reader=_PreviousStateReader(previous),
            clock=lambda: COMPLETED,
        ).enrich(_observation(_resource()))

    assert enriched.resources[0].props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    assert enriched.source_states[0].reason == "static_web_app_identity_unavailable"


@pytest.mark.parametrize(
    "provider_ref",
    [
        "https://management.azure.com/subscriptions/example",
        f"//subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Web/staticSites/one",
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/Microsoft.Web/sites/one",
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Web/staticSites/one/builds/default",
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Web/staticSites/one%2Fbuilds%2Fdefault",
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Web/staticSites/one?api-version=unexpected",
    ],
)
async def test_enricher_rejects_non_exact_static_site_arm_ids(provider_ref: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid ARM IDs MUST NOT be requested")

    resource = replace(_resource(), provider_ref=provider_ref)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].coverage == {"target_unresolved": 1, "targets": 1}


async def test_enricher_rejects_future_provider_time() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(effective_at=COMPLETED + timedelta(minutes=1)))

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                max_clock_skew_seconds=0,
            ),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].coverage == {"response_invalid": 1, "targets": 1}


async def test_enricher_bounds_response_size() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"padding":"' + (b"x" * 2048) + b'"}',
        )

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                max_response_bytes=1024,
            ),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].coverage == {"response_too_large": 1, "targets": 1}


async def test_enricher_bounds_target_count_and_retains_prior_state() -> None:
    resource = _resource()
    previous = _resource_with_state("Ready")

    class Reader:
        async def read_active_resources(
            self,
            *,
            resource_ids: tuple[str, ...],
        ) -> tuple[str, dict[str, ResourceRecord]]:
            assert len(resource_ids) == 2
            return "generation-0", {previous.resource_id: previous}

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("target limit MUST stop provider reads")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(
                subscription_ids=(SUBSCRIPTION,),
                max_targets=1,
            ),
            previous_state_reader=Reader(),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource, _resource("two")))

    assert enriched.resources[0].props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] == "Ready"
    assert STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY not in enriched.resources[1].props
    assert enriched.source_states[0].reason == "static_web_app_target_limit"


async def test_enricher_skips_provider_read_for_incomplete_generation() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("incomplete generations MUST NOT read provider state")

    resource = _resource()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource, complete=False))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].reason == "inventory_generation_incomplete"


async def test_enricher_does_not_target_other_resource_types() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("other ResourceTypes MUST NOT query Static Web App environments")

    resource = replace(_resource(), type="compute.web-app")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        enriched = await AzureStaticWebAppInventoryEnricher(
            identity=_identity(),
            http_client=client,
            config=AzureStaticWebAppInventoryConfig(subscription_ids=(SUBSCRIPTION,)),
            clock=lambda: COMPLETED,
        ).enrich(_observation(resource))

    assert enriched.resources == (resource,)
    assert enriched.source_states[0].coverage == {"targets": 0}

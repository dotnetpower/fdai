from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fdai.core.wara import (
    WaraAssessmentRequest,
    WaraAssessmentRuntime,
    WaraScopedResource,
    wara_observation_to_evidence,
)
from fdai.core.wara.runtime import WaraSatisfactionStatus
from fdai.delivery.azure.wara_observation import (
    AzureResourceGraphWaraConfig,
    AzureResourceGraphWaraObservationProvider,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import load_wara_assessment_catalog
from fdai.rule_catalog.schema.wara_evaluator_binding import load_wara_evaluator_bindings
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.wara_assessment import WaraObservationError

ROOT = Path(__file__).resolve().parents[5]
ASSESSMENT_ROOT = ROOT / "rule-catalog/collected/wara-aprl/assessment"
AT = datetime(2026, 9, 1, tzinfo=UTC)
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
AUDIENCE = "https://management.azure.com/.default"


def _bound_runtime():
    framework = load_framework_catalog(
        ROOT / "rule-catalog/collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        ASSESSMENT_ROOT / "crosswalk.json",
        ASSESSMENT_ROOT / "queries.json",
        framework=framework,
        framework_path=ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        ASSESSMENT_ROOT / "evaluator-bindings.json",
        catalog=catalog,
        queries=queries,
    )
    binding = bindings.bindings[0]
    record = next(item for item in catalog.recommendations if item.aprl_guid == binding.aprl_guid)
    resource_id = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-example/providers/"
        f"{record.provider_resource_type}/example"
    )
    request = WaraAssessmentRequest(
        assessment_id="assessment-exact-evaluator",
        framework_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=bindings.overlay_digest,
        ontology_release="ontology-release-1",
        inventory_generation="inventory-generation-1",
        workload_id="workload:representative",
        resources=(
            WaraScopedResource(
                resource_id=resource_id,
                provider_resource_type=record.provider_resource_type,
            ),
        ),
        evaluated_at=AT,
        recorded_at=AT,
    )
    runtime = WaraAssessmentRuntime(catalog, bindings)
    plan = runtime.build_read_plan(record, request)
    query = next(item for item in queries.queries if item.aprl_guid == binding.aprl_guid)
    return runtime, request, record, plan, query


def _provider(
    handler: httpx.MockTransport,
    *,
    clock=lambda: AT,
) -> tuple[AzureResourceGraphWaraObservationProvider, httpx.AsyncClient]:
    framework = load_framework_catalog(
        ROOT / "rule-catalog/collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        ASSESSMENT_ROOT / "crosswalk.json",
        ASSESSMENT_ROOT / "queries.json",
        framework=framework,
        framework_path=ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        ASSESSMENT_ROOT / "evaluator-bindings.json",
        catalog=catalog,
        queries=queries,
    )
    client = httpx.AsyncClient(transport=handler)
    return (
        AzureResourceGraphWaraObservationProvider(
            identity=StaticWorkloadIdentity(audience=AUDIENCE),
            http_client=client,
            queries=queries,
            evaluator_bindings=bindings,
            clock=clock,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_zero_rows_are_satisfied_with_exact_scoped_query() -> None:
    _, _, _, plan, exact_query = _bound_runtime()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [], "count": 0, "totalRecords": 0})

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        receipt = await provider.observe(plan)
    finally:
        await client.aclose()

    body = json.loads(captured[0].content)
    assert body["subscriptions"] == [SUBSCRIPTION_ID]
    assert exact_query.decoded_body().rstrip() in body["query"]
    assert plan.resource_ids[0].casefold() in body["query"]
    assert body["options"]["$top"] == plan.maximum_rows + 1
    assert captured[0].headers["Authorization"].startswith("Bearer ")
    assert receipt.satisfied is True
    assert receipt.complete is True
    assert receipt.truncated is False


@pytest.mark.parametrize(
    "config",
    (
        AzureResourceGraphWaraConfig(endpoint="https://example.com"),
        AzureResourceGraphWaraConfig(endpoint="https://management.azure.com/tenant"),
        AzureResourceGraphWaraConfig(endpoint="https://user@management.azure.com"),
        AzureResourceGraphWaraConfig(audience="https://example.com/.default"),
        AzureResourceGraphWaraConfig(api_version="latest"),
    ),
)
async def test_provider_rejects_unapproved_token_targets(
    config: AzureResourceGraphWaraConfig,
) -> None:
    framework = load_framework_catalog(
        ROOT / "rule-catalog/collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        ASSESSMENT_ROOT / "crosswalk.json",
        ASSESSMENT_ROOT / "queries.json",
        framework=framework,
        framework_path=ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        ASSESSMENT_ROOT / "evaluator-bindings.json",
        catalog=catalog,
        queries=queries,
    )

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match="approved Azure|dated Azure"):
            AzureResourceGraphWaraObservationProvider(
                identity=StaticWorkloadIdentity(audience=AUDIENCE),
                http_client=client,
                queries=queries,
                evaluator_bindings=bindings,
                config=config,
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_matching_rows_fail_and_feed_shadow_runtime() -> None:
    runtime, request, record, plan, _ = _bound_runtime()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": plan.resource_ids[0], "name": "example"}]},
        )

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        receipt = await provider.observe(plan)
    finally:
        await client.aclose()
    evidence = wara_observation_to_evidence(plan, receipt, request)
    result = runtime.assess(replace(request, evidence=(evidence,)))
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)

    assert receipt.satisfied is False
    assert control.satisfaction is WaraSatisfactionStatus.FAILED
    assert "missing_exact_evaluator" not in control.limitations
    assert result.execution_authority is False


async def test_pagination_cannot_multiply_the_read_plan_deadline() -> None:
    _, _, _, plan, _ = _bound_runtime()
    bounded_plan = replace(plan, timeout_seconds=1)
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.55)
        return httpx.Response(
            200,
            json={
                "data": [],
                **({"$skipToken": "next-page"} if calls == 1 else {}),
            },
        )

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(WaraObservationError, match="read-plan deadline"):
            await provider.observe(bounded_plan)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_receipt_digest_is_independent_of_row_order() -> None:
    _, _, _, plan, _ = _bound_runtime()
    rows = [
        {"id": plan.resource_ids[0], "value": 2},
        {"id": plan.resource_ids[0], "value": 1},
    ]

    def first_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": rows})

    def second_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": list(reversed(rows))})

    first_provider, first_client = _provider(httpx.MockTransport(first_handler))
    second_provider, second_client = _provider(httpx.MockTransport(second_handler))
    try:
        first = await first_provider.observe(plan)
        second = await second_provider.observe(plan)
    finally:
        await first_client.aclose()
        await second_client.aclose()

    assert first.evidence_digest == second.evidence_digest


@pytest.mark.asyncio
async def test_out_of_scope_or_truncated_rows_fail_closed() -> None:
    _, _, _, plan, _ = _bound_runtime()
    responses = iter(
        (
            httpx.Response(
                200,
                json={"data": [{"id": plan.resource_ids[0] + "-other"}]},
            ),
            httpx.Response(
                200,
                json={"data": [], "count": 0, "totalRecords": 1, "resultTruncated": True},
            ),
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(WaraObservationError, match="outside the exact resource scope"):
            await provider.observe(plan)
        with pytest.raises(WaraObservationError, match="truncated"):
            await provider.observe(plan)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_plan_binding_digest_mismatch_makes_no_request() -> None:
    _, _, _, plan, _ = _bound_runtime()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(WaraObservationError, match="no exact reviewed"):
            await provider.observe(replace(plan, evaluator_bindings_digest="sha256:" + "0" * 64))
    finally:
        await client.aclose()

    assert requests == []


@pytest.mark.asyncio
async def test_non_arm_resource_scope_makes_no_request() -> None:
    _, _, _, plan, _ = _bound_runtime()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    provider, client = _provider(httpx.MockTransport(handler))
    try:
        with pytest.raises(WaraObservationError, match="exact ARM resource ids"):
            await provider.observe(replace(plan, resource_ids=("resource:not-arm",)))
    finally:
        await client.aclose()

    assert requests == []

"""AzureArgQueryFactory - HTTP-level round-trip via httpx.MockTransport.

Verifies the wire contract the P1 executor + risk-gate rely on:

- Bearer-token authentication using the injected ``WorkloadIdentity``.
- Kusto query targets the ARM type resolved from the vocabulary; unknown
  CSP-neutral types raise a clear error.
- ``$skipToken`` pagination is followed until exhaustion or ``max_pages``.
- Non-2xx / non-JSON / missing ``data`` responses raise ``ArgQueryError``.
- Response rows map into CSP-neutral ``ResourceRecord`` (raw ARM id lives
  on ``provider_ref``); untrusted ``props`` are truncated when they exceed
  the byte cap.
- ``resource_type`` with a ``None`` ``azure_arm_type`` is a legitimate
  no-op - the factory returns empty tuples so
  :class:`AzureResourceGraphInventory` still emits its ``final=True`` fence.

No real Azure endpoints are contacted; every test builds an
``httpx.AsyncClient`` on top of ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from fdai.delivery.azure.arg_query import (
    ArgQueryError,
    AzureArgQueryFactory,
    AzureArgQueryFactoryConfig,
)
from fdai.delivery.azure.inventory import (
    AzureInventoryConfig,
    AzureResourceGraphInventory,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.workload_identity import (
    StaticWorkloadIdentity,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _vocab() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _identity(
    audience: str = "https://management.azure.com/.default",
    token: str = "test-token-xyz",  # noqa: S107 - deterministic test literal, not a secret
) -> WorkloadIdentity:
    return StaticWorkloadIdentity(audience=audience, token=token)


def _config(**overrides: Any) -> AzureArgQueryFactoryConfig:
    defaults = dict(
        subscription_scopes=("00000000-0000-0000-0000-000000000001",),
        page_size=2,
        max_pages=3,
        timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return AzureArgQueryFactoryConfig(**defaults)


def _arm_row(*, arm_id: str, arm_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": arm_id,
        "type": arm_type,
        "name": arm_id.rsplit("/", 1)[-1],
        "location": "koreacentral",
        "tags": {"owner": "team-a"},
        "properties": {"public_access": "enabled"},
        "resourceGroup": "rg-example",
        "subscriptionId": "00000000-0000-0000-0000-000000000001",
    }
    if extra:
        row.update(extra)
    return row


def _make_client(
    handler: httpx.MockTransport,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://mock-arm.local")


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_empty_subscription_scopes_is_rejected() -> None:
    with pytest.raises(ValueError, match="subscription_scopes MUST NOT be empty"):
        AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=httpx.AsyncClient(),
            config=AzureArgQueryFactoryConfig(subscription_scopes=()),
        )


@pytest.mark.parametrize(
    "override,message",
    [
        ({"page_size": 0}, "page_size MUST be in"),
        ({"page_size": 1001}, "page_size MUST be in"),
        ({"max_pages": 0}, "max_pages MUST be >= 1"),
        ({"timeout_seconds": 0}, "timeout_seconds MUST be > 0"),
        ({"max_props_bytes": 500}, "max_props_bytes MUST be >= 1024"),
    ],
)
def test_invalid_config_is_rejected(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=httpx.AsyncClient(),
            config=_config(**override),
        )


# ---------------------------------------------------------------------------
# Happy path - single page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_page_query_maps_to_resource_records() -> None:
    seen_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        payload = {
            "data": [
                _arm_row(
                    arm_id=(
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/rg-example/providers/Microsoft.Storage/"
                        "storageAccounts/stg1"
                    ),
                    arm_type="Microsoft.Storage/storageAccounts",
                ),
            ]
        }
        return httpx.Response(200, json=payload)

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        fetch = factory.build_query_fn()
        resources, links = await fetch("object-storage")

    assert len(resources) == 1
    record: ResourceRecord = resources[0]
    assert record.type == "object-storage"
    assert record.provider_ref is not None
    assert record.provider_ref.endswith("/storageAccounts/stg1")
    assert "/resource-group/rg-example/" in record.resource_id
    assert record.resource_id.startswith("scope-")
    # `contains(rg-example, stg1)` edge is derived from the ARM id.
    assert len(links) == 1
    (edge,) = links
    assert edge.link_type == "contains"
    assert edge.from_id.endswith("/resource-group/rg-example")
    assert edge.from_type == "resource-group"
    assert edge.to_id == record.resource_id
    assert edge.to_type == "object-storage"

    # Bearer auth + Kusto shape assertions.
    assert len(seen_requests) == 1
    req = seen_requests[0]
    assert req.method == "POST"
    assert req.headers["Authorization"] == "Bearer test-token-xyz"
    body = json.loads(req.content.decode("utf-8"))
    assert body["subscriptions"] == ["00000000-0000-0000-0000-000000000001"]
    assert "Microsoft.Storage/storageAccounts" in body["query"]
    assert body["options"]["$top"] == 2


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_token_is_followed_until_exhausted() -> None:
    pages: list[dict[str, Any]] = [
        {
            "data": [
                _arm_row(
                    arm_id=(
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/rg-a/providers/Microsoft.Storage/"
                        "storageAccounts/s1"
                    ),
                    arm_type="Microsoft.Storage/storageAccounts",
                ),
                _arm_row(
                    arm_id=(
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/rg-a/providers/Microsoft.Storage/"
                        "storageAccounts/s2"
                    ),
                    arm_type="Microsoft.Storage/storageAccounts",
                ),
            ],
            "$skipToken": "next-1",
        },
        {
            "data": [
                _arm_row(
                    arm_id=(
                        "/subscriptions/00000000-0000-0000-0000-000000000001/"
                        "resourceGroups/rg-b/providers/Microsoft.Storage/"
                        "storageAccounts/s3"
                    ),
                    arm_type="Microsoft.Storage/storageAccounts",
                ),
            ],
        },
    ]
    calls: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        return httpx.Response(200, json=pages[len(calls) - 1])

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        resources, _ = await factory.build_query_fn()("object-storage")

    assert [r.provider_ref.split("/")[-1] for r in resources] == ["s1", "s2", "s3"]  # type: ignore[union-attr]
    # First page has no $skipToken; second page carries it.
    assert "$skipToken" not in calls[0]["options"]
    assert calls[1]["options"]["$skipToken"] == "next-1"


@pytest.mark.asyncio
async def test_pagination_cap_raises() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _arm_row(
                        arm_id=(
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-a/providers/Microsoft.Storage/"
                            "storageAccounts/x"
                        ),
                        arm_type="Microsoft.Storage/storageAccounts",
                    ),
                ],
                "$skipToken": "runaway",  # never terminates
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(max_pages=2),
        )
        with pytest.raises(ArgQueryError, match="pagination cap"):
            await factory.build_query_fn()("object-storage")


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_2xx_response_raises() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden - insufficient RBAC")

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(ArgQueryError, match="HTTP 403"):
            await factory.build_query_fn()("object-storage")


@pytest.mark.asyncio
async def test_non_json_response_raises() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json-at-all")

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(ArgQueryError, match="non-JSON"):
            await factory.build_query_fn()("object-storage")


@pytest.mark.asyncio
async def test_missing_data_field_raises() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"$skipToken": "next"})  # no `data`

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(ArgQueryError, match="missing 'data'"):
            await factory.build_query_fn()("object-storage")


@pytest.mark.asyncio
async def test_httpx_transport_error_wraps_into_arg_query_error() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(ArgQueryError, match="ARG request failed"):
            await factory.build_query_fn()("object-storage")


# ---------------------------------------------------------------------------
# Resource-type resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_resource_type_raises_before_calling_arg() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("adapter must not hit HTTP for an unknown type")

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        with pytest.raises(ArgQueryError, match="unknown resource_type"):
            await factory.build_query_fn()("not-in-vocab")


# ---------------------------------------------------------------------------
# Untrusted-prop truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversize_properties_are_truncated() -> None:
    huge = {"blob": "x" * 20000, "nested": {"inner": "y" * 20000}}

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _arm_row(
                        arm_id=(
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-a/providers/Microsoft.Storage/"
                            "storageAccounts/big"
                        ),
                        arm_type="Microsoft.Storage/storageAccounts",
                        extra={"properties": huge, "tags": huge},
                    ),
                ]
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(max_props_bytes=2048),
        )
        resources, _ = await factory.build_query_fn()("object-storage")

    assert len(resources) == 1
    record = resources[0]
    # After truncation the record still exists and is auditable via provider_ref.
    assert record.provider_ref is not None
    assert record.props.get("_truncated") is True


# ---------------------------------------------------------------------------
# Empty ARM type (legitimate no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_type_without_arm_mapping_is_a_noop() -> None:
    """A CSP-neutral type with `azure_arm_type: None` MUST NOT call HTTP.

    We synthesize such an entry to exercise the branch - production
    vocabulary may or may not have one at any point, but the branch MUST
    behave deterministically either way.
    """
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    # Build a one-entry vocab whose azure_arm_type is null.
    minimal = load_resource_type_registry_from_mapping(
        {
            "schema_version": "1.0.0",
            "version": "0.0.1",
            "types": [
                {
                    "id": "phantom.type",
                    "category": "compute",
                    "description": "No Azure counterpart at this level.",
                    "azure_arm_type": None,
                }
            ],
        }
    )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=minimal,
            http_client=client,
            config=_config(),
        )
        resources, links = await factory.build_query_fn()("phantom.type")

    assert resources == ()
    assert links == ()
    assert seen == []  # no HTTP call


# ---------------------------------------------------------------------------
# End-to-end: full-scan through AzureResourceGraphInventory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_inventory_snapshot_streams_final_true() -> None:
    """AzureResourceGraphInventory + factory streams a real fence batch."""

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        # Return one resource per resource_type shard.
        query = body["query"]
        if "Microsoft.Storage/storageAccounts" in query:
            row = _arm_row(
                arm_id=(
                    "/subscriptions/00000000-0000-0000-0000-000000000001/"
                    "resourceGroups/rg-a/providers/Microsoft.Storage/"
                    "storageAccounts/s1"
                ),
                arm_type="Microsoft.Storage/storageAccounts",
            )
        else:
            row = _arm_row(
                arm_id=(
                    "/subscriptions/00000000-0000-0000-0000-000000000001/"
                    "resourceGroups/rg-a/providers/Microsoft.Compute/"
                    "virtualMachines/vm1"
                ),
                arm_type="Microsoft.Compute/virtualMachines",
            )
        return httpx.Response(200, json={"data": [row]})

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        inventory = AzureResourceGraphInventory(
            config=AzureInventoryConfig(
                resource_types=("object-storage", "compute.vm"),
                max_concurrent_queries=2,
            ),
            query=factory.build_query_fn(),
        )
        batches: list[Sequence[ResourceRecord]] = []
        final_seen = False
        async for batch in inventory.full_snapshot():
            if batch.final:
                final_seen = True
            batches.extend([batch.resources])

    assert final_seen
    # One shard yields one resource; final fence carries no data.
    payload_batches = [b for b in batches if b]
    assert len(payload_batches) == 2
    provider_refs = {r.provider_ref for shard in payload_batches for r in shard}
    assert any(pr and pr.endswith("/storageAccounts/s1") for pr in provider_refs)
    assert any(pr and pr.endswith("/virtualMachines/vm1") for pr in provider_refs)


# ---------------------------------------------------------------------------
# Edge cases: mapper / helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_mapping_rows_and_missing_id_are_skipped() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    "not-a-mapping",
                    {"id": "", "type": "Microsoft.Storage/storageAccounts"},  # empty id
                    {"type": "no-id"},  # missing id
                    _arm_row(
                        arm_id=(
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-a/providers/Microsoft.Storage/"
                            "storageAccounts/keep"
                        ),
                        arm_type="Microsoft.Storage/storageAccounts",
                    ),
                ]
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        resources, _ = await factory.build_query_fn()("object-storage")

    # Only the well-formed row survives; the three malformed ones are dropped
    # silently - no ArgQueryError because that's per-page level, not per-row.
    assert len(resources) == 1
    assert resources[0].provider_ref is not None
    assert resources[0].provider_ref.endswith("/storageAccounts/keep")


def test_neutral_id_falls_back_when_no_resource_group_marker() -> None:
    """Cover the branch where an ARM id lacks `/resourceGroups/`.

    Subscription-scoped resources (rare in the P1 rule set) have no RG
    segment; the helper MUST still return a stable, lowercased id.
    """
    from fdai.delivery.azure.arg_query import _to_neutral_id

    result = _to_neutral_id(
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "providers/Microsoft.Authorization/roleDefinitions/xyz"
    )
    assert result.startswith("scope-")
    assert result.endswith("/providers/microsoft.authorization/roledefinitions/xyz")
    assert "00000000-0000-0000-0000-000000000001" not in result


def test_truncate_props_extreme_case_returns_hint_only() -> None:
    """When even dropping `properties` + `tags` can't fit, return the
    minimal audit hint. Guards against a runaway `name`/`location` blob."""
    from fdai.delivery.azure.arg_query import _truncate_props

    huge = {
        "name": "n" * 5000,
        "location": "l" * 5000,
        "properties": {"x": "y" * 5000},
        "tags": {"a": "b" * 5000},
    }
    result = _truncate_props(huge, max_bytes=1024)
    assert result == {"_truncated": True, "resource_id_hint": huge["name"]}


def test_build_query_rejects_single_quote_in_arm_type() -> None:
    """Defense-in-depth against a corrupted vocabulary entry."""
    from fdai.delivery.azure.arg_query import ArgQueryError

    factory = AzureArgQueryFactory(
        identity=_identity(),
        resource_types=_vocab(),
        http_client=httpx.AsyncClient(),
        config=_config(),
    )
    with pytest.raises(ArgQueryError, match="illegal character"):
        factory._build_query(arm_type="Microsoft.Weird/type'; drop table --")


def test_resource_group_query_uses_resource_containers() -> None:
    factory = AzureArgQueryFactory(
        identity=_identity(),
        resource_types=_vocab(),
        http_client=httpx.AsyncClient(),
        config=AzureArgQueryFactoryConfig(subscription_scopes=("sub-1",)),
    )
    query = factory._build_query(arm_type="Microsoft.Resources/resourceGroups")
    assert query.startswith("ResourceContainers |")


def test_neutral_ids_do_not_collide_across_subscriptions() -> None:
    from fdai.delivery.azure.arg_query import _to_neutral_id

    suffix = "/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"
    first = _to_neutral_id(f"/subscriptions/sub-1{suffix}")
    second = _to_neutral_id(f"/subscriptions/sub-2{suffix}")
    assert first != second
    assert "sub-1" not in first
    assert "sub-2" not in second


def test_arg_config_rejects_insecure_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=httpx.AsyncClient(),
            config=AzureArgQueryFactoryConfig(
                subscription_scopes=("sub-1",),
                arg_endpoint="http://management.example",
            ),
        )


@pytest.mark.asyncio
async def test_row_property_with_null_value_is_dropped() -> None:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": (
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-a/providers/Microsoft.Storage/"
                            "storageAccounts/nullish"
                        ),
                        "type": "Microsoft.Storage/storageAccounts",
                        "name": "nullish",
                        "location": None,  # skipped by mapper
                        "tags": None,  # skipped by mapper
                        "properties": {"public_access": "disabled"},
                    }
                ]
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        resources, _ = await factory.build_query_fn()("object-storage")

    assert len(resources) == 1
    props = resources[0].props
    assert "location" not in props
    assert "tags" not in props
    assert props.get("properties") == {"public_access": "disabled"}


# ---------------------------------------------------------------------------
# _extract_rg_contains_links - pure helper, no HTTP
# ---------------------------------------------------------------------------


def _record(
    *,
    arm_id: str,
    rtype: str = "object-storage",
) -> ResourceRecord:
    from fdai.delivery.azure.arg_query import _to_neutral_id

    return ResourceRecord(
        resource_id=_to_neutral_id(arm_id),
        type=rtype,
        provider_ref=arm_id,
    )


def test_extract_rg_contains_returns_empty_for_no_resources() -> None:
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    assert _extract_rg_contains_links(()) == ()


def test_extract_rg_contains_emits_edge_for_rg_scoped_resource() -> None:
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    rec = _record(
        arm_id=(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourceGroups/rg-example/providers/Microsoft.Storage/"
            "storageAccounts/stg1"
        )
    )
    (edge,) = _extract_rg_contains_links([rec])
    assert edge.link_type == "contains"
    assert edge.from_id.endswith("/resource-group/rg-example")
    assert edge.from_type == "resource-group"
    assert edge.to_id == rec.resource_id
    assert edge.to_type == "object-storage"


def test_extract_rg_contains_skips_resource_group_itself() -> None:
    """A resource-group RECORD has no RG parent within P1 scope
    (its parent is the subscription, which lands in a later phase)."""
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    rg_record = _record(
        arm_id=("/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example"),
        rtype="resource-group",
    )
    assert _extract_rg_contains_links([rg_record]) == ()


def test_extract_rg_contains_skips_resource_without_provider_ref() -> None:
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    hand_crafted = ResourceRecord(
        resource_id="resource-group/rg-x/providers/microsoft.storage/x/y",
        type="object-storage",
        provider_ref=None,
    )
    assert _extract_rg_contains_links([hand_crafted]) == ()


def test_extract_rg_contains_skips_subscription_scoped_resource() -> None:
    """Role definitions and similar sub-scoped resources have no RG segment."""
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    rec = _record(
        arm_id=(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "providers/Microsoft.Authorization/roleDefinitions/xyz"
        )
    )
    assert _extract_rg_contains_links([rec]) == ()


def test_extract_rg_contains_deduplicates_repeats_within_shard() -> None:
    """Duplicate `(rg, contains, resource)` triples collapse into one edge."""
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Storage/storageAccounts/s1"
    )
    dup = _record(arm_id=arm_id)
    # Two records with identical resource_id - the extractor dedupes.
    (edge,) = _extract_rg_contains_links([dup, dup])
    assert edge.from_id.endswith("/resource-group/rg-a")


def test_extract_rg_contains_case_insensitive_marker() -> None:
    """The `/resourceGroups/` marker is matched case-insensitively so a
    provider variation (`/resourcegroups/` seen in some legacy ids)
    still yields an edge."""
    from fdai.delivery.azure.arg_query import _extract_rg_contains_links

    rec = _record(
        arm_id=(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourcegroups/rg-lower/providers/Microsoft.Storage/"
            "storageAccounts/lc"
        )
    )
    (edge,) = _extract_rg_contains_links([rec])
    assert edge.from_id.endswith("/resource-group/rg-lower")
    assert edge.to_type == "object-storage"


# ---------------------------------------------------------------------------
# _arm_id_to_type / _extract_attached_to_links_from_row helpers
# ---------------------------------------------------------------------------


def test_arm_id_to_type_extracts_top_level_type() -> None:
    from fdai.delivery.azure.arg_query import _arm_id_to_type

    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Storage/"
        "storageAccounts/stg1"
    )
    assert _arm_id_to_type(arm_id) == "Microsoft.Storage/storageAccounts"


def test_arm_id_to_type_extracts_multi_segment_type() -> None:
    from fdai.delivery.azure.arg_query import _arm_id_to_type

    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Network/"
        "virtualNetworks/vnet1/subnets/sub1"
    )
    assert _arm_id_to_type(arm_id) == "Microsoft.Network/virtualNetworks/subnets"


def test_arm_id_to_type_returns_none_without_providers_segment() -> None:
    from fdai.delivery.azure.arg_query import _arm_id_to_type

    assert _arm_id_to_type("/subscriptions/00000000-0000-0000-0000-000000000001") is None


def test_extract_attached_to_from_subnet_reference() -> None:
    """A NIC row with properties.subnet.id emits attached_to(nic, subnet)."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_attached_to_links_from_row,
        _to_neutral_id,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    subnet_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Network/"
        "virtualNetworks/vnet1/subnets/sub1"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.network/networkinterfaces/nic1",
        type="network.load-balancer",
        provider_ref=(
            "/subscriptions/.../resourceGroups/rg-a/providers/Microsoft.Network/"
            "networkInterfaces/nic1"
        ),
    )
    row = {"properties": {"subnet": {"id": subnet_arm_id}}}
    (edge,) = _extract_attached_to_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert edge.link_type == "attached_to"
    assert edge.from_id == child.resource_id
    assert edge.from_type == "network.load-balancer"
    assert edge.to_id == _to_neutral_id(subnet_arm_id)
    assert edge.to_type == "network.subnet"


def test_extract_attached_to_from_nsg_reference() -> None:
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_attached_to_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    nsg_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Network/"
        "networkSecurityGroups/nsg-1"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.network/virtualnetworks/vnet1/subnets/sub1",
        type="network.subnet",
        provider_ref="/subscriptions/.../subnets/sub1",
    )
    row = {"properties": {"networkSecurityGroup": {"id": nsg_arm_id}}}
    (edge,) = _extract_attached_to_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert edge.to_type == "network.nsg"


def test_extract_attached_to_drops_reference_to_unmapped_type() -> None:
    """A referenced ARM type not in the vocabulary is dropped, not
    emitted with an unknown to_type."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_attached_to_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    unknown_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Weird/thingies/x"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.network/networkinterfaces/nic1",
        type="network.load-balancer",
        provider_ref="/subscriptions/.../nic1",
    )
    row = {"properties": {"subnet": {"id": unknown_arm_id}}}
    assert _extract_attached_to_links_from_row(row, child=child, arm_to_neutral=reverse) == ()


def test_extract_attached_to_returns_empty_when_no_properties() -> None:
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_attached_to_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.storage/storageaccounts/x",
        type="object-storage",
        provider_ref="/subscriptions/.../x",
    )
    assert _extract_attached_to_links_from_row({}, child=child, arm_to_neutral=reverse) == ()
    # Properties present but not a mapping - same result.
    assert (
        _extract_attached_to_links_from_row(
            {"properties": "not a dict"}, child=child, arm_to_neutral=reverse
        )
        == ()
    )


def test_extract_attached_to_deduplicates_within_row() -> None:
    """Two whitelisted keys pointing at the same target collapse into
    a single edge - deduplication mirrors the LinkRecord idempotency
    contract on InventoryBatch."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_attached_to_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    same_target = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Network/"
        "virtualNetworks/vnet1/subnets/sub1"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.network/networkinterfaces/nic1",
        type="network.load-balancer",
        provider_ref="/subscriptions/.../nic1",
    )
    row = {
        "properties": {
            # Same subnet referenced twice via two whitelisted paths
            # (contrived - the extractor still dedupes).
            "subnet": {"id": same_target},
            "networkSecurityGroup": {"id": same_target},  # same target string
        }
    }
    edges = _extract_attached_to_links_from_row(row, child=child, arm_to_neutral=reverse)
    # Even though two keys were consumed, the extractor collapses to a
    # single edge because from_id / link_type / to_id are identical.
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_full_row_emits_contains_and_attached_to_links_together() -> None:
    """End-to-end via httpx.MockTransport: a NIC row surfaces
    contains(rg, nic) + attached_to(nic, subnet) in the same shard."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _arm_row(
                        arm_id=(
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-example/providers/Microsoft.Storage/"
                            "storageAccounts/stg1"
                        ),
                        arm_type="Microsoft.Storage/storageAccounts",
                        extra={
                            "properties": {
                                # A storage account rarely has a subnet
                                # attachment, but the extractor is
                                # property-driven - this exercises the
                                # end-to-end path deterministically.
                                "subnet": {
                                    "id": (
                                        "/subscriptions/"
                                        "00000000-0000-0000-0000-000000000001/"
                                        "resourceGroups/rg-example/providers/"
                                        "Microsoft.Network/virtualNetworks/"
                                        "vnet1/subnets/sub1"
                                    )
                                }
                            }
                        },
                    )
                ]
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        resources, links = await factory.build_query_fn()("object-storage")

    assert len(resources) == 1
    link_types = {edge.link_type for edge in links}
    assert link_types == {"contains", "attached_to"}
    (attached,) = [e for e in links if e.link_type == "attached_to"]
    assert attached.to_type == "network.subnet"
    (contained,) = [e for e in links if e.link_type == "contains"]
    assert contained.from_type == "resource-group"


# ---------------------------------------------------------------------------
# _extract_depends_on_links_from_row - soft-dependency whitelist
# ---------------------------------------------------------------------------


def test_extract_depends_on_from_storage_account_reference() -> None:
    """A Function / App Service / AKS row with `properties.storageAccount.id`
    emits `depends_on(child, storage)`."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
        _to_neutral_id,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    storage_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Storage/"
        "storageAccounts/stg1"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref=(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourceGroups/rg-a/providers/Microsoft.Web/sites/fn1"
        ),
    )
    row = {"properties": {"storageAccount": {"id": storage_arm_id}}}
    (edge,) = _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert edge.link_type == "depends_on"
    assert edge.from_id == child.resource_id
    assert edge.from_type == "compute.function"
    assert edge.to_id == _to_neutral_id(storage_arm_id)
    assert edge.to_type == "object-storage"


def test_extract_depends_on_from_workspace_resource_id() -> None:
    """A Diagnostic Setting row with `properties.workspaceResourceId`
    emits `depends_on(setting, log-workspace)`.

    Unlike `storageAccount.id`, this path is a top-level ARM-id string
    (no `.id` wrapper) - the extractor MUST handle both shapes."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
        _to_neutral_id,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    workspace_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-obs/providers/Microsoft.OperationalInsights/"
        "workspaces/law-central"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.insights/diagnosticsettings/ds1",
        type="diagnostic-settings",
        provider_ref=(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourceGroups/rg-a/providers/Microsoft.Insights/diagnosticSettings/ds1"
        ),
    )
    row = {"properties": {"workspaceResourceId": workspace_arm_id}}
    (edge,) = _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert edge.link_type == "depends_on"
    assert edge.to_id == _to_neutral_id(workspace_arm_id)
    assert edge.to_type == "log-workspace"


def test_extract_depends_on_from_acr_login_server_skipped_when_unresolvable() -> None:
    """`properties.acrLoginServer` is a DNS name; the current registry
    lookup returns ``None`` for every value, so the reference is
    silently dropped ("skip if not resolvable"). This proves the code
    path is exercised without emitting spurious edges."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    row = {"properties": {"acrLoginServer": "myregistry.azurecr.io"}}
    assert _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse) == ()


def test_extract_depends_on_from_acr_login_server_emits_when_resolver_returns_arm_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive-emission path: monkeypatch the placeholder resolver so
    it returns an ARM id whose type IS in the vocabulary. Uses
    ``Microsoft.Storage/storageAccounts`` as a stand-in target since
    ``container-registry`` is not (yet) in the vocabulary - the point
    is to exercise the emit branch, not the semantics of ACR."""
    from fdai.delivery.azure import arg_query as arg_query_mod
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    resolved_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Storage/"
        "storageAccounts/acr-stand-in"
    )
    monkeypatch.setattr(
        arg_query_mod,
        "_resolve_acr_login_server_to_arm_id",
        lambda _login_server: resolved_arm_id,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    row = {"properties": {"acrLoginServer": "myregistry.azurecr.io"}}
    (edge,) = _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert edge.link_type == "depends_on"
    assert edge.to_type == "object-storage"


def test_extract_depends_on_drops_reference_to_unmapped_type() -> None:
    """A soft-dep reference to an ARM type not in the vocabulary is
    dropped, not emitted with an unknown to_type - same envelope as
    `_extract_attached_to_links_from_row`."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    unknown_arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Weird/thingies/x"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    # Try each ARM-id-carrying path with an unmapped target.
    for row in (
        {"properties": {"storageAccount": {"id": unknown_arm_id}}},
        {"properties": {"workspaceResourceId": unknown_arm_id}},
    ):
        assert _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse) == ()


def test_extract_depends_on_drops_reference_without_providers_segment() -> None:
    """A ref value that IS a non-empty string but lacks the
    ``/providers/`` segment cannot yield an ARM type - the extractor
    treats it as un-typable and drops it (never emits an edge with
    an unknown ``to_type``)."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    junk = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-a"
    for row in (
        {"properties": {"storageAccount": {"id": junk}}},
        {"properties": {"workspaceResourceId": junk}},
    ):
        assert _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse) == ()


def test_extract_depends_on_returns_empty_when_no_properties() -> None:
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    assert _extract_depends_on_links_from_row({}, child=child, arm_to_neutral=reverse) == ()
    # Properties present but not a mapping.
    assert (
        _extract_depends_on_links_from_row(
            {"properties": ["not", "a", "dict"]}, child=child, arm_to_neutral=reverse
        )
        == ()
    )
    # Nested key present but value is not a mapping (defensive branch).
    assert (
        _extract_depends_on_links_from_row(
            {"properties": {"storageAccount": "not-a-mapping"}},
            child=child,
            arm_to_neutral=reverse,
        )
        == ()
    )
    # Nested key present but `.id` is missing / empty.
    assert (
        _extract_depends_on_links_from_row(
            {"properties": {"storageAccount": {"id": ""}}},
            child=child,
            arm_to_neutral=reverse,
        )
        == ()
    )
    # Top-level string key present but empty / non-string.
    assert (
        _extract_depends_on_links_from_row(
            {"properties": {"workspaceResourceId": ""}},
            child=child,
            arm_to_neutral=reverse,
        )
        == ()
    )
    assert (
        _extract_depends_on_links_from_row(
            {"properties": {"workspaceResourceId": 42}},
            child=child,
            arm_to_neutral=reverse,
        )
        == ()
    )
    # acrLoginServer non-string / empty is skipped before hitting the resolver.
    assert (
        _extract_depends_on_links_from_row(
            {"properties": {"acrLoginServer": ""}},
            child=child,
            arm_to_neutral=reverse,
        )
        == ()
    )


def test_extract_depends_on_deduplicates_within_row() -> None:
    """Two whitelisted paths pointing at the same target collapse into
    a single edge - mirrors the `attached_to` dedup contract."""
    from fdai.delivery.azure.arg_query import (
        _build_arm_to_neutral_map,
        _extract_depends_on_links_from_row,
    )

    reverse = _build_arm_to_neutral_map(_vocab())
    # Same target advertised twice: once as a nested `storageAccount.id`
    # and once as a top-level `workspaceResourceId` ARM string. This is
    # contrived (real rows never mix these keys against the same
    # target), but the extractor MUST still dedupe deterministically.
    same_target = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/"
        "resourceGroups/rg-a/providers/Microsoft.Storage/"
        "storageAccounts/shared"
    )
    child = ResourceRecord(
        resource_id="resource-group/rg-a/providers/microsoft.web/sites/fn1",
        type="compute.function",
        provider_ref="/subscriptions/.../fn1",
    )
    row = {
        "properties": {
            "storageAccount": {"id": same_target},
            "workspaceResourceId": same_target,
        }
    }
    edges = _extract_depends_on_links_from_row(row, child=child, arm_to_neutral=reverse)
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_full_row_emits_contains_attached_to_and_depends_on_together() -> None:
    """End-to-end via httpx.MockTransport: a single shard surfaces
    contains(rg, child) + attached_to(child, subnet) + depends_on(child, storage)."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _arm_row(
                        arm_id=(
                            "/subscriptions/00000000-0000-0000-0000-000000000001/"
                            "resourceGroups/rg-example/providers/Microsoft.Web/"
                            "sites/fn1"
                        ),
                        arm_type="Microsoft.Web/sites",
                        extra={
                            "properties": {
                                # attached_to path
                                "subnet": {
                                    "id": (
                                        "/subscriptions/"
                                        "00000000-0000-0000-0000-000000000001/"
                                        "resourceGroups/rg-example/providers/"
                                        "Microsoft.Network/virtualNetworks/"
                                        "vnet1/subnets/sub1"
                                    )
                                },
                                # depends_on path (nested id)
                                "storageAccount": {
                                    "id": (
                                        "/subscriptions/"
                                        "00000000-0000-0000-0000-000000000001/"
                                        "resourceGroups/rg-example/providers/"
                                        "Microsoft.Storage/storageAccounts/stg1"
                                    )
                                },
                            }
                        },
                    )
                ]
            },
        )

    async with _make_client(httpx.MockTransport(_handler)) as client:
        factory = AzureArgQueryFactory(
            identity=_identity(),
            resource_types=_vocab(),
            http_client=client,
            config=_config(),
        )
        resources, links = await factory.build_query_fn()("compute.function")

    assert len(resources) == 1
    link_types = {edge.link_type for edge in links}
    assert link_types == {"contains", "attached_to", "depends_on"}
    (depends,) = [e for e in links if e.link_type == "depends_on"]
    assert depends.to_type == "object-storage"
    assert depends.from_type == "compute.function"
    (attached,) = [e for e in links if e.link_type == "attached_to"]
    assert attached.to_type == "network.subnet"
    (contained,) = [e for e in links if e.link_type == "contains"]
    assert contained.from_type == "resource-group"

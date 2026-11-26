"""Current-source concept evidence, not a provider incident or live qualification."""

from __future__ import annotations

import json
import tracemalloc
from collections import UserDict
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import NoReturn, cast

import httpx
import pytest
from fdai.core.ontology_platform.inventory_projection_bounds import _MAX_PROJECTION_VALUES
from fdai.delivery.azure import arg_transport, arm_inventory_transport
from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.azure.dev_workload_identity import (
    AsyncAzureCliWorkloadIdentity,
    AzureCliWorkloadIdentity,
)
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
from fdai.delivery.inventory_collection import collection_context_digest
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync import InventorySyncCoordinator, PromotedInventoryObservation
from fdai.delivery.inventory_sync_cli_support import build_sources
from fdai.delivery.persistence import postgres_inventory_prepared
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_support import (
    MAX_STAGE_BATCH_BYTES,
    MAX_STAGE_JSON_BYTES,
    canonical_json_mapping,
    snapshot_write_batches,
)
from fdai.shared.providers.inventory import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)


async def test_arg_cooldown_is_adapter_local_not_replayed_by_a_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.setattr(arg_transport, "_monotonic", lambda: now)
    monkeypatch.setattr(arg_transport, "_sleep", sleep)
    original = arg_transport.ArgThrottleGate()
    await original.defer(20.0)
    replacement = arg_transport.ArgThrottleGate()
    await replacement.wait()
    assert waits == []
    assert now == 0.0
    await original.wait()
    assert waits == [20.0]
    assert now == 20.0


@pytest.mark.parametrize("source_name", ["arg", "arm"])
async def test_source_context_changes_with_the_selected_managed_identity(
    source_name: str,
) -> None:
    """Fence configured selector changes without claiming authenticated identity evidence."""

    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": source_name,
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )
    identity_selections: list[str] = []
    provider_authorizations: list[str] = []
    manifests: list[InventoryCoverageManifest] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "identity.example.invalid":
            selected = request.url.params["client_id"]
            identity_selections.append(selected)
            return httpx.Response(
                200,
                json={"access_token": f"synthetic-{selected}", "expires_on": 1_893_456_000},
            )
        provider_authorizations.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"},
            )
        return httpx.Response(200, json={"value": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for principal in (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ):
            identity = ManagedIdentityWorkloadIdentity(
                http_client=client,
                config=ManagedIdentityWorkloadIdentityConfig(
                    endpoint="https://identity.example.invalid/token",
                    header="synthetic-header",
                    client_id=principal,
                ),
            )
            (source,) = build_sources(
                config=config,
                vocabulary=load_resource_type_registry(),
                resource_types=("resource-group",),
                identity=identity,
                http_client=client,
                started_at=datetime(2026, 10, 21, tzinfo=UTC),
            )
            manifests.append(source.manifest)
            (same_source,) = build_sources(
                config=config,
                vocabulary=load_resource_type_registry(),
                resource_types=("resource-group",),
                identity=ManagedIdentityWorkloadIdentity(
                    http_client=client,
                    config=ManagedIdentityWorkloadIdentityConfig(
                        endpoint="https://identity.example.invalid/token",
                        header="rotated-synthetic-header",
                        client_id=principal,
                        timeout_seconds=2.0,
                    ),
                ),
                http_client=client,
                started_at=datetime(2026, 10, 21, tzinfo=UTC),
            )
            assert collection_context_digest(source.manifest) == collection_context_digest(
                same_source.manifest
            )
            before = len(provider_authorizations)
            batches = [batch async for batch in cast(Inventory, source.inventory).full_snapshot()]
            assert batches
            assert len(provider_authorizations) > before
            assert set(provider_authorizations[before:]) == {f"Bearer synthetic-{principal}"}

    assert len(set(identity_selections)) == 2
    assert manifests[0] != manifests[1]
    assert collection_context_digest(manifests[0]) != collection_context_digest(manifests[1])


@pytest.mark.parametrize("change", ["subscription", "tenant", "executable", "ignored_tenant"])
def test_cli_selector_digest_tracks_only_effective_configuration(change: str) -> None:
    original = AzureCliWorkloadIdentity(
        subscription_id="subscription-example" if change == "ignored_tenant" else None,
        tenant_id="tenant-example",
    )
    if change == "subscription":
        changed = replace(original, subscription_id="other-subscription")
    elif change == "executable":
        changed = replace(original, executable="/example/az")
    else:
        changed = replace(original, tenant_id="other-tenant")
    first = AsyncAzureCliWorkloadIdentity(credential=original).authentication_selector_digest
    second = AsyncAzureCliWorkloadIdentity(credential=changed).authentication_selector_digest
    assert (first == second) == (change == "ignored_tenant")
    assert "tenant-example" not in first
    assert original._cache == {}


@pytest.mark.parametrize("change", ["client", "tenant", "path"])
async def test_federated_selector_digest_does_not_read_projected_credentials(change: str) -> None:
    config = ManagedIdentityWorkloadIdentityConfig(
        endpoint="",
        header="",
        client_id="00000000-0000-0000-0000-000000000001",
        federated_tenant_id="00000000-0000-0000-0000-000000000002",
        federated_token_file="/example/projected-token",
    )
    if change == "client":
        changed = replace(config, client_id="00000000-0000-0000-0000-000000000003")
    elif change == "tenant":
        changed = replace(config, federated_tenant_id="00000000-0000-0000-0000-000000000004")
    else:
        changed = replace(config, federated_token_file="/example/other-projected-token")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("no HTTP"))
    ) as client:
        original = ManagedIdentityWorkloadIdentity(http_client=client, config=config)
        replacement = ManagedIdentityWorkloadIdentity(http_client=client, config=changed)
        assert original.authentication_selector_digest != replacement.authentication_selector_digest
        assert config.federated_tenant_id is not None
        assert config.federated_tenant_id not in original.authentication_selector_digest


async def test_arm_retry_after_is_not_retained_by_the_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained error deadline is not a gate on the next physical request."""

    now = datetime(2026, 10, 21, tzinfo=UTC)
    waits: list[float] = []
    calls = 0

    class Clock:
        @staticmethod
        def now(_: object) -> datetime:
            return now

    async def sleep(delay: float) -> None:
        waits.append(delay)

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, json={"value": []})

    monkeypatch.setattr(arm_inventory_transport, "_sleep", sleep)
    monkeypatch.setattr(arm_inventory_transport, "datetime", Clock)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        fetch = partial(
            fetch_arm_json,
            client=client,
            url="https://management.example.invalid/resources",
            headers={},
            resource_type="resource-group",
            timeout_seconds=1.0,
            max_response_bytes=1024,
            max_attempts=1,
        )
        with pytest.raises(ArmInventoryError) as failure:
            await fetch()
        deadline = failure.value.retry_not_before
        assert deadline == now + timedelta(seconds=120)
        payload, _ = await fetch()

    assert payload == {"value": []}
    assert calls == 2
    assert waits == []


@pytest.mark.parametrize("extra_byte", [0, 1])
def test_canonical_json_mapping_enforces_exact_stage_byte_bound(extra_byte: int) -> None:
    prefix = len(json.dumps({"blob": ""}, separators=(",", ":")).encode("utf-8"))
    payload = {"blob": "x" * (MAX_STAGE_JSON_BYTES - prefix + extra_byte)}
    if extra_byte:
        with pytest.raises(ValueError, match="exceeds its byte bound"):
            canonical_json_mapping(payload, "snapshot resource props")
    else:
        encoded = canonical_json_mapping(payload, "snapshot resource props")
        assert len(encoded.encode("utf-8")) == MAX_STAGE_JSON_BYTES


def test_canonical_json_mapping_refuses_oversized_and_expanded_inputs_with_bounded_allocation() -> (
    None
):
    for payload in (
        UserDict({"blob": "x" * (4 * 1024 * 1024)}),
        UserDict({"items": range(600_000)}),
    ):
        # Warm the refusal path so first-execution costs (such as coverage line
        # bookkeeping on a cold worker) are not counted as payload allocation.
        with pytest.raises(ValueError, match="exceeds its byte bound"):
            canonical_json_mapping(payload, "snapshot resource props")
        tracemalloc.start()
        try:
            with pytest.raises(ValueError, match="exceeds its byte bound"):
                canonical_json_mapping(payload, "snapshot resource props")
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 128 * 1024


async def test_snapshot_stage_preflights_derived_relationship_metadata_before_connecting() -> None:
    store = PostgresInventorySnapshotStore(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://example.invalid/unused")
    )
    now = datetime(2026, 10, 21, tzinfo=UTC)
    metadata = LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.TELEMETRY,
            source_identity="telemetry.runtime-calls",
            source_revision="1.0.0",
            effective_at=now,
            recorded_at=now,
            evidence_cutoff=now,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("sha256:" + "1" * 64,),
        ),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory.endpoint-verifier",
        verifier_revision="1.0.0",
        verification_receipt_ref="sha256:" + "2" * 64,
        inventory_generation="generation-1",
        mapping_id="runtime-call-endpoint-identity",
        mapping_revision="1.1.0",
        source_schema_version="fdai.runtime-call-observation@1.1.0",
        source_schema_digest="sha256:" + "3" * 64,
    )
    near_limit = "x" * (MAX_STAGE_JSON_BYTES - 128)
    link = LinkRecord(
        from_id="resource:caller",
        from_type="container-app",
        link_type="runtime_calls",
        to_id="resource:target",
        to_type="postgres-flexible",
        link_props={"note": near_limit},
        observation_metadata=metadata,
    )
    with pytest.raises(ValueError, match="snapshot relationship props exceeds its byte bound"):
        await store.stage("attempt-1", InventoryBatch(links=(link,)))


def test_snapshot_write_batches_split_on_sql_parameter_byte_bound() -> None:
    row_size = 900 * 1024
    batches = list(
        snapshot_write_batches(
            (({"resource_id": f"r-{index}"}, row_size) for index in range(6)),
            max_rows=1000,
        )
    )
    assert [len(batch) for batch in batches] == [4, 2]
    with pytest.raises(ValueError, match="exceeds the write-buffer byte limit"):
        list(
            snapshot_write_batches(
                [({"resource_id": "oversized"}, MAX_STAGE_BATCH_BYTES)],
                max_rows=1000,
            )
        )


def test_prepared_candidate_digest_rejects_dense_projection_overflow_before_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_normalize(*_: object, **__: object) -> NoReturn:
        raise AssertionError("prepared candidate normalized dense overflow before projection check")

    items: list[list[object]] = [[]] * 100_000
    resources = tuple(
        ResourceRecord(resource_id=f"resource-{index}", type="compute.vm", props={"items": items})
        for index in range(24)
    )
    assert len(resources) * len(items) > _MAX_PROJECTION_VALUES
    observation = PromotedInventoryObservation(
        generation="attempt-1",
        resources=resources,
        links=(),
        complete=True,
        recorded_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    monkeypatch.setattr(postgres_inventory_prepared, "normalize_json_value", unexpected_normalize)
    with pytest.raises(ValueError, match="expanded-value bound"):
        postgres_inventory_prepared.candidate_graph_digest(observation)


async def test_rebuilt_sources_do_not_share_request_admission_across_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebuilding sources creates a fresh local rate limiter; #2329 tracks shared admission."""

    now = 100.0
    waits: list[float] = []
    provider_calls = 0

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.setattr(arg_transport, "_monotonic", lambda: now)
    monkeypatch.setattr(arg_transport, "_sleep", sleep)
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": "arg",
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        if request.url.host == "identity.example.invalid":
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_on": 1_893_456_000}
            )
        provider_calls += 1
        return httpx.Response(
            200, json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for _ in range(2):
            identity = ManagedIdentityWorkloadIdentity(
                http_client=client,
                config=ManagedIdentityWorkloadIdentityConfig(
                    endpoint="https://identity.example.invalid/token",
                    header="synthetic-header",
                    client_id="00000000-0000-0000-0000-000000000001",
                ),
            )
            (source,) = build_sources(
                config=config,
                vocabulary=load_resource_type_registry(),
                resource_types=("resource-group",),
                identity=identity,
                http_client=client,
                started_at=datetime(2026, 10, 21, tzinfo=UTC),
            )
            batches = [batch async for batch in cast(Inventory, source.inventory).full_snapshot()]
            assert batches

    assert provider_calls == 2
    assert waits == []


async def test_equivalent_reads_within_one_generation_issue_duplicate_transport_requests() -> None:
    """Equivalent reads on the same source instance are not deduplicated; Finding 31 stays open."""

    provider_calls = 0
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": "arg",
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        if request.url.host == "identity.example.invalid":
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_on": 1_893_456_000}
            )
        provider_calls += 1
        return httpx.Response(
            200, json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        identity = ManagedIdentityWorkloadIdentity(
            http_client=client,
            config=ManagedIdentityWorkloadIdentityConfig(
                endpoint="https://identity.example.invalid/token",
                header="synthetic-header",
                client_id="00000000-0000-0000-0000-000000000001",
            ),
        )
        (source,) = build_sources(
            config=config,
            vocabulary=load_resource_type_registry(),
            resource_types=("resource-group",),
            identity=identity,
            http_client=client,
            started_at=datetime(2026, 10, 21, tzinfo=UTC),
        )
        first = [batch async for batch in cast(Inventory, source.inventory).full_snapshot()]
        second = [batch async for batch in cast(Inventory, source.inventory).full_snapshot()]

    assert first == second
    assert provider_calls == 2


async def test_unchanged_selector_promotes_without_independent_issuer_or_interval_witness() -> None:
    """Configured selector continuity does not attest whole-interval visibility (Finding 04)."""

    class InMemoryStore:
        def __init__(self) -> None:
            self.promoted: list[tuple[str, InventoryCoverageManifest]] = []

        async def begin(self, manifest: InventoryCoverageManifest) -> str:
            assert manifest.source == "arg"
            return "attempt-interval-residual"

        async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
            assert attempt_id == "attempt-interval-residual"
            assert not batch.final

        async def stage_chunk(
            self,
            attempt_id: str,
            batch: InventoryBatch,
            *,
            context_digest: str,
            sequence: int,
            previous_digest: str | None,
        ) -> Mapping[str, object]:
            return {
                "attempt_id": attempt_id,
                "context_digest": context_digest,
                "sequence": sequence,
                "previous_digest": previous_digest,
                "digest": "sha256:" + f"{sequence + 1:064x}",
                "cursor": batch.cursor,
            }

        async def read_chunk_checkpoint(
            self, attempt_id: str, *, context_digest: str
        ) -> Mapping[str, object] | None:
            return None

        def replay_chunks(
            self, attempt_id: str, *, context_digest: str
        ) -> AsyncIterator[InventoryBatch]:
            async def empty() -> AsyncIterator[InventoryBatch]:
                if attempt_id == context_digest:
                    yield InventoryBatch()

            return empty()

        async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
            self.promoted.append((attempt_id, manifest))

        async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
            raise AssertionError(f"unexpected failure for {attempt_id}: {failure}")

        async def active_snapshot_id(self) -> str | None:
            return self.promoted[-1][0] if self.promoted else None

    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": "arg",
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "identity.example.invalid":
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_on": 1_893_456_000}
            )
        return httpx.Response(
            200, json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
        )

    store = InMemoryStore()
    sealed_digests: list[str] = []

    async def prepare(
        source_manifest: InventoryCoverageManifest,
        manifest: InventoryCoverageManifest,
        observation: PromotedInventoryObservation,
    ) -> None:
        assert collection_context_digest(source_manifest)
        assert manifest.metadata.get("prepared_candidate_required") is True
        sealed_digests.append(postgres_inventory_prepared.candidate_graph_digest(observation))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        identity = ManagedIdentityWorkloadIdentity(
            http_client=client,
            config=ManagedIdentityWorkloadIdentityConfig(
                endpoint="https://identity.example.invalid/token",
                header="synthetic-header",
                client_id="00000000-0000-0000-0000-000000000001",
            ),
        )
        (source,) = build_sources(
            config=config,
            vocabulary=load_resource_type_registry(),
            resource_types=("resource-group",),
            identity=identity,
            http_client=client,
            started_at=datetime(2026, 10, 21, tzinfo=UTC),
        )
        result = await InventorySyncCoordinator(
            store=store,
            candidate_preparer=prepare,
            _isolated_requested_resource_types=True,
        ).run((source,))

    assert result.attempt_id == "attempt-interval-residual"
    assert len(sealed_digests) == 1
    assert len(store.promoted) == 1
    assert "provider_authorization" not in store.promoted[0][1].metadata

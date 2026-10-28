"""Production inventory seam keeps exact identity, time and failure dispositions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.resource_availability_evidence import ResourceOperationalState
from fdai.delivery.azure.resource_availability import (
    AZURE_AVAILABILITY_RESOURCE_TYPES,
    azure_resource_operational_state,
)
from fdai.delivery.resource_availability_inventory import (
    InventoryResourceAvailabilitySource,
    ResourceAvailabilityBinding,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
REF = "scope-example/resource-group/example/compute/example"
ARM = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/example/providers/Microsoft.Compute/virtualMachines/example"
)
BINDING = ResourceAvailabilityBinding(REF, "compute.vm", ARM, "scope-example")
RECORD = ResourceRecord(
    REF,
    "compute.vm",
    {"properties": {"extended": {"instanceView": {"powerState": {"code": "PowerState/running"}}}}},
    ARM,
    (NOW - timedelta(seconds=30)).isoformat(),
)


class Reader:
    revision = "example-snapshot"

    def __init__(self, record=RECORD, error=None):
        self.record = record
        self.error = error
        self.requests = []

    async def read_active_resources(self, *, resource_ids):
        self.requests.append(resource_ids)
        if self.error:
            raise self.error
        return self.revision, {REF: self.record} if self.record else {}


def _source(reader, **kwargs):
    return InventoryResourceAvailabilitySource(
        reader,
        bindings=(BINDING,),
        state_reader=azure_resource_operational_state,
        supported_resource_types=AZURE_AVAILABILITY_RESOURCE_TYPES,
        wall_clock=lambda: NOW,
        **kwargs,
    )


async def _observe(source):
    return await source.observe(resource_ref=REF, since=NOW - timedelta(minutes=5), until=NOW)


async def test_reads_real_inventory_protocol_and_preserves_observation_time() -> None:
    reader = Reader()
    observation = await _observe(_source(reader, expected_snapshot_id="example-snapshot"))
    assert reader.requests == [(REF,)]
    assert observation.state is ResourceOperationalState.RUNNING
    assert observation.observed_at == NOW - timedelta(seconds=30)
    assert observation.recorded_at == NOW
    assert observation.evidence_ref.startswith("inventory:example-snapshot:resource:")
    assert ARM not in observation.evidence_ref


@pytest.mark.parametrize(
    ("record", "status"),
    [
        (None, "resource_missing"),
        (replace(RECORD, provider_ref=ARM + "-another"), "identity_mismatch"),
        (replace(RECORD, type="mysql-server"), "identity_mismatch"),
        (replace(RECORD, resource_id="another-resource"), "identity_mismatch"),
        (replace(RECORD, props={"_truncated": True}), "observation_incomplete"),
    ],
)
async def test_invalid_inventory_never_supplies_a_positive_state(record, status) -> None:
    observation = await _observe(_source(Reader(record)))
    assert observation.unavailable_reason.value == status
    assert observation.state is ResourceOperationalState.UNKNOWN
    assert observation.observed_at is None


async def test_generation_changes_cannot_rebind_analyzer_identity() -> None:
    observation = await _observe(_source(Reader(), expected_snapshot_id="older-generation"))
    assert observation.unavailable_reason.value == "generation_changed"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError("private"), "authorization_denied"),
        (RuntimeError("private"), "source_unavailable"),
    ],
)
async def test_source_failures_are_bounded_and_do_not_leak_provider_messages(error, reason) -> None:
    observation = await _observe(_source(Reader(error=error)))
    assert observation.unavailable_reason.value == reason
    assert "private" not in repr(observation)


@pytest.mark.parametrize(
    ("kind", "props", "state"),
    [
        ("compute.vm", {"status": "PowerState/deallocated"}, "stopped"),
        ("compute.vm", {"properties": {"powerState": {"code": "PowerState/running"}}}, "running"),
        ("compute.vm", {"properties": {"provisioningState": "Succeeded"}}, "unknown"),
        ("compute.vm", {"status": "Unknown"}, "unknown"),
        ("compute.vm", {"status": "Stopped", "properties": {"powerState": "Running"}}, "unknown"),
        ("compute.vm-scale-set", {"status": "Succeeded"}, "unknown"),
        ("unclassified-resource", {"status": "Stopped"}, "unknown"),
        ("mysql-server", {"properties": {"state": "Ready"}}, "running"),
        ("mysql-server", {"properties": {"state": "Stopped"}}, "stopped"),
        ("network.application-gateway", {"properties": {"operationalState": "Stopped"}}, "stopped"),
        ("kubernetes-cluster", {"properties": {"powerState": {"code": "Stopped"}}}, "stopped"),
        ("compute.web-app", {"properties": {"state": "Running"}}, "running"),
        ("compute.container-app", {"properties": {"runningStatus": "Stopped"}}, "stopped"),
    ],
)
def test_reviewed_azure_operational_semantics_do_not_confuse_provisioning_health(
    kind, props, state
):
    assert azure_resource_operational_state(replace(RECORD, type=kind, props=props)).value == state


async def test_missing_last_seen_is_not_replaced_with_collection_time() -> None:
    observation = await _observe(_source(Reader(replace(RECORD, last_seen=None))))
    assert observation.observed_at is None


async def test_unsupported_type_is_not_polled() -> None:
    reader = Reader()
    source = InventoryResourceAvailabilitySource(
        reader,
        bindings=(replace(BINDING, resource_type="unclassified-resource"),),
        state_reader=azure_resource_operational_state,
        supported_resource_types=AZURE_AVAILABILITY_RESOURCE_TYPES,
    )
    observation = await _observe(source)
    assert not reader.requests
    assert observation.unavailable_reason.value == "unsupported_resource_type"


async def test_retained_state_timestamp_is_not_refreshed_by_resource_last_seen() -> None:
    state_time = NOW - timedelta(hours=1)
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="old-generation",
        effective_at=state_time,
        recorded_at=state_time,
        evidence_cutoff=state_time,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory:old-generation:state",),
    )
    record = replace(
        RECORD,
        props={
            **RECORD.props,
            STATE_FACT_METADATA_PROPERTY: {"state": metadata.to_mapping()},
        },
    )
    observation = await _observe(_source(Reader(record)))
    assert observation.observed_at == state_time
    assert observation.state_metadata == metadata


async def test_missing_active_snapshot_is_not_a_healthy_empty_inventory() -> None:
    reader = Reader()
    reader.revision = None
    observation = await _observe(_source(reader))
    assert observation.unavailable_reason.value == "source_unavailable"

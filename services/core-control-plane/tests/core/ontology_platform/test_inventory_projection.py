"""Coverage-honest projection of inventory observations into the resource subgraph."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.inventory_projection import (
    InventoryProjectionConflictError,
    build_inventory_ontology_projection,
)
from fdai.core.ontology_platform.pod_telemetry_evidence import (
    TelemetrySegmentStatus,
    evaluate_state_fact_metadata,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

OBSERVED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _resource(resource_id: str, *, type_id: str = "compute.vm", **props: str) -> ResourceRecord:
    return ResourceRecord(resource_id=resource_id, type=type_id, props=dict(props))


def _link(
    from_id: str,
    link_type: str,
    to_id: str,
    *,
    from_type: str = "compute.vm",
    to_type: str = "compute.vm",
) -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type=from_type,
        link_type=link_type,
        to_id=to_id,
        to_type=to_type,
        observation_metadata=_observation_metadata(),
    )


def _observation_metadata() -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision="revision-7",
            effective_at=OBSERVED_AT - timedelta(seconds=30),
            evidence_cutoff=OBSERVED_AT - timedelta(seconds=20),
            recorded_at=OBSERVED_AT,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("inventory-receipt-7",),
        ),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-3",
        verification_receipt_ref="verification-receipt-3",
        inventory_generation="snapshot-1",
        mapping_id="test.mapping",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="test-schema-v1",
        source_schema_digest="sha256:" + "2" * 64,
    )


def test_complete_observation_projects_typed_objects_and_links() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("rg-1", type_id="resource-group", name="group-one"),
            _resource("vm-1", name="vm-one", parent_id="rg-1"),
        ),
        links=(
            _link(
                "rg-1",
                "contains",
                "vm-1",
                from_type="resource-group",
                to_type="compute.vm",
            ),
        ),
    )

    assert projection.generation == "snapshot-1"
    assert [item.id for item in projection.objects] == ["rg-1", "vm-1"]
    assert all(item.object_type == "Resource" for item in projection.objects)
    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("contains", "rg-1", "vm-1")
    ]
    assert projection.complete is True
    assert projection.relationship_complete is True
    assert projection.dropped_reasons == ()

    vm = next(item for item in projection.objects if item.id == "vm-1")
    assert vm.properties["type"] == "compute.vm"
    assert vm.properties["name"] == "vm-one"
    assert vm.properties["parent_id"] == "rg-1"


def test_llm_deployment_projects_as_an_ontology_resource_instance() -> None:
    deployment_id = (
        "/subscriptions/example/resourcegroups/rg-example/providers/"
        "microsoft.cognitiveservices/accounts/ai-example/deployments/gpt-example"
    )
    endpoint_id = (
        "/subscriptions/example/resourcegroups/rg-example/providers/"
        "microsoft.cognitiveservices/accounts/ai-example"
    )
    projection = build_inventory_ontology_projection(
        generation="snapshot-llm-1",
        resources=(
            ResourceRecord(
                resource_id=deployment_id,
                type="llm-model-deployment",
                props={
                    "name": "gpt-example",
                    "parent_id": endpoint_id,
                    "model_name": "gpt-5.4",
                    "model_version": "2026-09-01",
                    "provisioning_state": "Succeeded",
                    "sku_name": "GlobalStandard",
                    "capacity_units": 50,
                    "current_capacity_units": 40,
                    "capacity_transitioning": True,
                    "capacity_tpm": 50_000,
                    "capacity_tpm_source": "properties.rateLimits",
                    "sku": {"name": "GlobalStandard", "capacity": 50},
                    "properties": {
                        "provisioningState": "Succeeded",
                        "model": {
                            "format": "OpenAI",
                            "name": "gpt-5.4",
                            "version": "2026-09-01",
                        },
                    },
                },
            ),
        ),
        links=(),
    )

    deployment = projection.objects[0]
    assert deployment.object_type == "Resource"
    assert deployment.properties["type"] == "llm-model-deployment"
    assert deployment.properties["name"] == "gpt-example"
    assert deployment.properties["parent_id"] == endpoint_id
    provider = deployment.properties["properties"]
    assert provider["model_name"] == "gpt-5.4"
    assert provider["model_version"] == "2026-09-01"
    assert provider["provisioning_state"] == "Succeeded"
    assert provider["sku_name"] == "GlobalStandard"
    assert provider["capacity_units"] == 50
    assert provider["current_capacity_units"] == 40
    assert provider["capacity_transitioning"] is True
    assert provider["capacity_tpm"] == 50_000
    assert provider["capacity_tpm_source"] == "properties.rateLimits"
    assert provider["properties"]["provisioningState"] == "Succeeded"
    assert provider["properties"]["model"]["name"] == "gpt-5.4"


def test_reviewed_resource_types_project_verified_classification_links() -> None:
    mapping_digest = "sha256:" + ("a" * 64)
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("rg-1", type_id="resource-group"),
            _resource("vm-1", type_id="compute.vm"),
        ),
        resource_type_mappings={
            "compute.vm": mapping_digest,
            "resource-group": mapping_digest,
        },
    )

    assert [(item.from_id, item.to_id) for item in projection.links] == [
        ("rg-1", "resource-group"),
        ("vm-1", "compute.vm"),
    ]
    assert all(item.link_type == "resource_classified_as" for item in projection.links)
    assert all(item.properties["verified"] is True for item in projection.links)
    assert all(item.properties["inventory_generation"] == "snapshot-1" for item in projection.links)
    assert projection.complete is True


def test_unmapped_resource_type_blocks_complete_classification_projection() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("unknown-1", type_id="unknown.resource"),),
        resource_type_mappings={"compute.vm": "sha256:" + ("a" * 64)},
    )

    assert projection.links == ()
    assert projection.complete is False
    assert projection.dropped_reasons == ("unmapped_resource_type",)


def test_classified_non_edge_preserves_promotable_generation_and_lowers_coverage() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"),),
        relationship_drops=(
            RelationshipDrop(
                reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT,
                mapping_id="azure.example-depends-on-target",
                unavailable_reason=(RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION),
            ),
        ),
    )

    assert projection.complete is True
    assert projection.relationship_complete is False
    assert projection.dropped_reasons == ("missing_target_endpoint",)


def test_link_observation_metadata_is_projected_canonically() -> None:
    metadata = _observation_metadata()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("rg-1", type_id="resource-group")),
        links=(
            LinkRecord(
                from_id="rg-1",
                from_type="resource-group",
                link_type="contains",
                to_id="vm-1",
                to_type="compute.vm",
                observation_metadata=metadata,
            ),
        ),
    )

    assert projection.links[0].properties[LINK_OBSERVATION_METADATA_PROPERTY] == (
        metadata.to_mapping()
    )


def test_resource_status_is_projected_as_observed_state_evidence() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider_properties = projection.objects[0].properties["properties"]
    assert provider_properties["state"] == "running"
    metadata = StateFactMetadata.from_mapping(provider_properties[STATE_FACT_METADATA_PROPERTY])
    assert metadata.lane is StateFactLane.OBSERVED
    assert metadata.source_revision == "snapshot-1"
    assert metadata.effective_at == OBSERVED_AT


@pytest.mark.parametrize(
    ("resource_type", "properties", "expected"),
    [
        ("compute.container-app", {"properties": {"runningStatus": "Running"}}, "Running"),
        (
            "network.application-gateway",
            {"properties": {"operationalState": "Started"}},
            "Started",
        ),
        (
            "network.dns-resolver",
            {"properties": {"dnsResolverState": "Connected"}},
            "Connected",
        ),
        ("disk", {"properties": {"diskState": "Reserved"}}, "Reserved"),
        (
            "disk-snapshot",
            {"properties": {"snapshotAccessState": "Available"}},
            "Available",
        ),
        (
            "network.private-dns-zone-link",
            {"properties": {"virtualNetworkLinkState": "Completed"}},
            "Completed",
        ),
        (
            "kubernetes-cluster",
            {"properties": {"powerState": {"code": "Stopped"}}},
            "Stopped",
        ),
    ],
)
def test_nested_operational_state_is_projected_with_observation_metadata(
    resource_type: str,
    properties: dict[str, object],
    expected: str,
) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="resource-1",
                type=resource_type,
                props=properties,
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider_properties = projection.objects[0].properties["properties"]
    assert provider_properties["state"] == expected
    metadata = StateFactMetadata.from_mapping(provider_properties[STATE_FACT_METADATA_PROPERTY])
    assert metadata.effective_at == OBSERVED_AT


def test_resource_health_availability_metadata_reaches_ontology_instance() -> None:
    health_metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="azure-resource-health",
        source_revision="azure-resource-health:sha256:" + "1" * 64,
        effective_at=OBSERVED_AT,
        recorded_at=OBSERVED_AT,
        evidence_cutoff=OBSERVED_AT,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("azure-resource-health:sha256:" + "1" * 64,),
    )
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="workspace-1",
                type="log-workspace",
                props={
                    "status": "Running",
                    "availabilityState": "Available",
                    "state_fact_metadata": {
                        "availabilityState": health_metadata.to_mapping(),
                    },
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert provider["availabilityState"] == "Available"
    assert "state" not in provider
    assert (
        StateFactMetadata.from_mapping(provider["state_fact_metadata"]["availabilityState"])
        == health_metadata
    )


@pytest.mark.parametrize(
    "resource_type",
    ["application-insights", "log-workspace", "resource-group"],
)
def test_not_applicable_resource_types_do_not_create_operational_state(
    resource_type: str,
) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id=f"{resource_type}-1",
                type=resource_type,
                props={
                    "status": "Running",
                    "state": "Running",
                    STATE_FACT_METADATA_PROPERTY: _observation_metadata().state_fact.to_mapping(),
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert "state" not in provider
    assert STATE_FACT_METADATA_PROPERTY not in provider


@pytest.mark.parametrize("state", ["Running\nsecret", "x" * 257])
def test_invalid_operational_values_do_not_create_verified_facts(state: str) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="function-1",
                type="compute.function",
                props={"state": state},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert STATE_FACT_METADATA_PROPERTY not in provider


def test_operational_cleanup_preserves_keyed_availability_metadata() -> None:
    metadata = _observation_metadata().state_fact.to_mapping()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="workspace-1",
                type="log-workspace",
                props={
                    "status": "Running",
                    "availabilityState": "Available",
                    STATE_FACT_METADATA_PROPERTY: {
                        "status": metadata,
                        "properties.status": metadata,
                        "availabilityState": metadata,
                    },
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert "state" not in provider
    assert provider[STATE_FACT_METADATA_PROPERTY] == {"availabilityState": metadata}


def test_projection_removes_metadata_for_unreviewed_resource_type_paths() -> None:
    metadata = _observation_metadata().state_fact.to_mapping()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="function-1",
                type="compute.function",
                props={
                    "state": "Running",
                    "properties": {
                        STATE_FACT_METADATA_PROPERTY: {"status": metadata},
                    },
                    STATE_FACT_METADATA_PROPERTY: {
                        "state": metadata,
                        "status": metadata,
                    },
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert set(provider[STATE_FACT_METADATA_PROPERTY]) == {"state"}
    assert STATE_FACT_METADATA_PROPERTY not in provider["properties"]


def test_root_metadata_without_an_allowlisted_value_is_removed() -> None:
    metadata = _observation_metadata().state_fact.to_mapping()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="function-1",
                type="compute.function",
                props={
                    "status": "Running",
                    STATE_FACT_METADATA_PROPERTY: {"status": metadata},
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert STATE_FACT_METADATA_PROPERTY not in provider


def test_allowed_nested_flat_metadata_is_preserved_without_snapshot_time() -> None:
    metadata = _observation_metadata().state_fact.to_mapping()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="event-hub-1",
                type="event-hub",
                props={
                    "properties": {
                        "status": "Active",
                        STATE_FACT_METADATA_PROPERTY: metadata,
                    },
                },
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert provider["properties"][STATE_FACT_METADATA_PROPERTY] == metadata


@pytest.mark.parametrize(
    ("resource_type", "properties", "expected"),
    [
        (
            "compute.function",
            {"status": "Running", "state": "Stopped"},
            "Stopped",
        ),
        (
            "compute.vm",
            {
                "status": "Running",
                "state": "Started",
                "properties": {"powerState": {"code": "PowerState/deallocated"}},
            },
            "PowerState/deallocated",
        ),
    ],
)
def test_operational_state_uses_only_resource_type_paths(
    resource_type: str,
    properties: dict[str, object],
    expected: str,
) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id=f"{resource_type}-1",
                type=resource_type,
                props=properties,
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert provider["state"] == expected


def test_unrelated_property_conflict_does_not_qualify_operational_state() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running", "status": "first"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running", "status": "second"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider[STATE_FACT_METADATA_PROPERTY])
    assert provider["state"] == "running"
    assert metadata.conflicts == ()
    assert metadata.completeness == 1.0


def test_unrelated_nested_conflict_preserves_agreed_operational_state() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={
                    "properties": {
                        "powerState": {"code": "PowerState/running"},
                        "hardwareProfile": "first",
                    }
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={
                    "properties": {
                        "powerState": {"code": "PowerState/running"},
                        "hardwareProfile": "second",
                    }
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider[STATE_FACT_METADATA_PROPERTY])
    assert provider["state"] == "PowerState/running"
    assert metadata.conflicts == ()
    assert metadata.completeness == 1.0


def test_ontology_uses_only_exact_declared_operational_paths() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="function-1",
                type="compute.function",
                props={"state": {"code": "Running"}},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    assert STATE_FACT_METADATA_PROPERTY not in provider


def test_operational_state_preserves_provider_identity_conflicts() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                provider_ref="provider/vm-1/a",
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                provider_ref="provider/vm-1/b",
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider[STATE_FACT_METADATA_PROPERTY])
    assert metadata.conflicts == ("observed_provider_ref_conflict",)
    assert metadata.completeness == 0.0


def test_non_operational_resource_rejects_unrepresentable_identity_conflict() -> None:
    with pytest.raises(InventoryProjectionConflictError, match="no applicable operational state"):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(
                ResourceRecord(
                    resource_id="application-insights-1",
                    type="application-insights",
                    props={"status": "Running"},
                    provider_ref="provider/application-insights-1/a",
                    last_seen=OBSERVED_AT.isoformat(),
                ),
                ResourceRecord(
                    resource_id="application-insights-1",
                    type="application-insights",
                    props={"status": "Running"},
                    provider_ref="provider/application-insights-1/b",
                    last_seen=OBSERVED_AT.isoformat(),
                ),
            ),
        )


def test_nested_operational_state_conflict_stays_incomplete() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="node-pool-1",
                type="kubernetes-node-pool",
                props={"properties": {"powerState": {"code": "Running"}}},
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="node-pool-1",
                type="kubernetes-node-pool",
                props={"properties": {"powerState": {"code": "Stopped"}}},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider[STATE_FACT_METADATA_PROPERTY])
    assert metadata.conflicts == ("observed_property_conflict:powerState",)
    assert metadata.completeness == 0.0
    assert "state" not in provider


def test_conflicting_values_across_declared_paths_stay_incomplete() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={
                    "powerState": "Running",
                    "properties": {"powerState": {"code": "Started"}},
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={
                    "powerState": "Running",
                    "properties": {"powerState": {"code": "Stopped"}},
                },
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider[STATE_FACT_METADATA_PROPERTY])
    assert metadata.conflicts == ("observed_property_conflict:powerState",)
    assert metadata.completeness == 0.0
    assert "state" not in provider


def test_snapshot_relationship_evidence_is_not_projected_as_provider_properties() -> None:
    link = LinkRecord(
        from_id="vm-1",
        from_type="compute.vm",
        link_type="depends_on",
        to_id="vm-2",
        to_type="compute.vm",
        link_props={
            "kind": "runtime",
            "provider_relationship_evidence": {
                "mapping_id": "mapping-1",
                "mapping_revision": "revision-1",
            },
        },
        observation_metadata=_observation_metadata(),
    )

    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(link,),
    )

    assert projection.links[0].properties["kind"] == "runtime"
    assert "provider_relationship_evidence" not in projection.links[0].properties


def test_incomplete_observation_claims_no_relationship() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("rg-1", type_id="resource-group")),
        links=(
            _link(
                "rg-1",
                "contains",
                "vm-1",
                from_type="resource-group",
                to_type="compute.vm",
            ),
        ),
        observation_complete=False,
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "observation_incomplete" in projection.dropped_reasons


def test_unregistered_link_type_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(_link("vm-1", "unknown_network_link", "vm-2"),),
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "unregistered_link_type" in projection.dropped_reasons


@pytest.mark.parametrize(
    "link_type",
    (
        "kubernetes_scheduled_on",
        "kubernetes_backed_by",
        "kubernetes_owned_by",
        "kubernetes_selects",
        "kubernetes_exposes_endpoints",
        "kubernetes_exposes_endpoint_slice",
    ),
)
def test_catalog_declared_kubernetes_links_are_projected(link_type: str) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("resource-1"), _resource("resource-2")),
        links=(_link("resource-1", link_type, "resource-2"),),
    )

    assert [item.link_type for item in projection.links] == [link_type]
    assert projection.complete is True
    assert projection.relationship_complete is True
    assert projection.dropped_reasons == ()


def test_catalog_declared_network_links_are_projected_as_directed_records() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("nic-1", type_id="network.nic"),
            _resource("route-1", type_id="network.route"),
            _resource("vnet-1", type_id="network.vnet"),
            _resource("vnet-2", type_id="network.vnet"),
        ),
        links=(
            _link(
                "nic-1",
                "routes_to",
                "route-1",
                from_type="network.nic",
                to_type="network.route",
            ),
            _link(
                "vnet-1",
                "peered_with",
                "vnet-2",
                from_type="network.vnet",
                to_type="network.vnet",
            ),
            _link(
                "vnet-2",
                "peered_with",
                "vnet-1",
                from_type="network.vnet",
                to_type="network.vnet",
            ),
        ),
    )

    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("peered_with", "vnet-1", "vnet-2"),
        ("peered_with", "vnet-2", "vnet-1"),
        ("routes_to", "nic-1", "route-1"),
    ]


@pytest.mark.parametrize(
    ("resources", "links", "expected_reason"),
    (
        (
            (_resource("vm-1"),),
            (
                _link(
                    "rg-missing",
                    "contains",
                    "vm-1",
                    from_type="resource-group",
                    to_type="compute.vm",
                ),
            ),
            "missing_source_endpoint",
        ),
        (
            (_resource("rg-1", type_id="resource-group"),),
            (
                _link(
                    "rg-1",
                    "contains",
                    "vm-missing",
                    from_type="resource-group",
                    to_type="compute.vm",
                ),
            ),
            "missing_target_endpoint",
        ),
    ),
)
def test_unobserved_endpoint_is_dropped_and_reported(
    resources: tuple[ResourceRecord, ...],
    links: tuple[LinkRecord, ...],
    expected_reason: str,
) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=resources,
        links=links,
    )

    assert projection.links == ()
    assert projection.complete is False
    assert expected_reason in projection.dropped_reasons


def test_self_reference_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"),),
        links=(_link("vm-1", "contains", "vm-1"),),
    )

    assert projection.links == ()
    assert "self_reference" in projection.dropped_reasons


def test_repeated_identical_observation_is_idempotent() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1", name="vm-one"), _resource("vm-1", name="vm-one")),
        links=(_link("vm-1", "contains", "vm-1"),) * 0,
    )

    assert [item.id for item in projection.objects] == ["vm-1"]


def test_conflicting_observation_for_one_id_becomes_an_explicit_state_conflict() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running", "name": "vm-one"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "deallocated", "name": "vm-one"},
                last_seen=(OBSERVED_AT + timedelta(seconds=5)).isoformat(),
            ),
        ),
    )

    provider_properties = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider_properties[STATE_FACT_METADATA_PROPERTY])
    assert metadata.conflicts == ("observed_property_conflict:powerState",)
    assert metadata.completeness == 0.0
    assert metadata.synthetic is False
    assert metadata.effective_at == OBSERVED_AT
    assert "state" not in provider_properties
    assert provider_properties["name"] == "vm-one"


def test_conflicting_observed_type_for_one_id_is_rejected() -> None:
    with pytest.raises(InventoryProjectionConflictError, match="conflicting type"):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(
                _resource("vm-1", type_id="compute.vm"),
                _resource("vm-1", type_id="network.nic"),
            ),
        )


def test_repeated_observation_differing_only_by_clock_read_is_not_a_conflict() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                last_seen=(OBSERVED_AT + timedelta(seconds=9)).isoformat(),
            ),
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
    )

    provider_properties = projection.objects[0].properties["properties"]
    metadata = StateFactMetadata.from_mapping(provider_properties[STATE_FACT_METADATA_PROPERTY])
    assert metadata.conflicts == ()
    assert metadata.completeness == 1.0
    assert provider_properties["state"] == "running"
    assert metadata.effective_at == OBSERVED_AT


def test_conflicting_observation_demotes_the_existing_state_evidence_consumer() -> None:
    def project(second_status: str) -> StateFactMetadata:
        projection = build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(
                ResourceRecord(
                    resource_id="vm-1",
                    type="compute.vm",
                    props={"powerState": "running"},
                    last_seen=OBSERVED_AT.isoformat(),
                ),
                ResourceRecord(
                    resource_id="vm-1",
                    type="compute.vm",
                    props={"powerState": second_status},
                    last_seen=OBSERVED_AT.isoformat(),
                ),
            ),
        )
        nested = projection.objects[0].properties["properties"]
        return StateFactMetadata.from_mapping(nested[STATE_FACT_METADATA_PROPERTY])

    agreed_status, agreed_reasons = evaluate_state_fact_metadata(
        project("running"),
        cutoff=OBSERVED_AT,
    )
    assert agreed_status is TelemetrySegmentStatus.VERIFIED
    assert agreed_reasons == ()

    contested_status, contested_reasons = evaluate_state_fact_metadata(
        project("deallocated"),
        cutoff=OBSERVED_AT,
    )
    assert contested_status is TelemetrySegmentStatus.UNVERIFIED
    assert "state_evidence_conflict:observed_property_conflict:powerState" in contested_reasons


def test_conflicting_duplicate_link_is_absent_and_reported() -> None:
    metadata = _observation_metadata()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(
            LinkRecord(
                "vm-1",
                "compute.vm",
                "depends_on",
                "vm-2",
                "compute.vm",
                observation_metadata=metadata,
            ),
            LinkRecord(
                "vm-1",
                "compute.vm",
                "depends_on",
                "vm-2",
                "compute.vm",
                link_props={"observation": "different"},
                observation_metadata=metadata,
            ),
        ),
    )

    assert projection.links == ()
    assert "conflicting_duplicate" in projection.dropped_reasons


def test_reciprocal_runtime_calls_preserve_both_directional_observations() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("service-a"), _resource("service-b")),
        links=(
            _link("service-a", "runtime_calls", "service-b"),
            _link("service-b", "runtime_calls", "service-a"),
        ),
    )

    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("runtime_calls", "service-a", "service-b"),
        ("runtime_calls", "service-b", "service-a"),
    ]
    assert projection.complete is True
    assert projection.relationship_complete is True
    assert projection.dropped_reasons == ()


def test_link_endpoint_types_must_match_observed_resource_types() -> None:
    with pytest.raises(InventoryProjectionConflictError, match="endpoint type"):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(
                _resource("nic-1", type_id="network.nic"),
                _resource("route-1", type_id="network.route"),
            ),
            links=(
                _link(
                    "nic-1",
                    "routes_to",
                    "route-1",
                    from_type="network.vnet",
                    to_type="network.route",
                ),
            ),
        )


def test_generation_is_required() -> None:
    with pytest.raises(ValueError, match="generation"):
        build_inventory_ontology_projection(generation="  ", resources=(_resource("vm-1"),))


def test_observed_state_uses_the_declared_refresh_cadence() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            ResourceRecord(
                resource_id="vm-1",
                type="compute.vm",
                props={"powerState": "running"},
                last_seen=OBSERVED_AT.isoformat(),
            ),
        ),
        freshness_ceiling_seconds=21_600,
    )

    state_fact = projection.objects[0].properties["properties"][STATE_FACT_METADATA_PROPERTY]
    assert state_fact["freshness_ceiling_seconds"] == 21_600


def test_projection_rejects_non_positive_freshness_ceiling() -> None:
    with pytest.raises(ValueError, match="freshness ceiling"):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(),
            freshness_ceiling_seconds=0,
        )


def test_a_contested_resource_without_an_observation_time_fails_closed() -> None:
    """The conflict travels on the state fact, which needs a time; silence would read as clean."""
    records = (
        ResourceRecord(
            resource_id="vm-1", type="compute.vm", props={"status": "running", "sku": "A"}
        ),
        ResourceRecord(
            resource_id="vm-1", type="compute.vm", props={"status": "running", "sku": "B"}
        ),
    )

    with pytest.raises(InventoryProjectionConflictError, match="no observation time"):
        build_inventory_ontology_projection(resources=records, links=(), generation="gen-1")


def test_an_agreeing_resource_without_an_observation_time_still_projects() -> None:
    records = (
        ResourceRecord(resource_id="vm-1", type="compute.vm", props={"status": "running"}),
        ResourceRecord(resource_id="vm-1", type="compute.vm", props={"status": "running"}),
    )

    projection = build_inventory_ontology_projection(
        resources=records, links=(), generation="gen-1"
    )

    resource = next(item for item in projection.objects if item.id == "vm-1")
    assert STATE_FACT_METADATA_PROPERTY not in resource.properties["properties"]

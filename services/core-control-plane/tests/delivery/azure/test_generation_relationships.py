"""Complete-generation Azure relationship projection tests."""

from pathlib import Path

from fdai.delivery.azure.arg_projection import (
    arm_id_to_type,
    build_arm_to_neutral_map,
    to_neutral_id,
)
from fdai.delivery.azure.arg_relationships import project_provider_relationships
from fdai.delivery.azure.generation_relationships import (
    project_complete_generation_relationships,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.shared.providers.inventory import RelationshipDropReason, ResourceRecord

CATALOG_ROOT = Path("rule-catalog/vocabulary/provider-relationship-mappings")
RESOURCE_TYPES = Path("rule-catalog/vocabulary/resource-types.yaml")
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


def _resource(
    name: str,
    resource_type: str,
    arm_type: str,
    properties: dict[str, object],
) -> ResourceRecord:
    provider_ref = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example/providers/{arm_type}/{name}"
    )
    return ResourceRecord(
        resource_id=to_neutral_id(provider_ref),
        type=resource_type,
        provider_ref=provider_ref,
        props={"providerType": arm_type, "properties": properties},
        last_seen="2026-08-23T00:00:00Z",
    )


def _resource_group(name: str, *, subscription: str = SUBSCRIPTION) -> ResourceRecord:
    provider_ref = f"/subscriptions/{subscription}/resourceGroups/{name}"
    return ResourceRecord(
        resource_id=to_neutral_id(provider_ref),
        type="resource-group",
        provider_ref=provider_ref,
        props={"providerType": "Microsoft.Resources/resourceGroups", "name": name},
        last_seen="2026-08-23T00:00:00Z",
    )


def _project(resources: tuple[ResourceRecord, ...]):
    registry = load_resource_type_registry_from_mapping(
        __import__("yaml").safe_load(RESOURCE_TYPES.read_text(encoding="utf-8"))
    )
    return project_complete_generation_relationships(
        resources,
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        arm_to_neutral=build_arm_to_neutral_map(registry),
        arm_id_to_type=arm_id_to_type,
        to_neutral_id=to_neutral_id,
    )


def test_complete_generation_projects_aks_node_resource_group() -> None:
    node_group = _resource_group("rg-aks-nodes-example")
    cluster = _resource(
        "aks-example",
        "kubernetes-cluster",
        "Microsoft.ContainerService/managedClusters",
        {"nodeResourceGroup": "rg-aks-nodes-example"},
    )

    result = _project((cluster, node_group))

    assert [
        (
            link.mapping_evidence.mapping_id if link.mapping_evidence is not None else None,
            link.from_id,
            link.link_type,
            link.to_id,
        )
        for link in result.links
    ] == [
        (
            "azure.aks-attached-to-node-resource-group",
            cluster.resource_id,
            "attached_to",
            node_group.resource_id,
        )
    ]
    assert result.dropped == ()


def test_complete_generation_does_not_guess_ambiguous_aks_node_resource_group() -> None:
    first_group = _resource_group("rg-aks-nodes-example")
    second_group = _resource_group(
        "rg-aks-nodes-example",
        subscription="00000000-0000-0000-0000-000000000004",
    )
    cluster = _resource(
        "aks-example",
        "kubernetes-cluster",
        "Microsoft.ContainerService/managedClusters",
        {"nodeResourceGroup": "rg-aks-nodes-example"},
    )

    result = _project((cluster, first_group, second_group))

    assert result.links == ()
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        (
            "azure.aks-attached-to-node-resource-group",
            RelationshipDropReason.UNRESOLVED_REFERENCE,
        )
    ]


def test_complete_generation_projects_unique_registry_workspace_and_endpoint_aliases() -> None:
    communication = _resource(
        "communication-example",
        "communication-service",
        "Microsoft.Communication/communicationServices",
        {"hostName": "communication-example.example.communication.azure.com"},
    )
    registry = _resource(
        "registry-example",
        "container-registry",
        "Microsoft.ContainerRegistry/registries",
        {"loginServer": "registry-example.azurecr.io"},
    )
    workspace = _resource(
        "workspace-example",
        "log-workspace",
        "Microsoft.OperationalInsights/workspaces",
        {"customerId": "00000000-0000-0000-0000-000000000002"},
    )
    database = _resource(
        "database-example",
        "postgresql-server",
        "Microsoft.DBforPostgreSQL/flexibleServers",
        {"fullyQualifiedDomainName": "database-example.postgres.database.azure.com"},
    )
    function = _resource(
        "function-example",
        "compute.function",
        "Microsoft.Web/sites",
        {"defaultHostName": "function-example.azurewebsites.net"},
    )
    environment = _resource(
        "environment-example",
        "compute.container-app-environment",
        "Microsoft.App/managedEnvironments",
        {
            "appLogsConfiguration": {
                "logAnalyticsConfiguration": {"customerId": "00000000-0000-0000-0000-000000000002"}
            }
        },
    )
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {
            "configuration": {"registries": [{"server": "registry-example.azurecr.io"}]},
            "template": {
                "containers": [
                    {
                        "env": [
                            {
                                "value": (
                                    "https://communication-example.example.communication.azure.com"
                                )
                            },
                            {"value": "https://database-example.postgres.database.azure.com/api"},
                            {"value": "https://function-example.azurewebsites.net/api"},
                            {"value": "00000000-0000-0000-0000-000000000002"},
                            {"value": "[malformed"},
                        ]
                    }
                ]
            },
        },
    )

    result = _project((app, communication, database, environment, function, registry, workspace))

    edges = {
        (
            link.mapping_evidence.mapping_id if link.mapping_evidence is not None else None,
            link.from_id,
            link.to_id,
        )
        for link in result.links
    }
    assert (
        "azure.container-workload-depends-on-registry",
        app.resource_id,
        registry.resource_id,
    ) in edges
    assert (
        "azure.container-workload-depends-on-configured-endpoint",
        app.resource_id,
        communication.resource_id,
    ) in edges
    assert (
        "azure.container-workload-depends-on-configured-endpoint",
        app.resource_id,
        database.resource_id,
    ) in edges
    assert (
        "azure.container-workload-depends-on-configured-endpoint",
        app.resource_id,
        function.resource_id,
    ) in edges
    assert (
        "azure.container-workload-depends-on-configured-endpoint",
        app.resource_id,
        workspace.resource_id,
    ) in edges
    assert (
        "azure.container-environment-depends-on-log-workspace",
        environment.resource_id,
        workspace.resource_id,
    ) in edges
    assert result.dropped == ()


def test_complete_generation_projects_exact_key_vault_secret_reference() -> None:
    vault = _resource(
        "vault-example",
        "secret-store",
        "Microsoft.KeyVault/vaults",
        {"vaultUri": "https://vault-example.vault.azure.net/"},
    )
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {
            "configuration": {
                "secrets": [
                    {
                        "keyVaultUrl": (
                            "https://vault-example.vault.azure.net/secrets/database-dsn/version"
                        )
                    }
                ]
            }
        },
    )

    result = _project((app, vault))

    assert [
        (
            link.mapping_evidence.mapping_id if link.mapping_evidence is not None else None,
            link.from_id,
            link.link_type,
            link.to_id,
        )
        for link in result.links
    ] == [
        (
            "azure.container-workload-depends-on-key-vault-secret",
            app.resource_id,
            "depends_on",
            vault.resource_id,
        )
    ]


def test_complete_generation_projects_role_assignment_principal() -> None:
    principal_id = "00000000-0000-0000-0000-000000000003"
    identity = _resource(
        "identity-example",
        "managed-identity",
        "Microsoft.ManagedIdentity/userAssignedIdentities",
        {"principalId": principal_id},
    )
    assignment = _resource(
        "assignment-example",
        "authorization.role-assignment",
        "Microsoft.Authorization/roleAssignments",
        {"principalId": principal_id},
    )

    result = _project((assignment, identity))

    assert [
        (
            link.mapping_evidence.mapping_id if link.mapping_evidence is not None else None,
            link.from_id,
            link.link_type,
            link.to_id,
        )
        for link in result.links
    ] == [
        (
            "azure.role-assignment-attached-to-managed-identity",
            assignment.resource_id,
            "attached_to",
            identity.resource_id,
        )
    ]


def test_complete_generation_projects_role_assignment_scope_from_observed_type() -> None:
    function = _resource(
        "function-example",
        "compute.function",
        "Microsoft.Web/sites",
        {},
    )
    assignment = _resource(
        "assignment-example",
        "authorization.role-assignment",
        "Microsoft.Authorization/roleAssignments",
        {"scope": function.provider_ref},
    )

    result = _project((assignment, function))

    assert [
        (
            link.mapping_evidence.mapping_id if link.mapping_evidence is not None else None,
            link.from_id,
            link.link_type,
            link.to_id,
            link.to_type,
        )
        for link in result.links
    ] == [
        (
            "azure.role-assignment-attached-to-scope",
            assignment.resource_id,
            "attached_to",
            function.resource_id,
            function.type,
        )
    ]


def test_complete_generation_does_not_resolve_ambiguous_aliases() -> None:
    first = _resource(
        "registry-one",
        "container-registry",
        "Microsoft.ContainerRegistry/registries",
        {"loginServer": "shared.azurecr.io"},
    )
    second = _resource(
        "registry-two",
        "container-registry",
        "Microsoft.ContainerRegistry/registries",
        {"loginServer": "shared.azurecr.io"},
    )
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {"configuration": {"registries": [{"server": "shared.azurecr.io"}]}},
    )

    result = _project((app, first, second))

    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {RelationshipDropReason.UNRESOLVED_REFERENCE}


def test_complete_generation_preserves_distinct_unresolved_reference_counts() -> None:
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {
            "template": {
                "containers": [
                    {
                        "env": [
                            {"value": "https://missing-one.example/api"},
                            {"value": "https://missing-two.example/api"},
                        ]
                    }
                ]
            }
        },
    )

    result = _project((app,))
    drops = [
        drop
        for drop in result.dropped
        if drop.mapping_id == "azure.container-workload-depends-on-configured-endpoint"
    ]

    assert [drop.reason for drop in drops] == [
        RelationshipDropReason.UNRESOLVED_REFERENCE,
        RelationshipDropReason.UNRESOLVED_REFERENCE,
    ]


def test_complete_generation_ignores_non_reference_environment_values() -> None:
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {
            "template": {
                "containers": [
                    {
                        "env": [
                            {"value": "true"},
                            {"value": "42"},
                            {"value": "plain-token"},
                            {"value": "00000000-0000-0000-0000-000000000099"},
                            {"value": '{"enabled":true}'},
                            {"value": "Key=Value;Other=Value"},
                        ]
                    }
                ]
            }
        },
    )

    result = _project((app,))

    assert result.links == ()
    assert result.dropped == ()


def test_per_row_projection_defers_complete_generation_aliases() -> None:
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {"template": {"containers": [{"env": [{"value": "https://unknown.example/api"}]}]}},
    )
    registry = load_resource_type_registry_from_mapping(
        __import__("yaml").safe_load(RESOURCE_TYPES.read_text(encoding="utf-8"))
    )

    result = project_provider_relationships(
        {"type": "Microsoft.App/containerApps", **app.props},
        owner=app,
        arm_to_neutral=build_arm_to_neutral_map(registry),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        arm_id_to_type=arm_id_to_type,
        to_neutral_id=to_neutral_id,
        source_identity="azure-resource-graph",
    )

    assert result.links == ()
    assert result.dropped == ()


def test_per_row_projection_keeps_unresolved_arm_id_gap() -> None:
    app = _resource(
        "app-example",
        "compute.container-app",
        "Microsoft.App/containerApps",
        {
            "template": {
                "containers": [
                    {
                        "env": [
                            {
                                "value": (
                                    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example/"
                                    "providers/Microsoft.Example/widgets/widget-example"
                                )
                            }
                        ]
                    }
                ]
            }
        },
    )
    registry = load_resource_type_registry_from_mapping(
        __import__("yaml").safe_load(RESOURCE_TYPES.read_text(encoding="utf-8"))
    )

    result = project_provider_relationships(
        {"type": "Microsoft.App/containerApps", **app.props},
        owner=app,
        arm_to_neutral=build_arm_to_neutral_map(registry),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        arm_id_to_type=arm_id_to_type,
        to_neutral_id=to_neutral_id,
        source_identity="azure-resource-graph",
    )

    assert result.links == ()
    assert [drop.mapping_id for drop in result.dropped] == [
        "azure.container-workload-depends-on-arm-resource"
    ]

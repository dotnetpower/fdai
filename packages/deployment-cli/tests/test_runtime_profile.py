from __future__ import annotations

import pytest

from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def test_container_apps_profile_preserves_the_existing_default() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )

    assert profile.to_mapping() == {
        "schema_version": "fdai.runtime-deployment-profile.v2",
        "runtime_platform": "container-apps",
        "database_placement": "postgres-flex",
        "system_node_count": 3,
        "system_node_sku": "Standard_D2as_v5",
        "user_node_min_count": 3,
        "user_node_max_count": 5,
        "user_node_sku": "Standard_D4as_v5",
        "product_profile": {
            "schema_version": "fdai.product-profile.v1",
            "name": "observation-first",
            "add_ons": [],
            "observation_permissions": {
                "base_role": "Reader",
                "selected_sources": [],
            },
            "authority_granted": False,
        },
    }
    assert len(profile.digest) == 64


@pytest.mark.parametrize(
    ("database", "user_nodes"),
    (("postgres-flex", 3), ("postgres-aks", 4)),
)
def test_aks_profile_accepts_supported_node_floors(database: str, user_nodes: int) -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement=database,
        system_node_count=2,
        user_node_min_count=user_nodes,
        user_node_max_count=user_nodes,
    )

    assert profile.runtime_platform.value == "aks"
    assert profile.system_node_sku == "Standard_D4as_v5"
    assert profile.user_node_min_count == user_nodes


@pytest.mark.parametrize(
    ("runtime", "database", "system_nodes", "user_min", "user_max", "message"),
    (
        ("container-apps", "postgres-aks", 3, 4, 5, "requires postgres-flex"),
        ("aks", "postgres-flex", 1, 3, 5, "system node count"),
        ("aks", "postgres-flex", 2, 2, 5, "user node minimum"),
        ("aks", "postgres-aks", 2, 3, 5, "user node minimum"),
        ("aks", "postgres-flex", 2, 4, 3, "user node maximum"),
    ),
)
def test_runtime_profile_rejects_unsafe_combinations(
    runtime: str,
    database: str,
    system_nodes: int,
    user_min: int,
    user_max: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RuntimeDeploymentProfile.create(
            runtime_platform=runtime,
            database_placement=database,
            system_node_count=system_nodes,
            user_node_min_count=user_min,
            user_node_max_count=user_max,
        )


@pytest.mark.parametrize("field", ("runtime", "database"))
def test_runtime_profile_rejects_unknown_choices(field: str) -> None:
    values = {
        "runtime_platform": "unknown" if field == "runtime" else "aks",
        "database_placement": "unknown" if field == "database" else "postgres-flex",
    }

    with pytest.raises(ValueError, match="unsupported"):
        RuntimeDeploymentProfile.create(**values)


def test_runtime_profile_requires_explicit_complete_add_on_selection() -> None:
    with pytest.raises(ValueError, match="Console currently requires"):
        RuntimeDeploymentProfile.create(
            runtime_platform="aks",
            database_placement="postgres-flex",
            product_add_ons=("read-only-console",),
        )
    with pytest.raises(ValueError, match="governed execution currently requires"):
        RuntimeDeploymentProfile.create(
            runtime_platform="aks",
            database_placement="postgres-flex",
            product_add_ons=("governed-execution",),
        )


def test_runtime_profile_preserves_explicit_full_product_behavior() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        product_add_ons=(
            "read-only-console",
            "notifications",
            "governed-execution",
            "enterprise-identity-governance",
        ),
        observation_data_sources=(
            "azure-monitor",
            "log-analytics",
        ),
    )

    assert tuple(item.value for item in profile.product_profile.add_ons) == (
        "enterprise-identity-governance",
        "governed-execution",
        "notifications",
        "read-only-console",
    )
    assert profile.product_profile.authority_granted is False


def test_runtime_profile_reads_legacy_mapping_as_explicit_full_product() -> None:
    legacy = {
        "schema_version": "fdai.runtime-deployment-profile.v1",
        "runtime_platform": "aks",
        "database_placement": "postgres-flex",
        "system_node_count": 3,
        "system_node_sku": "Standard_D4as_v5",
        "user_node_min_count": 3,
        "user_node_max_count": 5,
        "user_node_sku": "Standard_D4as_v5",
    }

    profile = RuntimeDeploymentProfile.from_mapping(legacy)

    assert profile.matches_mapping(legacy) is True
    assert len(profile.product_profile.add_ons) == 4
    assert profile.product_profile.authority_granted is False


def test_postgres_aks_accepts_console_after_in_cluster_ingestion_dsns_exist() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-aks",
        user_node_min_count=4,
        product_add_ons=(
            "read-only-console",
            "notifications",
            "governed-execution",
            "enterprise-identity-governance",
        ),
    )
    headless = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-aks",
        user_node_min_count=4,
    )

    assert profile.console_selected is True
    assert headless.console_selected is False

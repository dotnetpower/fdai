from __future__ import annotations

import pytest

from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def test_container_apps_profile_preserves_the_existing_default() -> None:
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )

    assert profile.to_mapping() == {
        "schema_version": "fdai.runtime-deployment-profile.v1",
        "runtime_platform": "container-apps",
        "database_placement": "postgres-flex",
        "system_node_count": 3,
        "system_node_sku": "Standard_D2as_v5",
        "user_node_min_count": 3,
        "user_node_max_count": 5,
        "user_node_sku": "Standard_D4as_v5",
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

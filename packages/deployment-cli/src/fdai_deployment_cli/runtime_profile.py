"""Validate and seal the runtime substrate selected for a new deployment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai_deployment_cli.contracts import canonical_digest


class RuntimePlatform(StrEnum):
    """Supported Azure runtime substrates for a new FDAI installation."""

    CONTAINER_APPS = "container-apps"
    AKS = "aks"


class DatabasePlacement(StrEnum):
    """Supported PostgreSQL placement choices for a new installation."""

    POSTGRES_FLEX = "postgres-flex"
    POSTGRES_AKS = "postgres-aks"


@dataclass(frozen=True, slots=True)
class RuntimeDeploymentProfile:
    """Secret-free runtime and node-pool intent bound to exact deployment plans."""

    runtime_platform: RuntimePlatform
    database_placement: DatabasePlacement
    system_node_count: int = 3
    system_node_sku: str = "Standard_D4as_v5"
    user_node_min_count: int = 3
    user_node_max_count: int = 5
    user_node_sku: str = "Standard_D4as_v5"

    def __post_init__(self) -> None:
        if self.runtime_platform is RuntimePlatform.CONTAINER_APPS:
            if self.database_placement is not DatabasePlacement.POSTGRES_FLEX:
                raise ValueError("Container Apps requires postgres-flex")
            return
        if not 2 <= self.system_node_count <= 100:
            raise ValueError("AKS system node count MUST be in [2, 100]")
        minimum_user_nodes = 4 if self.database_placement is DatabasePlacement.POSTGRES_AKS else 3
        if not minimum_user_nodes <= self.user_node_min_count <= 100:
            raise ValueError(f"AKS user node minimum MUST be in [{minimum_user_nodes}, 100]")
        if not self.user_node_min_count <= self.user_node_max_count <= 100:
            raise ValueError("AKS user node maximum MUST cover the minimum and be at most 100")
        for label, value in (
            ("system node SKU", self.system_node_sku),
            ("user node SKU", self.user_node_sku),
        ):
            if not value.startswith("Standard_") or any(character.isspace() for character in value):
                raise ValueError(f"AKS {label} is invalid")

    @property
    def digest(self) -> str:
        """Return a replay-stable digest over the complete runtime choice."""

        return canonical_digest(self.to_mapping())

    @classmethod
    def create(
        cls,
        *,
        runtime_platform: str,
        database_placement: str,
        system_node_count: int = 3,
        system_node_sku: str | None = None,
        user_node_min_count: int = 3,
        user_node_max_count: int = 5,
        user_node_sku: str = "Standard_D4as_v5",
    ) -> RuntimeDeploymentProfile:
        """Parse command values and reject unsupported runtime or database names."""

        try:
            runtime = RuntimePlatform(runtime_platform)
        except ValueError as exc:
            raise ValueError("runtime platform is unsupported") from exc
        try:
            database = DatabasePlacement(database_placement)
        except ValueError as exc:
            raise ValueError("database placement is unsupported") from exc
        return cls(
            runtime_platform=runtime,
            database_placement=database,
            system_node_count=system_node_count,
            system_node_sku=system_node_sku
            if system_node_sku is not None
            else ("Standard_D4as_v5" if runtime is RuntimePlatform.AKS else "Standard_D2as_v5"),
            user_node_min_count=user_node_min_count,
            user_node_max_count=user_node_max_count,
            user_node_sku=user_node_sku,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical machine representation stored with deployment evidence."""

        return {
            "schema_version": "fdai.runtime-deployment-profile.v1",
            "runtime_platform": self.runtime_platform.value,
            "database_placement": self.database_placement.value,
            "system_node_count": self.system_node_count,
            "system_node_sku": self.system_node_sku,
            "user_node_min_count": self.user_node_min_count,
            "user_node_max_count": self.user_node_max_count,
            "user_node_sku": self.user_node_sku,
        }

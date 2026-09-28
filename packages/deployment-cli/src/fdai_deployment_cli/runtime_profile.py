"""Validate and seal the runtime substrate selected for a new deployment."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from fdai_service_contracts.product_profile import (
    ObservationDataSource,
    ObservationReadPermissions,
    ProductAddOn,
    ProductProfile,
)

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
    product_profile: ProductProfile = field(default_factory=ProductProfile)

    @property
    def console_selected(self) -> bool:
        """Report the explicitly selected read-only Console surface."""

        return self.product_profile.selects(ProductAddOn.READ_ONLY_CONSOLE)

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
        product_add_ons: tuple[str, ...] = (),
        observation_data_sources: tuple[str, ...] = (),
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
        try:
            add_ons = tuple(sorted({ProductAddOn(value) for value in product_add_ons}, key=str))
        except ValueError as exc:
            raise ValueError("product add-on is unsupported") from exc
        if len(add_ons) != len(product_add_ons):
            raise ValueError("product add-ons MUST NOT contain duplicates")
        try:
            data_sources = tuple(
                sorted(
                    {ObservationDataSource(value) for value in observation_data_sources},
                    key=str,
                )
            )
        except ValueError as exc:
            raise ValueError("observation data source is unsupported") from exc
        if len(data_sources) != len(observation_data_sources):
            raise ValueError("observation data sources MUST NOT contain duplicates")
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
            product_profile=ProductProfile(
                add_ons=add_ons,
                observation_permissions=ObservationReadPermissions(
                    selected_sources=data_sources,
                ),
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical machine representation stored with deployment evidence."""

        return {
            "schema_version": "fdai.runtime-deployment-profile.v2",
            "runtime_platform": self.runtime_platform.value,
            "database_placement": self.database_placement.value,
            "system_node_count": self.system_node_count,
            "system_node_sku": self.system_node_sku,
            "user_node_min_count": self.user_node_min_count,
            "user_node_max_count": self.user_node_max_count,
            "user_node_sku": self.user_node_sku,
            "product_profile": self.product_profile.model_dump(mode="json"),
        }

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> RuntimeDeploymentProfile:
        """Read current profiles and preserve explicit legacy full-product behavior."""

        schema_version = value.get("schema_version")
        if schema_version not in {
            "fdai.runtime-deployment-profile.v1",
            "fdai.runtime-deployment-profile.v2",
        }:
            raise ValueError("runtime deployment profile schema is unsupported")
        product = value.get("product_profile")
        if schema_version == "fdai.runtime-deployment-profile.v1":
            add_ons = tuple(sorted(item.value for item in ProductAddOn))
            data_sources = tuple(item.value for item in ObservationDataSource)
        else:
            if not isinstance(product, dict):
                raise ValueError("runtime deployment product profile is missing")
            parsed = ProductProfile.model_validate(product)
            add_ons = tuple(item.value for item in parsed.add_ons)
            data_sources = tuple(
                item.value for item in parsed.observation_permissions.selected_sources
            )
        return cls.create(
            runtime_platform=str(value.get("runtime_platform", "")),
            database_placement=str(value.get("database_placement", "")),
            system_node_count=value.get("system_node_count", 0),  # type: ignore[arg-type]
            system_node_sku=(
                str(value["system_node_sku"]) if value.get("system_node_sku") is not None else None
            ),
            user_node_min_count=value.get("user_node_min_count", 0),  # type: ignore[arg-type]
            user_node_max_count=value.get("user_node_max_count", 0),  # type: ignore[arg-type]
            user_node_sku=str(value.get("user_node_sku", "")),
            product_add_ons=add_ons,
            observation_data_sources=data_sources,
        )

    def matches_mapping(self, value: dict[str, object]) -> bool:
        """Compare current mappings exactly and legacy mappings without invented fields."""

        if value.get("schema_version") == "fdai.runtime-deployment-profile.v1":
            return legacy_runtime_profile_mapping(self) == value
        return self.to_mapping() == value


def legacy_runtime_profile_mapping(
    profile: RuntimeDeploymentProfile,
) -> dict[str, object]:
    """Project the pre-product-axis mapping for immutable legacy evidence."""

    current = profile.to_mapping()
    current.pop("product_profile")
    current["schema_version"] = "fdai.runtime-deployment-profile.v1"
    return current


def legacy_runtime_profile_digest(profile: RuntimeDeploymentProfile) -> str:
    """Return the digest retained by a context created before profile v2."""

    return canonical_digest(legacy_runtime_profile_mapping(profile))

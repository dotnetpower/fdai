"""Authority-neutral product profile and Azure observation permission contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductAddOn(StrEnum):
    """Optional product surfaces selected independently from runtime authority."""

    READ_ONLY_CONSOLE = "read-only-console"
    NOTIFICATIONS = "notifications"
    GOVERNED_EXECUTION = "governed-execution"
    ENTERPRISE_IDENTITY_GOVERNANCE = "enterprise-identity-governance"


class AzureObservationRole(StrEnum):
    """Allowed read-only Azure roles for the observation-first profile."""

    READER = "Reader"
    MONITORING_READER = "Monitoring Reader"
    LOG_ANALYTICS_READER = "Log Analytics Reader"
    COST_MANAGEMENT_READER = "Cost Management Reader"
    AKS_READ_ONLY = "AKS read-only"
    EVIDENCE_STORE_DATA_READER = "Storage Blob Data Reader"


class ObservationDataSource(StrEnum):
    """Optional evidence sources whose selection derives extra read roles."""

    AKS = "aks"
    AZURE_MONITOR = "azure-monitor"
    COST_MANAGEMENT = "cost-management"
    EVIDENCE_STORE = "evidence-store"
    LOG_ANALYTICS = "log-analytics"


_SOURCE_ROLE = {
    ObservationDataSource.AKS: AzureObservationRole.AKS_READ_ONLY,
    ObservationDataSource.AZURE_MONITOR: AzureObservationRole.MONITORING_READER,
    ObservationDataSource.COST_MANAGEMENT: AzureObservationRole.COST_MANAGEMENT_READER,
    ObservationDataSource.EVIDENCE_STORE: AzureObservationRole.EVIDENCE_STORE_DATA_READER,
    ObservationDataSource.LOG_ANALYTICS: AzureObservationRole.LOG_ANALYTICS_READER,
}


class ObservationReadPermissions(BaseModel):
    """Scoped Reader plus explicitly selected read-only evidence roles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_role: Literal[AzureObservationRole.READER] = AzureObservationRole.READER
    selected_sources: tuple[ObservationDataSource, ...] = ()

    @field_validator("selected_sources")
    @classmethod
    def _canonical_selected_sources(
        cls,
        value: tuple[ObservationDataSource, ...],
    ) -> tuple[ObservationDataSource, ...]:
        if len(value) != len(set(value)):
            raise ValueError("observation data sources must be unique")
        if value != tuple(sorted(value, key=str)):
            raise ValueError("observation data sources must use canonical order")
        return value

    @property
    def optional_roles(self) -> tuple[AzureObservationRole, ...]:
        """Derive roles from selected sources; callers cannot select roles directly."""

        return tuple(_SOURCE_ROLE[source] for source in self.selected_sources)

    def selects_source(self, source: ObservationDataSource) -> bool:
        return source in self.selected_sources

    def selects(self, role: AzureObservationRole) -> bool:
        """Return whether the read-only role is part of this exact contract."""

        return role is AzureObservationRole.READER or role in self.optional_roles


class ProductProfile(BaseModel):
    """One immutable product-surface axis; selection never grants authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["fdai.product-profile.v1"] = "fdai.product-profile.v1"
    name: Literal["observation-first"] = "observation-first"
    add_ons: tuple[ProductAddOn, ...] = ()
    observation_permissions: ObservationReadPermissions = Field(
        default_factory=ObservationReadPermissions
    )
    authority_granted: Literal[False] = False

    @field_validator("add_ons")
    @classmethod
    def _canonical_add_ons(
        cls,
        value: tuple[ProductAddOn, ...],
    ) -> tuple[ProductAddOn, ...]:
        if len(value) != len(set(value)):
            raise ValueError("product add-ons must be unique")
        if value != tuple(sorted(value, key=str)):
            raise ValueError("product add-ons must use canonical order")
        return value

    def selects(self, add_on: ProductAddOn) -> bool:
        """Return whether one optional surface was explicitly selected."""

        return add_on in self.add_ons

    @property
    def graph_bindings_selected(self) -> bool:
        return self.selects(ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE)

    @property
    def approval_bindings_selected(self) -> bool:
        return self.selects(ProductAddOn.GOVERNED_EXECUTION)

    @property
    def enforcement_bindings_selected(self) -> bool:
        return self.selects(ProductAddOn.GOVERNED_EXECUTION)

    @property
    def rollback_bindings_selected(self) -> bool:
        return self.selects(ProductAddOn.GOVERNED_EXECUTION)

    @property
    def privileged_executor_bindings_selected(self) -> bool:
        return self.selects(ProductAddOn.GOVERNED_EXECUTION)


__all__ = [
    "AzureObservationRole",
    "ObservationDataSource",
    "ObservationReadPermissions",
    "ProductAddOn",
    "ProductProfile",
]

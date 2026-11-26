"""Scoped model-provider evidence, separate from the configured-adapter aggregate."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest

Role = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]


class ModelProviderHealth(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ConfiguredModelBindingV1(ContractBase):
    role: Role
    binding_digest: Digest | None = None


class ModelProviderRegistrationV1(ContractBase):
    """Startup-owned obligations, independently pinned from observed outcomes."""

    process_instance: Annotated[str, Field(min_length=1, max_length=128)]
    source_artifact_digest: Digest | None
    configured_bindings: tuple[ConfiguredModelBindingV1, ...]
    registration_digest: Digest

    @model_validator(mode="after")
    def _pin(self) -> Self:
        roles = tuple(item.role for item in self.configured_bindings)
        if roles != tuple(sorted(set(roles))):
            raise ValueError("model registration roles MUST be exact, unique and ordered")
        body = self.model_dump(mode="json", exclude={"registration_digest"})
        if canonical_digest(body) != self.registration_digest:
            raise ValueError("model registration digest mismatch")
        return self


class ModelProviderObservationV1(ContractBase):
    scope_kind: Literal["process_model_adapter"] = "process_model_adapter"
    role: Role
    binding_digest: Digest | None
    source: Annotated[str, Field(min_length=1, max_length=256)]
    health: ModelProviderHealth
    value: Decimal | None = None
    observed_at: datetime | None = None
    maximum_age_seconds: Annotated[int, Field(ge=1)]
    fresh: bool
    reason: Annotated[str, Field(min_length=1, max_length=128)]
    execution_authority: Literal[False] = False

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("model-provider observation time MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.health is ModelProviderHealth.UNKNOWN:
            if self.value is not None or self.fresh:
                raise ValueError("unknown provider observations MUST NOT imply health")
        elif (
            self.binding_digest is None
            or self.observed_at is None
            or not self.fresh
            or self.value != (1 if self.health is ModelProviderHealth.HEALTHY else 0)
        ):
            raise ValueError("known provider health requires exact binding and fresh evidence")
        return self


class ModelProviderScopeSnapshotV1(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope_kind: Literal["process_configured_model_roles"] = "process_configured_model_roles"
    process_instance: Annotated[str, Field(min_length=1, max_length=128)]
    registration_digest: Digest | None
    parent_snapshot_digest: Digest
    configured_bindings: tuple[ConfiguredModelBindingV1, ...]
    observations: tuple[ModelProviderObservationV1, ...]
    generated_at: datetime
    coverage_complete: bool
    health: ModelProviderHealth
    snapshot_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("generated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("model-provider scope time MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def _coverage(self) -> Self:
        roles = tuple(item.role for item in self.configured_bindings)
        if roles != tuple(sorted(set(roles))):
            raise ValueError("configured model roles MUST be exact, unique and ordered")
        observed_roles = tuple(item.role for item in self.observations)
        if observed_roles != roles:
            raise ValueError("observations MUST preserve every configured role obligation")
        known = bool(roles) and self.registration_digest is not None
        for binding, observation in zip(self.configured_bindings, self.observations, strict=True):
            if binding.binding_digest != observation.binding_digest:
                raise ValueError("provider observation belongs to another configured binding")
            if observation.health is ModelProviderHealth.UNKNOWN:
                known = False
                continue
            assert observation.observed_at is not None
            age = (self.generated_at - observation.observed_at).total_seconds()
            if not 0 <= age <= observation.maximum_age_seconds:
                raise ValueError("known provider health MUST be current")
        expected_health = (
            ModelProviderHealth.UNKNOWN
            if not known
            else ModelProviderHealth.UNHEALTHY
            if any(row.health is ModelProviderHealth.UNHEALTHY for row in self.observations)
            else ModelProviderHealth.HEALTHY
        )
        if self.coverage_complete is not known or self.health is not expected_health:
            raise ValueError("model-provider health and complete configured coverage disagree")
        body = self.model_dump(mode="json", exclude={"snapshot_digest"})
        if canonical_digest(body) != self.snapshot_digest:
            raise ValueError("model-provider scope digest mismatch")
        return self


def validate_model_provider_registration(
    scope: ModelProviderScopeSnapshotV1,
    registration: ModelProviderRegistrationV1,
) -> None:
    """A consumer must retain the owning registration, not trust a sub-source's scope claim."""
    expected = (
        registration.registration_digest
        if registration.source_artifact_digest is not None
        else None
    )
    if (
        scope.process_instance != registration.process_instance
        or scope.configured_bindings != registration.configured_bindings
        or scope.registration_digest != expected
    ):
        raise ValueError("model-provider scope does not match the owning registration")

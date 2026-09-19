"""Authority-free enrollment and delivery metadata for outbound cluster adapters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest

OpaqueRef = Annotated[
    str, Field(min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Namespace = Annotated[
    str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
]
Capability = Literal[
    "inventory.snapshot", "lifecycle.events", "diagnostic.read", "governed.execute"
]


class ConnectorContract(BaseModel):
    """Reject unknown fields, coercible numbers, and ambiguous clocks at the boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    @field_validator("*", mode="before")
    @classmethod
    def _validate_scalar(cls, value: object) -> object:
        if isinstance(value, str) and (
            value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("connector text must be unpadded and contain no control characters")
        return value


class ConnectorScope(ConnectorContract):
    """Name the registered deployment and exact cluster without carrying credentials."""

    deployment_ref: OpaqueRef
    cluster_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
    ]
    connector_id: OpaqueRef
    enrollment_revision: Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]


class ConnectorRegistration(ConnectorContract):
    """Server-owned admission ceiling, never a credential or mutation authorization."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: ConnectorScope
    principal_ref: OpaqueRef
    role: Literal["observer", "executor"]
    namespaces: Annotated[tuple[Namespace, ...], Field(min_length=1, max_length=32)]
    capabilities: Annotated[tuple[Capability, ...], Field(min_length=1, max_length=4)]
    valid_from: datetime
    expires_at: datetime
    revoked: Annotated[bool, Field(strict=True)] = False

    @field_validator("valid_from", "expires_at", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _validate_registration(self) -> Self:
        if self.expires_at <= self.valid_from:
            raise ValueError("connector registration validity must be ordered")
        if tuple(sorted(set(self.namespaces))) != self.namespaces:
            raise ValueError("connector namespaces must be sorted and unique")
        if tuple(sorted(set(self.capabilities))) != self.capabilities:
            raise ValueError("connector capabilities must be sorted and unique")
        executing = "governed.execute" in self.capabilities
        if executing != (self.role == "executor") or (executing and len(self.capabilities) != 1):
            raise ValueError("connector observation and execution roles must be separate")
        return self

    def admit(
        self, *, principal_ref: str, scope: ConnectorScope, capability: Capability, now: datetime
    ) -> None:
        """Validate current server-side registration before storage or task delivery."""
        current = connector_time(now)
        if (
            self.revoked
            or principal_ref != self.principal_ref
            or scope != self.scope
            or capability not in self.capabilities
            or not self.valid_from <= current < self.expires_at
        ):
            raise ValueError("connector registration does not admit this request")


class ConnectorEvidence(ConnectorContract):
    """Bind a separately validated immutable evidence artifact to one observation stream."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: ConnectorScope
    capability: Literal["inventory.snapshot", "lifecycle.events", "diagnostic.read"]
    stream_id: OpaqueRef
    sequence: Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
    observed_at: datetime
    producer_revision: Digest
    artifact_digest: Digest
    artifact_bytes: Annotated[int, Field(strict=True, ge=1, le=8_388_608)]
    namespaces: Annotated[tuple[Namespace, ...], Field(min_length=1, max_length=32)]
    complete: Annotated[bool, Field(strict=True)]
    limitations: Annotated[
        tuple[Literal["cursor_expired", "result_limit", "source_unavailable", "coverage_gap"], ...],
        Field(max_length=4),
    ] = ()
    execution_authority: Literal[False] = False

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _no_authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("connector evidence cannot grant execution authority")
        return value

    @field_validator("observed_at", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _validate_coverage(self) -> Self:
        if tuple(sorted(set(self.namespaces))) != self.namespaces:
            raise ValueError("connector namespaces must be sorted and unique")
        if tuple(sorted(set(self.limitations))) != self.limitations:
            raise ValueError("connector limitations must be sorted and unique")
        if self.complete == bool(self.limitations):
            raise ValueError("connector completeness must agree with explicit limitations")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))

    def admit(
        self,
        registration: ConnectorRegistration,
        *,
        principal_ref: str,
        now: datetime,
        max_age_seconds: int,
    ) -> None:
        """Validate provenance scope and freshness without trusting an artifact's contents."""
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("connector freshness limit must be in [1, 3600]")
        current = connector_time(now)
        registration.admit(
            principal_ref=principal_ref, scope=self.scope, capability=self.capability, now=current
        )
        if not set(self.namespaces) <= set(registration.namespaces):
            raise ValueError("connector evidence exceeds registered namespaces")
        if not registration.valid_from <= self.observed_at <= current:
            raise ValueError("connector observation is outside its admissible time window")
        if current - self.observed_at >= timedelta(seconds=max_age_seconds):
            raise ValueError("connector observation is stale")


class ConnectorWork(ConnectorContract):
    """Reference existing governed work without embedding commands or granting authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: ConnectorScope
    work_id: OpaqueRef
    correlation_id: OpaqueRef
    capability: Literal["diagnostic.read", "governed.execute"]
    namespace: Namespace
    target_uid: OpaqueRef
    target_revision: OpaqueRef
    artifact_digest: Digest
    issued_at: datetime
    expires_at: datetime
    idempotency_key: OpaqueRef

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if not timedelta(0) < self.expires_at - self.issued_at <= timedelta(minutes=15):
            raise ValueError("connector work validity must be positive and at most 15 minutes")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))

    def admit(
        self, registration: ConnectorRegistration, *, principal_ref: str, now: datetime
    ) -> None:
        """Admit delivery only; the existing owner must still authorize execution."""
        current = connector_time(now)
        registration.admit(
            principal_ref=principal_ref, scope=self.scope, capability=self.capability, now=current
        )
        if (
            self.namespace not in registration.namespaces
            or not registration.valid_from <= self.issued_at <= current < self.expires_at
            or self.expires_at > registration.expires_at
        ):
            raise ValueError("connector work is expired, future, or outside namespace scope")


def connector_time(value: object) -> datetime:
    """Accept only explicit offset-bearing timestamps and normalize them for replay."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("connector timestamp must be ISO 8601") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("connector timestamp must have an explicit UTC offset")
    return value.astimezone(UTC)

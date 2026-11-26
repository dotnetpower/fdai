"""Authority-free startup receipt for FDAI product and execution-venue scope.

FDAI-CONST-001 allows execution venues to vary only credentials, endpoints, scale, and provider
scope. This module turns the shared venue table and one service descriptor into a content-addressed
runtime receipt. The receipt records configuration selection only: it does not attest external
state, grant execution authority, or prove that a provider operation succeeded.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.descriptor import ServiceDescriptor
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.venue import (
    VENUE_CAPABILITIES,
    ExecutionVenue,
    VenueCapability,
    resolve_execution_venue,
)

ProductPurpose = Literal["cloud_operations_control_plane"]
VenueVariance = Literal["credentials", "endpoints", "provider_scope", "scale"]
PRODUCT_PURPOSE: ProductPurpose = "cloud_operations_control_plane"
PERMITTED_VENUE_VARIANCES: tuple[VenueVariance, ...] = (
    "credentials",
    "endpoints",
    "provider_scope",
    "scale",
)


class VenueCapabilityBinding(ContractBase):
    """One named binding selected from the shared venue contract."""

    capability: VenueCapability
    value: Annotated[str, Field(min_length=1, max_length=128)]


class _RuntimeScopeReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"]
    service_id: Annotated[
        str,
        Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]{0,79}$"),
    ]
    product_purpose: ProductPurpose
    execution_venue: ExecutionVenue
    permitted_variances: tuple[VenueVariance, ...]
    capability_bindings: tuple[VenueCapabilityBinding, ...]
    venue_contract_digest: Digest
    recorded_at: datetime
    external_state_authority: Literal[False]
    execution_authority: Literal[False]

    @field_validator("recorded_at")
    @classmethod
    def _normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("runtime scope receipt time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_scope_contract(self) -> _RuntimeScopeReceiptBody:
        if self.permitted_variances != PERMITTED_VENUE_VARIANCES:
            raise ValueError("runtime scope permitted variances do not match FDAI-CONST-001")
        expected_bindings = _bindings_for(self.execution_venue)
        if self.capability_bindings != expected_bindings:
            raise ValueError("runtime scope capability bindings do not match the selected venue")
        if self.venue_contract_digest != runtime_scope_contract_digest():
            raise ValueError(
                "runtime scope venue contract digest does not match the shared contract"
            )
        return self


class RuntimeScopeReceipt(_RuntimeScopeReceiptBody):
    """Bind one service startup to the FDAI product and venue contract without authority."""

    receipt_digest: Digest

    @model_validator(mode="after")
    def _validate_receipt_digest(self) -> RuntimeScopeReceipt:
        expected = _digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("runtime scope receipt digest does not match its content")
        return self


def runtime_scope_contract_digest() -> str:
    """Return the digest of the complete product-purpose and venue-selection contract."""

    bindings = {
        capability.value: {
            venue.value: VENUE_CAPABILITIES[capability][venue]
            for venue in sorted(ExecutionVenue, key=lambda item: item.value)
        }
        for capability in sorted(VenueCapability, key=lambda item: item.value)
    }
    return _digest(
        {
            "product_purpose": PRODUCT_PURPOSE,
            "permitted_variances": PERMITTED_VENUE_VARIANCES,
            "venue_capabilities": bindings,
        }
    )


def runtime_scope_receipt_digest(**values: object) -> str:
    """Return the canonical digest for a validated runtime-scope receipt body."""

    body = dict(values)
    body.pop("receipt_digest", None)
    candidate = _RuntimeScopeReceiptBody.model_validate(body)
    return _digest(candidate.model_dump(mode="json"))


def build_runtime_scope_receipt(
    descriptor: ServiceDescriptor,
    env: Mapping[str, str] | None = None,
    *,
    recorded_at: datetime | None = None,
) -> RuntimeScopeReceipt:
    """Resolve one service's venue and return its immutable startup-scope receipt."""

    venue = resolve_execution_venue(env)
    body = _RuntimeScopeReceiptBody(
        schema_version="1.0.0",
        service_id=descriptor.service_id,
        product_purpose=PRODUCT_PURPOSE,
        execution_venue=venue,
        permitted_variances=PERMITTED_VENUE_VARIANCES,
        capability_bindings=_bindings_for(venue),
        venue_contract_digest=runtime_scope_contract_digest(),
        recorded_at=recorded_at or datetime.now(UTC),
        external_state_authority=False,
        execution_authority=False,
    )
    values = body.model_dump(mode="json")
    return RuntimeScopeReceipt(**values, receipt_digest=_digest(values))


def record_runtime_scope_receipt(
    descriptor: ServiceDescriptor,
    env: Mapping[str, str] | None = None,
    *,
    recorded_at: datetime | None = None,
    logger: logging.Logger | None = None,
) -> RuntimeScopeReceipt:
    """Build and emit one secret-free structured receipt before a service starts."""

    receipt = build_runtime_scope_receipt(descriptor, env, recorded_at=recorded_at)
    target = logger or logging.getLogger(descriptor.service_id)
    target.info(
        "runtime_scope_receipt",
        extra={
            "runtime_scope_receipt": receipt.model_dump(mode="json"),
            "correlation_id": receipt.receipt_digest,
        },
    )
    return receipt


def _bindings_for(venue: ExecutionVenue) -> tuple[VenueCapabilityBinding, ...]:
    return tuple(
        VenueCapabilityBinding(
            capability=capability,
            value=VENUE_CAPABILITIES[capability][venue],
        )
        for capability in sorted(VenueCapability, key=lambda item: item.value)
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PERMITTED_VENUE_VARIANCES",
    "PRODUCT_PURPOSE",
    "RuntimeScopeReceipt",
    "VenueCapabilityBinding",
    "build_runtime_scope_receipt",
    "record_runtime_scope_receipt",
    "runtime_scope_contract_digest",
    "runtime_scope_receipt_digest",
]

"""FDAI-CONST-001 product-purpose and venue scope receipt tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fdai_service_contracts import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    RuntimeScopeReceipt,
    ServiceDescriptor,
    ServiceKind,
    VenueCapabilityBinding,
    build_runtime_scope_receipt,
    record_runtime_scope_receipt,
    runtime_scope_contract_digest,
    runtime_scope_receipt_digest,
)
from fdai_service_contracts.venue import EXECUTION_VENUE_ENV, ExecutionVenue, VenueCapability
from pydantic import ValidationError

RECORDED_AT = datetime(2026, 9, 16, 3, 30, tzinfo=UTC)
SERVICE = ServiceDescriptor(
    service_id="example-service",
    distribution="fdai-example-service",
    image="fdai-example-service",
    entrypoint="fdai-example-service",
    kind=ServiceKind.HTTP_API,
)


def _receipt(venue: ExecutionVenue) -> RuntimeScopeReceipt:
    return build_runtime_scope_receipt(
        SERVICE,
        {EXECUTION_VENUE_ENV: venue.value},
        recorded_at=RECORDED_AT,
    )


@pytest.mark.parametrize("venue", list(ExecutionVenue))
def test_runtime_scope_receipt_binds_product_and_complete_venue_contract(
    venue: ExecutionVenue,
) -> None:
    receipt = _receipt(venue)

    assert receipt.product_purpose == "cloud_operations_control_plane"
    assert receipt.execution_venue is venue
    assert receipt.permitted_variances == ("credentials", "endpoints", "provider_scope", "scale")
    assert tuple(binding.capability for binding in receipt.capability_bindings) == tuple(
        sorted(VenueCapability, key=lambda item: item.value)
    )
    assert receipt.venue_contract_digest == runtime_scope_contract_digest()
    assert receipt.external_state_authority is False
    assert receipt.execution_authority is False
    assert receipt.receipt_digest == runtime_scope_receipt_digest(**receipt.model_dump(mode="json"))


def test_runtime_scope_receipt_validates_against_the_registered_schema() -> None:
    receipt = _receipt(ExecutionVenue.DEPLOYED)
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    validator.validate(
        "runtime-scope-receipt",
        receipt.model_dump(mode="json"),
        version="1.0.0",
    )


def test_runtime_scope_receipt_rejects_tampered_binding_and_digest() -> None:
    receipt = _receipt(ExecutionVenue.LOCAL)
    bindings = list(receipt.capability_bindings)
    bindings[0] = VenueCapabilityBinding(
        capability=bindings[0].capability,
        value="tampered",
    )

    with pytest.raises(ValidationError, match="capability bindings"):
        RuntimeScopeReceipt(
            **{
                **receipt.model_dump(mode="json"),
                "capability_bindings": [item.model_dump(mode="json") for item in bindings],
            }
        )

    with pytest.raises(ValidationError, match="receipt digest"):
        RuntimeScopeReceipt(
            **{
                **receipt.model_dump(mode="json"),
                "receipt_digest": "sha256:" + "0" * 64,
            }
        )


def test_runtime_scope_receipt_rejects_a_naive_clock() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        build_runtime_scope_receipt(
            SERVICE,
            {EXECUTION_VENUE_ENV: "local"},
            recorded_at=datetime(2026, 9, 16, 3, 30),
        )


def test_runtime_scope_schema_rejects_authority_claims() -> None:
    receipt = _receipt(ExecutionVenue.LOCAL).model_dump(mode="json")
    receipt["execution_authority"] = True
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    with pytest.raises(ContractValidationError):
        validator.validate("runtime-scope-receipt", receipt, version="1.0.0")


def test_runtime_scope_schema_applies_cross_field_binding_validation() -> None:
    receipt = _receipt(ExecutionVenue.LOCAL).model_dump(mode="json")
    receipt["capability_bindings"][0]["value"] = "workload_identity"
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    with pytest.raises(ContractValidationError, match="capability bindings"):
        validator.validate("runtime-scope-receipt", receipt, version="1.0.0")


def test_record_runtime_scope_receipt_emits_the_complete_secret_free_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("runtime-scope-test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        receipt = record_runtime_scope_receipt(
            SERVICE,
            {EXECUTION_VENUE_ENV: "deployed"},
            recorded_at=RECORDED_AT,
            logger=logger,
        )

    record = caplog.records[-1]
    assert record.message == "runtime_scope_receipt"
    assert getattr(record, "correlation_id") == receipt.receipt_digest
    assert getattr(record, "runtime_scope_receipt") == receipt.model_dump(mode="json")


def test_runtime_scope_contract_digest_changes_with_the_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runtime_scope_contract_digest()
    from fdai_service_contracts import runtime_scope

    capabilities = getattr(runtime_scope, "VENUE_CAPABILITIES")
    local = capabilities[VenueCapability.BUS_SECURITY_PROTOCOL]
    changed = {
        **capabilities,
        VenueCapability.BUS_SECURITY_PROTOCOL: {
            **local,
            ExecutionVenue.LOCAL: "SASL_SSL",
        },
    }
    monkeypatch.setattr(runtime_scope, "VENUE_CAPABILITIES", changed)

    assert runtime_scope_contract_digest() != original

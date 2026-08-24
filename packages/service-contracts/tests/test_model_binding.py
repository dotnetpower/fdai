"""Shared environment model-binding policy contract tests."""

from __future__ import annotations

import pytest
from fdai_service_contracts import ModelBindingPolicy, ModelSelectionMode, ModelSku
from pydantic import ValidationError


def _pinned(*, sku: str, unit: str, value: int) -> dict[str, object]:
    return {
        "selection_mode": "pinned",
        "publisher": "OpenAI",
        "family": "gpt-4o",
        "version_policy": "latest-compatible",
        "sku": sku,
        "capacity": {"unit": unit, "value": value},
    }


def test_contract_accepts_revisioned_ptu_binding_without_authority() -> None:
    policy = ModelBindingPolicy.model_validate(
        {
            "schema_version": "1.0.0",
            "environment": "production",
            "revision": 2,
            "capabilities": {
                "t2.reasoner.primary": _pinned(
                    sku="GlobalProvisionedManaged",
                    unit="ptu",
                    value=30,
                )
            },
        }
    )

    binding = policy.capabilities["t2.reasoner.primary"]
    assert binding.selection_mode is ModelSelectionMode.PINNED
    assert binding.sku is ModelSku.GLOBAL_PROVISIONED_MANAGED
    assert policy.digest().startswith("sha256:")
    assert "execution_authority" not in policy.model_dump(mode="json")


def test_contract_rejects_extra_authority_and_capacity_mismatch() -> None:
    with pytest.raises(ValidationError):
        ModelBindingPolicy.model_validate(
            {
                "schema_version": "1.0.0",
                "environment": "production",
                "revision": 1,
                "execution_authority": True,
                "capabilities": {
                    "t2.reasoner.primary": _pinned(
                        sku="ProvisionedManaged",
                        unit="tpm",
                        value=30_000,
                    )
                },
            }
        )


def test_contract_rejects_malformed_capability_name() -> None:
    with pytest.raises(ValidationError, match="capability names"):
        ModelBindingPolicy.model_validate(
            {
                "schema_version": "1.0.0",
                "environment": "production",
                "revision": 1,
                "capabilities": {"t1.!invalid": {"selection_mode": "auto"}},
            }
        )


@pytest.mark.parametrize("field", ["publisher", "family"])
@pytest.mark.parametrize("value", ["OpenAI\nforged", "OpenAI\x00forged", "OpenAI forged"])
def test_contract_rejects_unsafe_model_identifiers(field: str, value: str) -> None:
    binding = _pinned(sku="Standard", unit="tpm", value=1000)
    binding[field] = value
    with pytest.raises(ValidationError):
        ModelBindingPolicy.model_validate(
            {
                "schema_version": "1.0.0",
                "environment": "production",
                "revision": 1,
                "capabilities": {"t1.embedding": binding},
            }
        )


@pytest.mark.parametrize("value", [999, 10_000_001])
def test_contract_rejects_out_of_range_tpm(value: int) -> None:
    with pytest.raises(ValidationError):
        ModelBindingPolicy.model_validate(
            {
                "schema_version": "1.0.0",
                "environment": "production",
                "revision": 1,
                "capabilities": {"t1.embedding": _pinned(sku="Standard", unit="tpm", value=value)},
            }
        )


def test_contract_rejects_more_than_sixty_four_capabilities() -> None:
    with pytest.raises(ValidationError, match="at most 64"):
        ModelBindingPolicy.model_validate(
            {
                "schema_version": "1.0.0",
                "environment": "production",
                "revision": 1,
                "capabilities": {
                    f"t1.slot-{index}": {"selection_mode": "auto"} for index in range(65)
                },
            }
        )

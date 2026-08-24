"""Environment model binding policy validation and registry overlay tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.rule_catalog.schema.llm_registry import Sku, load_llm_registry_from_mapping
from fdai.rule_catalog.schema.model_binding_policy import (
    ModelSelectionMode,
    capability_policy,
    load_model_binding_policy_from_mapping,
    load_model_binding_policy_from_yaml,
    validate_policy_against_registry,
)
from fdai_service_contracts import ModelSku


def _registry():  # type: ignore[no-untyped-def]
    return load_llm_registry_from_mapping(
        {
            "schema_version": "1.0.0",
            "models": {
                "t1.embedding": {
                    "preferences": [{"publisher": "OpenAI", "family": "text-embedding-3-small"}],
                    "capacity_tpm": 100_000,
                },
                "t2.reasoner.primary": {
                    "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                    "capacity_tpm": 20_000,
                },
                "t2.reasoner.secondary": {
                    "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                    "capacity_tpm": 10_000,
                },
            },
        }
    )


def _policy(capabilities: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "environment": "production",
        "revision": 3,
        "expected_active_digest": "sha256:" + "a" * 64,
        "capabilities": capabilities,
    }


def test_pinned_ptu_policy_builds_effective_capability() -> None:
    policy = load_model_binding_policy_from_mapping(
        _policy(
            {
                "t2.reasoner.primary": {
                    "selection_mode": "pinned",
                    "publisher": "OpenAI",
                    "family": "gpt-4.1",
                    "version_policy": "latest-compatible",
                    "sku": "GlobalProvisionedManaged",
                    "capacity": {"unit": "ptu", "value": 30},
                }
            }
        )
    )

    mode, capability = capability_policy(
        registry=_registry(), policy=policy, capability="t2.reasoner.primary"
    )

    assert mode is ModelSelectionMode.PINNED
    assert capability.preferences[0].family == "gpt-4.1"
    assert capability.sku == "GlobalProvisionedManaged"
    assert capability.capacity_tpm is None
    assert capability.capacity_ptu == 30
    assert policy.digest() == policy.digest()


@pytest.mark.parametrize(
    ("sku", "unit"),
    [
        ("Standard", "ptu"),
        ("GlobalStandard", "ptu"),
        ("ProvisionedManaged", "tpm"),
    ],
)
def test_pinned_policy_rejects_sku_capacity_mismatch(sku: str, unit: str) -> None:
    with pytest.raises(ValueError, match="requires|validation failed"):
        load_model_binding_policy_from_mapping(
            _policy(
                {
                    "t1.embedding": {
                        "selection_mode": "pinned",
                        "publisher": "OpenAI",
                        "family": "text-embedding-3-small",
                        "version_policy": "latest-compatible",
                        "sku": sku,
                        "capacity": {"unit": unit, "value": 30},
                    }
                }
            )
        )


def test_auto_and_hil_only_reject_pinned_fields() -> None:
    with pytest.raises(ValueError):
        load_model_binding_policy_from_mapping(
            _policy(
                {
                    "t1.embedding": {
                        "selection_mode": "hil-only",
                        "publisher": "OpenAI",
                    }
                }
            )
        )


def test_policy_rejects_unknown_capability() -> None:
    policy = load_model_binding_policy_from_mapping(
        _policy({"t1.unknown": {"selection_mode": "auto"}})
    )
    with pytest.raises(ValueError, match="unknown capabilities"):
        validate_policy_against_registry(registry=_registry(), policy=policy)


def test_policy_rejects_same_publisher_t2_pair() -> None:
    policy = load_model_binding_policy_from_mapping(
        _policy(
            {
                "t2.reasoner.secondary": {
                    "selection_mode": "pinned",
                    "publisher": "OpenAI",
                    "family": "gpt-4.1",
                    "version_policy": "latest-compatible",
                    "sku": "Standard",
                    "capacity": {"unit": "tpm", "value": 20_000},
                }
            }
        )
    )
    with pytest.raises(ValueError, match="distinct publishers"):
        validate_policy_against_registry(registry=_registry(), policy=policy)


def test_yaml_loader_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("- invalid\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        load_model_binding_policy_from_yaml(path)


def test_shared_and_core_sku_contracts_remain_identical() -> None:
    assert {sku.value for sku in ModelSku} == {sku.value for sku in Sku}
    assert {sku.value: sku.is_provisioned for sku in ModelSku} == {
        sku.value: sku.is_provisioned for sku in Sku
    }

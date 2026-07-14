"""Inventory job configuration boundary tests."""

from __future__ import annotations

import hashlib

import pytest

from fdai.delivery.inventory_sync_cli import InventoryJobConfig, _verify_sha256


def test_job_config_defaults_to_arg_then_arm() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    assert config.source_order == ("arg", "arm")
    assert config.scopes == ("sub-1",)
    assert config.freshness_budget_seconds == 86_400
    assert config.management_audience == "https://management.azure.com/.default"


def test_job_config_rejects_unsigned_declarative_fallback() -> None:
    with pytest.raises(ValueError, match="requires"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_SOURCES": "arg,declarative",
            }
        )


def test_declarative_sha_verification(tmp_path) -> None:
    fixture = tmp_path / "inventory.yaml"
    fixture.write_text("resources: []\nlinks: []\n", encoding="utf-8")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    _verify_sha256(fixture, digest)
    with pytest.raises(ValueError, match="does not match"):
        _verify_sha256(fixture, "0" * 64)

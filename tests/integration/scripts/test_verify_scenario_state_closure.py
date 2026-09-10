"""Tests for disposable scenario Terraform state closure."""

from __future__ import annotations

import pytest
from scripts.deployment.azure import verify_scenario_state_closure as closure


def test_accepts_absent_or_empty_scenario_state() -> None:
    absent = closure.verify_state_closed(None)
    empty = closure.verify_state_closed({"resources": []})

    assert absent["state_present"] is False
    assert empty["state_present"] is True
    assert absent["managed_resource_count"] == empty["managed_resource_count"] == 0


def test_rejects_remaining_managed_scenario_resources() -> None:
    state = {
        "resources": [
            {
                "mode": "managed",
                "type": "azurerm_role_assignment",
                "instances": [{"attributes": {}}],
            }
        ]
    }

    with pytest.raises(ValueError, match="still owns managed resources"):
        closure.verify_state_closed(state)


def test_ignores_data_source_cache_without_claiming_managed_resources() -> None:
    state = {
        "resources": [
            {
                "mode": "data",
                "type": "azurerm_client_config",
                "instances": [{"attributes": {}}],
            }
        ]
    }

    receipt = closure.verify_state_closed(state)

    assert receipt["state_closed"] is True

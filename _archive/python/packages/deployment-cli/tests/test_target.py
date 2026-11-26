from __future__ import annotations

import pytest

from fdai_deployment_cli.target import (
    azure_target_selection_arguments,
    require_selected_azure_target,
)

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"


def test_explicit_subscription_is_forwarded_to_azure_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)

    assert azure_target_selection_arguments() == ("--subscription", SUBSCRIPTION)


def test_explicit_target_rejects_shared_profile_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)

    with pytest.raises(ValueError, match="subscription differs"):
        require_selected_azure_target(
            subscription_id="00000000-0000-0000-0000-000000000003",
            tenant_id=TENANT,
        )
    with pytest.raises(ValueError, match="tenant differs"):
        require_selected_azure_target(
            subscription_id=SUBSCRIPTION,
            tenant_id="00000000-0000-0000-0000-000000000004",
        )


def test_unselected_target_preserves_active_profile_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)

    assert azure_target_selection_arguments() == ()
    require_selected_azure_target(subscription_id=SUBSCRIPTION, tenant_id=TENANT)

from __future__ import annotations

import json
import subprocess

import pytest

from fdai_deployment_cli import standalone_application
from fdai_deployment_cli.target import compute_target_binding


def test_missing_license_material_keeps_deployment_observation_only(monkeypatch) -> None:
    monkeypatch.setattr(standalone_application, "discover_license_signing_key", lambda _key: None)

    token = standalone_application._license_token(
        key=None,
        trial_token=None,
        image_digest="a" * 64,
        deployment_binding="b" * 64,
        work_ref="deployment",
    )

    assert token is None


def test_approval_actor_is_bound_to_current_azure_target(monkeypatch) -> None:
    tenant = "00000000-0000-0000-0000-000000000000"
    subscription = "00000000-0000-0000-0000-000000000001"
    binding = compute_target_binding(tenant_id=tenant, subscription_id=subscription)
    payload = {
        "subscription_id": subscription,
        "tenant_id": tenant,
        "user_name": "operator@example.com",
        "user_type": "user",
    }
    monkeypatch.setattr(
        standalone_application.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    digest = standalone_application._azure_actor_digest(binding)

    assert len(digest) == 64


def test_approval_actor_rejects_changed_azure_target(monkeypatch) -> None:
    payload = {
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "user_name": "operator@example.com",
        "user_type": "user",
    }
    monkeypatch.setattr(
        standalone_application.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    with pytest.raises(ValueError, match="active Azure target"):
        standalone_application._azure_actor_digest("a" * 64)

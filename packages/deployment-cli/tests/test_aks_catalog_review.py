from __future__ import annotations

import pytest

from fdai_deployment_cli.aks_catalog_review import (
    FROZEN_MANIFEST_PATH,
    REQUIRED_GITHUB_APP_PERMISSIONS,
    aks_catalog_review_configuration,
)

_REVISION = "a" * 40
_SECRET_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/example/providers/Microsoft.KeyVault/vaults/example/"
    "secrets/fdai-gitops-token"
)


def test_missing_binding_keeps_catalog_review_unavailable() -> None:
    assert (
        aks_catalog_review_configuration(
            None,
            selected=False,
            source_revision=_REVISION,
        )
        is None
    )


def test_static_token_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="GitHub App permission projection"):
        aks_catalog_review_configuration(
            {
                "enabled": True,
                "owner": "example-owner",
                "repo": "example-repo",
                "default_branch": "main",
                "auth_mode": "static_token",
                "token_secret_id": _SECRET_ID,
                "permissions": REQUIRED_GITHUB_APP_PERMISSIONS,
            },
            selected=True,
            source_revision=_REVISION,
        )


def test_missing_private_credential_fails_closed() -> None:
    with pytest.raises(ValueError, match="private GitOps credential binding"):
        aks_catalog_review_configuration(
            {
                "enabled": True,
                "owner": "example-owner",
                "repo": "example-repo",
                "default_branch": "main",
                "auth_mode": "github_app",
                "permissions": REQUIRED_GITHUB_APP_PERMISSIONS,
                "app_client_id": "client-id",
                "app_installation_id": "42",
                "app_private_key_secret_id": "",
            },
            selected=True,
            source_revision=_REVISION,
        )


def test_github_app_binding_keeps_private_key_out_of_values() -> None:
    configuration = aks_catalog_review_configuration(
        {
            "enabled": True,
            "owner": "example-owner",
            "repo": "example-repo",
            "default_branch": "main",
            "auth_mode": "github_app",
            "permissions": REQUIRED_GITHUB_APP_PERMISSIONS,
            "app_client_id": "client-id",
            "app_installation_id": "42",
            "app_private_key_secret_id": _SECRET_ID.replace(
                "fdai-gitops-token", "fdai-github-app-private-key"
            ),
        },
        selected=True,
        source_revision=_REVISION,
    )

    assert configuration is not None
    assert configuration.environment["FDAI_GITHUB_APP_INSTALLATION_ID"] == "42"
    assert configuration.environment["FDAI_CATALOG_REVIEW_FROZEN_MANIFEST"] == (
        FROZEN_MANIFEST_PATH
    )
    assert configuration.secret_environment == {
        "FDAI_GITHUB_APP_PRIVATE_KEY": "fdai-github-app-private-key"
    }

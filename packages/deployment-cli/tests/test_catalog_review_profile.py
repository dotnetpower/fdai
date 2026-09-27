from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.catalog_review_profile import (
    CatalogReviewDeploymentProfile,
    catalog_review_terraform_values,
    load_catalog_review_profile,
    load_staged_catalog_review_profile,
    stage_catalog_review_profile,
)


def _private_file(path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def test_selected_profile_uses_private_key_file_reference(tmp_path) -> None:
    key = tmp_path / "github-app.pem"
    _private_file(key, "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----\n")
    profile_path = tmp_path / "catalog-review.json"
    _private_file(
        profile_path,
        json.dumps(
            {
                "schema_version": "fdai.catalog-review-deployment-profile.v1",
                "selected": True,
                "owner": "example",
                "repo": "catalog",
                "default_branch": "main",
                "app_client_id": "client-id",
                "app_installation_id": "42",
                "app_private_key_file": str(key),
            }
        ),
    )

    profile = load_catalog_review_profile(profile_path)

    assert profile.selected is True
    assert profile.private_key_path == key
    assert len(profile.profile_digest) == 64
    assert "PRIVATE KEY" not in json.dumps(profile.staged_mapping())
    values = catalog_review_terraform_values(profile)
    assert values["enable_catalog_review"] is True
    assert values["github_app_private_key"] == profile.private_key_text()


def test_staged_selected_profile_requires_matching_private_key(tmp_path) -> None:
    key = tmp_path / "github-app.pem"
    _private_file(key, "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----\n")
    source = tmp_path / "source.json"
    _private_file(
        source,
        json.dumps(
            {
                "schema_version": "fdai.catalog-review-deployment-profile.v1",
                "selected": True,
                "owner": "example",
                "repo": "catalog",
                "default_branch": "main",
                "app_client_id": "client-id",
                "app_installation_id": "42",
                "app_private_key_file": str(key),
            }
        ),
    )
    profile = load_catalog_review_profile(source)
    staged = tmp_path / "staged.json"
    _private_file(staged, json.dumps(profile.staged_mapping()))

    assert (
        load_staged_catalog_review_profile(staged, private_key_path=key).profile_digest
        == profile.profile_digest
    )

    _private_file(tmp_path / "other.pem", "different")
    with pytest.raises(ValueError, match="private key digest differs"):
        load_staged_catalog_review_profile(
            staged,
            private_key_path=tmp_path / "other.pem",
        )


def test_unselected_profile_is_explicit_and_has_no_binding(tmp_path) -> None:
    path = tmp_path / "catalog-review.json"
    _private_file(
        path,
        json.dumps(
            {
                "schema_version": "fdai.catalog-review-deployment-profile.v1",
                "selected": False,
            }
        ),
    )

    assert load_catalog_review_profile(path) == CatalogReviewDeploymentProfile.unselected()


def test_selected_profile_stages_only_private_file_references(tmp_path) -> None:
    key = tmp_path / "github-app.pem"
    _private_file(key, "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----\n")
    source = tmp_path / "source.json"
    _private_file(
        source,
        json.dumps(
            {
                "schema_version": "fdai.catalog-review-deployment-profile.v1",
                "selected": True,
                "owner": "example",
                "repo": "catalog",
                "default_branch": "main",
                "app_client_id": "client-id",
                "app_installation_id": "42",
                "app_private_key_file": str(key),
            }
        ),
    )
    profile = load_catalog_review_profile(source)

    class Tunnel:
        def __init__(self) -> None:
            self.copies = []

        def copy_to(self, source_path, destination, *, timeout):
            self.copies.append((source_path, destination, timeout))

        def ssh(self, *_args, **_kwargs):
            raise AssertionError("successful staging must not execute a remote command")

    tunnel = Tunnel()
    arguments = stage_catalog_review_profile(
        profile,
        tunnel=tunnel,
        prepared_root=tmp_path,
        remote_root="/private/run",
    )

    assert arguments == (
        "--catalog-review-profile",
        "/private/run/catalog-review-profile.json",
        "--catalog-review-private-key",
        "/private/run/catalog-review-private-key.pem",
    )
    assert all("PRIVATE KEY" not in str(item) for item in arguments)
    assert [item[0] for item in tunnel.copies] == [
        tmp_path / "catalog-review-profile.json",
        key,
    ]

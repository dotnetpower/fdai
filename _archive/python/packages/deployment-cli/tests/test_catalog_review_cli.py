from __future__ import annotations

import json

import pytest

from fdai_deployment_cli import cli


def _private_file(path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _example_private_key() -> str:
    marker = "PRIVATE" + " KEY"
    return f"-----BEGIN {marker}-----\nexample\n-----END {marker}-----\n"


def test_public_coordinator_passes_selected_private_profile(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    key = tmp_path / "github-app.pem"
    _private_file(key, _example_private_key())
    profile = tmp_path / "catalog-review.json"
    _private_file(
        profile,
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
    captured = {}

    def deploy(**kwargs):
        captured.update(kwargs)
        return {"deployment_ready": True, "state": "deployment-ready"}

    monkeypatch.setattr(cli, "deploy_azure_foundation", deploy)
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            str(tmp_path / "kit.tar.gz"),
            "--runtime",
            "aks",
            "--catalog-review-profile",
            str(profile),
            "--output",
            "json",
        ]
    )

    assert args.handler(args) == 0
    assert captured["catalog_review_profile"].selected is True
    assert "PRIVATE KEY" not in capsys.readouterr().out


def test_public_coordinator_omission_is_explicit_unselected(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}

    def deploy(**kwargs):
        captured.update(kwargs)
        return {"deployment_ready": True, "state": "deployment-ready"}

    monkeypatch.setattr(cli, "deploy_azure_foundation", deploy)
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            str(tmp_path / "kit.tar.gz"),
            "--runtime",
            "aks",
            "--output",
            "json",
        ]
    )

    assert args.handler(args) == 0
    assert captured["catalog_review_profile"].selected is False


def test_public_coordinator_selected_missing_profile_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "deploy_azure_foundation",
        lambda **_kwargs: pytest.fail("missing profile reached deployment"),
    )
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            str(tmp_path / "kit.tar.gz"),
            "--runtime",
            "aks",
            "--catalog-review-profile",
            str(tmp_path / "missing.json"),
        ]
    )

    with pytest.raises(OSError):
        args.handler(args)

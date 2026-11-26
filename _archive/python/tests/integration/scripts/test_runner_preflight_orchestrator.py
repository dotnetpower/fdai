from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/run_runner_preflight.py"
_SPEC = importlib.util.spec_from_file_location("run_runner_preflight", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_manifest = _MODULE.build_manifest


def _by_id(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    checks = manifest["checks"]
    assert isinstance(checks, list)
    return {str(check["id"]): check for check in checks}


def test_manifest_combines_egress_and_terraform_targets() -> None:
    manifest = build_manifest(
        ["api.example.com"],
        terraform_outputs={
            "postgres_fqdn": "postgres.example.com",
            "key_vault_uri": "https://vault.example.com/",
        },
        private_networking=False,
        premium_acr=False,
        extra_checks=None,
    )

    checks = _by_id(manifest)
    assert checks["egress-01"]["expected_ip"] == "any"
    assert checks["postgres"]["port"] == 5432
    assert checks["postgres"]["expected_ip"] == "public"
    assert checks["key-vault"]["host"] == "vault.example.com"


def test_private_manifest_keeps_basic_acr_public() -> None:
    manifest = build_manifest(
        ["api.example.com"],
        terraform_outputs={"container_registry_login_server": "registry.example.com"},
        private_networking=True,
        premium_acr=False,
        extra_checks=None,
    )

    assert _by_id(manifest)["container-registry"]["expected_ip"] == "public"


def test_private_manifest_requires_premium_acr_private_address() -> None:
    manifest = build_manifest(
        ["api.example.com"],
        terraform_outputs={"container_registry_login_server": "registry.example.com"},
        private_networking=True,
        premium_acr=True,
        extra_checks=None,
    )

    assert _by_id(manifest)["container-registry"]["expected_ip"] == "private"


def test_extra_manifest_requires_exact_schema() -> None:
    with pytest.raises(ValueError, match="not a valid manifest"):
        build_manifest(
            ["api.example.com"],
            terraform_outputs={},
            private_networking=True,
            premium_acr=True,
            extra_checks={"schema_version": "wrong", "checks": []},
        )


def test_terraform_output_requires_hostname() -> None:
    with pytest.raises(ValueError, match="has no hostname"):
        build_manifest(
            ["api.example.com"],
            terraform_outputs={"postgres_fqdn": "://"},
            private_networking=True,
            premium_acr=True,
            extra_checks=None,
        )

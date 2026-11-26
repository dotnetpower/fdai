"""Independent Core capability-license deployment contract tests."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE = _ROOT / "infra/services/core-control-plane"
_ROOT_MAIN = (_SERVICE / "main.tf").read_text(encoding="utf-8")
_ROOT_VARIABLES = (_SERVICE / "variables.tf").read_text(encoding="utf-8")
_MODULE_MAIN = (_SERVICE / "modules/core-control-plane/main.tf").read_text(encoding="utf-8")
_MODULE_VARIABLES = (_SERVICE / "modules/core-control-plane/variables.tf").read_text(
    encoding="utf-8"
)


def test_core_root_preserves_the_complete_optional_license_contract() -> None:
    for source in (_ROOT_VARIABLES, _MODULE_VARIABLES):
        block = source.split('variable "license"', maxsplit=1)[1].split(
            '\nvariable "health"', maxsplit=1
        )[0]
        assert "token_secret_id" in block
        assert "image_digest" in block
        assert "deployment_digest" in block
        assert "token_revision" in block
        assert "^https://[^/]+/secrets/[^/]+$" in block
        assert block.count("^[0-9a-f]{64}$") == 3
    assert "license                    = var.license" in _ROOT_MAIN


def test_core_injects_only_a_key_vault_reference_and_binding_digests() -> None:
    assert 'license_enabled = trimspace(var.license.token_secret_id) != ""' in _MODULE_MAIN
    assert 'name                = "capability-license-token"' in _MODULE_MAIN
    assert "key_vault_secret_id = var.license.token_secret_id" in _MODULE_MAIN
    assert (
        '{ name = "FDAI_LICENSE_TOKEN", secret_name = "capability-license-token" }' in _MODULE_MAIN
    )
    assert (
        '{ name = "FDAI_LICENSE_IMAGE_DIGEST", value = var.license.image_digest }' in _MODULE_MAIN
    )
    assert (
        '{ name = "FDAI_LICENSE_DEPLOYMENT_BINDING", value = var.license.deployment_digest }'
        in _MODULE_MAIN
    )
    assert (
        '{ name = "FDAI_LICENSE_TOKEN_REVISION", value = var.license.token_revision }'
        in _MODULE_MAIN
    )
    assert 'name = "FDAI_LICENSE_TOKEN", value =' not in _MODULE_MAIN
    assert "integrity-signing-key.pem" not in _MODULE_MAIN
    assert "FDAI_REQUIRE_LICENSE" not in _MODULE_MAIN

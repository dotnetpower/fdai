"""Infrastructure contract for the OHL signed observation context."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_MAIN = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
_PLATFORM_OUTPUTS = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
_SERVICE_MAIN = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")


def test_platform_owns_random_ed25519_seed_in_key_vault() -> None:
    assert 'resource "random_id" "ohl_observation_signing_seed"' in _PLATFORM_MAIN
    assert "byte_length = 32" in _PLATFORM_MAIN
    assert 'resource "azurerm_key_vault_secret" "ohl_observation_signing_seed"' in _PLATFORM_MAIN
    assert 'content_type = "ed25519-seed-base64url"' in _PLATFORM_MAIN
    assert "count       = var.enable_isolated_executor" not in _PLATFORM_MAIN
    assert 'output "ohl_observation_context_binding"' in _PLATFORM_OUTPUTS


def test_core_receives_seed_only_as_managed_identity_key_vault_reference() -> None:
    assert 'name                = "ohl-observation-signing-seed"' in _SERVICE_MAIN
    assert "identity            = var.identity.resource_id" in _SERVICE_MAIN
    assert "key_vault_secret_id = var.observation_context.signing_seed_secret_id" in _SERVICE_MAIN
    assert (
        'name = "FDAI_OHL_OBSERVATION_SIGNING_SEED", secret_name = "ohl-observation-signing-seed"'
    ) in _SERVICE_MAIN
    assert 'name = "FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE"' in _SERVICE_MAIN
    assert 'name = "FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE"' in _SERVICE_MAIN
    assert 'name = "FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE"' in _SERVICE_MAIN

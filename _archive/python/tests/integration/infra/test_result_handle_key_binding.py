"""Infrastructure contract for the result-handle encryption key."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_MAIN = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
_PLATFORM_OUTPUTS = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
_SERVICE_MAIN = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")


def _block(text: str, header: str) -> str:
    start = text.index(header)
    return text[start : text.index("\n}\n", start)]


def test_platform_owns_a_random_256_bit_key_that_only_core_reads() -> None:
    assert 'resource "random_id" "result_handle_material"' in _PLATFORM_MAIN
    secret = _block(_PLATFORM_MAIN, 'resource "azurerm_key_vault_secret" "result_handle_material"')
    assert "random_id.result_handle_material.hex" in secret
    assert 'content_type = "aes-256-key-hex"' in secret
    reader = _block(
        _PLATFORM_MAIN,
        'resource "azurerm_role_assignment" "core_result_handle_material_reader"',
    )
    assert "azurerm_key_vault_secret.result_handle_material.resource_versionless_id" in reader
    assert "module.identity.principal_id" in reader
    assert "operator_api_identity" not in reader


def test_binding_output_exposes_only_a_versionless_secret_reference() -> None:
    output = _block(_PLATFORM_OUTPUTS, 'output "result_handle_binding"')

    assert re.search(r"secrets/fdai-result-handle-material\"", output)
    assert "resource_versionless_id" not in output
    assert "value =" in output and "random_id" not in output


def test_core_receives_the_key_only_as_a_managed_identity_key_vault_reference() -> None:
    assert 'name                = "result-handle-material"' in _SERVICE_MAIN
    assert "key_vault_secret_id = var.result_handles.key_secret_id" in _SERVICE_MAIN
    assert (
        'name = "FDAI_RESULT_HANDLE_MATERIAL", secret_name = "result-handle-material"'
        in _SERVICE_MAIN
    )
    # Providing the key never turns follow-ups on; the runtime setting alone decides.
    assert "FDAI_SEMANTIC_RESULT_HANDLES" not in _SERVICE_MAIN

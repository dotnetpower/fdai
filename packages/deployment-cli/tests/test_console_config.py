from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fdai_deployment_cli.console_config import (
    CONFIG_FILENAME,
    CONFIG_PLACEHOLDER,
    configure_console,
    render_console_config,
)

SETTINGS = {
    "schema_version": "fdai.console-runtime.v1",
    "operator_api_base_url": "https://operator.example.com",
    "ingestion_api_base_url": "https://ingestion.example.com",
    "tenant_id": "00000000-0000-0000-0000-000000000000",
    "spa_client_id": "00000000-0000-0000-0000-000000000001",
    "api_scope": "api://00000000-0000-0000-0000-000000000002/access",
}


def test_console_config_renders_only_public_authentication_settings() -> None:
    script = render_console_config(json.dumps(SETTINGS).encode())
    assert script.startswith(b"globalThis.__FDAI_CONSOLE_CONFIG__ = ")
    assert json.loads(script.split(b" = ", 1)[1][:-2]) == SETTINGS


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("dev_mode", True),
        ("localAzureCliAuth", True),
        ("client_secret", "not-a-credential"),
        ("operator_api_base_url", "http://operator.example.com"),
        ("operator_api_base_url", "https://user:pass@operator.example.com"),
        ("operator_api_base_url", "https://operator.example.com?token=none"),
        ("operator_api_base_url", "https://operator.example.com?"),
        ("operator_api_base_url", "https://operator.example.com#fragment"),
        ("operator_api_base_url", "https://operator.example.com#"),
        ("operator_api_base_url", "https://operator.example.com:99999"),
        ("operator_api_base_url", "https://operator.example.com/ white"),
        ("operator_api_base_url", "https://operator.example.com\\path"),
        ("operator_api_base_url", "https://operator.example.com/\u0001"),
        ("operator_api_base_url", "https://example.com/설정"),
        ("ingestion_api_base_url", ""),
        ("tenant_id", "common"),
        ("spa_client_id", []),
        ("api_scope", "https://management.azure.com/.default"),
        ("schema_version", "unknown"),
    ],
)
def test_console_config_rejects_unsafe_or_unknown_settings(key: str, value: object) -> None:
    with pytest.raises(ValueError):
        render_console_config(json.dumps({**SETTINGS, key: value}).encode())


def test_console_configuration_is_atomic_private_and_repeatable(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    settings.chmod(0o600)
    target = tmp_path / CONFIG_FILENAME
    target.write_bytes(CONFIG_PLACEHOLDER)
    result = configure_console(tmp_path, settings)
    assert result["changed"] is True
    assert result["cloud_mutation_performed"] is False
    assert result["console_access_verified"] is False
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not (tmp_path / ".fdai-config.js.pending").exists()
    assert configure_console(tmp_path, settings) == {**result, "changed": False}

    settings.write_text(
        json.dumps({**SETTINGS, "operator_api_base_url": "https://new.example.com"})
    )
    with pytest.raises(ValueError, match="fresh build copy"):
        configure_console(tmp_path, settings)


def test_console_configuration_does_not_follow_links(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS))
    settings.chmod(0o600)
    victim = tmp_path / "victim.js"
    victim.write_bytes(CONFIG_PLACEHOLDER)
    (tmp_path / CONFIG_FILENAME).symlink_to(victim)
    with pytest.raises(ValueError):
        configure_console(tmp_path, settings)
    assert victim.read_bytes() == CONFIG_PLACEHOLDER

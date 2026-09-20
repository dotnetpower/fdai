"""Deployment-owned configuration remains role-separated, bounded and reloadable."""

import json

import pytest
from fdai.delivery.kubernetes_connector_runtime import (
    ConnectorRuntimeConfig,
    FileConnectorRegistrations,
    load_connector_config,
    private_file,
)

from .test_kubernetes_connector_spool import registration


def test_role_configuration_rejects_observer_credentials_on_gateway(tmp_path) -> None:
    value = {
        "role": "gateway",
        "registration_path": "registration.json",
        "tls_ca_path": "ca.pem",
        "tls_certificate_path": "cert.pem",
        "tls_key_path": "key.pem",
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(value))
    config.chmod(0o600)
    assert load_connector_config(config).role == "gateway"
    with pytest.raises(ValueError):
        ConnectorRuntimeConfig.model_validate({**value, "api_token_path": "token"})
    with pytest.raises(ValueError):
        ConnectorRuntimeConfig.model_validate({**value, "role": "observer"})


async def test_registration_reload_observes_revocation_and_rejects_duplicates(tmp_path) -> None:
    path = tmp_path / "registrations.json"
    current = registration().model_dump(mode="json")
    path.write_text(json.dumps([current]))
    path.chmod(0o600)
    reader = FileConnectorRegistrations(path)
    assert await reader.read("foreign") is None
    assert (await reader.read("example")).revoked is False
    path.write_text(json.dumps([{**current, "revoked": True}]))
    assert (await reader.read("example")).revoked is True
    path.write_text(json.dumps([current, current]))
    with pytest.raises(ValueError):
        await reader.read("example")


def test_private_file_rejects_symlinks_public_permissions_and_large_content(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"x" * 100)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private_file(path)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        private_file(path, maximum=10)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_file(link)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://example.com/example",
        "host=localhost hostaddr=192.0.2.1 dbname=example",
        "service=example",
    ],
)
def test_local_gateway_rejects_remote_or_indirect_database(dsn, monkeypatch) -> None:
    from fdai.delivery.kubernetes_connector_runtime import validate_connector_database_venue

    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")
    with pytest.raises(ValueError):
        validate_connector_database_venue(dsn)
    validate_connector_database_venue("host=127.0.0.1 dbname=example")

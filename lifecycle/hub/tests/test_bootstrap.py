from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_lifecycle_hub import bootstrap


@pytest.fixture
def config():
    return bootstrap.BootstrapConfig(
        database_host="example.postgres.database.azure.com",
        database_name="release_hub",
        runtime_name="id-example-release",
        runtime_object_id="00000000-0000-0000-0000-000000000001",
        bootstrap_name="id-example-bootstrap",
        bootstrap_client_id="00000000-0000-0000-0000-000000000002",
        vault_uri="https://example.vault.azure.net/",
    )


@pytest.fixture
def backend(monkeypatch, config):
    credential = MagicMock()
    credential.__enter__.return_value = credential
    credential.get_token.return_value = SimpleNamespace(token="synthetic-not-a-real-token")
    monkeypatch.setattr(bootstrap, "ManagedIdentityCredential", lambda **kwargs: credential)
    connection, cursor = MagicMock(), MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [(config.runtime_object_id,)]
    cursor.fetchone.return_value = None
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(bootstrap.psycopg, "connect", connect)
    records, writes = {}, []

    def handle(request):
        name = request.url.path.split("/")[2]
        if request.method == "PUT":
            import json

            writes.append(name)
            records[name] = json.loads(request.content)["value"]
        if name not in records:
            return httpx.Response(404)
        return httpx.Response(200, json={"value": records[name], "attributes": {"enabled": True}})

    client = httpx.Client(base_url=config.vault_uri, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(bootstrap.httpx, "Client", lambda **kwargs: client)
    return SimpleNamespace(cursor=cursor, records=records, writes=writes, connect=connect)


def test_fresh_bootstrap_creates_only_app_data(config, backend):
    backend.cursor.fetchall.side_effect = [[], [(config.runtime_object_id,)]]
    bootstrap.initialize(config)
    assert backend.writes == ["hub-database-url", "development-signing-key"]
    key = serialization.load_pem_private_key(
        backend.records["development-signing-key"].encode(), password=None
    )
    assert isinstance(key, Ed25519PrivateKey)
    statements = [str(call.args[0]) for call in backend.cursor.execute.call_args_list]
    assert any("pgaadauth_create_principal_with_oid" in statement for statement in statements)
    assert any("GRANT USAGE, CREATE" in statement for statement in statements)
    assert not any("DROP" in statement or "ALTER ROLE" in statement for statement in statements)
    assert backend.connect.call_args.kwargs["sslmode"] == "verify-full"
    assert backend.connect.call_args.kwargs["sslrootcert"] == "/etc/ssl/certs/ca-certificates.crt"


def test_existing_matching_bootstrap_does_not_overwrite(config, backend):
    key = (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    backend.records.update(
        {"hub-database-url": config.database_url, "development-signing-key": key}
    )
    backend.cursor.fetchall.return_value = [(config.runtime_object_id,)]
    bootstrap.initialize(config)
    assert backend.writes == []
    assert not any(
        "pgaadauth_create_principal_with_oid" in str(call.args[0])
        for call in backend.cursor.execute.call_args_list
    )


@pytest.mark.parametrize("conflict", ["principal", "unbound_role", "database", "key"])
def test_partial_or_conflicting_state_is_not_replaced(config, backend, conflict):
    if conflict == "principal":
        backend.cursor.fetchall.return_value = [("00000000-0000-0000-0000-000000000003",)]
    elif conflict == "unbound_role":
        backend.cursor.fetchall.return_value = []
        backend.cursor.fetchone.return_value = (1,)
    elif conflict == "database":
        backend.records["hub-database-url"] = "synthetic-conflicting-value"
    else:
        backend.records.update(
            {"hub-database-url": config.database_url, "development-signing-key": "invalid-key"}
        )
    with pytest.raises(ValueError):
        bootstrap.initialize(config)
    assert backend.writes == []


def test_expected_error_does_not_echo_configuration(monkeypatch, capsys):
    monkeypatch.setenv("FDAI_HUB_BOOTSTRAP_CONFIG", "synthetic-sensitive-marker")
    with pytest.raises(SystemExit) as error:
        bootstrap.main()
    assert "synthetic-sensitive-marker" not in str(error.value)
    assert "synthetic-sensitive-marker" not in capsys.readouterr().err


def test_secret_failure_has_no_success_shaped_fallback():
    with httpx.Client(
        base_url="https://example.vault.azure.net/",
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    ) as client:
        with pytest.raises(ValueError, match="initialization failed"):
            bootstrap._secret(client, "hub-database-url", "synthetic-value")


def test_failed_principal_readback_stops_before_secrets(config, backend):
    backend.cursor.fetchall.side_effect = [[], []]
    with pytest.raises(ValueError, match="readback"):
        bootstrap.initialize(config)
    assert backend.writes == []

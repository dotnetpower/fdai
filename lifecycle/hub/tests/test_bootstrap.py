from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_lifecycle_hub import bootstrap


@pytest.fixture(params=["release_hub", "target_hub"])
def config(request):
    return bootstrap.BootstrapConfig(
        database_host="example.postgres.database.azure.com",
        database_name=request.param,
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
    database_connection, database_cursor = MagicMock(), MagicMock()
    database_connection.__enter__.return_value = database_connection
    database_connection.cursor.return_value.__enter__.return_value = database_cursor
    principal_session = {"open": False}

    def enter_principal():
        principal_session["open"] = True
        return connection

    def exit_principal(*args):
        principal_session["open"] = False

    connection.__enter__.side_effect = enter_principal
    connection.__exit__.side_effect = exit_principal

    def execute_database(statement, *args):
        assert principal_session["open"], "Bootstrap must retain its principal session lock."
        assert "pgaadauth_" not in str(statement), "Principal management requires postgres."

    database_cursor.execute.side_effect = execute_database
    connect = MagicMock(
        side_effect=lambda **kwargs: (
            connection if kwargs["dbname"] == "postgres" else database_connection
        )
    )
    monkeypatch.setattr(bootstrap.psycopg, "connect", connect)
    records, writes = {}, []

    def handle(request):
        assert principal_session["open"], "Secret initialization must retain the DB lock."
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
    return SimpleNamespace(
        cursor=cursor,
        database_cursor=database_cursor,
        records=records,
        writes=writes,
        connect=connect,
        principal_session=principal_session,
    )


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
    grants = [str(call.args[0]) for call in backend.database_cursor.execute.call_args_list]
    assert any("GRANT USAGE, CREATE" in statement for statement in grants)
    assert not any("DROP" in statement or "ALTER ROLE" in statement for statement in statements)
    assert [call.kwargs["dbname"] for call in backend.connect.call_args_list] == [
        "postgres",
        config.database_name,
    ]
    assert backend.connect.call_args_list[0].kwargs["autocommit"] is True
    assert backend.connect.call_args_list[1].kwargs["autocommit"] is False
    assert "pg_advisory_lock(" in statements[0]
    assert not any("GRANT" in statement for statement in statements)
    assert backend.principal_session["open"] is False
    for call in backend.connect.call_args_list:
        assert call.kwargs["sslmode"] == "verify-full"
        assert call.kwargs["sslrootcert"] == "/etc/ssl/certs/ca-certificates.crt"


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
    assert backend.principal_session["open"] is False


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
    assert backend.connect.call_count == 1
    assert backend.principal_session["open"] is False


def test_contended_principal_lock_stops_before_catalog_or_schema_work(config, backend):
    backend.cursor.execute.side_effect = bootstrap.psycopg.errors.LockNotAvailable(
        "synthetic-lock-contention"
    )
    with pytest.raises(bootstrap.psycopg.errors.LockNotAvailable):
        bootstrap.initialize(config)
    assert backend.cursor.execute.call_count == 1
    assert backend.connect.call_count == 1
    assert backend.writes == []
    assert backend.principal_session["open"] is False


def test_failed_product_connection_releases_principal_session(config, backend):
    principal = backend.connect(dbname="postgres")
    backend.connect.reset_mock()

    def connect(**kwargs):
        if kwargs["dbname"] == "postgres":
            return principal
        raise bootstrap.psycopg.OperationalError("synthetic-product-unavailable")

    backend.connect.side_effect = connect
    with pytest.raises(bootstrap.psycopg.OperationalError):
        bootstrap.initialize(config)
    assert backend.writes == []
    assert backend.principal_session["open"] is False

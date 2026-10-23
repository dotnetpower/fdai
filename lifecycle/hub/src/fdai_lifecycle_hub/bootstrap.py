"""Bounded, app-owned PostgreSQL and Key Vault initialization; no resource orchestration."""

from __future__ import annotations

import logging
import os
import re
from uuid import UUID

import httpx
import psycopg
from azure.core.exceptions import AzureError
from azure.identity import ManagedIdentityCredential
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)


class BootstrapRejectedError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__("Hub bootstrap rejected.")
        self.reason = reason


class BootstrapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    database_host: str
    database_name: str
    runtime_name: str
    runtime_object_id: str
    bootstrap_name: str
    bootstrap_client_id: str
    vault_uri: str

    @model_validator(mode="after")
    def validate_boundaries(self) -> BootstrapConfig:
        if not re.fullmatch(r"[a-z0-9-]+\.postgres\.database\.azure\.com", self.database_host):
            raise ValueError("Bootstrap requires an explicitly bound Azure PostgreSQL host.")
        if not re.fullmatch(r"https://[a-z0-9-]+\.vault\.azure\.net/", self.vault_uri):
            raise ValueError("Bootstrap requires an explicitly bound Azure Key Vault.")
        for name in (self.runtime_name, self.bootstrap_name, self.database_name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,62}", name):
                raise ValueError("Bootstrap role and database names must be bounded identifiers.")
        UUID(self.runtime_object_id)
        UUID(self.bootstrap_client_id)
        if self.runtime_name == self.bootstrap_name:
            raise ValueError("Bootstrap and runtime identities must be distinct.")
        return self

    @property
    def database_url(self) -> str:
        return URL.create(
            "postgresql+psycopg",
            username=self.runtime_name,
            host=self.database_host,
            database=self.database_name,
            query={
                "sslmode": "verify-full",
                "sslrootcert": "/etc/ssl/certs/ca-certificates.crt",
            },
        ).render_as_string(hide_password=False)


def _secret(client: httpx.Client, name: str, value: str | None = None) -> str | None:
    response = client.get(f"secrets/{name}", params={"api-version": "7.4"})
    if response.status_code == 404:
        if value is None:
            return None
        response = client.put(
            f"secrets/{name}",
            params={"api-version": "7.4"},
            json={"value": value, "attributes": {"enabled": True}},
        )
        if response.status_code != 200:
            raise BootstrapRejectedError("vault-secret-create")
        response = client.get(f"secrets/{name}", params={"api-version": "7.4"})
    if response.status_code != 200:
        raise BootstrapRejectedError("vault-secret-read")
    record = response.json()
    if not isinstance(record, dict) or not isinstance(record.get("attributes"), dict):
        raise BootstrapRejectedError("vault-secret-record")
    if record["attributes"].get("enabled") is not True:
        raise BootstrapRejectedError("vault-secret-disabled")
    stored = record.get("value")
    if not isinstance(stored, str):
        raise BootstrapRejectedError("vault-secret-value")
    if value is not None and stored != value:
        raise BootstrapRejectedError("vault-secret-conflict")
    return stored


def _connect(
    config: BootstrapConfig, token: str, database: str, *, autocommit: bool
) -> psycopg.Connection:
    return psycopg.connect(
        host=config.database_host,
        dbname=database,
        user=config.bootstrap_name,
        password=token,
        autocommit=autocommit,
        sslmode="verify-full",
        sslrootcert="/etc/ssl/certs/ca-certificates.crt",
        connect_timeout=5,
        options=(
            "-c statement_timeout=10000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=60000"
        ),
    )


def _principal_object_ids(cursor: psycopg.Cursor[tuple[object, ...]], role_name: str) -> list[str]:
    cursor.execute(
        "SELECT to_jsonb(principal) FROM pg_catalog.pgaadauth_list_principals(false) AS principal"
    )
    object_ids: list[str] = []
    for row in cursor.fetchall():
        record = row[0]
        if not isinstance(record, dict) or not all(isinstance(key, str) for key in record):
            raise BootstrapRejectedError("principal-catalog-record")
        normalized = {key.casefold(): value for key, value in record.items()}
        catalog_role = normalized.get("rolename")
        if not isinstance(catalog_role, str):
            raise BootstrapRejectedError("principal-catalog-schema")
        if catalog_role != role_name:
            continue
        object_id = normalized.get("objectid")
        if not isinstance(object_id, str):
            raise BootstrapRejectedError("principal-object-id")
        try:
            object_ids.append(str(UUID(object_id)))
        except ValueError as error:
            raise BootstrapRejectedError("principal-object-id") from error
    return object_ids


def initialize(config: BootstrapConfig) -> None:
    """Hold a postgres session lock across principal, product-schema and secret initialization."""
    with ManagedIdentityCredential(
        client_id=config.bootstrap_client_id,
        connection_timeout=5,
        read_timeout=5,
        retry_total=0,
    ) as credential:
        token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
        with _connect(config, token, "postgres", autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(hashtext('fdai_hub_bootstrap'))")
                principals = _principal_object_ids(cursor, config.runtime_name)
                if principals:
                    if len(principals) != 1 or UUID(principals[0]) != UUID(
                        config.runtime_object_id
                    ):
                        raise BootstrapRejectedError("principal-conflict")
                else:
                    cursor.execute(
                        "SELECT 1 FROM pg_roles WHERE rolname = %s", (config.runtime_name,)
                    )
                    if cursor.fetchone():
                        raise BootstrapRejectedError("principal-unbound-role")
                    cursor.execute(
                        "SELECT * FROM pg_catalog.pgaadauth_create_principal_with_oid"
                        "(%s, %s, 'service', false, false)",
                        (config.runtime_name, config.runtime_object_id),
                    )
                    created = _principal_object_ids(cursor, config.runtime_name)
                    if len(created) != 1 or UUID(created[0]) != UUID(config.runtime_object_id):
                        raise BootstrapRejectedError("principal-readback")
            with _connect(config, token, config.database_name, autocommit=False) as database:
                with database.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                            sql.Identifier(config.database_name),
                            sql.Identifier(config.runtime_name),
                        )
                    )
                    cursor.execute(
                        sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                            sql.Identifier(config.runtime_name)
                        )
                    )
                    vault_token = credential.get_token("https://vault.azure.net/.default").token
                    with httpx.Client(
                        base_url=config.vault_uri,
                        headers={"Authorization": f"Bearer {vault_token}"},
                        timeout=httpx.Timeout(10, connect=5),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        _secret(client, "hub-database-url", config.database_url)
                        existing = _secret(client, "development-signing-key")
                        if existing is None:
                            key = Ed25519PrivateKey.generate()
                            value = key.private_bytes(
                                serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption(),
                            ).decode()
                            _secret(client, "development-signing-key", value)
                        else:
                            existing_key = serialization.load_pem_private_key(
                                existing.encode(), password=None
                            )
                            if not isinstance(existing_key, Ed25519PrivateKey):
                                raise BootstrapRejectedError("signing-key-type")
    logger.info("hub_bootstrap_completed")


def main() -> None:
    try:
        raw = os.environ.get("FDAI_HUB_BOOTSTRAP_CONFIG", "")
        if len(raw) > 16384:
            raise ValueError("Bootstrap configuration is too large.")
        initialize(BootstrapConfig.model_validate_json(raw))
    except BootstrapRejectedError as error:
        logger.error("hub_bootstrap_rejected category=BootstrapRejected reason=%s", error.reason)
        raise SystemExit(
            "Hub bootstrap rejected; inspect private configuration and audit."
        ) from None
    except (ValueError, TypeError, AzureError, psycopg.Error, httpx.HTTPError) as error:
        logger.error("hub_bootstrap_rejected category=%s", type(error).__name__)
        raise SystemExit(
            "Hub bootstrap rejected; inspect private configuration and audit."
        ) from None


if __name__ == "__main__":
    main()

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
            raise ValueError("Key Vault secret creation failed; inspect the private service audit.")
        response = client.get(f"secrets/{name}", params={"api-version": "7.4"})
    if response.status_code != 200:
        raise ValueError("Key Vault initialization failed; inspect the private service audit.")
    record = response.json()
    if not isinstance(record, dict) or not isinstance(record.get("attributes"), dict):
        raise ValueError("Key Vault returned an invalid Hub secret record.")
    if record["attributes"].get("enabled") is not True:
        raise ValueError("Existing Hub secret is disabled; explicit repair is required.")
    stored = record.get("value")
    if not isinstance(stored, str):
        raise ValueError("Key Vault returned an invalid Hub secret.")
    if value is not None and stored != value:
        raise ValueError("Existing Hub secret conflicts with the bound runtime; not overwritten.")
    return stored


def initialize(config: BootstrapConfig) -> None:
    """Serialize initializers on the DB; preserve matching roles/secrets and reject conflicts."""
    with ManagedIdentityCredential(
        client_id=config.bootstrap_client_id,
        connection_timeout=5,
        read_timeout=5,
        retry_total=0,
    ) as credential:
        token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
        with psycopg.connect(
            host=config.database_host,
            dbname=config.database_name,
            user=config.bootstrap_name,
            password=token,
            sslmode="verify-full",
            sslrootcert="/etc/ssl/certs/ca-certificates.crt",
            connect_timeout=5,
            options=(
                "-c statement_timeout=10000 -c lock_timeout=5000 "
                "-c idle_in_transaction_session_timeout=60000"
            ),
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('fdai_hub_bootstrap'))")
                cursor.execute(
                    'SELECT "objectId" FROM pg_catalog.pgaadauth_list_principals(false) '
                    "WHERE rolename = %s",
                    (config.runtime_name,),
                )
                principals = cursor.fetchall()
                if principals:
                    if len(principals) != 1 or UUID(principals[0][0]) != UUID(
                        config.runtime_object_id
                    ):
                        raise ValueError("Existing runtime principal conflicts; not replaced.")
                else:
                    cursor.execute(
                        "SELECT 1 FROM pg_roles WHERE rolname = %s", (config.runtime_name,)
                    )
                    if cursor.fetchone():
                        raise ValueError("Unbound runtime role already exists; not adopted.")
                    cursor.execute(
                        "SELECT * FROM pg_catalog.pgaadauth_create_principal_with_oid"
                        "(%s, %s, 'service', false, false)",
                        (config.runtime_name, config.runtime_object_id),
                    )
                    cursor.execute(
                        'SELECT "objectId" FROM pg_catalog.pgaadauth_list_principals(false) '
                        "WHERE rolename = %s",
                        (config.runtime_name,),
                    )
                    created = cursor.fetchall()
                    if len(created) != 1 or UUID(created[0][0]) != UUID(config.runtime_object_id):
                        raise ValueError(
                            "Runtime principal readback failed; initialization stopped."
                        )
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(config.database_name), sql.Identifier(config.runtime_name)
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
                            raise ValueError("Existing signing key is not Ed25519; not replaced.")
    logger.info("hub_bootstrap_completed")


def main() -> None:
    try:
        raw = os.environ.get("FDAI_HUB_BOOTSTRAP_CONFIG", "")
        if len(raw) > 16384:
            raise ValueError("Bootstrap configuration is too large.")
        initialize(BootstrapConfig.model_validate_json(raw))
    except (ValueError, TypeError, AzureError, psycopg.Error, httpx.HTTPError) as error:
        logger.error("hub_bootstrap_rejected category=%s", type(error).__name__)
        raise SystemExit(
            "Hub bootstrap rejected; inspect private configuration and audit."
        ) from None


if __name__ == "__main__":
    main()

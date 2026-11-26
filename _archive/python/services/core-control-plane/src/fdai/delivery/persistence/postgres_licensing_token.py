"""Core-owned immutable full-entitlement acceptance and matching private audit."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.licensing.entitlement import (
    EntitlementSourceUnavailableError,
    LicenseEntitlementAuthority,
)
from fdai.core.licensing.entitlement_source import (
    EntitlementAcceptance,
    EntitlementAcceptanceConflictError,
    acceptance_identity,
    admitted_installation_entitlement,
    entitlement_token_digest,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ACTOR = "fdai.licensing-owner.import"
_SELECT = """
SELECT accepted.token_value, accepted.token_digest, accepted.acceptance_id, accepted.accepted_at,
       audit.token_digest AS audit_digest, audit.accepted_at AS audit_at, audit.actor
  FROM licensing_accepted_entitlement AS accepted
  LEFT JOIN licensing_entitlement_acceptance_audit AS audit
    ON audit.acceptance_id = accepted.acceptance_id
 WHERE accepted.installation_binding = %s AND accepted.deployment_binding = %s
"""


class PostgresAcceptedEntitlementStore:
    """Accept one exact original grant; duplicates read the same immutable receipt."""

    def __init__(
        self,
        *,
        dsn: str,
        installation_binding: str,
        deployment_binding: str,
        statement_timeout_ms: int = 5000,
        connect_timeout_s: int = 5,
    ) -> None:
        if not dsn.strip():
            raise ValueError("accepted entitlement source requires its Core database")
        if any(
            _DIGEST.fullmatch(value) is None for value in (installation_binding, deployment_binding)
        ):
            raise ValueError("accepted entitlement source requires exact binding digests")
        if statement_timeout_ms <= 0 or connect_timeout_s <= 0:
            raise ValueError("accepted entitlement source timeouts must be positive")
        self._dsn = dsn
        self._installation = installation_binding
        self._deployment = deployment_binding
        self._statement_timeout = int(statement_timeout_ms)
        self._connect_timeout = int(connect_timeout_s)

    def accept(
        self, token: str, *, authority: LicenseEntitlementAuthority, now: datetime
    ) -> EntitlementAcceptance:
        """Verify before storage and atomically create the immutable record and audit."""
        digest = entitlement_token_digest(token)
        claims = admitted_installation_entitlement(token, authority=authority, now=now)
        if (
            claims.installation_binding != self._installation
            or claims.deployment_binding != self._deployment
        ):
            raise ValueError("accepted entitlement store differs from the verified installation")
        identity = acceptance_identity(
            claims.installation_binding, claims.deployment_binding, digest
        )
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout, row_factory=dict_row
                ) as connection,
                connection.transaction(),
            ):
                self._timeout(connection)
                inserted = connection.execute(
                    """
                    INSERT INTO licensing_accepted_entitlement
                      (installation_binding, deployment_binding, token_value, token_digest,
                       acceptance_id, accepted_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT DO NOTHING
                    RETURNING accepted_at
                    """,
                    (self._installation, self._deployment, token, digest, identity),
                ).fetchone()
                if inserted is not None:
                    connection.execute(
                        """
                        INSERT INTO licensing_entitlement_acceptance_audit
                          (acceptance_id, installation_binding, deployment_binding,
                           token_digest, accepted_at, actor)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            identity,
                            self._installation,
                            self._deployment,
                            digest,
                            inserted["accepted_at"],
                            _ACTOR,
                        ),
                    )
                row = connection.execute(_SELECT, (self._installation, self._deployment)).fetchone()
                if row is None:
                    raise EntitlementSourceUnavailableError("accepted entitlement did not commit")
                receipt = self._receipt(row)
                if receipt.token_digest != digest:
                    raise EntitlementAcceptanceConflictError(
                        "a different original entitlement is already authoritative"
                    )
                return receipt
        except psycopg.Error as exc:
            raise EntitlementSourceUnavailableError("accepted entitlement storage failed") from exc

    def read(self) -> str | None:
        """Read current committed bytes, never activating, rotating or repairing a record."""
        snapshot = self._snapshot()
        return None if snapshot is None else snapshot[0]

    def inspect(self) -> EntitlementAcceptance | None:
        """Independently read the original safe receipt after an uncertain delivery."""
        snapshot = self._snapshot()
        return None if snapshot is None else snapshot[1]

    def _snapshot(self) -> tuple[str, EntitlementAcceptance] | None:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout, row_factory=dict_row
                ) as connection,
                connection.transaction(),
            ):
                connection.execute("SET TRANSACTION READ ONLY")
                self._timeout(connection)
                row = connection.execute(_SELECT, (self._installation, self._deployment)).fetchone()
                if row is None:
                    return None
                receipt = self._receipt(row)
                token = row["token_value"]
                if not isinstance(token, str):
                    raise EntitlementSourceUnavailableError("accepted entitlement is malformed")
                return token, receipt
        except psycopg.Error as exc:
            raise EntitlementSourceUnavailableError("accepted entitlement storage failed") from exc

    def _timeout(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute(f"SET LOCAL statement_timeout = {self._statement_timeout}")

    def _receipt(self, row: dict[str, Any]) -> EntitlementAcceptance:
        token = row["token_value"]
        digest = row["token_digest"]
        identity = row["acceptance_id"]
        at = row["accepted_at"]
        if (
            not isinstance(token, str)
            or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None
            or not isinstance(identity, str)
            or _DIGEST.fullmatch(identity) is None
            or not isinstance(at, datetime)
            or at.utcoffset() is None
            or row["audit_digest"] != digest
            or row["audit_at"] != at
            or row["actor"] != _ACTOR
        ):
            raise EntitlementSourceUnavailableError("accepted entitlement and audit conflict")
        try:
            actual_digest = entitlement_token_digest(token)
        except ValueError as exc:
            raise EntitlementSourceUnavailableError("accepted entitlement is malformed") from exc
        if actual_digest != digest:
            raise EntitlementSourceUnavailableError("accepted entitlement bytes conflict")
        expected_identity = acceptance_identity(self._installation, self._deployment, digest)
        if identity != expected_identity:
            raise EntitlementSourceUnavailableError("accepted entitlement identity conflicts")
        return EntitlementAcceptance(identity, digest, at)

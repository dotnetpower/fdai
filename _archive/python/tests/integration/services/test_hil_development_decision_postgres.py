"""The PostgreSQL decision transaction guards a parked category-only denial on a real database.

Only the development Owner's freshly attested self-approval may approve it, any authorized
approver, including that Owner, may reject it, and a value other than approve or reject never
reaches the receipt or the outbox.
"""

from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai_operator_service.families.iam.hil_development_approval import (
    development_attestation,
    development_metadata,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.postgres_hil_decision import (
    PostgresHilDecisionPermissionError,
    PostgresHilDecisionStore,
)
from fdai_service_contracts import OperatorRole

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database, _role = _support["database"], _support["_role"]

pytestmark = pytest.mark.integration

OWNER = "00000000-0000-0000-0000-00000000a001"
APPROVER = "00000000-0000-0000-0000-00000000a002"


def _owner_only_park(approval_id: str, parked_at: datetime) -> dict[str, Any]:
    expires_at = (parked_at + timedelta(minutes=30)).isoformat()
    return {
        "approval_id": approval_id,
        "status": "pending",
        "idempotency_key": f"idem-{approval_id}",
        "request_fingerprint": f"hash-{approval_id}",
        "submitter_oid": OWNER,
        "parked_at": parked_at.isoformat(),
        "approval_context": {"expires_at": expires_at},
        "development_authority": {
            "owner_principal": OWNER,
            "block_digest": "sha256:" + "a" * 64,
            "binding_digest": "sha256:" + "b" * 64,
            "profile_digest": "sha256:" + "c" * 64,
            "expires_at": expires_at,
            "original_level": "deny",
            "owner_self_approval_only": True,
        },
    }


def _receipt(dsn: str, approval_id: str) -> dict[str, Any] | None:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT value FROM state_kv WHERE key = %s",
            (f"operator-hil-decision:{approval_id}",),
        ).fetchone()
    return None if row is None else dict(row[0])


async def test_the_decision_transaction_guards_an_owner_only_park(database: str) -> None:
    parked_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    parks = {name: _owner_only_park(name, parked_at) for name in ("refused", "owner", "approver")}
    with psycopg.connect(database) as connection:
        for name, park in parks.items():
            connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                (f"hil_park:{name}", json.dumps(park)),
            )
    store = PostgresHilDecisionStore(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )

    async def decide(
        name: str,
        decision: str,
        approver: str,
        attestation: dict[str, object] | None = None,
    ) -> Any:
        return await store.append_hil_decision(
            approval_id=name,
            idempotency_key=f"idem-{name}",
            action_hash=f"hash-{name}",
            decision=decision,
            approver_oid=approver,
            approver_roles=frozenset(
                {OperatorRole.OWNER if approver == OWNER else OperatorRole.APPROVER}
            ),
            justification="Reviewed the exact development action.",
            decided_at=datetime.now(UTC),
            expected_expires_at=parked_at + timedelta(minutes=30),
            expected_submitter_oid=OWNER,
            expected_decision_route="action",
            expected_required_role="",
            **({"development_attestation": attestation} if attestation is not None else {}),
        )

    for decision, approver in (("pending", APPROVER), ("timeout", OWNER)):
        with pytest.raises(ValueError, match="approve or reject"):
            await decide("refused", decision, approver)
    with pytest.raises(PostgresHilDecisionPermissionError, match="development Owner"):
        await decide("refused", "approve", APPROVER)
    with pytest.raises(PostgresHilDecisionPermissionError, match="own request"):
        await decide("refused", "approve", OWNER)
    assert _receipt(database, "refused") is None

    attested = development_attestation(
        claims={"oid": OWNER, "auth_time": int(parked_at.timestamp()) + 30, "uti": "token-1"},
        actor_oid=OWNER,
        actor_roles=frozenset({OperatorRole.OWNER}),
        approval_id="owner",
        metadata=development_metadata(parks["owner"]),
        now=datetime.now(UTC),
    )
    assert attested is not None
    await decide("owner", "approve", OWNER, attested.model_dump(mode="json"))
    await decide("refused", "reject", OWNER)
    await decide("approver", "reject", APPROVER)

    owner_receipt = _receipt(database, "owner")
    assert owner_receipt is not None
    assert (owner_receipt["decision"], owner_receipt["approver_oid"]) == ("approve", OWNER)
    assert owner_receipt["development_attestation"]["authenticated_principal"] == OWNER
    for name, approver in (("refused", OWNER), ("approver", APPROVER)):
        receipt = _receipt(database, name)
        assert receipt is not None
        assert (receipt["decision"], receipt["approver_oid"]) == ("reject", approver)

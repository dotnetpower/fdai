"""Validate one authority-free Teams A1 onboarding proposal for protected planning.

The Console `Prepare Teams connection` button records a durable, no-authority
`plan-requested` proposal plus the `operator-teams-a1-onboarding-plan:current`
state snapshot. This module is the protected deployment runner's consumer: it
re-reads that exact durable pair, revalidates every fence the Operator wrote,
and resolves one deterministic provisioning action. It never mutates Azure,
Teams, or the Operator database; a mismatch fails closed with an explicit error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

import psycopg
from psycopg.rows import dict_row

_PROPOSAL_ID = re.compile(r"^operator-[0-9a-f]{32}$")
_ENVIRONMENT = re.compile(r"^(dev|staging|prod)$")
_OPERATION = "runtime-settings.teams-a1.plan"
_PLAN_STATE_KEY = "operator-teams-a1-onboarding-plan:current"

_PROPOSAL_KEYS = frozenset(
    {
        "accepted_at",
        "dispatch_status",
        "family",
        "idempotency_key",
        "kind",
        "mode",
        "operation",
        "payload",
        "principal_id",
        "proposal_id",
        "request_digest",
    }
)
_PAYLOAD_KEYS = frozenset({"actor_id", "environment", "idempotency_key"})
_PLAN_STATE_KEYS = frozenset(
    {
        "activation_boundary",
        "environment",
        "execution_authority",
        "revision",
        "state",
    }
)


def resolve_teams_a1_action(
    *,
    proposal: Mapping[str, object],
    plan_state: Mapping[str, object],
    expected_proposal_id: str,
    expected_environment: str,
) -> dict[str, str]:
    """Resolve one provisioning action only when every durable fence agrees."""
    if _PROPOSAL_ID.fullmatch(expected_proposal_id) is None:
        raise ValueError("Teams A1 proposal id is invalid")
    if _ENVIRONMENT.fullmatch(expected_environment) is None:
        raise ValueError("Teams A1 onboarding environment is invalid")
    _require_exact_keys(proposal, _PROPOSAL_KEYS, label="Teams A1 proposal")
    if proposal.get("proposal_id") != expected_proposal_id:
        raise ValueError("Teams A1 proposal id does not match the protected request")
    for key, expected in {
        "kind": "operator.proposal",
        "family": "iam",
        "operation": _OPERATION,
        "dispatch_status": "pending",
        "mode": "shadow",
    }.items():
        if proposal.get(key) != expected:
            raise ValueError(f"Teams A1 proposal {key} is invalid")
    accepted_at = _required_string(proposal, "accepted_at")
    try:
        accepted_timestamp = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Teams A1 proposal accepted_at is invalid") from exc
    if accepted_timestamp.tzinfo is None:
        raise ValueError("Teams A1 proposal accepted_at is invalid")

    principal_id = _required_string(proposal, "principal_id")
    idempotency_key = _required_string(proposal, "idempotency_key")
    payload = proposal.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("Teams A1 proposal payload must be an object")
    request = cast(Mapping[str, object], payload)
    _require_exact_keys(request, _PAYLOAD_KEYS, label="Teams A1 proposal payload")
    if request.get("actor_id") != principal_id:
        raise ValueError("Teams A1 proposal actor does not match its principal")
    if request.get("idempotency_key") != idempotency_key:
        raise ValueError("Teams A1 proposal idempotency key is inconsistent")
    if request.get("environment") != expected_environment:
        raise ValueError("Teams A1 proposal environment does not match the target")
    digest_source = {
        "family": "iam",
        "operation": _OPERATION,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": dict(request),
    }
    request_digest = hashlib.sha256(
        json.dumps(digest_source, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if proposal.get("request_digest") != request_digest:
        raise ValueError("Teams A1 proposal request digest is invalid")

    _require_exact_keys(plan_state, _PLAN_STATE_KEYS, label="Teams A1 plan state")
    _required_revision(plan_state, "revision")
    if (
        plan_state.get("state") != "plan-requested"
        or plan_state.get("environment") != expected_environment
        or plan_state.get("execution_authority") is not False
        or plan_state.get("activation_boundary") != "protected-plan-only"
    ):
        raise ValueError("Teams A1 plan state metadata is inconsistent")
    return {"action": "provision_teams_a1_approval", "environment": expected_environment}


def load_teams_a1_records(
    *, database_url: str, proposal_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Read one exact proposal plus the current Teams A1 onboarding plan state."""
    if _PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise ValueError("Teams A1 proposal id is invalid")
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise ValueError("Teams A1 database URL must use PostgreSQL")
    try:
        with psycopg.connect(dsn, connect_timeout=10, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL statement_timeout = '10s'")
                proposal_rows = connection.execute(
                    """
                    SELECT value
                      FROM state_kv
                     WHERE key LIKE 'operator-proposal:iam:%%'
                       AND value ->> 'proposal_id' = %s
                       AND value ->> 'operation' = %s
                     LIMIT 2
                    """,
                    (proposal_id, _OPERATION),
                ).fetchall()
                plan_rows = connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s LIMIT 2",
                    (_PLAN_STATE_KEY,),
                ).fetchall()
    except psycopg.Error as exc:
        raise ValueError("Teams A1 proposal database is unavailable") from exc
    return (
        _one_json_value(proposal_rows, label="Teams A1 proposal"),
        _one_json_value(plan_rows, label="Teams A1 plan state"),
    )


def _one_json_value(rows: Sequence[Mapping[str, object]], *, label: str) -> dict[str, object]:
    if len(rows) != 1:
        raise ValueError(f"{label} lookup must return exactly one row")
    value = rows[0].get("value")
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} database value must be an object")
    return dict(value)


def _require_exact_keys(
    value: Mapping[str, object], expected: frozenset[str], *, label: str
) -> None:
    if frozenset(value) != expected:
        raise ValueError(f"{label} fields are invalid")


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result or len(result) > 256:
        raise ValueError(f"Teams A1 proposal {key} is invalid")
    return result


def _required_revision(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ValueError(f"Teams A1 {key} is invalid")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-database", action="store_true")
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.from_database:
        raise SystemExit("--from-database is required")
    proposal, plan_state = load_teams_a1_records(
        database_url=os.environ.get("FDAI_DATABASE_URL", ""),
        proposal_id=args.proposal_id,
    )
    result = resolve_teams_a1_action(
        proposal=proposal,
        plan_state=plan_state,
        expected_proposal_id=args.proposal_id,
        expected_environment=args.environment,
    )
    args.output.write_text(
        json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

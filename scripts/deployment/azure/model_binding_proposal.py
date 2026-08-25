"""Validate one authority-free model binding proposal for protected planning."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

import psycopg
from fdai_service_contracts.model_binding import ModelBindingPolicy
from psycopg.rows import dict_row

_PROPOSAL_ID = re.compile(r"^operator-[0-9a-f]{32}$")
_MAX_INPUT_BYTES = 65_536
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
_REQUEST_KEYS = frozenset(
    {
        "actor_id",
        "environment",
        "idempotency_key",
        "policy_digest",
        "policy_revision",
    }
)
_STATE_KEYS = frozenset(
    {
        "activation_boundary",
        "environment",
        "execution_authority",
        "policy",
        "policy_digest",
        "revision",
        "state",
    }
)


def materialize_model_binding_policy(
    *,
    proposal: Mapping[str, object],
    state: Mapping[str, object],
    expected_proposal_id: str,
    expected_environment: str,
) -> dict[str, object]:
    """Return the exact policy only when proposal, state, and request fences agree."""
    if _PROPOSAL_ID.fullmatch(expected_proposal_id) is None:
        raise ValueError("model binding proposal id is invalid")
    _require_exact_keys(proposal, _PROPOSAL_KEYS, label="model binding proposal")
    if proposal.get("proposal_id") != expected_proposal_id:
        raise ValueError("model binding proposal id does not match the protected request")
    expected_proposal_values = {
        "kind": "operator.proposal",
        "family": "iam",
        "operation": "model-settings.binding-policy.plan",
        "dispatch_status": "pending",
        "mode": "shadow",
    }
    for key, expected in expected_proposal_values.items():
        if proposal.get(key) != expected:
            raise ValueError(f"model binding proposal {key} is invalid")
    accepted_at = _required_string(proposal, "accepted_at", max_length=64)
    try:
        accepted_timestamp = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("model binding proposal accepted_at is invalid") from exc
    if accepted_timestamp.tzinfo is None:
        raise ValueError("model binding proposal accepted_at is invalid")

    principal_id = _required_string(proposal, "principal_id", max_length=256)
    idempotency_key = _required_string(proposal, "idempotency_key", max_length=256)
    payload = proposal.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("model binding proposal payload must be an object")
    request = cast(Mapping[str, object], payload)
    _require_exact_keys(request, _REQUEST_KEYS, label="model binding proposal payload")
    if request.get("actor_id") != principal_id:
        raise ValueError("model binding proposal actor does not match its principal")
    if request.get("idempotency_key") != idempotency_key:
        raise ValueError("model binding proposal idempotency key is inconsistent")
    if request.get("environment") != expected_environment:
        raise ValueError("model binding proposal environment does not match the target")

    digest_source = {
        "family": "iam",
        "operation": "model-settings.binding-policy.plan",
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": dict(request),
    }
    request_digest = hashlib.sha256(
        json.dumps(digest_source, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if proposal.get("request_digest") != request_digest:
        raise ValueError("model binding proposal request digest is invalid")

    _require_exact_keys(state, _STATE_KEYS, label="model binding policy state")
    if state.get("state") != "draft":
        raise ValueError("model binding policy state is not a draft")
    if state.get("execution_authority") is not False:
        raise ValueError("model binding policy state grants execution authority")
    if state.get("activation_boundary") != "protected-plan-only":
        raise ValueError("model binding policy activation boundary is invalid")
    if state.get("environment") != expected_environment:
        raise ValueError("model binding policy environment does not match the target")

    policy_raw = state.get("policy")
    if not isinstance(policy_raw, Mapping):
        raise ValueError("model binding policy state has no policy object")
    policy = ModelBindingPolicy.model_validate(policy_raw)
    if policy.expected_active_digest is None:
        raise ValueError("model binding plan requires an active artifact digest fence")
    policy_digest = policy.digest()
    if (
        state.get("revision") != policy.revision
        or state.get("policy_digest") != policy_digest
        or state.get("environment") != policy.environment
    ):
        raise ValueError("model binding policy state metadata is inconsistent")
    if (
        request.get("policy_revision") != policy.revision
        or request.get("policy_digest") != policy_digest
    ):
        raise ValueError("model binding proposal does not match the current policy")
    return cast(dict[str, object], policy.model_dump(mode="json", exclude_none=True))


def load_model_binding_records(
    *,
    database_url: str,
    proposal_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Read one exact proposal and current policy state without database writes."""
    if _PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise ValueError("model binding proposal id is invalid")
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise ValueError("model binding database URL must use PostgreSQL")
    try:
        with psycopg.connect(dsn, connect_timeout=10, row_factory=dict_row) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL statement_timeout = '10s'")
                proposal_rows = connection.execute(
                    """
                    SELECT value
                      FROM state_kv
                     WHERE key LIKE 'operator-proposal:iam:%'
                       AND value ->> 'proposal_id' = %s
                       AND value ->> 'family' = 'iam'
                       AND value ->> 'operation' = 'model-settings.binding-policy.plan'
                     LIMIT 2
                    """,
                    (proposal_id,),
                ).fetchall()
                state_rows = connection.execute(
                    """
                    SELECT value
                      FROM state_kv
                     WHERE key = 'operator-model-binding-policy:current'
                     LIMIT 2
                    """
                ).fetchall()
    except psycopg.Error as exc:
        raise ValueError("model binding proposal database is unavailable") from exc
    proposal = _one_json_value(proposal_rows, label="model binding proposal")
    state = _one_json_value(state_rows, label="model binding policy state")
    return proposal, state


def _one_json_value(
    rows: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> dict[str, object]:
    if len(rows) != 1:
        raise ValueError(f"{label} lookup must return exactly one row")
    value = rows[0].get("value")
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} database value must be an object")
    return dict(value)


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ValueError(f"{label} fields are invalid")


def _required_string(
    value: Mapping[str, object],
    key: str,
    *,
    max_length: int,
) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > max_length:
        raise ValueError(f"model binding proposal {key} is invalid")
    return item


def _read_object(path: Path, *, label: str) -> dict[str, object]:
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds the input size limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], payload)


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-database", action="store_true")
    source.add_argument("--proposal", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate bounded JSON inputs and write one private canonical policy file."""
    args = _parser().parse_args(argv)
    if args.from_database:
        database_url = os.environ.get("FDAI_DATABASE_URL", "")
        if not database_url:
            raise SystemExit("FDAI_DATABASE_URL is required for database proposal loading")
        proposal, state = load_model_binding_records(
            database_url=database_url,
            proposal_id=args.proposal_id,
        )
    else:
        if args.state is None:
            raise SystemExit("--state is required with --proposal")
        proposal = _read_object(args.proposal, label="model binding proposal")
        state = _read_object(args.state, label="model binding policy state")
    policy = materialize_model_binding_policy(
        proposal=proposal,
        state=state,
        expected_proposal_id=args.proposal_id,
        expected_environment=args.environment,
    )
    _write_private_json(args.output, policy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

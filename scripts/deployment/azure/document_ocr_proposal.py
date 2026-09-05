"""Validate one authority-free document OCR proposal for protected planning."""

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
from fdai_service_contracts import DocumentOcrPolicy, DocumentOcrProvider
from psycopg.rows import dict_row

_PROPOSAL_ID = re.compile(r"^operator-[0-9a-f]{32}$")
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
_POLICY_STATE_KEYS = frozenset(
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
_PLAN_STATE_KEYS = frozenset(
    {
        "activation_boundary",
        "environment",
        "execution_authority",
        "policy_digest",
        "policy_revision",
        "revision",
        "state",
    }
)


def resolve_document_ocr_action(
    *,
    proposal: Mapping[str, object],
    policy_state: Mapping[str, object],
    plan_state: Mapping[str, object],
    expected_proposal_id: str,
    expected_environment: str,
) -> dict[str, str]:
    """Resolve one workflow action only when every durable fence agrees."""
    if _PROPOSAL_ID.fullmatch(expected_proposal_id) is None:
        raise ValueError("document OCR proposal id is invalid")
    _require_exact_keys(proposal, _PROPOSAL_KEYS, label="document OCR proposal")
    if proposal.get("proposal_id") != expected_proposal_id:
        raise ValueError("document OCR proposal id does not match the protected request")
    for key, expected in {
        "kind": "operator.proposal",
        "family": "iam",
        "operation": "model-settings.document-ocr.plan",
        "dispatch_status": "pending",
        "mode": "shadow",
    }.items():
        if proposal.get(key) != expected:
            raise ValueError(f"document OCR proposal {key} is invalid")
    accepted_at = _required_string(proposal, "accepted_at")
    try:
        accepted_timestamp = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("document OCR proposal accepted_at is invalid") from exc
    if accepted_timestamp.tzinfo is None:
        raise ValueError("document OCR proposal accepted_at is invalid")

    principal_id = _required_string(proposal, "principal_id")
    idempotency_key = _required_string(proposal, "idempotency_key")
    payload = proposal.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("document OCR proposal payload must be an object")
    request = cast(Mapping[str, object], payload)
    _require_exact_keys(request, _REQUEST_KEYS, label="document OCR proposal payload")
    if request.get("actor_id") != principal_id:
        raise ValueError("document OCR proposal actor does not match its principal")
    if request.get("idempotency_key") != idempotency_key:
        raise ValueError("document OCR proposal idempotency key is inconsistent")
    if request.get("environment") != expected_environment:
        raise ValueError("document OCR proposal environment does not match the target")
    digest_source = {
        "family": "iam",
        "operation": "model-settings.document-ocr.plan",
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": dict(request),
    }
    request_digest = hashlib.sha256(
        json.dumps(digest_source, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if proposal.get("request_digest") != request_digest:
        raise ValueError("document OCR proposal request digest is invalid")

    _require_exact_keys(policy_state, _POLICY_STATE_KEYS, label="document OCR policy state")
    policy_raw = policy_state.get("policy")
    if not isinstance(policy_raw, Mapping):
        raise ValueError("document OCR policy state has no policy object")
    policy = DocumentOcrPolicy.model_validate(policy_raw)
    if (
        policy_state.get("environment") != policy.environment
        or policy_state.get("revision") != policy.revision
        or policy_state.get("policy_digest") != policy.digest()
        or policy_state.get("state") not in {"plan-required", "plan-requested"}
        or policy_state.get("execution_authority") is not False
        or policy_state.get("activation_boundary") != "protected-plan-only"
    ):
        raise ValueError("document OCR policy state metadata is inconsistent")

    _require_exact_keys(plan_state, _PLAN_STATE_KEYS, label="document OCR plan state")
    _required_revision(plan_state, "revision")
    if (
        plan_state.get("state") != "plan-requested"
        or plan_state.get("environment") != policy.environment
        or plan_state.get("policy_revision") != policy.revision
        or plan_state.get("policy_digest") != policy.digest()
        or plan_state.get("execution_authority") is not False
        or plan_state.get("activation_boundary") != "protected-plan-only"
    ):
        raise ValueError("document OCR plan state metadata is inconsistent")
    if (
        request.get("policy_revision") != policy.revision
        or request.get("policy_digest") != policy.digest()
    ):
        raise ValueError("document OCR proposal does not match the current policy")
    if policy.desired_provider is DocumentOcrProvider.AZURE_DOCUMENT_INTELLIGENCE:
        action = "use_azure_provision"
    elif policy.deprovision_requested:
        action = "deprovision_use_local"
    else:
        action = "use_local_retain"
    return {"action": action, "policy_digest": policy.digest()}


def load_document_ocr_records(
    *, database_url: str, proposal_id: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Read one exact proposal plus current OCR policy and plan states."""
    if _PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise ValueError("document OCR proposal id is invalid")
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise ValueError("document OCR database URL must use PostgreSQL")
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
                       AND value ->> 'operation' = 'model-settings.document-ocr.plan'
                     LIMIT 2
                    """,
                    (proposal_id,),
                ).fetchall()
                policy_rows = connection.execute(
                    "SELECT value FROM state_kv "
                    "WHERE key = 'operator-document-ocr-policy:current' LIMIT 2"
                ).fetchall()
                plan_rows = connection.execute(
                    "SELECT value FROM state_kv "
                    "WHERE key = 'operator-document-ocr-plan:current' LIMIT 2"
                ).fetchall()
    except psycopg.Error as exc:
        raise ValueError("document OCR proposal database is unavailable") from exc
    return (
        _one_json_value(proposal_rows, label="document OCR proposal"),
        _one_json_value(policy_rows, label="document OCR policy state"),
        _one_json_value(plan_rows, label="document OCR plan state"),
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
        raise ValueError(f"document OCR proposal {key} is invalid")
    return result


def _required_revision(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ValueError(f"document OCR {key} is invalid")
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
    records = load_document_ocr_records(
        database_url=os.environ.get("FDAI_DATABASE_URL", ""),
        proposal_id=args.proposal_id,
    )
    result = resolve_document_ocr_action(
        proposal=records[0],
        policy_state=records[1],
        plan_state=records[2],
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

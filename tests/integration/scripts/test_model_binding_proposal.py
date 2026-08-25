from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

import psycopg
import pytest
from scripts.deployment.azure import model_binding_proposal as proposal_module
from scripts.deployment.azure.model_binding_proposal import (
    _one_json_value,
    load_model_binding_records,
    main,
    materialize_model_binding_policy,
)

_PROPOSAL_ID = "operator-" + "1" * 32
_ACTIVE_DIGEST = "sha256:" + "a" * 64


def _records() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = {
        "schema_version": "1.0.0",
        "environment": "dev",
        "revision": 3,
        "expected_active_digest": _ACTIVE_DIGEST,
        "capabilities": {"t2.reasoner.secondary": {"selection_mode": "hil-only"}},
    }
    canonical = json.dumps(policy, separators=(",", ":"), sort_keys=True).encode()
    policy_digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    payload = {
        "actor_id": "owner-1",
        "environment": "dev",
        "policy_revision": 3,
        "policy_digest": policy_digest,
        "idempotency_key": "plan-3",
    }
    request = {
        "family": "iam",
        "operation": "model-settings.binding-policy.plan",
        "principal_id": "owner-1",
        "idempotency_key": "plan-3",
        "payload": payload,
    }
    request_digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    proposal = {
        "kind": "operator.proposal",
        "proposal_id": _PROPOSAL_ID,
        "request_digest": request_digest,
        "dispatch_status": "pending",
        "mode": "shadow",
        "accepted_at": "2026-08-25T00:00:00+00:00",
        **request,
    }
    state = {
        "environment": "dev",
        "revision": 3,
        "state": "draft",
        "policy": policy,
        "policy_digest": policy_digest,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }
    return proposal, state


def test_materializes_exact_current_plan_policy() -> None:
    proposal, state = _records()

    policy = materialize_model_binding_policy(
        proposal=proposal,
        state=state,
        expected_proposal_id=_PROPOSAL_ID,
        expected_environment="dev",
    )

    assert policy == state["policy"]


@pytest.mark.parametrize(
    ("target", "key", "value", "message"),
    [
        ("proposal", "operation", "model-settings.binding-policy.assessment", "operation"),
        ("proposal", "dispatch_status", "claimed", "dispatch_status"),
        ("proposal", "mode", "enforce", "mode"),
        ("state", "execution_authority", True, "execution authority"),
        ("state", "activation_boundary", "runtime", "activation boundary"),
        ("state", "revision", 4, "metadata"),
    ],
)
def test_rejects_authority_and_fence_mismatches(
    target: str,
    key: str,
    value: object,
    message: str,
) -> None:
    proposal, state = _records()
    selected = proposal if target == "proposal" else state
    selected[key] = value

    with pytest.raises(ValueError, match=message):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


def test_rejects_tampered_request_digest() -> None:
    proposal, state = _records()
    proposal["payload"]["policy_revision"] = 4

    with pytest.raises(ValueError, match="request digest"):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


def test_rejects_stale_proposal_after_policy_revision() -> None:
    proposal, state = _records()
    stale = deepcopy(state)
    stale["policy"]["revision"] = 4
    stale["revision"] = 4
    canonical = json.dumps(stale["policy"], separators=(",", ":"), sort_keys=True).encode()
    stale["policy_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()

    with pytest.raises(ValueError, match="current policy"):
        materialize_model_binding_policy(
            proposal=proposal,
            state=stale,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


def test_rejects_policy_without_active_artifact_fence() -> None:
    proposal, state = _records()
    state["policy"].pop("expected_active_digest")
    canonical = json.dumps(state["policy"], separators=(",", ":"), sort_keys=True).encode()
    state["policy_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    proposal["payload"]["policy_digest"] = state["policy_digest"]
    request = {
        key: proposal[key]
        for key in ("family", "operation", "principal_id", "idempotency_key", "payload")
    }
    proposal["request_digest"] = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="active artifact digest"):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


def test_database_lookup_requires_one_object_row() -> None:
    proposal, _state = _records()

    assert _one_json_value([{"value": proposal}], label="proposal") == proposal
    with pytest.raises(ValueError, match="exactly one row"):
        _one_json_value([], label="proposal")
    with pytest.raises(ValueError, match="must be an object"):
        _one_json_value([{"value": []}], label="proposal")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda proposal, _state: proposal.update(proposal_id="operator-" + "2" * 32), "id"),
        (lambda proposal, _state: proposal.update(accepted_at="not-a-time"), "accepted_at"),
        (
            lambda proposal, _state: proposal.update(accepted_at="2026-08-25T00:00:00"),
            "accepted_at",
        ),
        (lambda proposal, _state: proposal.update(principal_id=""), "principal_id"),
        (lambda proposal, _state: proposal.update(payload=[]), "payload"),
        (lambda proposal, _state: proposal["payload"].update(actor_id="owner-2"), "actor"),
        (
            lambda proposal, _state: proposal["payload"].update(idempotency_key="other"),
            "idempotency",
        ),
        (lambda proposal, _state: proposal["payload"].update(environment="prod"), "environment"),
        (lambda _proposal, state: state.update(state="active"), "not a draft"),
        (lambda _proposal, state: state.update(environment="prod"), "environment"),
        (lambda _proposal, state: state.update(policy=[]), "policy object"),
    ],
)
def test_rejects_malformed_proposal_and_state_boundaries(mutation, message: str) -> None:
    proposal, state = _records()
    mutation(proposal, state)

    with pytest.raises(ValueError, match=message):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


def test_rejects_invalid_expected_id_and_unknown_fields() -> None:
    proposal, state = _records()
    with pytest.raises(ValueError, match="proposal id is invalid"):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id="proposal-1",
            expected_environment="dev",
        )
    proposal["unexpected"] = True
    with pytest.raises(ValueError, match="fields are invalid"):
        materialize_model_binding_policy(
            proposal=proposal,
            state=state,
            expected_proposal_id=_PROPOSAL_ID,
            expected_environment="dev",
        )


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self, proposal: dict[str, Any], state: dict[str, Any]) -> None:
        self.proposal = proposal
        self.state = state
        self.statements: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def transaction(self):
        return self

    def execute(self, statement: str, parameters: object = None) -> _Cursor:
        self.statements.append((statement, parameters))
        if "operator-proposal:iam" in statement:
            return _Cursor([{"value": self.proposal}])
        if "operator-model-binding-policy:current" in statement:
            return _Cursor([{"value": self.state}])
        return _Cursor([])


def test_database_loader_is_read_only_and_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    proposal, state = _records()
    connection = _Connection(proposal, state)
    connect_args: list[tuple[str, dict[str, object]]] = []

    def connect(dsn: str, **kwargs: object) -> _Connection:
        connect_args.append((dsn, kwargs))
        return connection

    monkeypatch.setattr(proposal_module.psycopg, "connect", connect)

    loaded = load_model_binding_records(
        database_url="postgresql+psycopg://example.invalid/fdai",
        proposal_id=_PROPOSAL_ID,
    )

    assert loaded == (proposal, state)
    assert connect_args[0][0] == "postgresql://example.invalid/fdai"
    assert connect_args[0][1]["connect_timeout"] == 10
    assert connection.statements[0][0] == "SET TRANSACTION READ ONLY"
    assert connection.statements[1][0] == "SET LOCAL statement_timeout = '10s'"
    assert connection.statements[2][1] == (_PROPOSAL_ID,)


def test_database_loader_rejects_invalid_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="proposal id is invalid"):
        load_model_binding_records(database_url="postgresql://example/db", proposal_id="bad")
    with pytest.raises(ValueError, match="must use PostgreSQL"):
        load_model_binding_records(database_url="https://example.invalid", proposal_id=_PROPOSAL_ID)

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError("sensitive provider detail")

    monkeypatch.setattr(proposal_module.psycopg, "connect", unavailable)
    with pytest.raises(ValueError, match="database is unavailable") as caught:
        load_model_binding_records(
            database_url="postgresql://example.invalid/fdai",
            proposal_id=_PROPOSAL_ID,
        )
    assert "sensitive provider detail" not in str(caught.value)


def _write_records(tmp_path: Path) -> tuple[Path, Path]:
    proposal, state = _records()
    proposal_path = tmp_path / "proposal.json"
    state_path = tmp_path / "state.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return proposal_path, state_path


def test_file_cli_writes_private_canonical_policy(tmp_path: Path) -> None:
    proposal_path, state_path = _write_records(tmp_path)
    output = tmp_path / "nested" / "policy.json"

    assert (
        main(
            [
                "--proposal",
                str(proposal_path),
                "--state",
                str(state_path),
                "--proposal-id",
                _PROPOSAL_ID,
                "--environment",
                "dev",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert json.loads(output.read_text(encoding="utf-8"))["revision"] == 3
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_file_cli_rejects_missing_state_and_oversized_input(tmp_path: Path) -> None:
    proposal_path, _state_path = _write_records(tmp_path)
    output = tmp_path / "policy.json"
    with pytest.raises(SystemExit, match="--state is required"):
        main(
            [
                "--proposal",
                str(proposal_path),
                "--proposal-id",
                _PROPOSAL_ID,
                "--environment",
                "dev",
                "--output",
                str(output),
            ]
        )
    proposal_path.write_text("x" * 65_537, encoding="utf-8")
    with pytest.raises(ValueError, match="size limit"):
        proposal_module._read_object(proposal_path, label="proposal")


def test_database_cli_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="FDAI_DATABASE_URL"):
        main(
            [
                "--from-database",
                "--proposal-id",
                _PROPOSAL_ID,
                "--environment",
                "dev",
                "--output",
                str(tmp_path / "policy.json"),
            ]
        )

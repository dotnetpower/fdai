"""Focused tests for the authority-free Teams A1 onboarding proposal consumer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/azure/teams_a1_proposal.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("teams_a1_proposal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _records(
    *,
    environment: str = "dev",
    actor_id: str = "owner-1",
    idempotency_key: str = "teams-a1-plan-1",
) -> tuple[dict[str, object], dict[str, object], str]:
    payload = {
        "actor_id": actor_id,
        "environment": environment,
        "idempotency_key": idempotency_key,
    }
    digest_source = {
        "family": "iam",
        "operation": "runtime-settings.teams-a1.plan",
        "principal_id": actor_id,
        "idempotency_key": idempotency_key,
        "payload": payload,
    }
    request_digest = hashlib.sha256(
        json.dumps(digest_source, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    proposal_id = f"operator-{request_digest[:32]}"
    proposal = {
        "kind": "operator.proposal",
        "proposal_id": proposal_id,
        "request_digest": request_digest,
        "dispatch_status": "pending",
        "mode": "shadow",
        "accepted_at": "2026-09-14T00:00:00+00:00",
        "family": "iam",
        "operation": "runtime-settings.teams-a1.plan",
        "principal_id": actor_id,
        "idempotency_key": idempotency_key,
        "payload": payload,
    }
    plan_state = {
        "revision": 1,
        "state": "plan-requested",
        "environment": environment,
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }
    return proposal, plan_state, proposal_id


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_resolves_provision_action(environment: str) -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records(environment=environment)

    result = module.resolve_teams_a1_action(
        proposal=proposal,
        plan_state=plan_state,
        expected_proposal_id=proposal_id,
        expected_environment=environment,
    )

    assert result == {"action": "provision_teams_a1_approval", "environment": environment}


def test_rejects_execution_authority_true() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records()
    plan_state["execution_authority"] = True

    with pytest.raises(ValueError, match="plan state metadata is inconsistent"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="dev",
        )


def test_rejects_wrong_activation_boundary() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records()
    plan_state["activation_boundary"] = "enforce"

    with pytest.raises(ValueError, match="plan state metadata is inconsistent"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="dev",
        )


def test_rejects_environment_mismatch() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records(environment="dev")

    with pytest.raises(ValueError, match="environment does not match"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="prod",
        )


def test_rejects_tampered_digest() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records()
    proposal["request_digest"] = "0" * 64

    with pytest.raises(ValueError, match="request digest is invalid"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="dev",
        )


def test_rejects_unknown_proposal_field() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records()
    proposal["unexpected"] = "x"

    with pytest.raises(ValueError, match="Teams A1 proposal fields are invalid"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="dev",
        )


def test_rejects_proposal_id_mismatch() -> None:
    module = _module()
    proposal, plan_state, _ = _records()

    with pytest.raises(ValueError, match="proposal id does not match"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=f"operator-{'a' * 32}",
            expected_environment="dev",
        )


def test_rejects_invalid_environment_argument() -> None:
    module = _module()
    proposal, plan_state, proposal_id = _records()

    with pytest.raises(ValueError, match="onboarding environment is invalid"):
        module.resolve_teams_a1_action(
            proposal=proposal,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="production",
        )

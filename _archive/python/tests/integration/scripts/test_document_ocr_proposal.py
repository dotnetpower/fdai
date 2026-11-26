from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fdai_service_contracts import DocumentOcrPolicy

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/azure/document_ocr_proposal.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("document_ocr_proposal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _records(
    *,
    provider: str,
    resource_desired: bool,
    deprovision_requested: bool,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], str]:
    policy = DocumentOcrPolicy(
        environment="dev",
        revision=2,
        desired_provider=provider,
        azure_resource_desired=resource_desired,
        deprovision_requested=deprovision_requested,
    )
    payload = {
        "actor_id": "owner-1",
        "environment": "dev",
        "policy_revision": 2,
        "policy_digest": policy.digest(),
        "idempotency_key": "ocr-plan-2",
    }
    digest_source = {
        "family": "iam",
        "operation": "model-settings.document-ocr.plan",
        "principal_id": "owner-1",
        "idempotency_key": "ocr-plan-2",
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
        "accepted_at": "2026-09-04T00:00:00+00:00",
        "family": "iam",
        "operation": "model-settings.document-ocr.plan",
        "principal_id": "owner-1",
        "idempotency_key": "ocr-plan-2",
        "payload": payload,
    }
    policy_state = {
        "environment": "dev",
        "revision": 2,
        "state": "plan-required",
        "policy": policy.model_dump(mode="json"),
        "policy_digest": policy.digest(),
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }
    plan_state = {
        "revision": 1,
        "state": "plan-requested",
        "environment": "dev",
        "policy_revision": 2,
        "policy_digest": policy.digest(),
        "execution_authority": False,
        "activation_boundary": "protected-plan-only",
    }
    return proposal, policy_state, plan_state, proposal_id


@pytest.mark.parametrize(
    ("provider", "resource_desired", "deprovision_requested", "expected"),
    [
        ("local_python", False, False, "use_local_retain"),
        ("local_python", True, False, "use_local_retain"),
        ("local_python", False, True, "deprovision_use_local"),
        ("azure_document_intelligence", True, False, "use_azure_provision"),
    ],
)
def test_resolves_exact_document_ocr_action(
    provider: str,
    resource_desired: bool,
    deprovision_requested: bool,
    expected: str,
) -> None:
    module = _module()
    proposal, policy_state, plan_state, proposal_id = _records(
        provider=provider,
        resource_desired=resource_desired,
        deprovision_requested=deprovision_requested,
    )

    result = module.resolve_document_ocr_action(
        proposal=proposal,
        policy_state=policy_state,
        plan_state=plan_state,
        expected_proposal_id=proposal_id,
        expected_environment="dev",
    )

    assert result["action"] == expected
    assert result["policy_digest"] == policy_state["policy_digest"]


def test_rejects_stale_document_ocr_plan_state() -> None:
    module = _module()
    proposal, policy_state, plan_state, proposal_id = _records(
        provider="azure_document_intelligence",
        resource_desired=True,
        deprovision_requested=False,
    )
    plan_state["policy_revision"] = 1

    with pytest.raises(ValueError, match="plan state metadata"):
        module.resolve_document_ocr_action(
            proposal=proposal,
            policy_state=policy_state,
            plan_state=plan_state,
            expected_proposal_id=proposal_id,
            expected_environment="dev",
        )


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(
        self,
        proposal: dict[str, object],
        policy_state: dict[str, object],
        plan_state: dict[str, object],
    ) -> None:
        self.proposal = proposal
        self.policy_state = policy_state
        self.plan_state = plan_state
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
        if "operator-document-ocr-policy:current" in statement:
            return _Cursor([{"value": self.policy_state}])
        if "operator-document-ocr-plan:current" in statement:
            return _Cursor([{"value": self.plan_state}])
        return _Cursor([])


def test_database_loader_escapes_like_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    proposal, policy_state, plan_state, proposal_id = _records(
        provider="azure_document_intelligence",
        resource_desired=True,
        deprovision_requested=False,
    )
    connection = _Connection(proposal, policy_state, plan_state)
    monkeypatch.setattr(module.psycopg, "connect", lambda *_args, **_kwargs: connection)

    loaded = module.load_document_ocr_records(
        database_url="postgresql://example.invalid/fdai",
        proposal_id=proposal_id,
    )

    assert loaded == (proposal, policy_state, plan_state)
    assert "LIKE 'operator-proposal:iam:%%'" in connection.statements[2][0]
    assert connection.statements[2][1] == (proposal_id,)

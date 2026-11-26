"""Trusted protected-deployment decision-evidence policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.decision_evidence_policy import (
    DecisionEvidencePolicyError,
    deployment_freshness_policy_digest,
    load_deployment_decision_evidence_policy,
)

_ROOT = Path(__file__).resolve().parents[4]
_POLICY = _ROOT / "config/decision-evidence-deployment-policy.json"


def test_shipped_policy_pins_source_verifier_and_freshness() -> None:
    policy = load_deployment_decision_evidence_policy(_POLICY)

    assert policy.source_workflow_path == ".github/workflows/deploy-dev.yml"
    assert policy.verifier_id == "github-actions.remote-evidence"
    assert policy.trust_anchor_id == "github-actions:protected-main"
    assert policy.freshness_ceiling_seconds == 3600
    assert deployment_freshness_policy_digest(policy).startswith("sha256:")


def test_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    raw = json.loads(_POLICY.read_text(encoding="utf-8"))
    raw["unreviewed_override"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DecisionEvidencePolicyError, match="shape"):
        load_deployment_decision_evidence_policy(path)


def test_policy_rejects_unbounded_freshness(tmp_path: Path) -> None:
    raw = json.loads(_POLICY.read_text(encoding="utf-8"))
    raw["freshness_ceiling_seconds"] = 86401
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DecisionEvidencePolicyError, match="freshness ceiling"):
        load_deployment_decision_evidence_policy(path)

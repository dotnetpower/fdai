"""Security contract for Cost Governance one-target review workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github/workflows/cost-governance-promotion-review.yml").read_text(
    encoding="utf-8"
)
_ROUTES = (_ROOT / "scripts/lib/design-routes.json").read_text(encoding="utf-8")


def test_review_workflow_is_protected_and_source_attempt_bound() -> None:
    assert "verify-protected-workflow-source" in _WORKFLOW
    assert "source workflow attempt changed before artifact download" in _WORKFLOW
    assert "source workflow attempt changed during artifact download" in _WORKFLOW
    assert '.path == ".github/workflows/cost-governance-observation-export.yml"' in _WORKFLOW
    assert 'gh api "users/$GITHUB_ACTOR"' in _WORKFLOW
    assert "source_actor=\"$(jq -er '.actor.login | ascii_downcase'" in _WORKFLOW
    assert "source_triggering_actor=\"$(jq -er '.triggering_actor.login | ascii_downcase'" in (
        _WORKFLOW
    )
    assert 'review_actor="${GITHUB_ACTOR,,}"' in _WORKFLOW
    assert '"$review_actor" != "$source_actor"' in _WORKFLOW
    assert '"$review_actor" != "$source_triggering_actor"' in _WORKFLOW
    assert "gh attestation verify" in _WORKFLOW


def test_review_recomputes_exact_release_and_rechecks_active_pin() -> None:
    assert "ref: ${{ steps.pin.outputs.source_revision }}" in _WORKFLOW
    assert "fdai_cost_governance.validation_cli evaluate" in _WORKFLOW
    assert "--require-ready" in _WORKFLOW
    assert "attested campaign result changed before independent review" in _WORKFLOW
    assert _WORKFLOW.count("fdai_cost_governance.validation_cli pin") == 2
    assert "active package pin changed during independent review" in _WORKFLOW


def test_review_records_one_target_without_authority_or_lifecycle_change() -> None:
    assert "record_cost_governance_review.py" in _WORKFLOW
    assert '--target-kind "$REVIEW_TARGET_KIND"' in _WORKFLOW
    assert '--target-id "$REVIEW_TARGET_ID"' in _WORKFLOW
    assert ".review.approval_authority == false" in _WORKFLOW
    assert ".review.execution_authority == false" in _WORKFLOW
    assert ".review.promotion_authority == false" in _WORKFLOW
    assert ".review.campaign_evidence_digest" in _WORKFLOW
    assert "fdai_cost_governance.lifecycle_cli" not in _WORKFLOW
    assert "promote-action-type" not in _WORKFLOW
    assert "terraform apply" not in _WORKFLOW


def test_review_workflow_is_valid_yaml_and_owned_by_cost_route() -> None:
    assert yaml.safe_load(_WORKFLOW)["jobs"]["review"]["timeout-minutes"] == 30
    route = _ROUTES.split('"id": "cost-governance-package"', 1)[1].split('"must_read"', 1)[0]
    assert '".github/workflows/cost-governance-promotion-review.yml"' in route
    assert '"scripts/deployment/azure/record_cost_governance_review.py"' in route

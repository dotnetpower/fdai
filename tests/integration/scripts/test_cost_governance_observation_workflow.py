from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (
    _ROOT / ".github/workflows/cost-governance-observation-export.yml"
).read_text(encoding="utf-8")
_ROUTES = (_ROOT / "scripts/lib/design-routes.json").read_text(encoding="utf-8")


def test_observation_workflow_is_scheduled_protected_and_exact_revision_bound() -> None:
    assert 'cron: "17 2 * * *"' in _WORKFLOW
    assert "verify-protected-workflow-source" in _WORKFLOW
    assert "workflow-path: .github/workflows/cost-governance-observation-export.yml" in (
        _WORKFLOW
    )
    assert "git rev-list --first-parent origin/main" in _WORKFLOW
    assert 'select(.name == "required" and .conclusion == "success")' in _WORKFLOW


def test_source_is_attested_and_uploaded_before_trusted_import() -> None:
    attest = _WORKFLOW.index("- name: Attest normalized source observations")
    upload = _WORKFLOW.index("- name: Upload immutable source observations")
    importer = _WORKFLOW.index("- name: Import observations and evaluate every review target")

    assert attest < upload < importer
    assert "fdai_cost_governance.campaign_export" in _WORKFLOW
    assert "fdai_cost_governance.validation_cli import" in _WORKFLOW
    assert "fdai_cost_governance.validation_cli evaluate" in _WORKFLOW
    assert "FDAI_OPERATOR_STORE_DSN" in _WORKFLOW
    assert "cost-governance-ontology-qualification.txt" in _WORKFLOW
    assert "cost-governance-parity-qualification.txt" in _WORKFLOW


def test_review_is_non_authoritative_and_cannot_promote() -> None:
    assert ".approval_authority == false and .promotion_authority == false" in _WORKFLOW
    assert "promote-action-type" not in _WORKFLOW
    assert "terraform apply" not in _WORKFLOW
    assert "--require-ready" not in _WORKFLOW


def test_cost_governance_design_route_owns_observation_workflow() -> None:
    route = _ROUTES.split('"id": "cost-governance-package"', 1)[1].split(
        '"must_read"', 1
    )[0]

    assert '".github/workflows/cost-governance-observation-export.yml"' in route
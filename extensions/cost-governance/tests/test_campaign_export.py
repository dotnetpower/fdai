from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai_cost_governance.campaign_export import (
    CostReleaseQualification,
    NoCompleteCostObservationsError,
    _normalize_observation,
    export_cost_campaign_batch,
    load_cost_release_qualification,
)
from fdai_cost_governance.campaign_import import _canonical_digest

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_ACTION_ID = "00000000-0000-0000-0000-000000000001"


def _qualification() -> CostReleaseQualification:
    return CostReleaseQualification(
        source_revision="a" * 40,
        revision_pin_digest=f"sha256:{'b' * 64}",
        ontology_competency_passed=True,
        parity_explained=True,
        evidence_refs=(f"sha256:{'c' * 64}", f"sha256:{'d' * 64}"),
        digest=f"sha256:{'e' * 64}",
    )


def _row() -> dict[str, object]:
    expected = {
        "prediction_id": "prediction-001",
        "metric": "monthly-cost",
        "expected_min": 0,
        "expected_max": 100,
        "predicted_at": "2026-09-11T00:00:00+00:00",
        "observation_deadline": "2026-09-13T00:00:00+00:00",
    }
    return {
        "outcome_seq": 14,
        "outcome_created_at": _NOW,
        "outcome_entry": {
            "action_id": _ACTION_ID,
            "action_type_id": "remediate.right-size",
            "actor": "fdai.measurement",
            "decision": "auto",
            "evidence_refs": ["effect:prediction-001"],
            "execution_mode": "shadow",
            "execution_outcome": "published",
            "label": "verified",
            "observed_at": "2026-09-12T00:00:00+00:00",
            "verification_passed": True,
            "verification_reason": "value_within_expected_range",
            **expected,
        },
        "risk_seq": 11,
        "risk_entry": {
            "action_id": _ACTION_ID,
            "decision": "shadow",
            "producer_principal": "Forseti",
            "authority": {"ceiling_inputs": {"system_degraded": False}},
        },
        "intent_seq": 12,
        "intent_entry": {
            "action_id": _ACTION_ID,
            "dry_run_passed": True,
            "dry_run_receipt": "dry-run:001",
            "idempotency_key": "action:001",
        },
        "terminal_seq": 13,
        "terminal_entry": {
            "action_id": _ACTION_ID,
            "action_kind": "remediate.right-size",
            "actor": "fdai.core.executor.shadow",
            "blast_radius": {"scope": "resource", "count": 1},
            "dry_run_receipt": "dry-run:001",
            "idempotency_key": "action:001",
            "rollback_kind": "pr_revert",
            "rollback_reference": "pr-1",
            "safeguard_bundle_digest": f"sha256:{'a' * 64}",
            "stop_condition": "provider_api_error_streak",
        },
        "workflow_ref": "cost-aware-remediation",
        "plan_entry": {
            "proposal": {"plan": {"plan_id": "prediction-001"}},
            "operational_plan": {
                "complete": True,
                "selection": {"selected_option_id": "option-001"},
                "decision_case": {
                    "protected_objective_ids": ["service-objective-001"],
                    "options": [
                        {
                            "option_id": "option-001",
                            "action_type": "remediate.right-size",
                            "effects": [
                                {
                                    "objective_id": "service-objective-001",
                                    "metric": "monthly-cost",
                                    "expected_min": 0,
                                    "expected_max": 100,
                                }
                            ],
                        }
                    ],
                },
            },
        },
    }


def test_normalization_requires_complete_lineage_and_preserves_workflow_target() -> None:
    observation = _normalize_observation(
        _row(),
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    assert observation["target_refs"] == [
        "remediate.right-size",
        "cost-aware-remediation",
    ]
    assert observation["outcome"] == "no-op"
    assert observation["settlement_statuses"] == ["verified"]
    assert observation["policy_escape"] is False
    assert observation["decision_correct"] is True
    assert observation["safeguards_complete"] is True
    assert observation["hard_dependencies_complete"] is True
    assert observation["protected_objectives_complete"] is True
    assert observation["ontology_competency_passed"] is True
    assert observation["parity_explained"] is True
    assert observation["unauthorized_disclosure"] is False


def test_policy_mismatch_and_missing_safeguard_fail_closed() -> None:
    row = _row()
    row["risk_entry"] = {**row["risk_entry"], "decision": "deny"}  # type: ignore[dict-item]
    row["intent_entry"] = {**row["intent_entry"], "dry_run_passed": False}  # type: ignore[dict-item]

    observation = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=True,
    )

    assert observation["policy_escape"] is True
    assert observation["decision_correct"] is False
    assert observation["safeguards_complete"] is False
    assert observation["unauthorized_disclosure"] is True
    assert observation["target_refs"] == ["remediate.right-size"]


def test_enforce_effect_settlement_is_separate_from_policy_escape() -> None:
    row = _row()
    row["risk_entry"] = {**row["risk_entry"], "decision": "auto"}  # type: ignore[dict-item]
    row["outcome_entry"] = {  # type: ignore[dict-item]
        **row["outcome_entry"],  # type: ignore[misc]
        "execution_mode": "enforce",
    }
    row["terminal_entry"] = {  # type: ignore[dict-item]
        **row["terminal_entry"],  # type: ignore[misc]
        "workflow_action": {
            "process_id": "process-001",
            "step_id": "apply_rightsize",
            "proposal_ref": "proposal-001",
            "attempt": 3,
        },
    }

    beneficial = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert beneficial["outcome"] == "beneficial-action"
    assert beneficial["policy_escape"] is False
    assert beneficial["recovery_attempts"] == 2

    row["outcome_entry"] = {  # type: ignore[dict-item]
        **row["outcome_entry"],  # type: ignore[misc]
        "decision": "abstain",
        "label": "mismatch",
        "verification_passed": False,
    }
    mismatch = _normalize_observation(
        row,
        workflow_ids=frozenset(),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )
    assert mismatch["outcome"] == "execute"
    assert mismatch["policy_escape"] is False
    assert mismatch["objective_regression"] is True
    assert mismatch["decision_correct"] is False


def test_missing_plan_lineage_blocks_protected_objective_claim() -> None:
    row = _row()
    row["plan_entry"] = None

    observation = _normalize_observation(
        row,
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    assert observation["protected_objectives_complete"] is False


def test_release_qualification_is_digest_and_active_pin_bound(tmp_path: Path) -> None:
    body = {
        "evidence_refs": [f"sha256:{'c' * 64}", f"sha256:{'d' * 64}"],
        "ontology_competency_passed": True,
        "parity_explained": True,
        "revision_pin_digest": f"sha256:{'b' * 64}",
        "schema_version": "1.0.0",
        "source_revision": "a" * 40,
    }
    path = tmp_path / "qualification.json"
    path.write_text(
        json.dumps({**body, "qualification_digest": _canonical_digest(body)}),
        encoding="utf-8",
    )

    qualification = load_cost_release_qualification(
        path,
        source_revision="a" * 40,
        revision_pin_digest=f"sha256:{'b' * 64}",
    )

    assert qualification.ontology_competency_passed is True
    with pytest.raises(ValueError, match="active release"):
        load_cost_release_qualification(
            path,
            source_revision="e" * 40,
            revision_pin_digest=f"sha256:{'b' * 64}",
        )


def test_export_batch_is_canonical_and_rejects_empty_cohort() -> None:
    observation = _normalize_observation(
        _row(),
        workflow_ids=frozenset({"cost-aware-remediation"}),
        qualification=_qualification(),
        unauthorized_disclosure=False,
    )

    batch = export_cost_campaign_batch(
        campaign_id="campaign-001",
        revision_pin_digest=f"sha256:{'a' * 64}",
        observations=(observation,),
    )
    body = {key: value for key, value in batch.items() if key != "batch_digest"}

    assert batch["batch_digest"] == _canonical_digest(body)

    try:
        export_cost_campaign_batch(
            campaign_id="campaign-001",
            revision_pin_digest=f"sha256:{'a' * 64}",
            observations=(),
        )
    except NoCompleteCostObservationsError:
        pass
    else:
        raise AssertionError("empty campaign export must use the bounded no-data outcome")

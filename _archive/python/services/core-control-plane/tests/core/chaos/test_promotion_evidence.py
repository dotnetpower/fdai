from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionError,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
    load_promotion_ledger,
)

_FINGERPRINT = "a" * 64


def _evidence(
    evidence_id: str,
    from_state: ScenarioPromotionState,
    to_state: ScenarioPromotionState,
    *,
    actor: str,
    key: ScenarioEvidenceKey | None = None,
) -> ScenarioPromotionEvidence:
    return ScenarioPromotionEvidence(
        evidence_id=evidence_id,
        key=key or ScenarioEvidenceKey("chaos.test.one", 1, _FINGERPRINT),
        from_state=from_state,
        to_state=to_state,
        actor_principal=actor,
        audit_ref=f"audit:{evidence_id}",
        observed_at=datetime(2026, 7, 17, tzinfo=UTC),
        runner_version="runner/1",
        stop_condition_observed=True,
        rollback_succeeded=True,
        blast_radius_compliant=True,
        detection_latency_ms=100,
        latency_budget_ms=500,
    )


def test_full_promotion_and_regression_are_append_only() -> None:
    ledger = ScenarioPromotionLedger()
    key = ScenarioEvidenceKey("chaos.test.one", 1, _FINGERPRINT)
    shadow = _evidence(
        "shadow",
        ScenarioPromotionState.COLLECTED,
        ScenarioPromotionState.SHADOW_VALIDATED,
        actor="Saga",
        key=key,
    )
    pending = _evidence(
        "pending",
        ScenarioPromotionState.SHADOW_VALIDATED,
        ScenarioPromotionState.APPROVAL_PENDING,
        actor="Mimir",
        key=key,
    )
    approved = replace(
        _evidence(
            "approved",
            ScenarioPromotionState.APPROVAL_PENDING,
            ScenarioPromotionState.ENFORCE_ELIGIBLE,
            actor="Mimir",
            key=key,
        ),
        approval_ref="approval:scenario",
        approval_principal="Var",
    )
    regressed = replace(
        _evidence(
            "regressed",
            ScenarioPromotionState.ENFORCE_ELIGIBLE,
            ScenarioPromotionState.REGRESSED,
            actor="Mimir",
            key=key,
        ),
        regression_reasons=("rollback_failed",),
    )

    for record in (shadow, pending, approved):
        ledger.append(record)
    assert ledger.is_enforce_eligible(key)
    ledger.append(regressed)

    assert ledger.state_for(key) is ScenarioPromotionState.REGRESSED
    assert ledger.records == (shadow, pending, approved, regressed)


def test_jsonl_replay_restores_current_approval_ref(tmp_path) -> None:
    key = ScenarioEvidenceKey("chaos.test.one", 1, _FINGERPRINT)
    records = [
        _evidence(
            "shadow",
            ScenarioPromotionState.COLLECTED,
            ScenarioPromotionState.SHADOW_VALIDATED,
            actor="Saga",
            key=key,
        ),
        _evidence(
            "pending",
            ScenarioPromotionState.SHADOW_VALIDATED,
            ScenarioPromotionState.APPROVAL_PENDING,
            actor="Mimir",
            key=key,
        ),
        replace(
            _evidence(
                "approved",
                ScenarioPromotionState.APPROVAL_PENDING,
                ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor="Mimir",
                key=key,
            ),
            approval_ref="approval:scenario",
            approval_principal="Var",
        ),
    ]
    path = tmp_path / "evidence.jsonl"
    path.write_text("\n".join(json.dumps(record.to_dict()) for record in records) + "\n")

    ledger = load_promotion_ledger(path)

    assert ledger.is_enforce_eligible(key)
    assert ledger.approval_ref_for(key) == "approval:scenario"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"stop_condition_observed": False}, "stop condition"),
        ({"rollback_succeeded": False}, "rollback"),
        ({"blast_radius_compliant": False}, "blast-radius"),
        ({"detection_latency_ms": 501}, "latency budget"),
        ({"actor_principal": "Loki"}, "Saga"),
    ],
)
def test_shadow_validation_fails_closed_on_missing_evidence(
    changes: dict[str, object],
    message: str,
) -> None:
    evidence = replace(
        _evidence(
            "shadow",
            ScenarioPromotionState.COLLECTED,
            ScenarioPromotionState.SHADOW_VALIDATED,
            actor="Saga",
        ),
        **changes,
    )
    with pytest.raises(ScenarioPromotionError, match=message):
        ScenarioPromotionLedger().append(evidence)


def test_enforce_eligibility_requires_var_approval() -> None:
    ledger = ScenarioPromotionLedger()
    ledger.append(
        _evidence(
            "shadow",
            ScenarioPromotionState.COLLECTED,
            ScenarioPromotionState.SHADOW_VALIDATED,
            actor="Saga",
        )
    )
    ledger.append(
        _evidence(
            "pending",
            ScenarioPromotionState.SHADOW_VALIDATED,
            ScenarioPromotionState.APPROVAL_PENDING,
            actor="Mimir",
        )
    )

    with pytest.raises(ScenarioPromotionError, match="Var HIL approval"):
        ledger.append(
            _evidence(
                "approved",
                ScenarioPromotionState.APPROVAL_PENDING,
                ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor="Mimir",
            )
        )


def test_new_version_does_not_inherit_old_eligibility() -> None:
    ledger = ScenarioPromotionLedger()
    old_key = ScenarioEvidenceKey("chaos.test.one", 1, _FINGERPRINT)
    new_key = ScenarioEvidenceKey("chaos.test.one", 2, "b" * 64)
    ledger._states[old_key] = ScenarioPromotionState.ENFORCE_ELIGIBLE

    assert ledger.is_enforce_eligible(old_key)
    assert ledger.state_for(new_key) is ScenarioPromotionState.COLLECTED


def test_duplicate_or_out_of_order_evidence_is_rejected() -> None:
    ledger = ScenarioPromotionLedger()
    shadow = _evidence(
        "shadow",
        ScenarioPromotionState.COLLECTED,
        ScenarioPromotionState.SHADOW_VALIDATED,
        actor="Saga",
    )
    ledger.append(shadow)
    with pytest.raises(ScenarioPromotionError, match="duplicate"):
        ledger.append(shadow)
    with pytest.raises(ScenarioPromotionError, match="from_state"):
        ledger.append(replace(shadow, evidence_id="other"))


def test_promotion_evidence_validation_and_loader_edges(tmp_path) -> None:
    with pytest.raises(ValueError, match="scenario_id"):
        ScenarioEvidenceKey(" ", 1, _FINGERPRINT)
    with pytest.raises(ValueError, match="scenario_version"):
        ScenarioEvidenceKey("chaos.test.one", 0, _FINGERPRINT)
    with pytest.raises(ValueError, match="catalog_fingerprint"):
        ScenarioEvidenceKey("chaos.test.one", 1, "bad")

    key = ScenarioEvidenceKey("chaos.test.one", 1, _FINGERPRINT)
    base = _evidence(
        "shadow",
        ScenarioPromotionState.COLLECTED,
        ScenarioPromotionState.SHADOW_VALIDATED,
        actor="Saga",
        key=key,
    )
    with pytest.raises(ValueError, match="evidence_id MUST be non-empty"):
        replace(base, evidence_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(base, observed_at=datetime(2026, 7, 17))
    with pytest.raises(ValueError, match="detection_latency_ms"):
        replace(base, detection_latency_ms=-1)
    with pytest.raises(ValueError, match="latency_budget_ms"):
        replace(base, latency_budget_ms=0)

    raw_base = base.to_dict()
    with pytest.raises(ScenarioPromotionError, match="schema_version"):
        ScenarioPromotionEvidence.from_dict({**raw_base, "schema_version": 2})
    for field, invalid_val in (
        ("stop_condition_observed", "yes"),
        ("detection_latency_ms", True),
        ("approval_ref", 123),
        ("regression_reasons", [123]),
    ):
        with pytest.raises(ScenarioPromotionError, match="malformed"):
            ScenarioPromotionEvidence.from_dict({**raw_base, field: invalid_val})

    minimal_raw = {
        **raw_base,
        "detection_latency_ms": None,
        "latency_budget_ms": None,
        "regression_reasons": None,
    }
    parsed_minimal = ScenarioPromotionEvidence.from_dict(minimal_raw)
    assert parsed_minimal.detection_latency_ms is None
    assert parsed_minimal.regression_reasons == ()

    ledger = ScenarioPromotionLedger()
    assert ledger.approval_ref_for(key) is None
    with pytest.raises(ScenarioPromotionError, match="invalid promotion transition"):
        ledger.append(
            _evidence(
                "skip",
                ScenarioPromotionState.COLLECTED,
                ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor="Mimir",
                key=key,
            )
        )
    with pytest.raises(ScenarioPromotionError, match="latency measurement"):
        ledger.append(replace(base, detection_latency_ms=None))

    ledger.append(base)
    with pytest.raises(ScenarioPromotionError, match="only Mimir may request"):
        ledger.append(
            _evidence(
                "pending-bad",
                ScenarioPromotionState.SHADOW_VALIDATED,
                ScenarioPromotionState.APPROVAL_PENDING,
                actor="Saga",
                key=key,
            )
        )
    ledger.append(
        _evidence(
            "pending",
            ScenarioPromotionState.SHADOW_VALIDATED,
            ScenarioPromotionState.APPROVAL_PENDING,
            actor="Mimir",
            key=key,
        )
    )
    with pytest.raises(ScenarioPromotionError, match="only Mimir may mark"):
        ledger.append(
            replace(
                _evidence(
                    "approved-bad",
                    ScenarioPromotionState.APPROVAL_PENDING,
                    ScenarioPromotionState.ENFORCE_ELIGIBLE,
                    actor="Saga",
                    key=key,
                ),
                approval_ref="approval:1",
                approval_principal="Var",
            )
        )
    ledger.append(
        replace(
            _evidence(
                "approved",
                ScenarioPromotionState.APPROVAL_PENDING,
                ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor="Mimir",
                key=key,
            ),
            approval_ref="approval:1",
            approval_principal="Var",
        )
    )
    with pytest.raises(ScenarioPromotionError, match="only Mimir may regress"):
        ledger.append(
            replace(
                _evidence(
                    "regressed-bad",
                    ScenarioPromotionState.ENFORCE_ELIGIBLE,
                    ScenarioPromotionState.REGRESSED,
                    actor="Saga",
                    key=key,
                ),
                regression_reasons=("rollback_failed",),
            )
        )

    blank_path = tmp_path / "blank.jsonl"
    blank_path.write_text("\n" + json.dumps(raw_base) + "\n\n", encoding="utf-8")
    assert len(load_promotion_ledger(blank_path).records) == 1

    bad_json_path = tmp_path / "bad.jsonl"
    bad_json_path.write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(ScenarioPromotionError, match="not valid JSON"):
        load_promotion_ledger(bad_json_path)

    non_obj_path = tmp_path / "array.jsonl"
    non_obj_path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ScenarioPromotionError, match="MUST be an object"):
        load_promotion_ledger(non_obj_path)

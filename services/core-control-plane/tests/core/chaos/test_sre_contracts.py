from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionError,
    ScenarioPromotionEvidence,
    ScenarioPromotionLedger,
    ScenarioPromotionState,
)
from fdai.core.chaos.promotion_guard import (
    ChaosPromotionGuard,
    ChaosPromotionObservation,
)
from fdai.core.chaos.sre_contracts import (
    SreScenarioContract,
    sre_scenario_contracts,
    validate_sre_scenario_contracts,
)
from fdai.core.detection.signals import known_signals
from fdai.core.recovery import RecoveryProbeKind
from fdai.core.risk_gate import ActionPromotionRegistry, PromotionMetrics
from fdai.shared.contracts.models import Mode, OntologyActionType

_ROOT = Path(__file__).resolve().parents[5]
_NOW = datetime(2026, 7, 31, tzinfo=UTC)
_KEY = ScenarioEvidenceKey("chaos.test.one", 1, "a" * 64)


def test_sre_contracts_cover_exactly_s1_s14() -> None:
    validate_sre_scenario_contracts()
    contracts = sre_scenario_contracts()
    assert [item.scenario_id for item in contracts] == [f"S{i}" for i in range(1, 15)]
    assert sum(item.fault for item in contracts) == 12
    assert all(set(item.signals) <= set(known_signals()) for item in contracts)
    for contract in contracts[:12]:
        assert set(contract.recovery_probes) == set(RecoveryProbeKind)
        assert contract.chaos_scenario_id is not None
        assert contract.recovery_action_types
    assert all(item.chaos_scenario_id is None for item in contracts[12:])


def _promoted_ledger() -> ScenarioPromotionLedger:
    ledger = ScenarioPromotionLedger()
    common = {
        "key": _KEY,
        "audit_ref": "audit:test",
        "observed_at": _NOW,
        "runner_version": "runner/1",
        "stop_condition_observed": True,
        "rollback_succeeded": True,
        "blast_radius_compliant": True,
        "detection_latency_ms": 10,
        "latency_budget_ms": 100,
    }
    ledger.append(
        ScenarioPromotionEvidence(
            evidence_id="shadow",
            from_state=ScenarioPromotionState.COLLECTED,
            to_state=ScenarioPromotionState.SHADOW_VALIDATED,
            actor_principal="Saga",
            **common,
        )
    )
    ledger.append(
        ScenarioPromotionEvidence(
            evidence_id="pending",
            from_state=ScenarioPromotionState.SHADOW_VALIDATED,
            to_state=ScenarioPromotionState.APPROVAL_PENDING,
            actor_principal="Mimir",
            **common,
        )
    )
    ledger.append(
        replace(
            ScenarioPromotionEvidence(
                evidence_id="approved",
                from_state=ScenarioPromotionState.APPROVAL_PENDING,
                to_state=ScenarioPromotionState.ENFORCE_ELIGIBLE,
                actor_principal="Mimir",
                **common,
            ),
            approval_ref="approval:1",
            approval_principal="Var",
        )
    )
    return ledger


def _promoted_action_registry() -> ActionPromotionRegistry:
    raw = yaml.safe_load(
        (_ROOT / "rule-catalog/action-types/ops.scale-out.yaml").read_text(encoding="utf-8")
    )
    action = OntologyActionType.model_validate(raw)
    registry = ActionPromotionRegistry(allow_legacy_metrics=True)
    record = registry.consider_promotion(
        action_type=action,
        metrics=PromotionMetrics(
            action_type=action.name,
            shadow_days=action.promotion_gate.min_shadow_days,
            samples=action.promotion_gate.min_samples,
            accuracy=action.promotion_gate.min_accuracy,
            policy_escapes=0,
        ),
    )
    assert record.mode is Mode.ENFORCE
    return registry


def test_unsafe_observation_demotes_scenario_and_actions() -> None:
    ledger = _promoted_ledger()
    actions = _promoted_action_registry()
    reasons = ChaosPromotionGuard(
        scenario_ledger=ledger,
        action_registry=actions,
    ).observe(
        key=_KEY,
        action_type_names=("ops.scale-out",),
        observation=ChaosPromotionObservation(
            observed_at=_NOW,
            audit_ref="audit:unsafe",
            runner_version="runner/1",
            containment_compliant=False,
            recovery_within_objective=False,
            telemetry_complete=True,
            stop_observed=False,
            rollback_succeeded=False,
            policy_escapes=1,
        ),
    )
    assert set(reasons) == {
        "impact_outside_envelope",
        "policy_escape",
        "recovery_objective_missed",
        "rollback_failed",
        "stop_condition_missed",
    }
    assert ledger.state_for(_KEY) is ScenarioPromotionState.REGRESSED
    assert actions.mode_of("ops.scale-out") is Mode.SHADOW
    terminal = ledger.records[-1]
    assert ScenarioPromotionEvidence.from_dict(terminal.to_dict()).regression_reasons == reasons


def test_safe_observation_keeps_enforce_eligibility() -> None:
    ledger = _promoted_ledger()
    actions = _promoted_action_registry()
    reasons = ChaosPromotionGuard(
        scenario_ledger=ledger,
        action_registry=actions,
    ).observe(
        key=_KEY,
        action_type_names=("ops.scale-out",),
        observation=ChaosPromotionObservation(
            observed_at=_NOW,
            audit_ref="audit:safe",
            runner_version="runner/1",
            containment_compliant=True,
            recovery_within_objective=True,
            telemetry_complete=True,
            stop_observed=True,
            rollback_succeeded=True,
        ),
    )
    assert reasons == ()
    assert ledger.is_enforce_eligible(_KEY)
    assert actions.mode_of("ops.scale-out") is Mode.ENFORCE


def test_regression_evidence_requires_grounded_reasons() -> None:
    ledger = _promoted_ledger()
    with pytest.raises(ScenarioPromotionError, match="requires reasons"):
        ledger.append(
            ScenarioPromotionEvidence(
                evidence_id="ungrounded-regression",
                key=_KEY,
                from_state=ScenarioPromotionState.ENFORCE_ELIGIBLE,
                to_state=ScenarioPromotionState.REGRESSED,
                actor_principal="Mimir",
                audit_ref="audit:missing-reason",
                observed_at=_NOW,
                runner_version="runner/1",
            )
        )


def test_regression_rejects_unpromoted_action_without_partial_demotion() -> None:
    ledger = _promoted_ledger()
    actions = _promoted_action_registry()
    observation = ChaosPromotionObservation(
        observed_at=_NOW,
        audit_ref="audit:unsafe",
        runner_version="runner/1",
        containment_compliant=False,
        recovery_within_objective=True,
        telemetry_complete=True,
        stop_observed=True,
        rollback_succeeded=True,
    )

    with pytest.raises(ValueError, match="enforce-promoted"):
        ChaosPromotionGuard(
            scenario_ledger=ledger,
            action_registry=actions,
        ).observe(
            key=_KEY,
            action_type_names=("ops.scale-out", "ops.unrelated"),
            observation=observation,
        )

    assert ledger.is_enforce_eligible(_KEY)
    assert actions.mode_of("ops.scale-out") is Mode.ENFORCE


def test_sre_contract_and_promotion_guard_validation_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        SreScenarioContract(
            scenario_id="",
            title="t",
            fault=False,
            signals=("sig",),
            causal_mechanism="m",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        )
    with pytest.raises(ValueError, match="MUST be a boolean"):
        SreScenarioContract(
            scenario_id="S1",
            title="t",
            fault="yes",  # type: ignore[arg-type]
            signals=("sig",),
            causal_mechanism="m",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        )
    with pytest.raises(ValueError, match="signals MUST be non-empty"):
        SreScenarioContract(
            scenario_id="S1",
            title="t",
            fault=False,
            signals=(" ",),
            causal_mechanism="m",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        )

    base = list(sre_scenario_contracts())
    monkeypatch.setattr(
        "fdai.core.chaos.sre_contracts.sre_scenario_contracts",
        lambda: tuple(base[:-1]),
    )
    with pytest.raises(ValueError, match="exactly S1-S14"):
        validate_sre_scenario_contracts()

    for idx, replacement, match in (
        (0, replace(base[0], signals=("unknown.signal",)), "unknown signal"),
        (0, replace(base[0], chaos_scenario_id="unknown-chaos"), "unknown chaos scenario"),
        (0, replace(base[0], recovery_probes=()), "complete recovery verification"),
        (0, replace(base[0], recovery_action_types=()), "lacks a recovery action"),
        (12, replace(base[12], chaos_scenario_id="aks-pod-kill"), "non-fault"),
    ):
        modified = list(base)
        modified[idx] = replacement
        monkeypatch.setattr(
            "fdai.core.chaos.sre_contracts.sre_scenario_contracts",
            lambda m=tuple(modified): m,
        )
        with pytest.raises(ValueError, match=match):
            validate_sre_scenario_contracts()

    with pytest.raises(ValueError, match="timezone-aware"):
        ChaosPromotionObservation(
            observed_at=datetime(2026, 7, 31),
            audit_ref="audit:1",
            runner_version="runner/1",
            containment_compliant=True,
            recovery_within_objective=True,
            telemetry_complete=True,
            stop_observed=True,
            rollback_succeeded=True,
        )
    with pytest.raises(ValueError, match="MUST be non-empty"):
        ChaosPromotionObservation(
            observed_at=_NOW,
            audit_ref=" ",
            runner_version="runner/1",
            containment_compliant=True,
            recovery_within_objective=True,
            telemetry_complete=True,
            stop_observed=True,
            rollback_succeeded=True,
        )
    with pytest.raises(ValueError, match="policy_escapes"):
        ChaosPromotionObservation(
            observed_at=_NOW,
            audit_ref="audit:1",
            runner_version="runner/1",
            containment_compliant=True,
            recovery_within_objective=True,
            telemetry_complete=True,
            stop_observed=True,
            rollback_succeeded=True,
            policy_escapes=-1,
        )

    obs = ChaosPromotionObservation(
        observed_at=_NOW,
        audit_ref="audit:1",
        runner_version="runner/1",
        containment_compliant=True,
        recovery_within_objective=True,
        telemetry_complete=False,
        stop_observed=True,
        rollback_succeeded=True,
    )
    assert obs.regression_reasons() == ("telemetry_incomplete",)

    unpromoted_guard = ChaosPromotionGuard(
        scenario_ledger=ScenarioPromotionLedger(),
        action_registry=_promoted_action_registry(),
    )
    assert unpromoted_guard.observe(
        key=_KEY,
        action_type_names=("ops.scale-out",),
        observation=obs,
    ) == ("telemetry_incomplete",)

    promoted_guard = ChaosPromotionGuard(
        scenario_ledger=_promoted_ledger(),
        action_registry=_promoted_action_registry(),
    )
    with pytest.raises(ValueError, match="non-empty ActionType"):
        promoted_guard.observe(
            key=_KEY,
            action_type_names=(),
            observation=obs,
        )

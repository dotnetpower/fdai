"""RulePromotionController + ContinuousRulePipeline invariants."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.pipeline import (
    BaselineState,
    ContinuousRulePipeline,
    PromotionOutcome,
    RegressionDecision,
    RegressionGate,
    RegressionOutcome,
    RulePromotionController,
    ScenarioOutcome,
    ShadowEvalReport,
    build_pipeline,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _shipped_rules() -> tuple[Rule, ...]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    return load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )


def _outcome(scenario_id: str = "s1") -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario_id,
        expected_tier="t0",
        expected_decision="abstain",
        actual_tier="t0",
        actual_pipeline_stage="abstain",
    )


def _report(*, tag: str = "v1", scenario_count: int = 1) -> ShadowEvalReport:
    return ShadowEvalReport(
        scenario_set_id=tag,
        candidate_rule_ids=("r.x",),
        scenario_count=scenario_count,
        outcomes=tuple(_outcome(scenario_id=f"s{i}") for i in range(scenario_count)),
    )


# ---------------------------------------------------------------------------
# RulePromotionController
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pass_decision_promotes_and_audits() -> None:
    audit = InMemoryStateStore()
    ctrl = RulePromotionController(audit_store=audit)
    decision = RegressionDecision(
        outcome=RegressionOutcome.PASS,
        scenario_set_id="v1",
        candidate_rule_ids=("r.x",),
        baseline_coverage=0.5,
        candidate_coverage=0.7,
        policy_violation_escapes=0,
        missing_expected_rules=0,
    )
    record, baseline = await ctrl.apply(decision=decision)
    assert record.outcome is PromotionOutcome.PROMOTED
    assert baseline is not None
    assert baseline.rule_ids == ("r.x",)
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["outcome"] == "promoted"
    assert entries[0]["entry"]["candidate_coverage"] == 0.7


@pytest.mark.asyncio
async def test_fail_decision_rolls_back_and_preserves_previous_baseline() -> None:
    audit = InMemoryStateStore()
    ctrl = RulePromotionController(audit_store=audit)
    previous = BaselineState(scenario_set_id="v1", rule_ids=("r.prev",), promoted_at=_now())
    decision = RegressionDecision(
        outcome=RegressionOutcome.FAIL,
        scenario_set_id="v1",
        candidate_rule_ids=("r.candidate",),
        baseline_coverage=0.7,
        candidate_coverage=0.3,
        policy_violation_escapes=2,
        missing_expected_rules=0,
        reasons=("policy_violation_escapes=2 > max=0",),
    )
    record, baseline = await ctrl.apply(decision=decision, previous_baseline=previous)
    assert record.outcome is PromotionOutcome.ROLLED_BACK
    assert baseline is previous  # untouched
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["outcome"] == "rolled_back"
    assert entries[0]["entry"]["policy_violation_escapes"] == 2


@pytest.mark.asyncio
async def test_fail_on_first_run_leaves_baseline_none() -> None:
    audit = InMemoryStateStore()
    ctrl = RulePromotionController(audit_store=audit)
    decision = RegressionDecision(
        outcome=RegressionOutcome.FAIL,
        scenario_set_id="v1",
        candidate_rule_ids=("r.x",),
        baseline_coverage=0.0,
        candidate_coverage=0.0,
        policy_violation_escapes=1,
        missing_expected_rules=0,
        reasons=("policy_violation_escapes=1 > max=0",),
    )
    record, baseline = await ctrl.apply(decision=decision, previous_baseline=None)
    assert record.outcome is PromotionOutcome.ROLLED_BACK
    assert baseline is None


# ---------------------------------------------------------------------------
# ContinuousRulePipeline orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_runs_end_to_end_and_promotes_first_rollout() -> None:
    audit = InMemoryStateStore()
    pipeline = build_pipeline(audit_store=audit)
    scenarios = [
        {
            "id": "compliant-1",
            "event": {
                "schema_version": "1.0.0",
                "event_id": "00000000-0000-0000-0000-000000000101",
                "idempotency_key": "s-compliant-1",
                "source": "src",
                "event_type": "change_detected",
                "detected_at": "2026-07-05T08:00:00Z",
                "ingested_at": "2026-07-05T08:00:01Z",
                "mode": "shadow",
                "payload": {"resource": {"type": "object-storage", "props": {}}},
            },
            "expected": {
                "tier": "t0",
                "decision": "abstain",
                "citing_rule_ids": [],
                "guard": {
                    "should_execute": False,
                    "should_rollback": False,
                    "should_trigger_policy_violation": False,
                },
            },
        }
    ]
    run = await pipeline.run(
        candidate_rules=_shipped_rules(),
        scenario_set_id="v-pipeline",
        scenarios=scenarios,
    )
    assert run.decision.outcome is RegressionOutcome.PASS
    assert run.promotion.outcome is PromotionOutcome.PROMOTED
    assert run.baseline is not None
    assert await audit.verify_chain()


@pytest.mark.asyncio
async def test_pipeline_rolls_back_on_policy_escape() -> None:
    audit = InMemoryStateStore()
    pipeline = build_pipeline(audit_store=audit)
    # Scenario expects a violation but the abstain evaluator never fires it
    # → policy_violation_escape → regression FAIL.
    scenarios = [
        {
            "id": "escape-1",
            "event": {
                "schema_version": "1.0.0",
                "event_id": "00000000-0000-0000-0000-000000000102",
                "idempotency_key": "s-escape",
                "source": "src",
                "event_type": "change_detected",
                "detected_at": "2026-07-05T08:00:00Z",
                "ingested_at": "2026-07-05T08:00:01Z",
                "mode": "shadow",
                "payload": {
                    "resource": {
                        "type": "object-storage",
                        "props": {"public_access": "enabled"},
                    }
                },
            },
            "expected": {
                "tier": "t0",
                "decision": "auto",
                "citing_rule_ids": ["object-storage.public-access.deny"],
                "guard": {
                    "should_execute": True,
                    "should_rollback": False,
                    "should_trigger_policy_violation": True,
                },
            },
        }
    ]
    run = await pipeline.run(
        candidate_rules=_shipped_rules(),
        scenario_set_id="v-pipeline",
        scenarios=scenarios,
    )
    assert run.decision.outcome is RegressionOutcome.FAIL
    assert run.promotion.outcome is PromotionOutcome.ROLLED_BACK
    assert run.baseline is None
    # Reasons are surfaced on the promotion record for audit.
    assert any("policy_violation_escapes" in r for r in run.promotion.reasons)


@pytest.mark.asyncio
async def test_pipeline_requires_exactly_one_scenario_source() -> None:
    pipeline = build_pipeline(audit_store=InMemoryStateStore())
    with pytest.raises(ValueError, match="exactly one"):
        await pipeline.run(
            candidate_rules=_shipped_rules(),
            scenario_set_id="v",
            scenarios=None,
            scenarios_dir=None,
        )
    with pytest.raises(ValueError, match="exactly one"):
        await pipeline.run(
            candidate_rules=_shipped_rules(),
            scenario_set_id="v",
            scenarios=[],
            scenarios_dir=Path("."),
        )


@pytest.mark.asyncio
async def test_pipeline_loads_scenarios_from_directory(tmp_path: Path) -> None:
    import json

    (tmp_path / "s.json").write_text(
        json.dumps(
            {
                "id": "d1",
                "event": {
                    "schema_version": "1.0.0",
                    "event_id": "00000000-0000-0000-0000-000000000103",
                    "idempotency_key": "d1",
                    "source": "src",
                    "event_type": "change_detected",
                    "detected_at": "2026-07-05T08:00:00Z",
                    "ingested_at": "2026-07-05T08:00:01Z",
                    "mode": "shadow",
                    "payload": {"resource": {"type": "object-storage", "props": {}}},
                },
                "expected": {
                    "tier": "t0",
                    "decision": "abstain",
                    "citing_rule_ids": [],
                    "guard": {
                        "should_execute": False,
                        "should_rollback": False,
                        "should_trigger_policy_violation": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    pipeline = build_pipeline(audit_store=InMemoryStateStore())
    run = await pipeline.run(
        candidate_rules=_shipped_rules(),
        scenario_set_id="v-dir",
        scenarios_dir=tmp_path,
    )
    assert run.candidate_report.scenario_count == 1


@pytest.mark.asyncio
async def test_pipeline_replays_baseline_when_supplied() -> None:
    audit = InMemoryStateStore()
    pipeline = build_pipeline(audit_store=audit)
    scenarios: list[dict[str, Any]] = [
        {
            "id": "s",
            "event": {
                "schema_version": "1.0.0",
                "event_id": "00000000-0000-0000-0000-000000000104",
                "idempotency_key": "s-base",
                "source": "src",
                "event_type": "change_detected",
                "detected_at": "2026-07-05T08:00:00Z",
                "ingested_at": "2026-07-05T08:00:01Z",
                "mode": "shadow",
                "payload": {"resource": {"type": "object-storage", "props": {}}},
            },
            "expected": {
                "tier": "t0",
                "decision": "abstain",
                "citing_rule_ids": [],
                "guard": {
                    "should_execute": False,
                    "should_rollback": False,
                    "should_trigger_policy_violation": False,
                },
            },
        }
    ]
    rules = _shipped_rules()
    run = await pipeline.run(
        candidate_rules=rules,
        scenario_set_id="v-base",
        scenarios=scenarios,
        baseline_rules=rules,
    )
    assert run.baseline_report is not None
    assert run.baseline_report.scenario_set_id.endswith("::baseline")


def test_custom_regression_gate_config_flows_through() -> None:
    """The composition root can inject a tighter gate config."""
    from fdai.rule_catalog.pipeline import RegressionGateConfig

    gate = RegressionGate(
        config=RegressionGateConfig(max_policy_escapes=0, min_coverage_ratio=0.99)
    )
    pipeline = ContinuousRulePipeline(
        regression_gate=gate,
        promotion=RulePromotionController(audit_store=InMemoryStateStore()),
    )
    assert isinstance(pipeline.regression_gate, RegressionGate)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:  # noqa: F821 - string-annotated for lazy import in tests
    from datetime import UTC, datetime

    return datetime.now(tz=UTC)

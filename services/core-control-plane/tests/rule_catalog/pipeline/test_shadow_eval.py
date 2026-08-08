"""ShadowEvaluator - replay + measurement invariants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.pipeline import (
    ShadowEvalError,
    ShadowEvalReport,
    ShadowEvaluator,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
SCENARIOS_DIR = REPO_ROOT / "services" / "core-control-plane" / "tests" / "scenarios" / "v2026.07"


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


def _scenario(
    *,
    scenario_id: str = "s1",
    resource_type: str | None = None,
    props: dict[str, Any] | None = None,
    expected_decision: str = "abstain",
    expected_rule_ids: tuple[str, ...] = (),
    should_execute: bool = False,
    should_trigger_policy_violation: bool = False,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": f"00000000-0000-0000-0000-{hash(scenario_id) & 0xFFFFFFFFFFFF:012x}",
        "idempotency_key": scenario_id,
        "source": "test",
        "event_type": "change_detected",
        "detected_at": "2026-07-05T08:00:00Z",
        "ingested_at": "2026-07-05T08:00:01Z",
        "mode": "shadow",
    }
    if resource_type is not None:
        event["payload"] = {
            "resource": {
                "type": resource_type,
                "resource_id": f"{resource_type}::{scenario_id}",
                "props": props or {},
            }
        }
    return {
        "schema_version": "1.0.0",
        "id": scenario_id,
        "version": "v2026.07",
        "domain": "change",
        "tags": ["test"],
        "event": event,
        "expected": {
            "tier": "t0",
            "decision": expected_decision,
            "citing_rule_ids": list(expected_rule_ids),
            "guard": {
                "should_execute": should_execute,
                "should_rollback": False,
                "should_trigger_policy_violation": should_trigger_policy_violation,
            },
        },
    }


# ---------------------------------------------------------------------------
# Empty / smoke
# ---------------------------------------------------------------------------


def test_empty_scenario_set_returns_empty_report() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenarios(scenario_set_id="v-empty", scenarios=[])
    assert isinstance(report, ShadowEvalReport)
    assert report.scenario_count == 0
    assert report.coverage == 0.0
    assert report.policy_violation_escapes == 0


def test_missing_required_scenario_field_raises() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    with pytest.raises(ShadowEvalError, match="required field"):
        evaluator.evaluate_scenarios(
            scenario_set_id="bad",
            scenarios=[{"id": "x", "event": {}}],  # missing 'expected'
        )


def test_malformed_event_is_reported_via_shadow_eval_error() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    with pytest.raises(ShadowEvalError, match="invalid event"):
        evaluator.evaluate_scenarios(
            scenario_set_id="bad",
            scenarios=[
                {
                    "id": "x",
                    "event": {"schema_version": "1.0.0"},  # missing required
                    "expected": {
                        "tier": "t0",
                        "decision": "abstain",
                        "guard": {
                            "should_execute": False,
                            "should_rollback": False,
                            "should_trigger_policy_violation": False,
                        },
                    },
                }
            ],
        )


def test_max_scenarios_cap_rejects_runaway_set() -> None:
    scenarios = [_scenario(scenario_id=f"s-{i}") for i in range(5)]
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules(), max_scenarios_per_replay=2)
    with pytest.raises(ShadowEvalError, match="scenario cap"):
        evaluator.evaluate_scenarios(scenario_set_id="huge", scenarios=scenarios)


# ---------------------------------------------------------------------------
# Trust-router abstain paths (no OPA needed)
# ---------------------------------------------------------------------------


def test_scenario_without_resource_type_routes_to_abstain() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s1",
        scenarios=[_scenario(scenario_id="no-rt")],
    )
    assert report.scenario_count == 1
    outcome = report.outcomes[0]
    assert outcome.actual_tier == "abstain"
    assert outcome.matched_rule_ids == ()


def test_unmatched_resource_type_scenario_routes_to_t1() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s2",
        scenarios=[
            _scenario(
                scenario_id="unknown",
                resource_type="something.unrelated",
                props={},
            )
        ],
    )
    outcome = report.outcomes[0]
    assert outcome.actual_tier == "t1"
    assert outcome.reason == "no_rule_matches_resource_and_signal_type"


def test_known_resource_type_without_rules_routes_to_t1() -> None:
    evaluator = ShadowEvaluator(candidate_rules=())
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s3",
        scenarios=[
            _scenario(
                scenario_id="known-no-rules",
                resource_type="azure.storage.account",
                props={},
            )
        ],
    )
    outcome = report.outcomes[0]
    assert outcome.actual_tier == "t1"
    assert outcome.actual_pipeline_stage == "abstain"
    assert outcome.matched_rule_ids == ()
    assert outcome.reason == "no_rule_matches_resource_and_signal_type"


# ---------------------------------------------------------------------------
# Policy-violation escape detection (no OPA needed - Abstain evaluator)
# ---------------------------------------------------------------------------


def test_policy_violation_escape_counted_when_expected_but_no_match() -> None:
    """`AbstainEvaluator` never fires; when a scenario expects a
    violation, the escape counter increments."""
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())  # abstain evaluator
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s3",
        scenarios=[
            _scenario(
                scenario_id="expect-violation",
                resource_type="object-storage",
                props={"public_access": "enabled"},
                expected_decision="auto",
                expected_rule_ids=("object-storage.public-access.deny",),
                should_execute=True,
                should_trigger_policy_violation=True,
            )
        ],
    )
    assert report.policy_violation_escapes == 1


def test_no_escape_when_no_violation_expected() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s4",
        scenarios=[_scenario(scenario_id="clean", resource_type="object-storage")],
    )
    assert report.policy_violation_escapes == 0


# ---------------------------------------------------------------------------
# Real OPA replay (skipped when opa missing)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    __import__("shutil").which("opa") is None,
    reason="opa binary missing",
)
def test_opa_replay_matches_expected_public_access_rule() -> None:
    from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator

    evaluator = ShadowEvaluator(
        candidate_rules=_shipped_rules(),
        evaluator=OpaRegoEvaluator(policies_root=POLICIES_ROOT),
    )
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s5",
        scenarios=[
            _scenario(
                scenario_id="deny-me",
                resource_type="object-storage",
                props={"public_access": "enabled", "tags": {"owner": "x"}},
                expected_decision="auto",
                expected_rule_ids=("object-storage.public-access.deny",),
                should_execute=True,
                should_trigger_policy_violation=True,
            )
        ],
    )
    assert report.policy_violation_escapes == 0
    assert report.matched_count == 1
    assert report.coverage == 1.0
    outcome = report.outcomes[0]
    assert "object-storage.public-access.deny" in outcome.matched_rule_ids
    assert outcome.rules_match_expectation


@pytest.mark.skipif(
    __import__("shutil").which("opa") is None,
    reason="opa binary missing",
)
def test_opa_replay_no_match_when_props_are_compliant() -> None:
    from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator

    evaluator = ShadowEvaluator(
        candidate_rules=_shipped_rules(),
        evaluator=OpaRegoEvaluator(policies_root=POLICIES_ROOT),
    )
    # The compliant snapshot MUST satisfy every shipped object-storage rule;
    # if a new rule adds a property, its compliant baseline goes here so this
    # test keeps asserting "no rule fires on a compliant resource".
    report = evaluator.evaluate_scenarios(
        scenario_set_id="s6",
        scenarios=[
            _scenario(
                scenario_id="compliant",
                resource_type="object-storage",
                props={
                    "public_access": "disabled",
                    "public_network_access_enabled": False,
                    "private_endpoints": ["pe-1"],
                    "tags": {"owner": "x", "cost_center": "y"},
                    "infrastructure_encryption_enabled": True,
                    "enable_https_traffic_only": True,
                    "min_tls_version": "TLS1_2",
                    "blob_soft_delete_enabled": True,
                    "blob_versioning_enabled": True,
                    "allow_shared_key_access": False,
                    "diagnostic_settings": ["diag-1"],
                },
                expected_decision="abstain",
            )
        ],
    )
    assert report.matched_count == 0
    assert report.policy_violation_escapes == 0


# ---------------------------------------------------------------------------
# Directory loader
# ---------------------------------------------------------------------------


def test_evaluate_scenario_directory_loads_json_files(tmp_path: Path) -> None:
    (tmp_path / "one.json").write_text(json.dumps(_scenario(scenario_id="d1")), encoding="utf-8")
    (tmp_path / "two.json").write_text(json.dumps(_scenario(scenario_id="d2")), encoding="utf-8")
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenario_directory(scenario_set_id="dir", directory=tmp_path)
    assert {o.scenario_id for o in report.outcomes} == {"d1", "d2"}


def test_evaluate_scenario_directory_rejects_bad_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    with pytest.raises(ShadowEvalError, match="not valid JSON"):
        evaluator.evaluate_scenario_directory(scenario_set_id="dir", directory=tmp_path)


def test_evaluate_frozen_scenario_directory_smoke() -> None:
    """Baseline: replay the frozen Phase-0 scenario set without crashing.

    Every P0 scenario cites `example.*` rule ids that aren't in the P1
    shipped catalog, so we expect zero matches - this test guards
    against regressions in the loader / router / T0 abstain path, not
    against the P0 baseline coverage (that's a separate measurement).
    """
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenario_directory(
        scenario_set_id="v2026.07", directory=SCENARIOS_DIR
    )
    assert report.scenario_count == 9  # frozen count
    assert report.matched_count == 0  # P0 scenarios use example.* rule ids
    # Every scenario expects `should_trigger_policy_violation: false`, so
    # zero-match doesn't escape.
    assert report.policy_violation_escapes == 0


# ---------------------------------------------------------------------------
# Guard invariants (properties)
# ---------------------------------------------------------------------------


def test_construction_rejects_zero_scenario_cap() -> None:
    with pytest.raises(ValueError, match="max_scenarios_per_replay"):
        ShadowEvaluator(candidate_rules=_shipped_rules(), max_scenarios_per_replay=0)


def test_shadow_eval_report_is_immutable() -> None:
    evaluator = ShadowEvaluator(candidate_rules=_shipped_rules())
    report = evaluator.evaluate_scenarios(scenario_set_id="x", scenarios=[])
    with pytest.raises((AttributeError, TypeError)):
        report.scenario_count = 99  # type: ignore[misc]


def test_scenario_outcome_derived_properties() -> None:
    """Direct test of the derived-property helpers on ScenarioOutcome."""
    from fdai.rule_catalog.pipeline import ScenarioOutcome

    escape = ScenarioOutcome(
        scenario_id="escape",
        expected_tier="t0",
        expected_decision="auto",
        actual_tier="t0",
        actual_pipeline_stage="abstain",
        matched_rule_ids=(),
        expected_rule_ids=("r.x",),
        expected_should_execute=True,
        expected_should_trigger_policy_violation=True,
    )
    assert escape.policy_violation_escape is True
    assert escape.tier_matches_expectation is True
    assert escape.decision_matches_expectation is False
    assert escape.rules_match_expectation is False

    clean = ScenarioOutcome(
        scenario_id="clean",
        expected_tier="t0",
        expected_decision="abstain",
        actual_tier="t0",
        actual_pipeline_stage="abstain",
        matched_rule_ids=(),
        expected_rule_ids=(),
    )
    assert clean.policy_violation_escape is False
    assert clean.rules_match_expectation is True

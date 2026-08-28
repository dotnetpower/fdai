"""Tests for the Cost Governance W0 package inventory."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.vidar import Vidar
from fdai.core.mscp_profile import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    build_response_outcome,
    response_outcome_audit_entry,
)
from fdai.core.risk_gate.risk_table import FeatureVector, load_risk_table
from fdai.core.verticals.cost_governance.finops import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    FinOpsGuard,
    ResourceContext,
)
from fdai.shared.contracts.models import Action

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "quality"
    / "architecture"
    / "check-cost-governance-package-inventory.py"
)
INVENTORY = REPO_ROOT / "config" / "cost-governance-package-inventory.json"
FIXTURE_DIR = REPO_ROOT / "tests/integration/fixtures/cost_governance_w0_outcomes"
RISK_TABLE = REPO_ROOT / "rule-catalog/risk-classification.yaml"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cost_governance_package_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker() -> ModuleType:
    return _load_module()


@pytest.fixture
def payload() -> dict[str, Any]:
    value = json.loads(INVENTORY.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_repository_inventory_passes(checker: ModuleType) -> None:
    assert checker.validate() == []


def test_duplicate_rule_ownership_is_rejected(checker: ModuleType, payload: dict[str, Any]) -> None:
    candidate = copy.deepcopy(payload)
    candidate["cost_rule_bindings"].append(copy.deepcopy(candidate["cost_rule_bindings"][0]))

    errors = checker.validate_payload(candidate)

    assert any("duplicate cost rule ownership" in error for error in errors)


def test_missing_rule_binding_is_rejected(checker: ModuleType, payload: dict[str, Any]) -> None:
    candidate = copy.deepcopy(payload)
    candidate["cost_rule_bindings"].pop()

    errors = checker.validate_payload(candidate)

    assert any("cost rule inventory drift" in error for error in errors)


def test_action_type_mismatch_is_rejected(checker: ModuleType, payload: dict[str, Any]) -> None:
    candidate = copy.deepcopy(payload)
    candidate["cost_rule_bindings"][0]["action_type_id"] = "ops.scale-out"

    errors = checker.validate_payload(candidate)

    assert any("action_type_id does not match the rule" in error for error in errors)


def test_disclosure_preset_outside_lattice_is_rejected(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["cost_disclosure"]["presets"]["masked"]["amount_precision"] = "unbounded"

    errors = checker.validate_payload(candidate)

    assert any("outside its lattice" in error for error in errors)


def test_axis_cannot_implicitly_grant_another_axis(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["axis_contract"]["enabled"]["does_not_grant"].remove("mode")

    errors = checker.validate_payload(candidate)

    assert any("does_not_grant" in error for error in errors)


def test_scenario_digest_drift_is_rejected(checker: ModuleType, payload: dict[str, Any]) -> None:
    candidate = copy.deepcopy(payload)
    candidate["baseline_corpus"]["cases"][0]["sha256"] = "0" * 64

    errors = checker.validate_payload(candidate)

    assert any("does not match the scenario content" in error for error in errors)


def test_missing_outcome_coverage_is_rejected(checker: ModuleType, payload: dict[str, Any]) -> None:
    candidate = copy.deepcopy(payload)
    candidate["baseline_corpus"]["cases"] = [
        case for case in candidate["baseline_corpus"]["cases"] if case.get("outcome") != "rollback"
    ]

    errors = checker.validate_payload(candidate)

    assert any("outcome corpus is incomplete" in error for error in errors)


def test_duplicate_asset_ownership_is_rejected(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["assets"][-1]["paths"].append(candidate["assets"][0]["path"])

    errors = checker.validate_payload(candidate)

    assert any("duplicate asset ownership" in error for error in errors)


def test_missing_non_rule_asset_ownership_is_rejected(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["assets"] = [
        asset for asset in candidate["assets"] if asset["id"] != "console-cost-surfaces"
    ]

    errors = checker.validate_payload(candidate)

    assert any("asset inventory digest drift" in error for error in errors)


@pytest.mark.parametrize(
    "field",
    ["rule_path", "policy_path", "remediation_path", "action_type_path"],
)
def test_dangling_rule_graph_reference_is_rejected(
    checker: ModuleType,
    payload: dict[str, Any],
    field: str,
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["cost_rule_bindings"][0][field] = f"missing/{field}"

    errors = checker.validate_payload(candidate)

    assert any("references a missing file" in error and field in error for error in errors)


def test_cost_model_reconciliation_drift_is_rejected(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["contract_freeze"]["cost_models"]["overlap_policy"] = "merge-fields"

    errors = checker.validate_payload(candidate)

    assert any("contract_freeze" in error for error in errors)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("active_owner", "base-and-package", "identity or ownership"),
        ("package_version", "0.1.2", "identity or ownership"),
        ("package_manifest_sha256", "0" * 64, "manifest digest drift"),
    ],
)
def test_w6_current_ownership_drift_is_rejected(
    checker: ModuleType,
    payload: dict[str, Any],
    field: str,
    value: str,
    message: str,
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["w6_cutover"][field] = value

    assert any(message in error for error in checker.validate_payload(candidate))


def test_w6_parity_corpus_digest_drift_is_rejected(
    checker: ModuleType,
    payload: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["w6_cutover"]["parity_corpus"]["sha256"] = "0" * 64

    assert any(
        "parity corpus digest drift" in error for error in checker.validate_payload(candidate)
    )


def test_missing_future_contract_definition_is_rejected(
    checker: ModuleType, payload: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["future_contracts"].pop()

    errors = checker.validate_payload(candidate)

    assert any("complete frozen W0 set" in error for error in errors)


def _load_fixture(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _counting_executor(
    calls: list[dict[str, Any]],
    *,
    result: bool,
) -> Callable[[dict[str, Any]], Awaitable[bool]]:
    async def execute(context: dict[str, Any]) -> bool:
        calls.append(context)
        return result

    return execute


def test_allow_fixture_exercises_finops_guard() -> None:
    case = _load_fixture("allow")
    given = case["input"]
    decision = FinOpsGuard().evaluate(
        FinOpsCandidate(
            action_id=given["action_id"],
            kind=FinOpsActionKind(given["kind"]),
            resource=ResourceContext(
                resource_id=given["resource_id"],
                environment=FinOpsEnvironment(given["environment"]),
                tags=frozenset(given["tags"]),
                current_capacity=given["current_capacity"],
                dependent_ids=tuple(given["dependent_ids"]),
            ),
            target_capacity=given["target_capacity"],
        )
    )

    assert decision.outcome.value == case["expected"]["decision"]
    assert list(decision.reasons) == case["expected"]["reasons"]


@pytest.mark.parametrize("fixture_name", ["hold", "deny"])
def test_risk_fixture_exercises_shipped_risk_table(fixture_name: str) -> None:
    case = _load_fixture(fixture_name)
    verdict = load_risk_table(RISK_TABLE).evaluate(FeatureVector(**case["input"]))

    assert verdict.decision.value == case["expected"]["decision"]
    assert verdict.rule_id == case["expected"]["rule_id"]
    assert verdict.quorum == case["expected"]["quorum"]


@pytest.mark.asyncio
async def test_no_op_fixture_exercises_thor_idempotency() -> None:
    case = _load_fixture("no-op")
    calls: list[dict[str, Any]] = []
    thor = Thor(executor=_counting_executor(calls, result=True))

    first = await thor.dispatch_verdict(dict(case["input"]))
    duplicate = await thor.dispatch_verdict(dict(case["input"]))

    assert (first is duplicate) is case["expected"]["duplicate_returns_existing_run"]
    assert duplicate.state.value == case["expected"]["state"]
    assert len(calls) == case["expected"]["executor_calls"]


@pytest.mark.asyncio
async def test_human_approval_fixture_exercises_thor_hold() -> None:
    case = _load_fixture("human-approval")
    calls: list[dict[str, Any]] = []
    thor = Thor(executor=_counting_executor(calls, result=True))

    run = await thor.dispatch_verdict(dict(case["input"]))

    assert run.state.value == case["expected"]["state"]
    assert run.quorum_required == case["expected"]["quorum_required"]
    assert len(calls) == case["expected"]["executor_calls"]


@pytest.mark.asyncio
async def test_execute_fixture_exercises_thor_executor() -> None:
    case = _load_fixture("execute")
    calls: list[dict[str, Any]] = []
    thor = Thor(executor=_counting_executor(calls, result=True))

    run = await thor.dispatch_verdict(dict(case["input"]))

    assert run.state.value == case["expected"]["state"]
    assert run.shadow_mode is case["expected"]["shadow_mode"]
    assert len(calls) == case["expected"]["executor_calls"]


@pytest.mark.asyncio
async def test_rollback_fixture_exercises_thor_and_vidar() -> None:
    case = _load_fixture("rollback")
    bus = InMemoryBus(registry=load_pantheon())
    thor = Thor(bus=bus, executor=_counting_executor([], result=False))

    async def rollback_executor(action_run: dict[str, Any]) -> str:
        return f"rollback:{action_run['correlation_id']}"

    vidar = Vidar(bus=bus, executors={"state_forward_only": rollback_executor})
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = await thor.dispatch_verdict(dict(case["input"]))

    assert run.state is ActionRunState.ROLLED_BACK
    assert run.state.value == case["expected"]["state"]
    assert run.rollback_ref == case["expected"]["rollback_ref"]
    assert vidar.records[-1].state == case["expected"]["rollback_state"]


def test_unverified_effect_fixture_exercises_response_contract() -> None:
    case = _load_fixture("unverified-effect")
    given = case["input"]
    outcome = build_response_outcome(
        action=Action.model_validate(given["action"]),
        execution_outcome=given["execution_outcome"],
        verification=EffectVerificationResult(
            EffectVerificationStatus(given["verification_status"]),
            EffectVerificationReason(given["verification_reason"]),
        ),
        recorded_at=datetime.fromisoformat(given["recorded_at"].replace("Z", "+00:00")),
    )
    audit_entry = response_outcome_audit_entry(outcome)

    assert outcome.label.value == case["expected"]["label"]
    assert outcome.verification_status.value == case["expected"]["verification_status"]
    assert audit_entry["verification_reason"] == given["verification_reason"]
    assert audit_entry["verification_passed"] is case["expected"]["verification_passed"]
    assert audit_entry["scorable"] is case["expected"]["scorable"]

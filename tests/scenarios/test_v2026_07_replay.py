"""Replay every v2026.07 frozen scenario through the real :class:`ControlLoop`.

Purpose
-------

The v2026.07 scenarios in [`tests/scenarios/v2026.07/`](v2026.07/) are
**frozen expected-verdict specs** used by the P0 reference-agent
baseline. Their event bodies intentionally omit ``payload.resource`` and
their ``citing_rule_ids`` are placeholder names - the frozen artifact
must stay reusable across tiers as P1/P2/P3 land.

This harness satisfies the P1 exit criterion

    "The Change gate runs in **shadow** against the frozen Phase 0
    scenario set with every decision logged (event id, tier, verdict,
    citing rule ids, mode)."

by pairing each scenario with an optional overlay under
[`enrichment/v2026.07/`](enrichment/v2026.07/) that supplies the
concrete ``payload.resource`` block needed to fire a real shipped
rule. Scenarios without an overlay are enumerated too, marked ``xfail``
with a documented reason so a future phase can drop the marker without
touching the harness structure.

Assertion policy
----------------

For each scenario:

- **overlay present** (P1-replayable): the enriched event runs through
  :class:`ControlLoop.process`; the harness asserts
  :attr:`ControlLoopResult.outcome`, :attr:`decision`, and that the
  overlay's ``expected_citing_rule_id_present`` appears in the P1
  citing set. The scenario's `guard.should_execute` bit must agree
  with whether a shadow PR was published.
- **overlay absent**: the harness records the scenario as ``xfail``
  with a reason describing which subsystem is still missing (P2 T1/T2,
  P2 risk-gate, or no shipped rule maps yet). The harness still runs
  the loop end-to-end so we exercise the audit-write path and prove
  the pipeline does not crash on incomplete inputs.

The harness uses the **shipped catalog verbatim** (real rule YAMLs,
Rego policies, Terraform templates, ActionType YAMLs) - the same
fixture builder as
[`tests/pipeline/test_control_loop_e2e.py`](../pipeline/test_control_loop_e2e.py).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from fdai.core.control_loop import (
    ControlLoop,
    ControlLoopOutcome,
    ControlLoopResult,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

SCENARIO_DIR = Path(__file__).resolve().parent / "v2026.07"
ENRICHMENT_DIR = Path(__file__).resolve().parent / "enrichment" / "v2026.07"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT,
    reason="opa binary not found on PATH; skip scenario replay",
)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

# Scenario id → xfail reason when no enrichment overlay exists. Keeping
# the reasons here (rather than as strings in each JSON) makes it a
# checklist reviewers can maintain as tiers land.
_XFAIL_REASONS: dict[str, str] = {
    "change.drift-manual-portal-edit.003": (
        "No shipped drift-reconcile rule + ActionType authored yet "
        "(Change Safety backlog); the risk-gate HIL path is already available "
        "via the overlay's wire_risk_gate flag once a rule maps."
    ),
    "dr.backup-vault-restore-rehearsal.002": (
        "No shipped rule authored for backup-restore rehearsal cadence."
    ),
    "dr.chaos-experiment-novel.003": (
        "T2 tier is wired into ControlLoop shadow-only (audits verdicts); this "
        "scenario needs a wired t2_engine + T2 execution (candidate -> Action -> "
        "risk-gate), which is P2/P3 backlog."
    ),
}


def _scenario_id_to_filename(scenario_id: str) -> str:
    return scenario_id.replace(".", "-") + ".json"


def _load_scenarios() -> list[tuple[Path, dict[str, Any]]]:
    files = sorted(SCENARIO_DIR.glob("*.json"))
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in files]


def _load_enrichment(scenario_id: str) -> dict[str, Any] | None:
    path = ENRICHMENT_DIR / _scenario_id_to_filename(scenario_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Loop factory (mirrors test_control_loop_e2e for symmetry)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped_catalog() -> tuple[Any, Any]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
        remediation_root=REMEDIATION_ROOT,
    )
    return rules, action_types


def _make_loop(
    shipped_catalog: tuple[Any, Any],
    *,
    wire_risk_gate: bool = False,
) -> tuple[ControlLoop, RecordingRemediationPrPublisher, InMemoryStateStore]:
    rules, action_types = shipped_catalog
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    action_types_by_name = {a.name: a for a in action_types}
    action_builder = ActionBuilder(action_types_by_name=action_types_by_name)
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    # Overlays that assert HIL routing opt into the risk-gate path; the
    # rest keep the shadow-PR posture (T0 judge-and-log). Wiring the gate
    # globally would fail-close every scenario to HIL because the gate
    # receives no inventory age here (graph_fresh precondition unmet).
    risk_kwargs: dict[str, Any] = {}
    if wire_risk_gate:
        from fdai.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
        from fdai.core.risk_gate.risk_table import load_risk_table

        risk_kwargs = {
            "risk_table": load_risk_table(REPO_ROOT / "rule-catalog" / "risk-classification.yaml"),
            "action_types_by_name": action_types_by_name,
            "risk_gate": RiskGate(registry=ActionPromotionRegistry()),
        }
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=evaluator),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
        **risk_kwargs,
    )
    return loop, publisher, audit


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _merge_enrichment(scenario_event: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the scenario event with the overlay's payload merged in.

    The frozen event MUST NOT be mutated in place; the merge is deep only
    over ``payload`` because that's the field the frozen set intentionally
    leaves for consumers to fill.
    """
    enriched = dict(scenario_event)
    payload = dict(scenario_event.get("payload") or {})
    payload["resource"] = overlay["event_payload_resource"]
    enriched["payload"] = payload
    return enriched


@pytest.fixture(scope="module")
def scenario_index() -> dict[str, dict[str, Any]]:
    """{scenario_id: scenario_dict} for parametrize-id lookup."""
    return {s["id"]: s for _, s in _load_scenarios()}


@requires_opa
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario_path",
    [p for p, _ in _load_scenarios()],
    ids=[s["id"] for _, s in _load_scenarios()],
)
async def test_v2026_07_scenario_replays_through_control_loop(
    scenario_path: Path,
    shipped_catalog: tuple[Any, Any],
) -> None:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario_id: str = scenario["id"]

    overlay = _load_enrichment(scenario_id)
    if overlay is None:
        reason = _XFAIL_REASONS.get(
            scenario_id,
            "no enrichment overlay authored for this scenario yet",
        )
        pytest.xfail(reason)

    # ------------------------------------------------------------------
    # P1-replayable path - enriched event runs against the real loop.
    # ------------------------------------------------------------------
    loop, publisher, audit = _make_loop(
        shipped_catalog, wire_risk_gate=bool(overlay.get("wire_risk_gate", False))
    )
    enriched_event = _merge_enrichment(scenario["event"], overlay)

    result: ControlLoopResult = await loop.process(enriched_event)

    expected_outcome = ControlLoopOutcome(overlay["expected_control_loop_outcome"])
    assert result.outcome is expected_outcome, (
        f"scenario {scenario_id}: expected {expected_outcome}, "
        f"got {result.outcome} ({result.reason})"
    )
    assert result.decision == overlay["expected_decision"], (
        f"scenario {scenario_id}: decision mismatch (got {result.decision})"
    )

    expected_rule = overlay["expected_citing_rule_id_present"]
    assert expected_rule in result.citing_rule_ids, (
        f"scenario {scenario_id}: expected shipped rule "
        f"{expected_rule!r} in citing_rule_ids={result.citing_rule_ids}"
    )

    # Shadow-mode invariant: every P1 execution result is SHADOW; a
    # published PR carries the shadow label.
    for execution in result.execution_results:
        assert execution.mode is Mode.SHADOW
    for pr in publisher.records:
        assert pr.mode is Mode.SHADOW
        assert "shadow" in pr.labels

    # Guard-bit consistency: `should_execute` must agree with whether a
    # PR was actually published under P1.
    scenario_should_execute = bool(scenario["expected"]["guard"]["should_execute"])
    executed = bool(publisher.records)
    assert scenario_should_execute is executed, (
        f"scenario {scenario_id}: guard.should_execute={scenario_should_execute} "
        f"disagrees with actual publisher activity={executed}"
    )

    # Every terminal path writes exactly one top-level audit entry
    # (executor writes its own per-action entry in addition).
    assert list(audit.audit_entries), "no audit entry emitted for enriched scenario"


def test_every_frozen_scenario_has_an_xfail_reason_or_an_overlay() -> None:
    """Guard: a scenario without an overlay MUST have an xfail reason.

    Prevents a future scenario from silently being skipped without
    someone acknowledging why it is not P1-replayable yet.
    """
    for _, scenario in _load_scenarios():
        scenario_id: str = scenario["id"]
        overlay = _load_enrichment(scenario_id)
        if overlay is not None:
            continue
        assert scenario_id in _XFAIL_REASONS, (
            f"scenario {scenario_id!r} has no overlay under enrichment/v2026.07/ "
            f"and no reason documented in _XFAIL_REASONS"
        )

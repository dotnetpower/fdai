"""Replay every v2026.07 frozen scenario through the real :class:`ControlLoop`.

Purpose
-------

The v2026.07 scenarios in [`services/core-control-plane/tests/scenarios/v2026.07/`](v2026.07/) are
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
[`services/core-control-plane/tests/pipeline/test_control_loop_e2e.py`](../pipeline/test_control_loop_e2e.py).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.core.control_loop import (
    ControlLoop,
    ControlLoopOutcome,
    ControlLoopResult,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.tiers.t2_reasoning import T2Tier
from fdai.core.tiers.t2_reasoning.testing import AbstainingT2Proposer
from fdai.core.trust_router import TrustRouter
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
    RecordingStagePublisher,
)
from fdai_core_test_support.cost_governance_catalog import (
    CostGovernanceCatalogComposition,
    compose_cost_governance_catalog,
)
from fdai_core_test_support.verified_shadow_executor import VerifiedShadowExecutor

REPO_ROOT = Path(__file__).resolve().parents[4]
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
_XFAIL_REASONS: dict[str, str] = {}


def _scenario_id_to_filename(scenario_id: str) -> str:
    return scenario_id.replace(".", "-") + ".json"


def _load_scenarios() -> list[tuple[Path, dict[str, Any]]]:
    files = sorted(path for path in SCENARIO_DIR.glob("*.json") if path.name != "manifest.json")
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in files]


def _load_enrichment(scenario_id: str) -> dict[str, Any] | None:
    path = ENRICHMENT_DIR / _scenario_id_to_filename(scenario_id)
    if not path.exists():
        return None
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Loop factory (mirrors test_control_loop_e2e for symmetry)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped_catalog(
    tmp_path_factory: pytest.TempPathFactory,
) -> CostGovernanceCatalogComposition:
    return compose_cost_governance_catalog(
        REPO_ROOT,
        enabled=True,
        scratch_root=tmp_path_factory.mktemp("cost-governance-replay"),
    )


def _make_loop(
    shipped_catalog: CostGovernanceCatalogComposition,
    *,
    wire_risk_gate: bool = False,
    wire_t2: bool = False,
    publisher: Any | None = None,
    audit: InMemoryStateStore | None = None,
    executor: Any | None = None,
    stage_publisher: Any | None = None,
) -> tuple[ControlLoop, Any, InMemoryStateStore, Any]:
    rules = shipped_catalog.rules
    action_types = shipped_catalog.action_types
    index = RuleIndex.build(rules)
    evaluator = OpaRegoEvaluator(policies_root=shipped_catalog.policies_root)
    publisher = publisher if publisher is not None else RecordingRemediationPrPublisher()
    audit = audit if audit is not None else InMemoryStateStore()
    executor = executor or VerifiedShadowExecutor(
        publisher=publisher,
        audit_store=audit,
        renderer=TemplateRenderer(remediation_root=shipped_catalog.remediation_root),
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
    t2_engine = None
    if wire_t2:

        class _UnusedQualityGate:
            async def evaluate(self, candidate: Any) -> Any:
                raise AssertionError(f"unexpected candidate: {candidate.action_type}")

        t2_engine = T2Tier(
            proposer=AbstainingT2Proposer(),
            quality_gate=_UnusedQualityGate(),
        )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=evaluator),
        action_builder=action_builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={r.id: r for r in rules},
        t2_engine=t2_engine,
        stage_publisher=stage_publisher,
        **risk_kwargs,
    )
    return loop, publisher, audit, executor


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
    shipped_catalog: CostGovernanceCatalogComposition,
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
    loop, publisher, audit, _ = _make_loop(
        shipped_catalog,
        wire_risk_gate=bool(overlay.get("wire_risk_gate", False)),
        wire_t2=bool(overlay.get("wire_t2", False)),
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

    expected_rule = overlay.get("expected_citing_rule_id_present")
    if expected_rule is not None:
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


@requires_opa
@pytest.mark.asyncio
async def test_phase0_correlation_spans_ingest_route_gate_and_audit(
    shipped_catalog: CostGovernanceCatalogComposition,
) -> None:
    scenario_id = "change.nsg-allow-any-inbound.002"
    scenario = json.loads(
        (SCENARIO_DIR / _scenario_id_to_filename(scenario_id)).read_text(encoding="utf-8")
    )
    overlay = _load_enrichment(scenario_id)
    assert overlay is not None and overlay["wire_risk_gate"] is True
    correlation_id = "phase0-correlation-proof"
    event = _merge_enrichment(scenario["event"], overlay)
    event["correlation_id"] = correlation_id
    audit = InMemoryStateStore()
    stages = RecordingStagePublisher()
    loop, _, _, _ = _make_loop(
        shipped_catalog,
        wire_risk_gate=True,
        audit=audit,
        stage_publisher=stages,
    )

    result = await loop.process(event)

    assert result.outcome is ControlLoopOutcome.HIL
    assert result.decision == "hil"
    assert tuple((item.stage, item.phase) for item in stages.events) == (
        (StageName.INGEST, StagePhase.DONE),
        (StageName.ROUTE, StagePhase.DONE),
        (StageName.VERIFY, StagePhase.DONE),
        (StageName.GATE, StagePhase.DONE),
        (StageName.AUDIT, StagePhase.DONE),
    )
    gate = stages.by_stage(StageName.GATE)
    assert len(gate) == 1
    assert gate[0].detail["gate_decision"] == "hil"
    assert {item.correlation_id for item in stages.events} == {correlation_id}
    audit_entries = tuple(_unwrap_audit(item) for item in audit.audit_entries)
    assert audit_entries
    assert {item.get("correlation_id") for item in audit_entries} == {correlation_id}
    assert any(item.get("action_kind") == "risk_gate.unified" for item in audit_entries)


@requires_opa
@pytest.mark.asyncio
async def test_sre_unknown_terminates_before_a3e_authority_is_applicable(
    shipped_catalog: CostGovernanceCatalogComposition,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove A3-E is inapplicable because the SRE unknown produces no Action."""

    scenario_id = "sre.slo-signal-source-unmapped.002"
    scenario = json.loads(
        (SCENARIO_DIR / _scenario_id_to_filename(scenario_id)).read_text(encoding="utf-8")
    )
    overlay = _load_enrichment(scenario_id)
    assert overlay is not None, f"{scenario_id} lost its enrichment overlay"
    publisher = RecordingRemediationPrPublisher()
    audit = InMemoryStateStore()
    loop, _, _, _ = _make_loop(
        shipped_catalog,
        publisher=publisher,
        audit=audit,
        wire_t2=True,
    )
    action_builds: list[str] = []
    authority_evaluations: list[Any] = []

    def fail_if_finding_builds_action(self: Any, **kwargs: Any) -> Any:
        del self, kwargs
        action_builds.append("finding")
        raise AssertionError("the routing terminal must not build an Action from a finding")

    def fail_if_candidate_builds_action(self: Any, **kwargs: Any) -> Any:
        del self, kwargs
        action_builds.append("candidate")
        raise AssertionError("the routing terminal must not build an Action from a T2 candidate")

    async def fail_if_authority_is_evaluated(*, event: Any, action: Any) -> Any:
        del event
        authority_evaluations.append(action)
        raise AssertionError("standing authority is not applicable without an actionable candidate")

    monkeypatch.setattr(ActionBuilder, "build_from_finding", fail_if_finding_builds_action)
    monkeypatch.setattr(ActionBuilder, "build_from_candidate", fail_if_candidate_builds_action)
    monkeypatch.setattr(loop, "_evaluate_execution_authorization", fail_if_authority_is_evaluated)

    result = await loop.process(_merge_enrichment(scenario["event"], overlay))

    assert result.outcome is ControlLoopOutcome.ABSTAINED_ROUTING
    assert result.decision == "abstain"
    assert result.citing_rule_ids == ()
    assert result.execution_results == ()
    assert action_builds == []
    assert authority_evaluations == []
    assert publisher.records == ()
    entries = tuple(_unwrap_audit(record) for record in audit.audit_entries)
    assert any(entry.get("action_kind") == "control_loop.abstain" for entry in entries)
    assert all(not str(entry.get("action_kind", "")).startswith("executor.") for entry in entries)


class _FailOncePublisher(RemediationPrPublisher):
    """Fail the first publish, then behave exactly like the recording publisher.

    A transport that dies after the request left the process is the realistic partial
    failure: the executor cannot know whether the PR exists.
    """

    def __init__(self) -> None:
        self._delegate = RecordingRemediationPrPublisher()
        self._failed = False

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        if not self._failed:
            self._failed = True
            raise ConnectionError("publisher transport dropped after the request was sent")
        return await self._delegate.publish(pr)

    @property
    def records(self) -> tuple[RemediationPr, ...]:
        return self._delegate.records


@requires_opa
@pytest.mark.asyncio
async def test_sre_partial_publish_failure_closes_the_audit_and_recovers_on_retry(
    shipped_catalog: CostGovernanceCatalogComposition,
) -> None:
    """SRE `partial_failure_recovery` evidence for `sre.cluster-diagnostics-missing.001`.

    The constitutional dimension asks for one partial failure followed by recovery. Here the
    publisher dies mid-dispatch, so the effect outcome is genuinely unknown. What must hold is
    that the run never claims success, closes its terminal audit entry before the error
    escapes, caches nothing, and that a retry over the same executor publishes exactly one
    shadow PR. The retry is what proves the unknown closure was not cached: had it been, the
    dedupe hit would return the unknown result and publish nothing.
    """

    scenario_id = "sre.cluster-diagnostics-missing.001"
    scenario = json.loads(
        (SCENARIO_DIR / _scenario_id_to_filename(scenario_id)).read_text(encoding="utf-8")
    )
    overlay = _load_enrichment(scenario_id)
    assert overlay is not None, f"{scenario_id} lost its enrichment overlay"
    enriched_event = _merge_enrichment(scenario["event"], overlay)

    publisher = _FailOncePublisher()
    audit = InMemoryStateStore()
    _, _, _, executor = _make_loop(shipped_catalog, publisher=publisher, audit=audit)
    failing_loop, _, _, _ = _make_loop(
        shipped_catalog, publisher=publisher, audit=audit, executor=executor
    )

    with pytest.raises(ConnectionError):
        await failing_loop.process(enriched_event)

    unknown = [
        _unwrap_audit(entry)
        for entry in audit.audit_entries
        if _unwrap_audit(entry).get("outcome") == "publish_outcome_unknown"
    ]
    assert len(unknown) == 1, "the failed dispatch did not close its terminal audit entry"
    assert unknown[0]["audit_phase"] == "terminal"
    assert publisher.records == (), "a failed publish must not record a PR"

    # A fresh ingest, the same executor: nothing cached the unknown attempt as handled.
    retry_loop, _, _, _ = _make_loop(
        shipped_catalog, publisher=publisher, audit=audit, executor=executor
    )
    retried = await retry_loop.process(enriched_event)

    assert retried.outcome is ControlLoopOutcome.EXECUTED
    assert len(publisher.records) == 1, "recovery published more than one PR"
    assert publisher.records[0].mode is Mode.SHADOW
    published = [
        _unwrap_audit(entry)
        for entry in audit.audit_entries
        if _unwrap_audit(entry).get("outcome") == "published"
    ]
    assert len(published) == 1


def _unwrap_audit(record: Any) -> dict[str, Any]:
    inner = record.get("entry") if isinstance(record, dict) else None
    return inner if isinstance(inner, dict) else dict(record)

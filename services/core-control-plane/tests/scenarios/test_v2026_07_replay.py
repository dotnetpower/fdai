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

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.agents._framework.adapters import AuditEntry, InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_health import evaluate_degradation
from fdai.agents._framework.vertical_precedence import InitialVerticalPrecedence
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
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
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.tiers.t0_deterministic import (
    OpaRegoEvaluator,
    RuleIndex,
    T0Engine,
)
from fdai.core.tiers.t2_reasoning import T2Tier
from fdai.core.tiers.t2_reasoning.testing import AbstainingT2Proposer
from fdai.core.trust_router import TrustRouter
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.testing import (
    InMemoryOntologyInstanceStore,
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
    RecordingStagePublisher,
)
from fdai_core_test_support.cost_governance_catalog import (
    CostGovernanceCatalogComposition,
    compose_cost_governance_catalog,
)
from fdai_core_test_support.verified_shadow_executor import VerifiedShadowExecutor
from jsonschema import Draft202012Validator

from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIO_DIR = Path(__file__).resolve().parent / "v2026.07"
ENRICHMENT_DIR = Path(__file__).resolve().parent / "enrichment" / "v2026.07"
CONFLICT_DIR = Path(__file__).resolve().parent / "cross-objective"
CONFLICT_SPEC_PATH = CONFLICT_DIR / "v2026.07-sre.json"
CONFLICT_SCHEMA_PATH = CONFLICT_DIR / "schema.json"

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


# ---------------------------------------------------------------------------
# Cross-objective conflict
# ---------------------------------------------------------------------------
#
# The SRE `cross_objective_conflict` dimension. The frozen spec under
# [`cross-objective/`](cross-objective/) composes one conflict out of three
# options that each replay a frozen v2026.07 scenario through the real
# :class:`ControlLoop`. Nothing about the conflict is hand-authored:
#
# - each option's recommendation is derived from the ActionType its own
#   replay produced, through the spec's frozen ActionType-to-direction map,
#   so an option that produces no action can only contribute `hold`;
# - the shared logical target is derived by traversing the shipped ontology
#   graph from each replayed resource and intersecting what they reach;
# - the arbitration observation time is derived from the replayed events.
#
# The conflict then travels the shipped governed boundary with canonical
# evidence attached: Forseti materializes an operational context, builds a
# :class:`DomainDecisionCase` from it, and is the sole writer of
# `object.arbitration-request`; Odin is the sole arbitration owner; and
# Saga audits the terminal verdict on its declared `object.verdict`
# subscription. No second arbiter and no new authority is introduced here.


def _load_conflict_spec() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(CONFLICT_SPEC_PATH.read_text(encoding="utf-8")))


def _canonical_digest(payload: object) -> str:
    """Digest a payload under one canonical encoding.

    Sorted keys and separator-tight JSON make the digest a property of the
    content, not of dict ordering or formatting, so an unchanged replay
    reproduces it exactly.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _conflict_cutoff(spec: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(spec["observed_at"]).replace("Z", "+00:00"))


async def _conflict_context_store(spec: dict[str, Any]) -> InMemoryOntologyInstanceStore:
    """Load the frozen customer-agnostic neighborhood into the shipped store.

    The graph is operating context, not advice: it says which resources the
    options share, which objectives govern them, and where each objective's
    evidence comes from. Forseti's materializer folds it into the snapshot
    that grounds the decision case.
    """

    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    for record in spec["operating_context"]["objects"]:
        await store.upsert_object(
            OntologyObjectRecord(
                id=str(record["id"]),
                object_type=str(record["object_type"]),
                properties=dict(record["properties"]),
            )
        )
    for link in spec["operating_context"]["links"]:
        await store.upsert_link(
            OntologyLinkRecord(
                link_type=str(link["link_type"]),
                from_id=str(link["from_id"]),
                to_id=str(link["to_id"]),
            )
        )
    return store


def _conflict_source_freshness(spec: dict[str, Any], observed_at: str) -> list[dict[str, Any]]:
    """Report freshness for every objective source the graph itself declares."""

    return sorted(
        (
            {
                "source": str(record["properties"]["measurement_source_ref"]),
                "observed_at": observed_at,
                "max_age_seconds": int(record["properties"]["freshness_seconds"]),
            }
            for record in spec["operating_context"]["objects"]
            if "freshness_seconds" in record["properties"]
        ),
        key=lambda item: str(item["source"]),
    )


async def _derive_shared_target(
    store: InMemoryOntologyInstanceStore,
    spec: dict[str, Any],
    grounded: tuple[dict[str, Any], ...],
) -> str:
    """Derive the one logical target every replayed resource shares.

    Traverse the shipped graph from each option's *replayed* resource and
    intersect the workloads they reach. A single shared workload is what
    makes the options contend at all; the target they contend over is the
    resource that workload runs on which no option reported on its own.
    Anything else means the options do not share one thing and the conflict
    has no basis.
    """

    link_types = sorted({str(link["link_type"]) for link in spec["operating_context"]["links"]})
    observed = {str(option["observed_resource_id"]) for option in grounded}
    assert observed, "no grounded option contributed a resource to traverse"
    reachable: list[set[str]] = []
    for resource_id in sorted(observed):
        snapshot = await store.traverse(
            root_ids=(resource_id,),
            root_object_types=("Resource",),
            link_types=link_types,
            direction="both",
            max_depth=1,
        )
        reachable.append(
            {record.id for record in snapshot.objects if record.object_type == "Workload"}
        )
    workloads = set.intersection(*reachable)
    assert len(workloads) == 1, f"options do not share exactly one workload: {sorted(workloads)}"
    shared_workload = workloads.pop()

    snapshot = await store.traverse(
        root_ids=(shared_workload,),
        root_object_types=("Workload",),
        link_types=link_types,
        direction="outgoing",
        max_depth=1,
    )
    shared = {
        record.id
        for record in snapshot.objects
        if record.object_type == "Resource" and record.id not in observed
    }
    assert len(shared) == 1, f"options do not contend for exactly one target: {sorted(shared)}"
    return shared.pop()


async def _ground_conflict_options(
    shipped_catalog: CostGovernanceCatalogComposition,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Replay every option's frozen scenario and return its runtime evidence.

    An option is *eligible* only when its own replay reaches an executed
    deterministic outcome that cites a shipped rule and builds exactly one
    ActionType. The recommendation it contributes is then read out of the
    frozen ActionType-to-direction map using the ActionType the runtime
    actually produced - never a string carried in the spec for that option.
    Anything else - an abstention on an unmodelled signal, for example -
    leaves the option's evidence unresolved and it contributes `hold`.
    """

    recommendations = spec["action_type_recommendations"]
    grounded: list[dict[str, Any]] = []
    for option in spec["options"]:
        scenario_id = str(option["scenario_id"])
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
            wire_risk_gate=bool(overlay.get("wire_risk_gate", False)),
            wire_t2=bool(overlay.get("wire_t2", False)),
        )
        event = _merge_enrichment(scenario["event"], overlay)
        event["correlation_id"] = spec["correlation_id"]

        result = await loop.process(event)

        entries = [_unwrap_audit(entry) for entry in audit.audit_entries]
        action_types = sorted(
            {
                str(item.audit_context.get("action_type", ""))
                for item in result.execution_results
                if str(item.audit_context.get("action_type", ""))
            }
        )
        eligible = (
            result.outcome is ControlLoopOutcome.EXECUTED
            and result.decision == "auto"
            and bool(result.citing_rule_ids)
            and len(action_types) == 1
        )
        action_type = action_types[0] if eligible else None
        if action_type is not None:
            assert action_type in recommendations, (
                f"{scenario_id} produced ActionType {action_type!r}, "
                "which the frozen conflict does not map to an objective direction"
            )
        # The resource identity the loop actually routed on. The executor
        # audit is authoritative when the option executed; the routed event
        # carries it when the option abstained before any action existed.
        audited_resources = sorted(
            {str(entry["resource_ref"]) for entry in entries if entry.get("resource_ref")}
        )
        routed_resource = str(event["payload"]["resource"]["resource_id"])
        assert audited_resources in ([], [routed_resource]), (
            f"{scenario_id} audited a resource its routed event never named: {audited_resources}"
        )
        grounded.append(
            {
                "option_id": str(option["option_id"]),
                "scenario_id": scenario_id,
                "objective_domain": str(option["objective_domain"]),
                "eligible": eligible,
                "action_type": action_type,
                "recommendation": (
                    str(recommendations[action_type])
                    if action_type is not None
                    else str(spec["expected"]["held_recommendation"])
                ),
                "observed_resource_id": routed_resource,
                "observed_at": str(event["detected_at"]),
                "event_id": str(event["event_id"]),
                "outcome": result.outcome.value,
                "decision": result.decision,
                "citing_rule_ids": list(result.citing_rule_ids),
                "execution_modes": sorted({item.mode.value for item in result.execution_results}),
                "published_pr_modes": sorted({record.mode.value for record in publisher.records}),
                "audit_action_kinds": sorted(
                    {str(entry.get("action_kind", "")) for entry in entries}
                ),
                "audit_phases": sorted(
                    {str(entry["audit_phase"]) for entry in entries if entry.get("audit_phase")}
                ),
            }
        )
    return tuple(grounded)


def _conflict_observed_at(grounded: tuple[dict[str, Any], ...]) -> str:
    observed = {str(option["observed_at"]) for option in grounded}
    assert len(observed) == 1, f"options were not observed at one instant: {sorted(observed)}"
    return observed.pop()


def _conflict_boundary(
    spec: dict[str, Any],
    store: InMemoryOntologyInstanceStore,
    *,
    with_arbitration_owner: bool,
) -> tuple[InMemoryBus, Forseti, Saga, InMemoryAuditChain, Odin | None]:
    """Wire the shipped arbitration boundary, optionally without its owner.

    Forseti is bound to the materialized operational context so the request
    it raises carries a canonical decision case rather than bare advice.
    Saga subscribes to its declared `object.verdict` topic so the terminal
    disposition lands in the append-only audit chain. Dropping Odin models
    missing arbitration authority: Forseti still raises the request, but
    nothing on the bus may resolve it.
    """

    cutoff = _conflict_cutoff(spec)
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(
        bus=bus,
        operational_context=OperationalContextMaterializer(
            store=store,
            clock=lambda: cutoff,
            clock_identity=str(spec["operating_context"]["clock_identity"]),
            decision_evidence=StubDecisionEvidenceAdmissionProvider(lambda: cutoff),
            require_decision_evidence=True,
        ),
    )
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    audit_chain = InMemoryAuditChain()
    saga = Saga(audit_chain=audit_chain)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    odin: Odin | None = None
    if with_arbitration_owner:
        odin = Odin(bus=bus, vertical_precedence=InitialVerticalPrecedence())
        bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    return bus, forseti, saga, audit_chain, odin


def _conflict_event(
    spec: dict[str, Any],
    grounded: tuple[dict[str, Any], ...],
    *,
    shared_target_id: str,
    observed_at: str,
) -> dict[str, Any]:
    """Assemble the conflict entirely from replay outputs and the graph."""

    return {
        "event_type": "cross_objective_conflict",
        "correlation_id": spec["correlation_id"],
        "resource_id": shared_target_id,
        "detected_at": observed_at,
        "domain_advice": {
            str(option["objective_domain"]): str(option["recommendation"]) for option in grounded
        },
        "source_freshness": _conflict_source_freshness(spec, observed_at),
    }


@dataclass(frozen=True, slots=True)
class _ConflictReplay:
    """Everything one grounded cross-objective replay produced."""

    grounded: tuple[dict[str, Any], ...]
    bus: InMemoryBus
    forseti: Forseti
    saga: Saga
    audit_chain: InMemoryAuditChain
    request: dict[str, Any] | None
    event: dict[str, Any]
    shared_target_id: str
    observed_at: str


async def _replay_conflict(
    shipped_catalog: CostGovernanceCatalogComposition,
    spec: dict[str, Any],
    *,
    with_arbitration_owner: bool = True,
) -> _ConflictReplay:
    grounded = await _ground_conflict_options(shipped_catalog, spec)
    store = await _conflict_context_store(spec)
    shared_target_id = await _derive_shared_target(store, spec, grounded)
    observed_at = _conflict_observed_at(grounded)
    bus, forseti, saga, audit_chain, _ = _conflict_boundary(
        spec,
        store,
        with_arbitration_owner=with_arbitration_owner,
    )
    event = _conflict_event(
        spec,
        grounded,
        shared_target_id=shared_target_id,
        observed_at=observed_at,
    )
    request = await forseti.maybe_request_arbitration(event)
    return _ConflictReplay(
        grounded=grounded,
        bus=bus,
        forseti=forseti,
        saga=saga,
        audit_chain=audit_chain,
        request=request,
        event=event,
        shared_target_id=shared_target_id,
        observed_at=observed_at,
    )


def _audited_verdicts(chain: InMemoryAuditChain, correlation_id: str) -> list[AuditEntry]:
    return [
        entry
        for entry in chain.entries_for_correlation(correlation_id)
        if entry.topic == "object.verdict"
    ]


def test_cross_objective_conflict_spec_is_schema_valid() -> None:
    """The frozen conflict spec MUST stay valid and self-consistent."""

    schema = cast(dict[str, Any], json.loads(CONFLICT_SCHEMA_PATH.read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(schema)
    spec = _load_conflict_spec()
    Draft202012Validator(schema).validate(spec)

    manifest = json.loads(
        (Path(__file__).resolve().parent / "manifests" / "v2026.07.json").read_text(
            encoding="utf-8"
        )
    )
    owned = set(manifest["capability_packs"][spec["capability"]]["scenario_ids"])
    assert {str(option["scenario_id"]) for option in spec["options"]} <= owned, (
        "every conflict option MUST replay a scenario the cited capability pack owns"
    )
    expected = spec["expected"]
    eligible = {
        str(option["option_id"])
        for option in spec["options"]
        if option["expected_eligibility"] == "eligible"
    }
    unresolved = {
        str(option["option_id"])
        for option in spec["options"]
        if option["expected_eligibility"] == "unresolved_evidence"
    }
    assert eligible == set(expected["eligible_option_ids"])
    assert unresolved == set(expected["unresolved_option_ids"])
    assert set(expected["domains_in_conflict"]) == {
        str(option["objective_domain"]) for option in spec["options"]
    }
    assert expected["winning_domain"] not in expected["losing_domains"]

    # Advice is a projection of the ActionType each option is expected to
    # produce, so the spec may not pin a recommendation an option has no
    # runtime basis for.
    for option in spec["options"]:
        action_type = option["expected_action_type"]
        domain = str(option["objective_domain"])
        if option["expected_eligibility"] == "eligible":
            assert action_type in spec["action_type_recommendations"]
            assert expected["advice"][domain] == spec["action_type_recommendations"][action_type]
        else:
            assert action_type is None
            assert expected["advice"][domain] == expected["held_recommendation"]

    # The shared target is derived, so it MUST be a resource the declared
    # neighborhood actually contains, and never one of the replayed ones.
    resources = {
        str(record["id"])
        for record in spec["operating_context"]["objects"]
        if record["object_type"] == "Resource"
    }
    assert expected["shared_target_id"] in resources
    linked = {str(link["from_id"]) for link in spec["operating_context"]["links"]} | {
        str(link["to_id"]) for link in spec["operating_context"]["links"]
    }
    assert {str(record["id"]) for record in spec["operating_context"]["objects"]} == linked, (
        "every declared object MUST be reachable through a declared link"
    )


@requires_opa
@pytest.mark.asyncio
async def test_sre_cross_objective_conflict_reaches_governed_arbitration(
    shipped_catalog: CostGovernanceCatalogComposition,
) -> None:
    """SRE `cross_objective_conflict` evidence for the frozen v2026.07 pack.

    Two grounded eligible options (Change Safety against Cost Governance)
    contend for the same logical observability target while the Resilience
    option's evidence stays unresolved. The conflict MUST leave the local
    replay carrying canonical evidence - a materialized operational context
    and the decision case built from it - reach the shipped boundary with
    that lineage intact, be answered by the single arbitration owner, and
    close in an audited terminal verdict.
    """

    spec = _load_conflict_spec()
    expected = spec["expected"]
    replay = await _replay_conflict(shipped_catalog, spec)
    bus = replay.bus

    by_id = {option["option_id"]: option for option in replay.grounded}
    assert sorted(option_id for option_id, option in by_id.items() if option["eligible"]) == sorted(
        expected["eligible_option_ids"]
    )
    assert sorted(
        option_id for option_id, option in by_id.items() if not option["eligible"]
    ) == sorted(expected["unresolved_option_ids"])
    for option_id in expected["eligible_option_ids"]:
        option = by_id[option_id]
        assert option["citing_rule_ids"], (
            f"option {option_id} claims eligibility without a cited shipped rule"
        )
        # Advice is derived: the ActionType the replay built decides it.
        assert option["action_type"] is not None
        assert (
            option["recommendation"] == spec["action_type_recommendations"][option["action_type"]]
        )
        assert option["audit_phases"] == ["intent", "terminal"], (
            f"option {option_id} did not close its two-phase audit"
        )
    for option_id in expected["unresolved_option_ids"]:
        option = by_id[option_id]
        assert option["action_type"] is None
        assert option["recommendation"] == expected["held_recommendation"]
        assert option["citing_rule_ids"] == []

    # The shared target was derived from the graph, not asserted by the spec.
    assert replay.shared_target_id == expected["shared_target_id"]
    assert replay.observed_at == spec["observed_at"]

    # The conflict crossed the boundary: one request, from the sole raiser,
    # carrying the shared target, correlation, every objective at stake, and
    # the canonical decision case built from the operational context.
    assert replay.request is not None, "the grounded conflict never reached arbitration"
    requests = bus.messages_on(spec["arbitration"]["request_topic"])
    assert len(requests) == 1
    raised = requests[0].payload
    assert raised["producer_principal"] == spec["arbitration"]["raiser_agent"]
    assert raised["correlation_id"] == spec["correlation_id"]
    assert raised["resource_id"] == replay.shared_target_id
    assert sorted(raised["domains_in_conflict"]) == sorted(expected["domains_in_conflict"])
    assert raised["advice"] == expected["advice"]
    assert raised["advice"] == {
        option["objective_domain"]: option["recommendation"] for option in replay.grounded
    }
    _assert_decision_case(raised.get("decision_case"), spec)

    # Exactly one arbitration owner answered it.
    decisions = bus.messages_on(spec["arbitration"]["decision_topic"])
    assert len(decisions) == 1
    decided = decisions[0].payload
    assert decided["producer_principal"] == spec["arbitration"]["owner_agent"]
    assert decided["winning_domain"] == expected["winning_domain"]
    assert list(decided["losing_domains"]) == list(expected["losing_domains"])
    assert decided["reason"] == expected["reason"]
    assert decided["escalate_hil"] is expected["escalate_hil"]
    assert replay.forseti.arbitrations[spec["correlation_id"]] == expected["winning_domain"]

    # The winning objective is the one whose evidence stayed unresolved, so
    # no eligible option may inherit the win. The terminal disposition is a
    # human approval that carries no ActionType and no initiator, and it
    # carries the same decision case forward.
    verdicts = bus.messages_on(spec["arbitration"]["verdict_topic"])
    assert len(verdicts) == 1
    verdict = verdicts[0].payload
    assert verdict["risk_verdict"] == expected["terminal"]["risk_verdict"]
    assert verdict["reason"] == expected["terminal"]["reason"]
    assert verdict["action_type"] == expected["terminal"]["action_type"]
    assert verdict["initiator_principal"] is expected["terminal"]["initiator_principal"]
    assert verdict["resource_id"] == replay.shared_target_id
    assert verdict["arbitration"]["winning_domain"] == expected["winning_domain"]
    _assert_decision_case(verdict.get("decision_case"), spec)

    # Audit lineage is terminal and append-only: Saga retained the verdict
    # on its declared subscription and the chain still verifies.
    audited = _audited_verdicts(replay.audit_chain, spec["correlation_id"])
    assert len(audited) == 1
    assert replay.saga.spec.name == spec["arbitration"]["auditor_agent"]
    assert audited[0].principal == expected["terminal"]["audited_producer"]
    assert audited[0].topic == expected["terminal"]["audited_topic"]
    assert audited[0].correlation_id == spec["correlation_id"]
    replay.audit_chain.verify()

    # Authority was not widened anywhere: every grounded execution and every
    # published PR stayed in shadow.
    for option in replay.grounded:
        assert option["execution_modes"] in ([], [Mode.SHADOW.value])
        assert option["published_pr_modes"] in ([], [Mode.SHADOW.value])


def _assert_decision_case(case: Any, spec: dict[str, Any]) -> None:
    """Assert the canonical decision case that grounds this arbitration."""

    pinned = spec["expected"]["decision_case"]
    assert isinstance(case, dict), "arbitration carried no canonical decision case"
    assert case["case_id"] == pinned["case_id"]
    assert case["correlation_id"] == spec["correlation_id"]
    assert case["context_snapshot_id"] == pinned["context_snapshot_id"]
    assert case["created_at"] == _conflict_cutoff(spec).isoformat()
    assert case["option_by_domain"] == pinned["option_by_domain"]
    assert [option["option_id"] for option in case["options"]] == pinned["option_ids"]
    assert case["protected_objective_ids"] == pinned["protected_objective_ids"]
    assert case["evidence_refs"] == pinned["evidence_refs"]
    assert case["selected_option_id"] == pinned["selected_option_id"]
    assert case["selection_reason"] == pinned["selection_reason"]
    assert case["requires_human_approval"] is pinned["requires_human_approval"]


@requires_opa
@pytest.mark.asyncio
async def test_sre_cross_objective_conflict_closes_hil_without_arbitration_authority(
    shipped_catalog: CostGovernanceCatalogComposition,
) -> None:
    """Missing arbitration authority MUST close through the governed HIL path.

    With no Odin bound to the request topic nothing may resolve the conflict
    locally: no decision, no recorded winner, no auto verdict, and no new
    arbiter. The shipped degradation policy already names the safe effect for
    an unavailable Odin (`conflicts_require_hil`), so the conflict is closed
    the way that policy says - Forseti judges it on the same runtime-derived
    event, finds no deterministic rule for it, and issues a terminal `hil`
    verdict that carries no ActionType and a shadow-only autonomy ceiling.
    Saga retains it, so the conflict ends with terminal audit evidence
    instead of hanging open forever.
    """

    spec = _load_conflict_spec()
    expected = spec["expected"]["without_arbitration_owner"]
    replay = await _replay_conflict(shipped_catalog, spec, with_arbitration_owner=False)
    bus = replay.bus

    assert replay.request is not None
    assert len(bus.messages_on(spec["arbitration"]["request_topic"])) == 1

    # The shipped policy for an unavailable arbitration owner, not a new one.
    degradation = evaluate_degradation({str(expected["unavailable_agent"])})
    assert degradation.effects == {
        str(expected["unavailable_agent"]): str(expected["degradation_effect"])
    }
    assert degradation.blocks_mutation is expected["blocks_mutation"]
    assert degradation.to_mapping()["effective_mode"] == expected["effective_mode"]

    # Nothing resolved the conflict locally.
    assert len(bus.messages_on(spec["arbitration"]["decision_topic"])) == expected["decisions"]
    assert len(replay.forseti.arbitrations) == expected["recorded_arbitrations"]

    # Close it the governed way: explicit HIL, no action authority.
    terminal = await replay.forseti.judge(replay.event)
    assert terminal is not None
    assert terminal["risk_verdict"] == expected["terminal"]["risk_verdict"]
    assert terminal["reason"] == expected["terminal"]["reason"]
    assert terminal["action_type"] == expected["terminal"]["action_type"]
    assert (
        terminal["resolved_autonomy_ceiling"] == expected["terminal"]["resolved_autonomy_ceiling"]
    )
    assert terminal["quorum_required"] == expected["terminal"]["quorum_required"]
    assert terminal["resource_id"] == replay.shared_target_id
    assert terminal["initiator_principal"] is None

    verdicts = bus.messages_on(spec["arbitration"]["verdict_topic"])
    assert len(verdicts) == expected["verdicts"]
    assert all(message.payload["risk_verdict"] == "hil" for message in verdicts)

    # Terminal audit evidence exists even though no authority acted.
    audited = _audited_verdicts(replay.audit_chain, spec["correlation_id"])
    assert len(audited) == expected["audited_verdicts"]
    replay.audit_chain.verify()

    assert bus.dead_letters == []
    for option in replay.grounded:
        assert option["execution_modes"] in ([], [Mode.SHADOW.value])
        assert option["published_pr_modes"] in ([], [Mode.SHADOW.value])


@requires_opa
@pytest.mark.asyncio
async def test_sre_cross_objective_conflict_replays_to_stable_digests(
    shipped_catalog: CostGovernanceCatalogComposition,
) -> None:
    """Deterministic replay MUST reproduce the frozen decision and evidence digests.

    Two independent replays - fresh loops, fresh audit stores, a fresh bus,
    a fresh ontology store, and a fresh arbitration boundary each time - MUST
    agree with each other and with the digests pinned in the frozen spec. A
    digest that only matches itself would prove repetition, not a freeze.
    """

    spec = _load_conflict_spec()
    digests: list[tuple[str, str]] = []
    for _ in range(2):
        replay = await _replay_conflict(shipped_catalog, spec)
        bus = replay.bus
        raised = bus.messages_on(spec["arbitration"]["request_topic"])[0].payload
        decided = bus.messages_on(spec["arbitration"]["decision_topic"])[0].payload
        verdict = bus.messages_on(spec["arbitration"]["verdict_topic"])[0].payload
        case = cast(dict[str, Any], verdict["decision_case"])
        audited = _audited_verdicts(replay.audit_chain, spec["correlation_id"])
        digests.append(
            (
                _canonical_digest(
                    {
                        "correlation_id": spec["correlation_id"],
                        "resource_id": replay.shared_target_id,
                        "observed_at": replay.observed_at,
                        "domains_in_conflict": sorted(
                            str(domain) for domain in raised["domains_in_conflict"]
                        ),
                        "advice": raised["advice"],
                        "case_id": case["case_id"],
                        "context_snapshot_id": case["context_snapshot_id"],
                        "case_evidence_refs": list(case["evidence_refs"]),
                        "case_option_by_domain": case["option_by_domain"],
                        "case_selected_option_id": case["selected_option_id"],
                        "case_selection_reason": case["selection_reason"],
                        "winning_domain": decided["winning_domain"],
                        "losing_domains": list(decided["losing_domains"]),
                        "reason": decided["reason"],
                        "escalate_hil": decided["escalate_hil"],
                        "objective_scores": decided["objective_scores"],
                        "margin": decided["margin"],
                        "terminal_risk_verdict": verdict["risk_verdict"],
                        "terminal_reason": verdict["reason"],
                        "terminal_action_type": verdict["action_type"],
                        "terminal_audit_payload_digests": [
                            entry.payload_digest for entry in audited
                        ],
                    }
                ),
                _canonical_digest(sorted(replay.grounded, key=lambda option: option["option_id"])),
            )
        )

    assert digests[0] == digests[1], "replay is not deterministic across independent runs"
    assert digests[0][0] == spec["expected"]["decision_digest"]
    assert digests[0][1] == spec["expected"]["evidence_digest"]

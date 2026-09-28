"""Learned patterns and predictions stay advisory evidence (#1541).

These negative proofs run the fixed pantheon topology and the real learning,
prediction, catalog-review, Rule activation, promotion, and T1 code. Only external
I/O is replaced: in-memory stores and bus transport, a constant embedding model,
and fakes for the metric source, catalog validator, review publisher, and the
privileged executor, which records any call it receives.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.agents import (
    PANTHEON_SPECS,
    Agent,
    InMemoryAuditChain,
    InMemoryBus,
    instantiate_pantheon,
    load_pantheon,
)
from fdai.agents._framework.registry import PantheonRegistryError
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.core.case_history import CaseHistoryMaterializer, OperationalOutcomeClass
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode_testing import InMemoryForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator, ForecastTargetSpec
from fdai.core.detection.forecast_observation import MetricForecastObservationProvider
from fdai.core.detection.metric_source import MetricSeriesSource
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.runners import PatternGrowthIntakeRunner
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    ReviewedReplayAuthority,
    ReviewedReplayPromotionEvidence,
    ReviewedReplayReceiptVerifier,
)
from fdai.core.rule_activation import RuleActivationCoordinator, StateStoreRuleActivationLedger
from fdai.core.tiers.t1_lightweight import LearnedAction, T1Outcome, T1Tier
from fdai.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.runtime.rule_activation import reconcile_rule_activation
from fdai.shared.contracts.models import Event, Mode, OntologyActionType, Rule
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation import RuleActivationStatus

from tests.agents.test_forecast_learning_chain import T0
from tests.agents.test_forecast_learning_chain import _outcome as _forecast_outcome
from tests.agents.test_governed_learning_loop import (
    _action_type,
    _outcome,
    _promotion_metrics,
    _promotion_receipt,
    _publish_case,
    _Publisher,
    _scenario,
    _timestamp,
    _Validator,
)
from tests.core.rule_activation.test_coordinator import NOW, _operator_record, _rule
from tests.core.test_control_loop_stage_events import _make_loop
from tests.measurement.test_runners import _outcome as _growth_outcome
from tests.measurement.test_runners import _ScriptedBuilder, _ScriptedOutcomeSource

_REMEDIATION_ROOT = Path(__file__).resolve().parents[4] / "rule-catalog" / "remediation"

_LEARNING_AND_PREDICTION_PRODUCERS = ("Norns", "Muninn", "Heimdall", "Freyr")
_DECISION_AND_EXECUTION_TOPICS = (
    "object.verdict",
    "object.approval",
    "object.action-run",
    "object.rollback",
    "object.arbitration-decision",
)
_CATALOG_TOPICS = ("object.rule", "object.policy")
_LEARNING_AND_PREDICTION_OUTPUTS = (
    "object.pattern",
    "object.rule-candidate",
    "object.forecast",
    "object.forecast-outcome",
    "object.capacity-forecast",
    "object.state-snapshot",
    "object.context-index",
    "object.rule",
    "object.policy",
)
_ACTION_OR_AUTHORITY_FIELDS = frozenset(
    {
        "action_type",
        "action_id",
        "params",
        "workflow_action",
        "operator_initiated",
        "initiator_principal",
        "event_type",
        "domain_advice",
        "domain_evidence",
        "human_approval_required",
        "execution_authority",
        "promotion_authority",
    }
)


class _RecordingExecutor:
    """Privileged executor fake: any call is a boundary violation."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, run: dict[str, Any]) -> bool:
        self.calls.append(dict(run))
        return True


class _ConstantEmbedding:
    """Embed every text to one vector so only the learned-action floor decides."""

    dim = 2

    async def embed(self, text: str) -> Sequence[float]:
        del text
        return (1.0, 0.0)


class _QueuedBus(InMemoryBus):
    """Deliver nested publications only after the current delivery returns.

    The production bridge hands each delivery to an independent consumer, so one
    handler never re-enters another subscriber inside its own call stack. The
    synchronous in-memory bus would nest Mimir -> Saga -> Norns inside the Norns
    candidate flush and wait forever on Norns' non-reentrant learning lock. The
    single-writer check still runs at publish time.
    """

    def __init__(self) -> None:
        super().__init__(registry=load_pantheon(), isolate_handlers=False)
        self._queued: deque[tuple[str, str, dict[str, Any]]] = deque()
        self._draining = False

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        self.registry.assert_can_publish(principal, topic)
        self._queued.append((principal, topic, payload))
        if self._draining:
            return
        self._draining = True
        try:
            while self._queued:
                await super().publish(*self._queued.popleft())
        finally:
            self._draining = False


def _wire_pantheon(bus: InMemoryBus, *overrides: Agent) -> dict[str, Agent]:
    """Subscribe all 15 agents exactly as PANTHEON_SPECS declares."""

    agents = instantiate_pantheon()
    agents.update({agent.spec.name: agent for agent in overrides})
    for agent in agents.values():
        agent.bind_bus(bus)
        for topic in agent.spec.subscribes:
            bus.subscribe(topic, agent.spec.name, agent.on_typed_message)
    return agents


def _assert_no_decision_or_execution(bus: InMemoryBus, thor: Thor) -> None:
    for topic in ("object.action-run", "object.approval", "object.rollback"):
        assert bus.messages_on(topic) == []
    assert thor.action_runs == {}
    assert all(
        not message.payload.get("action_type") for message in bus.messages_on("object.verdict")
    )


@pytest.mark.parametrize("topic", _DECISION_AND_EXECUTION_TOPICS + _CATALOG_TOPICS)
@pytest.mark.parametrize("principal", _LEARNING_AND_PREDICTION_PRODUCERS)
def test_learning_and_prediction_producers_cannot_publish_authority(
    principal: str,
    topic: str,
) -> None:
    with pytest.raises(PantheonRegistryError, match="is not the owner"):
        load_pantheon().assert_can_publish(principal, topic)


@pytest.mark.parametrize("topic", _DECISION_AND_EXECUTION_TOPICS)
def test_catalog_review_owner_cannot_publish_decision_or_execution(topic: str) -> None:
    with pytest.raises(PantheonRegistryError, match="is not the owner"):
        load_pantheon().assert_can_publish("Mimir", topic)


def test_learning_and_prediction_outputs_reach_no_executor_or_approver() -> None:
    consumers = {
        topic: {spec.name for spec in PANTHEON_SPECS if topic in spec.subscribes}
        for topic in _LEARNING_AND_PREDICTION_OUTPUTS
    }

    for authority_owner in ("Thor", "Var", "Vidar", "Odin"):
        assert all(authority_owner not in names for names in consumers.values())
    assert consumers["object.pattern"] == {"Muninn"}
    assert consumers["object.rule-candidate"] == {"Mimir"}
    assert consumers["object.forecast"] == {"Forseti"}
    assert consumers["object.forecast-outcome"] == {"Muninn", "Saga"}
    assert consumers["object.state-snapshot"] == {"Saga"}
    assert consumers["object.rule"] == {"Forseti", "Saga"}


async def test_heimdall_forecast_reaches_thor_only_as_a_non_action_verdict() -> None:
    bus = _QueuedBus()
    store = InMemoryForecastEpisodeStore()
    points = tuple(
        MetricPoint(
            metric_name="capacity_percent",
            at=T0 + timedelta(seconds=index),
            value=float(index),
            labels={"resource_id": "resource-1"},
        )
        for index in range(10)
    ) + tuple(
        MetricPoint(
            metric_name="capacity_percent",
            at=T0 + timedelta(seconds=offset),
            value=109.0,
            labels={"resource_id": "resource-1"},
        )
        for offset in (100, 109)
    )
    metric_provider = StaticMetricProvider(points)
    clock = [T0 + timedelta(seconds=10)]
    heimdall = Heimdall(
        forecast_clock=lambda: clock[0],
        forecast_evaluator=ForecastEpisodeEvaluator(
            source=MetricSeriesSource(metric_provider),
            store=store,
            targets=(
                ForecastTargetSpec(
                    detector_id="capacity-linear",
                    detector_version="1.0.0",
                    scorer_version="1.0.0",
                    access_scope_digest="a" * 64,
                    resource_ref="resource-1",
                    metric="capacity_percent",
                    threshold=20.0,
                    horizon_seconds=100,
                    lookback_seconds=300,
                    telemetry_grace_seconds=20,
                ),
            ),
        ),
        forecast_closer=ForecastClosureCoordinator(
            store=store,
            observations=MetricForecastObservationProvider(metric_provider),
        ),
        forecast_store=store,
    )
    executor = _RecordingExecutor()
    thor = Thor(executor=executor, clock=lambda: clock[0])
    saga = Saga(audit_chain=InMemoryAuditChain())
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        case_history_clock=lambda: clock[0],
    )
    _wire_pantheon(bus, heimdall, thor, saga, muninn)

    for tick, now in enumerate((T0 + timedelta(seconds=10), T0 + timedelta(seconds=130)), 1):
        clock[0] = now
        await heimdall.on_typed_message(
            "object.event",
            {
                "event_id": f"forecast-evaluation:{tick}",
                "idempotency_key": f"forecast-evaluation:{tick}",
                "correlation_id": f"forecast-evaluation:{tick}",
                "source": "forecast-evaluation-scheduler",
                "event_type": "forecast.evaluation_due",
            },
        )

    forecasts = [message.payload for message in bus.messages_on("object.forecast")]
    assert forecasts
    for forecast in forecasts:
        assert _ACTION_OR_AUTHORITY_FIELDS.isdisjoint(forecast)
        assert forecast["mode"] == "shadow"
        (verdict,) = (
            message.payload
            for message in bus.messages_on("object.verdict")
            if message.payload["correlation_id"] == forecast["correlation_id"]
        )
        assert verdict["action_type"] == ""
        assert verdict["risk_verdict"] == "hil"
        assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
        # The default observation-first profile records why no rule match was attempted.
        assert verdict["reason"] == "governed_execution_unselected"
        assert verdict["advisory_source"] == "forecast"
    assert thor.behavior_snapshot()["non_action_verdict_ignored"] == len(
        bus.messages_on("object.verdict")
    )
    (outcome,) = (message.payload for message in bus.messages_on("object.forecast-outcome"))
    assert outcome["label"] == "true_positive"
    assert outcome["mode"] == "shadow"
    _assert_no_decision_or_execution(bus, thor)
    assert executor.calls == []
    audited_topics = {
        entry.topic for entry in saga.replay_for_correlation(str(outcome["correlation_id"]))
    }
    assert {"object.verdict", "object.forecast-outcome"} <= audited_topics


async def test_forecast_derived_rule_candidate_stays_an_inert_pending_candidate() -> None:
    bus = _QueuedBus()
    closed_at = _forecast_outcome(1).closed_at
    heimdall = Heimdall()
    mimir = Mimir(clock=lambda: closed_at)
    thor = Thor(executor=_RecordingExecutor(), clock=lambda: closed_at)
    _wire_pantheon(
        bus,
        heimdall,
        Muninn(
            case_history=CaseHistoryMaterializer(
                metadata=InMemoryCaseHistoryMetadataStore(),
                artifacts=InMemoryCaseHistoryArtifactStore(),
            ),
            case_history_clock=lambda: closed_at,
        ),
        Norns(forecast_error_threshold=1, clock=lambda: closed_at),
        mimir,
        Saga(audit_chain=InMemoryAuditChain()),
        thor,
    )

    assert await heimdall.publish_forecast_outcome(_forecast_outcome(1))

    (candidate,) = mimir.pending_candidates()
    assert candidate["source_signal"] == "forecast_case_history"
    assert candidate["proposal_kind"] == "threshold_adjustment"
    assert candidate["suggested_change"] == "review_forecast_detector"
    assert _ACTION_OR_AUTHORITY_FIELDS.isdisjoint(candidate)
    assert mimir.promotion_ready_candidates() == ()
    with pytest.raises(ValueError, match="shadow dwell evidence is insufficient"):
        mimir.promote(str(candidate["target_rule_id"]), source="handoff")
    assert mimir.status(str(candidate["target_rule_id"])) is None
    assert mimir.catalog_review_packages() == ()
    assert bus.messages_on("object.rule") == []
    _assert_no_decision_or_execution(bus, thor)


async def _run_operating_pattern_chain() -> tuple[
    InMemoryBus, Thor, Mimir, _Publisher, dict[str, Any]
]:
    scenario = _scenario()
    bus = _QueuedBus()
    publisher = _Publisher()
    # Every learning clock is pinned: case currency, deletion due dates, and cohort
    # age are judged against the scenario review instant, never the wall clock.
    reviewed_at = _timestamp(scenario["reviewed_at"])
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        durable_state_store=InMemoryStateStore(),
        case_history_clock=lambda: reviewed_at,
    )
    mimir = Mimir(
        catalog_candidate_compiler=CatalogCandidateCompiler(
            validator=_Validator(scenario["scenario_set_version"]),
            catalog_version="catalog-v2026.08",
            schema_version="2.0.0",
            expected_fdai_revision=scenario["fdai_revision"],
            expected_scenario_set_version=scenario["scenario_set_version"],
            clock=lambda: reviewed_at,
        ),
        catalog_review_publisher=publisher,
        clock=lambda: reviewed_at,
    )
    mimir.bind_case_history(muninn._case_history)
    thor = Thor(executor=_RecordingExecutor(), clock=lambda: reviewed_at)
    _wire_pantheon(
        bus,
        muninn,
        Norns(clock=lambda: reviewed_at),
        mimir,
        Saga(audit_chain=InMemoryAuditChain()),
        thor,
    )
    await _publish_case(
        bus, _outcome("a", OperationalOutcomeClass.SUCCESS, scenario).to_case_input()
    )
    await _publish_case(
        bus, _outcome("b", OperationalOutcomeClass.ROLLBACK, scenario).to_case_input()
    )
    return bus, thor, mimir, publisher, scenario


async def test_operating_pattern_chain_leaves_only_inert_shadow_review_evidence() -> None:
    bus, thor, mimir, publisher, scenario = await _run_operating_pattern_chain()

    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert len(bus.messages_on("object.pattern")) == 1
    retained = [
        message.payload
        for message in bus.messages_on("object.state-snapshot")
        if message.payload.get("kind") == "operating_pattern_retained"
    ]
    assert len(retained) == 1
    assert retained[0]["execution_authority"] is False
    assert retained[0]["promotion_authority"] is False
    (package,) = publisher.packages
    assert package.review_required is True
    # remediate.tag-add is already a registered ActionType, so this scenario compiles no
    # draft ActionType. Draft ActionType shadow-first enforcement is proven separately by
    # tests/core/operational_learning/test_catalog_compilation.py.
    assert package.draft_action_type is None
    rule_messages = [message.payload for message in bus.messages_on("object.rule")]
    assert rule_messages
    assert {payload["kind"] for payload in rule_messages} == {"catalog_review_outcome"}
    assert {payload["mode"] for payload in rule_messages} == {"shadow"}
    assert [payload["outcome"] for payload in rule_messages] == ["published"]
    audited = [
        message.payload
        for message in bus.messages_on("object.audit-entry")
        if message.payload.get("action_kind") == "catalog_review.outcome"
    ]
    assert [(entry["outcome"], entry["mode"]) for entry in audited] == [("published", "shadow")]
    draft_rule_id = str(package.draft_rule.mapping["id"])
    with pytest.raises(ValueError, match="reviewed catalog PR"):
        mimir.promote(draft_rule_id, source="handoff")
    assert mimir.status(draft_rule_id) is None
    with pytest.raises(ValueError, match="reviewed catalog PR"):
        mimir.promote(scenario["action_type"], source="handoff")
    _assert_no_decision_or_execution(bus, thor)


async def _activate(
    coordinator: RuleActivationCoordinator,
    ledger: StateStoreRuleActivationLedger,
    rule_id: str,
    *,
    key: str,
) -> RuleActivationStatus:
    """Drive one authenticated request and a distinct approval to enable ``rule_id``."""

    current = await ledger.current_generation()
    assert current is not None
    request = _operator_record(
        operation="rule.activation-request",
        principal_id="requester",
        idempotency_key=f"enable-{key}",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": f"Enable the {key} Rule for T0 evaluation.",
            "changes": [{"rule_id": rule_id, "enabled": True}],
        },
        accepted_at=NOW + timedelta(minutes=1),
        roles=("Contributor",),
    )
    proposal = await coordinator.accept_request(
        request,
        source_ref=f"operator-proposal:workflow:enable-{key}",
        at=NOW + timedelta(minutes=1),
    )
    approval = _operator_record(
        operation="rule.activation-approve",
        principal_id="approver",
        idempotency_key=f"approve-{key}",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        accepted_at=NOW + timedelta(minutes=2),
        roles=("Approver",),
    )
    return await coordinator.approve(
        approval,
        source_ref=f"operator-proposal:workflow:approve-{key}",
        at=NOW + timedelta(minutes=2),
    )


async def test_learned_rule_never_reaches_the_t0_matching_surface() -> None:
    bus, _, _, publisher, _ = await _run_operating_pattern_chain()
    learned = publisher.packages[0].draft_rule.mapping
    learned_id = str(learned["id"])
    learned_type = str(learned["resource_type"])
    # A wildcard-triggered draft would be cited for every signal on its resource type
    # if it ever entered the active generation.
    assert learned["triggered_by"] == ["*"]
    reviewed = Rule.model_validate(
        {**_rule("rule.reviewed").model_dump(mode="json"), "resource_type": learned_type}
    )
    available = (_rule("rule.alpha"), reviewed)
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    await reconcile_rule_activation(
        ledger=ledger,
        available_rules=available,
        desired_rules=available[:1],
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="offline-kit:baseline",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )
    loop = _make_loop(stage_publisher=None, tmp_path=_REMEDIATION_ROOT)
    coordinator = RuleActivationCoordinator(
        store=store,
        ledger=ledger,
        runtime=loop,
        available_rules=available,
    )
    assert await coordinator.synchronize_runtime()

    def cited(resource_type: str) -> tuple[str, ...]:
        verdict = loop._t0_engine.evaluate(
            event_id="t0-probe",
            signal_id="t0-probe",
            resource_id="resource-1",
            resource_type=resource_type,
            resource_props={},
        )
        return verdict.audit_hint.citing_rule_ids

    assert cited("example.resource") == ("rule.alpha",)
    assert cited(learned_type) == ()
    with pytest.raises(ValueError, match="workflow proposal is invalid"):
        await coordinator.accept_request(
            dict(bus.messages_on("object.rule-candidate")[0].payload),
            source_ref=f"catalog-review:{publisher.packages[0].content_digest[:16]}",
            at=NOW,
        )
    with pytest.raises(ValueError, match="unavailable Rule artifact"):
        await _activate(coordinator, ledger, learned_id, key="learned")
    assert learned_id not in {rule.id for rule in loop.rules}
    assert cited(learned_type) == ()

    # Positive control: the same governed path activates a reviewed catalog Rule for
    # the learned resource type, so the T0 surface is live and the refusal is real.
    assert await _activate(coordinator, ledger, "rule.reviewed", key="reviewed") is (
        RuleActivationStatus.APPLIED
    )
    assert cited(learned_type) == ("rule.reviewed",)
    assert {rule.id for rule in loop.rules} == {"rule.alpha", "rule.reviewed"}


def _consider(
    verifier: ReviewedReplayReceiptVerifier | None,
    action_type: OntologyActionType,
    receipt: OperationalPromotionReceipt,
) -> Mode:
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        receipt_verifier=verifier,
    )
    record = registry.consider_promotion(
        action_type=action_type,
        metrics=_promotion_metrics(receipt),
        receipt=receipt,
    )
    assert registry.mode_of(action_type.name) is record.mode
    assert record.production_ready is (record.mode is Mode.ENFORCE)
    return record.mode


@pytest.mark.parametrize("review", ["absent", "unapproved"])
async def test_learned_action_type_stays_shadow_without_independent_review(review: str) -> None:
    _, _, _, publisher, scenario = await _run_operating_pattern_chain()
    package = publisher.packages[0]
    action_type = _action_type(scenario["action_type"])
    receipt = _promotion_receipt(action_type, scenario)
    pending = ReviewedReplayPromotionEvidence(
        action_type=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=receipt.action_type_digest,
        fdai_revision=scenario["fdai_revision"],
        scenario_set_version=scenario["scenario_set_version"],
        candidate_digest=package.candidate.digest,
        package_digest=package.content_digest,
        replay_first_digest=package.replay.first_result_digest,
        replay_second_digest=package.replay.second_result_digest,
        promotion_evidence_digest=receipt.evidence_digest,
        review_ref="governance-review:pending",
        reviewer_principal="independent-governance-reviewer",
        approved=False,
    )
    evidence = () if review == "absent" else (pending,)

    assert _consider(None, action_type, receipt) is Mode.SHADOW
    assert (
        _consider(
            ReviewedReplayReceiptVerifier(ReviewedReplayAuthority(evidence)),
            action_type,
            receipt,
        )
        is Mode.SHADOW
    )
    # Control: the same learned package, receipt, and metrics promote only once an
    # independent reviewer approves them, so the refusals above are not vacuous.
    approved = replace(pending, approved=True, review_ref="governance-review:approved")
    assert (
        _consider(
            ReviewedReplayReceiptVerifier(ReviewedReplayAuthority((approved,))),
            action_type,
            receipt,
        )
        is Mode.ENFORCE
    )


async def test_grown_t1_pattern_cannot_be_reused_before_a_measured_lift() -> None:
    library = InMemoryPatternLibrary()
    learned = LearnedAction(
        signature="grown-pattern",
        rule_id="rg.tagging.owner-required",
        action_type="remediate.tag-add",
        params={"tag": "owner"},
        incident_id="incident-grown-pattern",
        success_rate=1.0,
        reuse_count=500,
    )
    report = await PatternGrowthIntakeRunner(
        outcome_source=_ScriptedOutcomeSource((_growth_outcome(action_id="grown"),)),
        pattern_builder=_ScriptedBuilder(results={"grown": ((1.0, 0.0), learned)}),
        writer=library,
        audit_store=InMemoryStateStore(),
    ).run_once()
    assert report.ingested_signatures == ("grown-pattern",)
    event = Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000001541",
            "idempotency_key": "00000000-0000-0000-0000-000000001541",
            "source": "src",
            "event_type": "change_detected",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
            "payload": {},
        }
    )

    decision = await T1Tier(
        embedding_model=_ConstantEmbedding(),
        pattern_library=library,
    ).evaluate(event=event)

    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.best_match is not None
    assert decision.best_match.score == pytest.approx(1.0)
    assert decision.best_match.action.success_rate == 0.0
    assert decision.reason is not None and decision.reason.startswith("success_rate=0.0000<floor")
    assert decision.requires_reverification is True

"""Runtime wiring and delivery-edge regressions over the process-local event bus."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fdai.agents import PANTHEON_SPECS
from fdai.agents._framework import architecture_review_runtime, factory, runtime_subscriptions
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.njord import Njord
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictStatus
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostAnomalyAdvisory,
    CostPackageActivation,
    SignedCostEffectEstimate,
)
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.user_context import UserPreferenceRecord
from fdai_service_contracts.bus_poison_halt_clear import ORDERED_POISON_HALT_CLEAR_TOPIC

_RAW_TOPIC = "fdai.events.package-e"
_NOW = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


class _CostActivationReader:
    async def read_cost_activation(self, _package_id: str) -> CostPackageActivation:
        return CostPackageActivation(
            vertical_id="cost",
            package_id="cost-governance",
            available=True,
            enabled=True,
            availability_reasons=(),
            package_version="1.0.0",
            image_digest="sha256:" + "1" * 64,
            asset_manifest_digest="sha256:" + "2" * 64,
            semantic_profile_digest="sha256:" + "3" * 64,
            revision=7,
            effective_at=_NOW,
            ontology_release_id="ontology:2026-09-30",
            ontology_release_digest=_DIGEST,
            source_authority="cost-package:test",
        )


class _CostProvider:
    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> CostAnomalyAdvisory:
        return CostAnomalyAdvisory(
            scope_id=sample.scope_id,
            resource_id=sample.resource_id,
            amount_usd=sample.amount_usd,
            baseline_usd=Decimal("10.0"),
            ratio=Decimal("2.5"),
            impact=Decimal("0.9"),
            recommendation="scale_down",
            correlation_id=sample.correlation_id,
            observed_at=sample.observed_at,
        )

    async def hydrate_cost_samples(
        self,
        samples: tuple[CostAnalysisSample, ...],
    ) -> tuple[CostAnalysisSample, ...]:
        return samples

    def estimate_cost_effect(self, _action_type: str) -> SignedCostEffectEstimate | None:
        return None


async def _run_until(
    runtime: PantheonRuntime,
    predicate: Callable[[], bool],
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _runtime(**kwargs: Any) -> tuple[PantheonRuntime, LocalEventBus]:
    provider = LocalEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC, **kwargs)
    return runtime, provider


def _published_payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def _consumer_committed(
    runtime: PantheonRuntime,
    provider: LocalEventBus,
    topic: str,
    agent: str,
) -> bool:
    """Return whether ``agent`` finished handling and committed every record on ``topic``."""

    group_id = f"{runtime.bridge.consumer_group_prefix}.{agent}"
    end_offset = provider._base_offsets.get(topic, 0) + len(provider._records.get(topic, ()))
    return end_offset > 0 and provider._offsets.get((topic, group_id), 0) >= end_offset


def test_runtime_subscriptions_match_specs_plus_declared_framework_topics() -> None:
    runtime, _provider = _runtime()

    async def _recovery_observer(_topic: str, _payload: dict[str, Any]) -> None:
        return None

    runtime_subscriptions.bind_recovery_effect_observation(
        runtime.bridge,
        _recovery_observer,
    )

    expected = {(topic, spec.name) for spec in PANTHEON_SPECS for topic in spec.subscribes}
    expected.update(
        {
            (_RAW_TOPIC, "Huginn"),
            ("object.verdict", "runtime-observer"),
            ("object.action-run", "runtime-observer"),
            (
                runtime_subscriptions.RECOVERY_EFFECT_OBSERVATION_TOPIC,
                runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL,
            ),
            *(
                (topic, architecture_review_runtime.ARCHITECTURE_REVIEW_OBSERVER_PRINCIPAL)
                for topic in architecture_review_runtime.ARCHITECTURE_REVIEW_OBSERVER_TOPICS
            ),
        }
    )
    actual = {
        (topic, principal)
        for topic, subscribers in runtime.bridge._subs.items()
        for principal, _handler in subscribers
    }

    assert actual == expected


def test_runtime_subscriptions_include_declared_conditional_rule_generation_topics() -> None:
    class _Binder:
        async def handle(self, _command: Any) -> None:
            return None

    class _StateStore:
        pass

    runtime, _provider = _runtime(
        rule_generation_activation_binder=_Binder(),
        rule_generation_state_store=_StateStore(),
    )

    actual = {
        (topic, principal)
        for topic, subscribers in runtime.bridge._subs.items()
        for principal, _handler in subscribers
    }

    assert set(runtime_subscriptions.CONDITIONAL_RULE_GENERATION_COMMAND_SUBSCRIPTIONS) <= actual


def test_runtime_subscriptions_include_ordered_poison_clear_when_durable_halts_bound() -> None:
    runtime, _provider = _runtime(ordered_poison_halt_state_store=object())

    actual = {
        (topic, principal)
        for topic, subscribers in runtime.bridge._subs.items()
        for principal, _handler in subscribers
    }

    assert (
        ORDERED_POISON_HALT_CLEAR_TOPIC,
        runtime_subscriptions.POISON_HALT_CLEAR_PRINCIPAL,
    ) in actual


def test_raw_specialist_samples_travel_from_huginn_to_freyr_and_njord() -> None:
    runtime, provider = _runtime(
        cost_runtime=factory.CostRuntimeBindings(
            advisory_provider=_CostProvider(),
            activation_reader=_CostActivationReader(),
            package_enabled=True,
        )
    )

    async def _drive() -> None:
        await provider.publish(
            _RAW_TOPIC,
            "capacity-raw",
            {
                "id": "capacity-raw",
                "event_type": "specialist.capacity_sample",
                "correlation_id": "corr-capacity",
                "idempotency_key": "raw-capacity-key",
                "resource_id": "resource-capacity",
                "occurred_at": "2026-09-30T01:02:03+00:00",
                "attributes": {"utilization": 0.91},
            },
        )
        await provider.publish(
            _RAW_TOPIC,
            "cost-raw",
            {
                "id": "cost-raw",
                "event_type": "specialist.cost_sample",
                "correlation_id": "corr-cost",
                "idempotency_key": "raw-cost-key",
                "resource_id": "resource-cost",
                "occurred_at": "2026-09-30T02:03:04+00:00",
                "attributes": {
                    "scope": "scope-cost",
                    "amount_usd": 25.0,
                    "activation_revision": 7,
                    "source_authority": "cost-package:test",
                    "ontology_release_digest": _DIGEST,
                    "completeness": 1.0,
                },
            },
        )
        await _run_until(
            runtime,
            lambda: (
                bool(_published_payloads(provider, "object.capacity-forecast"))
                and bool(_published_payloads(provider, "object.cost-anomaly"))
            ),
        )

    asyncio.run(_drive())

    forecast = _published_payloads(provider, "object.capacity-forecast")[-1]
    anomaly = _published_payloads(provider, "object.cost-anomaly")[-1]
    assert forecast["resource_id"] == "resource-capacity"
    assert forecast["observed_at"] == "2026-09-30T01:02:03+00:00"
    assert forecast["correlation_id"] == "corr-capacity"
    assert anomaly["resource_id"] == "resource-cost"
    assert anomaly["observed_at"] == "2026-09-30T02:03:04+00:00"
    assert anomaly["correlation_id"] == "corr-cost"
    assert isinstance(runtime.agents["Freyr"], Freyr)
    assert runtime.agents["Freyr"].behavior_snapshot()["capacity_sample:accepted"] == 1
    assert isinstance(runtime.agents["Njord"], Njord)
    assert runtime.agents["Njord"].behavior_snapshot()["cost_sample:accepted"] == 1


def test_runtime_exercises_spec_delivery_edges_with_observable_effects() -> None:
    runtime, provider = _runtime()
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)
    thor.action_runs["corr-effect"] = ActionRun(
        correlation_id="corr-effect",
        action_type="ops.scale-out",
        resource_id="resource-effect",
        state=ActionRunState.EXECUTION_UNKNOWN,
        verdict="hil",
        action_id="action-effect",
        idempotency_key="action-effect-key",
        params={"replica_count": 2},
        resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY,
    )

    async def _drive() -> None:
        await runtime.bridge.publish(
            "Loki",
            "object.chaos-experiment",
            {
                "correlation_id": "corr-chaos",
                "idempotency_key": "chaos-key",
                "resource_id": "resource-chaos",
                "experiment_id": "experiment-1",
                "action_type": "tool.run-chaos-experiment",
                "targets": ["resource-chaos"],
                "causal_hypothesis_ref": "hypothesis-1",
                "refutation_query_ref": "query-1",
                "impact_envelope_id": "impact-1",
                "recovery_plan_id": "recovery-1",
                "dry_run_receipt": "dry-run-1",
            },
        )
        await runtime.bridge.publish(
            "Heimdall",
            "object.evidence-conflict",
            {
                "kind": "cross_source_state",
                "correlation_id": "corr-conflict",
                "idempotency_key": "conflict-key",
                "resource_id": "resource-conflict",
                "status": EvidenceConflictStatus.ACTIVE.value,
                "target_ref": "resource-conflict",
            },
        )
        issue = {
            "correlation_id": "corr-issue",
            "idempotency_key": "issue-key",
            "resource_id": "issue-resource",
            "fingerprint": "fp-runtime-edge",
            "issue_number": 123,
            "created": True,
            "open": True,
        }
        await runtime.bridge.publish("Saga", "object.issue", issue)
        await runtime.bridge.publish(
            "Heimdall",
            "object.recovery-effect-observation",
            {
                "schema_version": "1.0.0",
                "event_type": "action.execution.effect_verified.v1",
                "correlation_id": "corr-effect",
                "idempotency_key": "effect-key",
                "resource_id": "resource-effect",
                "action_id": "action-effect",
                "action_type": "ops.scale-out",
                "action_idempotency_key": "action-effect-key",
                "params": {"replica_count": 2},
                "effect_verification_ref": "sha256:" + "b" * 64,
                "execution_closure_ref": "sha256:" + "c" * 64,
                "observed_at": "2026-09-30T03:04:05+00:00",
            },
        )
        await runtime.bridge.publish(
            "Forseti",
            "object.security-event",
            {
                "correlation_id": "corr-security",
                "idempotency_key": "security-key",
                "resource_id": "resource-security",
                "severity": "high",
                "event_type": "security.privilege_escalation",
            },
        )
        await _run_until(
            runtime,
            lambda: (
                thor.action_runs["corr-effect"].state is ActionRunState.SUCCEEDED
                and bool(_published_payloads(provider, "object.anomaly"))
                and _consumer_committed(runtime, provider, "object.chaos-experiment", "Heimdall")
            ),
        )

    asyncio.run(_drive())

    heimdall = runtime.agents["Heimdall"]
    saga = runtime.agents["Saga"]
    mimir = runtime.agents["Mimir"]
    forseti = runtime.agents["Forseti"]
    assert isinstance(heimdall, Heimdall)
    assert isinstance(saga, Saga)
    assert isinstance(mimir, Mimir)
    assert isinstance(forseti, Forseti)
    assert heimdall.behavior_snapshot()["chaos_experiment:grounded"] == 1
    assert thor.behavior_snapshot()["execution:independent_effect_verified"] == 1
    assert mimir.behavior_snapshot()["issue_fingerprint:accepted"] == 1
    assert len(saga.replay_for_correlation("corr-conflict")) == 1
    assert len(saga.replay_for_correlation("corr-issue")) == 1
    assert len(saga.replay_for_correlation("corr-security")) == 1
    effect_runs = [
        payload
        for payload in _published_payloads(provider, "object.action-run")
        if payload.get("correlation_id") == "corr-effect"
    ]
    assert effect_runs[-1]["state"] == "succeeded"
    assert any(
        payload["event_type"] == "chaos_experiment_request"
        for payload in _published_payloads(provider, "object.anomaly")
    )


def test_bragi_user_preference_publication_reaches_muninn_through_runtime() -> None:
    runtime, provider = _runtime()
    bragi = runtime.agents["Bragi"]
    muninn = runtime.agents["Muninn"]
    assert isinstance(bragi, Bragi)
    assert isinstance(muninn, Muninn)
    preference = UserPreferenceRecord(
        principal_id="operator-edge",
        locale="ko",
        verbosity="detailed",
        timezone="Asia/Seoul",
        share_with_learner=True,
        revision=4,
        updated_at=_NOW,
    )

    async def _drive() -> None:
        assert await bragi.publish_user_preference(preference) is True
        await _run_until(
            runtime,
            lambda: _consumer_committed(runtime, provider, "object.user-preference", "Muninn"),
        )

    asyncio.run(_drive())

    (published,) = _published_payloads(provider, "object.user-preference")
    assert published["producer_principal"] == "Bragi"
    assert "operator-edge" not in str(published)
    projection = muninn.get_context(
        "user_preferences",
        published["id"],
        requester_user_id="operator-edge",
    )
    assert projection is not None
    assert projection["preference_digest"] == published["preference_digest"]
    assert "locale" not in projection
    assert (
        muninn.get_context("user_preferences", published["id"], requester_user_id="operator-other")
        is None
    )

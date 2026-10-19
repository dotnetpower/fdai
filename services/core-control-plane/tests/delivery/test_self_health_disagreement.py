"""Real SDK/Core comparisons supply round counts, not operational learning outcomes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import httpx
import pytest
from fdai.core.quality_gate._verification import cross_check_candidate
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.testing import MatchTypeCrossCheckModel, MismatchCrossCheckModel
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.self_health_disagreement import RuntimeMixedModelHealthSource
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError

CANDIDATE = QualityCandidate(
    action_type="remediate.tag-add",
    target_resource_ref="resource:example",
    params={"value": 1},
    cited_rule_ids=("example.rule",),
    confidence_signals={"example": 0.99},
)


@dataclass
class Clock:
    seconds: int = 0

    def now(self):
        return datetime(2026, 10, 19, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def ticks(self):
        return self.seconds * 1_000_000_000


def _source(clock):
    return RuntimeMixedModelHealthSource(
        metric="fdai.models.disagreement_rate",
        window_seconds=300,
        clock=clock.now,
        ticks=clock.ticks,
    )


def _models(client, *, roles=("t2.reasoner.primary", "t2.reasoner.secondary")):
    return tuple(
        AzureOpenAICrossCheckModel(
            identity=LocalWorkloadIdentity(),
            http_client=client,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://example.openai.azure.com",
                deployment=f"example-{index}",
                system_prompt="Synthetic comparison test.",
                model_id=f"example-model-{index}",
            ),
            observation_role=role,
        )
        for index, role in enumerate(roles)
    )


def _response(value=1):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"action_type": CANDIDATE.action_type, "params": {"value": value}}
                        )
                    }
                }
            ]
        },
    )


async def _unavailable(source, clock, reason):
    with pytest.raises(SelfHealthExporterUnavailableError) as caught:
        await source.observe(now=clock.now())
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    "kind",
    [
        "local-fake",
        "hil",
        "missing-role",
        "duplicate",
        "wrong-role",
        "claimed-source",
        "pool-claimed",
    ],
)
async def test_non_native_or_incomplete_group_never_binds_or_probes(kind, caplog):
    from fdai.delivery.azure.llm.latency_routed_cross_check import LatencyRoutedCrossCheckModel

    class ClaimedSource(MatchTypeCrossCheckModel):
        def __init__(self, original):
            super().__init__(model_id=f"claimed-{original.model_id}")
            self.original = original

        def model_provider_observations(self, **kwargs):
            return self.original.model_provider_observations(**kwargs)

    caplog.set_level("INFO", logger="fdai.delivery.self_health_disagreement")
    source = _source(Clock())
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("binding must not call provider"))
    ) as client:
        models = _models(client)
        if kind == "local-fake":
            models = (
                MatchTypeCrossCheckModel(model_id="a"),
                MatchTypeCrossCheckModel(model_id="b"),
            )
        elif kind == "hil":
            models = (models[0], MismatchCrossCheckModel(model_id="hil"))
        elif kind == "claimed-source":
            models = tuple(ClaimedSource(model) for model in models)
        elif kind == "pool-claimed":
            models = (
                LatencyRoutedCrossCheckModel(
                    candidates=[("native", models[0]), ("claimed", ClaimedSource(models[0]))]
                ),
                models[1],
            )
        else:
            roles = {
                "missing-role": ("t2.reasoner.primary", None),
                "duplicate": ("t2.reasoner.primary", "t2.reasoner.primary"),
                "wrong-role": ("t2.reasoner.primary", "t2.reasoner.other"),
            }[kind]
            models = _models(client, roles=roles)
        assert source.bind(models) is None
        await _unavailable(source, Clock(), "source_missing")
        assert "mixed_model_health" in caplog.text


async def test_exact_round_denominator_original_time_and_no_added_requests():
    clock = Clock()
    source = _source(clock)
    disagree = False
    calls = []

    def handler(request):
        calls.append(request)
        return _response(True if disagree and "/example-1/" in request.url.path else 1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = _models(client)
        observer = source.bind(models)
        await _unavailable(source, clock, "source_incomplete")
        for index in range(3):
            clock.seconds += 1
            disagree = index == 1
            result = await cross_check_candidate(CANDIDATE, models, observer=observer)
            assert result.agree_count == (1 if disagree else 2)
        clock.seconds = 300
        with localcontext() as context:
            context.prec = 1
            context.traps[Inexact] = True
            sample = await source.observe(now=clock.now())
        assert Decimal("0.33333333333333333333") < sample.value < Decimal("0.33333333333333333334")
        assert sample.observed_at == datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC)
        assert source.latest_window.completed == 3
        assert source.latest_window.rejected_or_abstained == 1
        assert "runtime:t2-cross-check:" in sample.source
        assert "example" not in repr(sample)
        clock.seconds = 301
        assert await source.observe(now=clock.now()) == sample
        assert len(calls) == 6


async def test_native_latency_pool_produces_one_comparison_round_not_member_counts():
    from fdai.delivery.azure.llm.latency_routed_cross_check import LatencyRoutedCrossCheckModel

    clock = Clock()
    source = _source(clock)
    calls = []

    def handler(request):
        calls.append(request)
        return _response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first, second = _models(client, roles=("t2.reasoner.primary", "t2.reasoner.primary"))
        secondary = _models(client)[1]
        pool = LatencyRoutedCrossCheckModel(
            candidates=[("first", first), ("second", second)], model_id="example-pool"
        )
        models = (pool, secondary)
        observer = source.bind(models)
        assert observer is not None
        for _ in range(2):
            result = await cross_check_candidate(CANDIDATE, models, observer=observer)
            assert result.agree_count == 2
        clock.seconds = 300
        assert (await source.observe(now=clock.now())).value == 0
        assert source.latest_window.completed == 2
        assert len(calls) == 4


@pytest.mark.parametrize("other", ["fake", "rebound-sdk", "partial-group"])
async def test_qualified_group_cannot_supply_health_for_another_model_tuple(other):
    clock = Clock()
    source = _source(clock)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: _response())) as client:
        observer = source.bind(_models(client))
        models = (
            (MatchTypeCrossCheckModel(model_id="a"), MatchTypeCrossCheckModel(model_id="b"))
            if other == "fake"
            else _models(client)[:1]
            if other == "partial-group"
            else _models(client)
        )
        result = await cross_check_candidate(CANDIDATE, models, observer=observer)
        assert result.agree_count == len(models)
        clock.seconds = 300
        await _unavailable(source, clock, "source_incomplete")


@pytest.mark.parametrize("failed,total,alert", [(0, 1, False), (1, 10, False), (1, 9, True)])
async def test_exact_ten_percent_boundary_uses_the_existing_actual_policy(failed, total, alert):
    from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
    from fdai.delivery.self_health_sources import runtime_self_health_registry
    from fdai.runtime.bootstrap_readiness import load_runtime_self_health_catalog
    from fdai.shared.providers.testing.state_store import InMemoryStateStore
    from fdai_service_contracts.self_health import SelfHealthSignalStatus

    clock = Clock()
    source = _source(clock)
    disagree = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: _response(True if disagree else 1))
    ) as client:
        models = _models(client)
        observer = source.bind(models)
        for index in range(total):
            disagree = index < failed
            await cross_check_candidate(CANDIDATE, models, observer=observer)
        clock.seconds = 300
        store = InMemoryStateStore()
        registry = runtime_self_health_registry(
            catalog=load_runtime_self_health_catalog(),
            store=store,
            readiness=lambda now: False,
            mixed_model_health_source=source,
        )
        snapshot = await SelfHealthRuntimeMonitor(
            registry=registry, store=store
        ).collect_and_persist(now=clock.now())
        row = next(row for row in snapshot.self_health.signals if row.signal is source.signal)
        assert row.status is (
            SelfHealthSignalStatus.ALERT if alert else SelfHealthSignalStatus.HEALTHY
        )
        assert source.latest_window.completed == total
        assert source.latest_window.rejected_or_abstained == failed
        assert row.fresh


@pytest.mark.parametrize("kind", ["http", "invalid-json", "drift"])
async def test_unknown_round_does_not_become_disagreement_or_reexpose_old_healthy_window(kind):
    clock = Clock()
    source = _source(clock)
    failure = False
    params = {"value": 1}
    candidate = replace(CANDIDATE, params=params)

    async def handler(request):
        if failure:
            if kind == "http":
                return httpx.Response(503)
            if kind == "invalid-json":
                return httpx.Response(200, content=b"not json")
            params["value"] = True
        return _response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = _models(client)
        observer = source.bind(models)
        await cross_check_candidate(candidate, models, observer=observer)
        clock.seconds = 300
        assert (await source.observe(now=clock.now())).value == 0
        clock.seconds = 301
        failure = True
        with pytest.raises((httpx.HTTPError, ValueError)):
            await cross_check_candidate(candidate, models, observer=observer)
        await _unavailable(source, clock, "source_incomplete")
        assert source._pending == 0
        clock.seconds = 600
        await _unavailable(source, clock, "source_incomplete")


@pytest.mark.parametrize("cancel", [False, True])
async def test_inflight_round_and_cancelled_sibling_hold_all_prior_health(cancel):
    clock = Clock()
    source = _source(clock)
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    block = False
    calls = 0

    async def handler(request):
        nonlocal calls
        index = calls % 2
        calls += 1
        if block:
            entered[index].set()
            await release.wait()
        return _response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = _models(client)
        observer = source.bind(models)
        await cross_check_candidate(CANDIDATE, models, observer=observer)
        clock.seconds = 300
        assert (await source.observe(now=clock.now())).value == 0
        clock.seconds = 301
        block = True
        task = asyncio.create_task(cross_check_candidate(CANDIDATE, models, observer=observer))
        await asyncio.gather(*(event.wait() for event in entered))
        await _unavailable(source, clock, "source_incomplete")
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await _unavailable(source, clock, "source_incomplete")
        else:
            release.set()
            await task
            assert (await source.observe(now=clock.now())).value == 0
        assert source._pending == 0
        assert calls == 4


@pytest.mark.parametrize("fault", ["clock", "naive", "regression", "duplicate", "restart", "close"])
async def test_lifetime_and_clock_faults_never_reuse_previous_rate(fault, monkeypatch):
    clock = Clock()
    source = _source(clock)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: _response())) as client:
        models = _models(client)
        observer = source.bind(models)
        await cross_check_candidate(CANDIDATE, models, observer=observer)
        clock.seconds = 300
        await source.observe(now=clock.now())
        reason = "source_incomplete"
        if fault in {"clock", "naive"}:

            def failed_clock():
                if fault == "clock":
                    raise OSError("synthetic private clock detail")
                return datetime(2026, 10, 19)

            monkeypatch.setattr(source, "_clock", failed_clock)
            clock.seconds = 301
            result = await cross_check_candidate(CANDIDATE, models, observer=observer)
            assert result.agree_count == 2
            reason = "source_malformed"
        elif fault == "regression":
            clock.seconds = 299
            reason = "source_malformed"
        elif fault == "duplicate":
            source.bind(models)
        elif fault == "restart":
            source = _source(clock)
            source.bind(models)
        else:
            source.close()
            reason = "source_missing"
        await _unavailable(source, clock, reason)


async def test_actual_gate_bootstrap_persisted_contract_and_shutdown_share_source(
    app_config, monkeypatch
):
    from unittest.mock import MagicMock

    from fdai.composition import default_container
    from fdai.core.quality_gate.promotion import ActionModeSource
    from fdai.delivery.startup_probe import StaticStartupProbe
    from fdai.runtime import bootstrap_readiness as bootstrap_module
    from fdai.runtime.bootstrap_resources import RuntimeResources
    from fdai.runtime.control_loop_auxiliary import build_t2_quality_gate
    from fdai.runtime.readiness import build_startup_readiness_runtime
    from fdai.shared.contracts.models import Rule
    from fdai.shared.providers.local.event_bus import LocalEventBus
    from fdai.shared.providers.testing.state_store import InMemoryStateStore
    from fdai_service_contracts.self_health import (
        OperationalStateSnapshotV1,
        SelfHealthSignalName,
        SelfHealthSignalStatus,
    )

    clock = Clock()
    monkeypatch.setattr(
        bootstrap_module,
        "RuntimeMixedModelHealthSource",
        lambda **kwargs: RuntimeMixedModelHealthSource(
            clock=clock.now, ticks=clock.ticks, **kwargs
        ),
    )
    rule = Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "example.rule",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "security",
            "resource_type": "object-storage",
            "check_logic": {"kind": "rego", "reference": "policies/example.rego"},
            "remediation": {"template_ref": "remediation/example.tftpl"},
            "remediates": CANDIDATE.action_type,
            "alternatives": [CANDIDATE.action_type],
            "provenance": {
                "source_url": "https://example.com/rule",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:0",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-05T00:00:00Z",
            },
        }
    )
    candidate = replace(CANDIDATE, target_resource_type="object-storage")
    calls = []

    def handler(request):
        calls.append(request)
        return _response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        container = default_container(app_config)
        container = replace(
            container,
            llm_bindings=replace(
                container.require_llm_bindings(), cross_check_models=_models(client)
            ),
        )
        resources = RuntimeResources()
        bindings = bootstrap_module.build_runtime_self_health_bindings(
            container, resources=resources
        )
        source = bindings.mixed_model_health_source
        assert source is resources.mixed_model_health_source
        modes = MagicMock(spec=ActionModeSource)
        before = await build_t2_quality_gate(
            container,
            rules_by_id={rule.id: rule},
            action_modes=modes,
            deterministic_evidence_verifiers=None,
        ).evaluate(candidate)
        gate = build_t2_quality_gate(
            container,
            rules_by_id={rule.id: rule},
            action_modes=modes,
            deterministic_evidence_verifiers=None,
            mixed_model_health_source=source,
        )
        clock.seconds = 299
        after = await gate.evaluate(candidate)
        assert before == after
        assert len(after.model_votes) == 2
        assert all(vote.agreed for vote in after.model_votes)
        assert len(calls) == 4
        store = InMemoryStateStore()
        runtime = build_startup_readiness_runtime(
            state_store=store,
            event_bus=LocalEventBus(),
            transition_event_bus=LocalEventBus(),
            event_validator=container.event_validator,
            identity=LocalWorkloadIdentity(),
            embedding_model=container.require_llm_bindings().embedding_model,
            policy_compile_probe=StaticStartupProbe(
                probe_id="policy.compile", evidence_key="compiled"
            ),
            environment={},
            self_health_catalog=bindings.catalog,
            mixed_model_health_source=source,
        )
        clock.seconds = 300
        await runtime.self_health_monitor.collect_and_persist(now=clock.now())
        record = await store.read_state("runtime:operational-state")
        snapshot = OperationalStateSnapshotV1.model_validate(record["snapshot"])
        row = next(
            row
            for row in snapshot.self_health.signals
            if row.signal is SelfHealthSignalName.MIXED_MODEL_DISAGREEMENT_RATE
        )
        assert row.value == 0
        assert row.status is SelfHealthSignalStatus.HEALTHY
        assert row.observed_at == datetime(2026, 10, 19, 0, 4, 59, tzinfo=UTC)
        assert not row.execution_authority
        assert len(calls) == 4
        assert await store.verify_chain()
        await resources.close()
        await _unavailable(source, clock, "source_missing")

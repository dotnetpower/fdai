from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai.composition import default_container
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    DynamicRuntimeCoordinator,
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
)
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.runtime.dynamic_evidence import (
    DYNAMIC_CONFIG_ENV,
    ConfiguredCausalEvidenceVerifier,
    bind_dynamic_evidence_from_env,
)
from fdai.shared.config import AppConfig
from fdai.shared.contracts.models import Event, Mode, ResponseOutcome
from fdai.shared.providers.testing import InMemoryStateStore
from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _CurrentFixtureSource


def _dynamic_config() -> str:
    def model(status: str) -> dict[str, object]:
        return {
            "model_id": f"model-{status}",
            "version": "1.0.0",
            "revision": 1,
            "action_type_id": "ops.scale-out",
            "metric": "service_latency_ms",
            "status": status,
            "evidence_grade": "quasi_experimental",
            "causal_evidence_receipt_digest": "a" * 64,
            "learned_at": "2026-08-01T00:00:00Z",
            "learned_through": "2026-08-01T00:00:00Z",
            "sample_count": 30,
            "bias_correction": 0.0,
            "mean_absolute_error": 2.0,
            "interval_radius": 5.0,
        }

    return json.dumps(
        {
            "actions": {
                "ops.scale-out": {
                    "metric": "service_latency_ms",
                    "objective": "minimize",
                    "effect_delta": -20.0,
                    "interval_radius": 5.0,
                    "divergence_threshold": 3.0,
                    "max_snapshot_age_seconds": 300,
                }
            },
            "causal_receipt_digests": ["a" * 64],
            "models": [model("active"), model("challenger")],
        }
    )


def _app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "fdai.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


async def _inventory_context(resource_ref: str) -> Mapping[str, object] | None:
    return {
        "resource_id": resource_ref,
        "resource_type": "compute.vm",
        "props": {
            "operational_context": {
                "topology_roles": ["workload"],
                "ownership_shape": ["service_selects_workload"],
                "graph_digest": "b" * 64,
                "owner_digest": "c" * 64,
                "observed_at": datetime.now(tz=UTC).isoformat(),
                "evidence_refs": ["d" * 64],
                "metric_values": {"service_latency_ms": 100.0},
            }
        },
    }


async def test_dynamic_binding_is_unavailable_without_explicit_config() -> None:
    container = default_container(_app_config())

    bound = await bind_dynamic_evidence_from_env(
        container,
        state_store=InMemoryStateStore(),
        environ={},
    )

    assert bound is container
    assert bound.dynamic_simulation_request_provider is None


async def test_dynamic_binding_requires_strict_complete_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )

    state_store = InMemoryStateStore()
    bound = await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=state_store,
        environ={DYNAMIC_CONFIG_ENV: _dynamic_config()},
    )

    assert bound.dynamic_simulation_request_provider is not None
    assert bound.effect_model_reader is not None
    assert bound.effect_model_causal_evidence_verifier is not None
    assert (
        await bound.effect_model_reader.get(
            status=EffectModelStatus.ACTIVE,
            action_type_id="ops.scale-out",
            metric="service_latency_ms",
        )
        is not None
    )


async def test_dynamic_binding_accepts_durable_challenger_learning_on_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )
    state_store = InMemoryStateStore()
    config = json.loads(_dynamic_config())
    for model in config["models"]:
        model.update(
            prediction_model_ref="baseline.scale-out@1.0.0",
            prediction_model_digest="b" * 64,
            unit="ms",
        )
    configuration = json.dumps(config)
    source = _CurrentFixtureSource()
    first = await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=state_store,
        environ={DYNAMIC_CONFIG_ENV: configuration},
        feedback_source=source,
    )
    assert first.effect_model_reader is not None
    challenger = await first.effect_model_reader.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="service_latency_ms",
    )
    assert challenger is not None
    predicted_at = datetime(2026, 8, 1, tzinfo=UTC)
    initial = _feedback(1)
    assert initial.prediction_snapshot is not None
    snapshot = initial.prediction_snapshot.model_copy(
        update={
            "metric": "service_latency_ms",
            "known_at": predicted_at,
            "predicted_at": predicted_at,
            "observation_deadline": predicted_at + timedelta(minutes=5),
        }
    )
    await retain_prediction(state_store, snapshot, recorded_at=predicted_at)
    outcome = ResponseOutcome.model_validate(
        {
            **initial.model_dump(),
            "metric": snapshot.metric,
            "prediction_snapshot": snapshot,
            "predicted_at": snapshot.predicted_at,
            "observation_deadline": snapshot.observation_deadline,
            "observed_at": predicted_at + timedelta(minutes=1),
            "recorded_at": predicted_at + timedelta(minutes=2),
        }
    )
    updated = await StateStoreEffectModelRegistry(
        state_store,
        clock=lambda: predicted_at + timedelta(days=1),
        feedback_source=source,
    ).update_from_outcome(outcome)
    assert updated.accepted

    restarted = await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=state_store,
        environ={DYNAMIC_CONFIG_ENV: configuration},
        feedback_source=source,
    )

    assert restarted.effect_model_reader is not None
    loaded = await restarted.effect_model_reader.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="service_latency_ms",
    )
    assert loaded is not None
    assert loaded.revision == 2
    assert loaded.sample_count == 31
    source.available = False
    held = await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=state_store,
        environ={DYNAMIC_CONFIG_ENV: configuration},
        feedback_source=source,
    )
    assert held.effect_model_reader is not None
    assert (
        await held.effect_model_reader.get(
            status=EffectModelStatus.CHALLENGER,
            action_type_id="ops.scale-out",
            metric="service_latency_ms",
        )
        is None
    )
    config["models"][1]["version"] = "2.0.0"
    with pytest.raises(ValueError, match="configured model lineage"):
        await bind_dynamic_evidence_from_env(
            default_container(_app_config()),
            state_store=state_store,
            environ={DYNAMIC_CONFIG_ENV: json.dumps(config)},
            feedback_source=source,
        )
    source.available = True
    recovered = await held.effect_model_reader.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id="ops.scale-out",
        metric="service_latency_ms",
    )
    assert recovered == loaded
    for field, value in (
        ("bias_correction", 100.0),
        ("mean_absolute_error", 100.0),
        ("interval_radius", 100.0),
        ("sample_count", 29),
        ("learned_through", "2026-08-01T00:00:01Z"),
    ):
        changed_seed = json.loads(configuration)
        changed_seed["models"][1][field] = value
        with pytest.raises(ValueError, match="configured model lineage"):
            await bind_dynamic_evidence_from_env(
                default_container(_app_config()),
                state_store=state_store,
                environ={DYNAMIC_CONFIG_ENV: json.dumps(changed_seed)},
                feedback_source=source,
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bias_correction", 100.0),
        ("mean_absolute_error", 100.0),
        ("interval_radius", 100.0),
        ("sample_count", 29),
    ],
)
async def test_same_revision_requires_the_complete_configured_model_body(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )
    store = InMemoryStateStore()
    await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=store,
        environ={DYNAMIC_CONFIG_ENV: _dynamic_config()},
    )
    config = json.loads(_dynamic_config())
    config["models"][1][field] = value
    with pytest.raises(ValueError, match="configured model lineage"):
        await bind_dynamic_evidence_from_env(
            default_container(_app_config()),
            state_store=store,
            environ={DYNAMIC_CONFIG_ENV: json.dumps(config)},
        )


async def test_configured_dynamic_binding_produces_verified_prediction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )
    bound = await bind_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=InMemoryStateStore(),
        environ={DYNAMIC_CONFIG_ENV: _dynamic_config()},
    )
    assert bound.dynamic_simulation_request_provider is not None
    assert bound.effect_model_reader is not None
    assert bound.effect_model_causal_evidence_verifier is not None
    coordinator = DynamicRuntimeCoordinator(
        request_provider=bound.dynamic_simulation_request_provider,
        model_reader=bound.effect_model_reader,
        causal_evidence_verifier=bound.effect_model_causal_evidence_verifier,
    )
    now = datetime.now(tz=UTC)
    event = Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000201",
        idempotency_key="dynamic-binding-e2e",
        source="test",
        event_type="metric.latency.observed",
        resource_ref="resource-1",
        detected_at=now,
        ingested_at=now,
        payload={},
        mode=Mode.SHADOW,
    )
    action = LearnedAction(
        signature="scale-out-latency",
        rule_id="compute.vm.latency.high",
        action_type="ops.scale-out",
        params={},
        incident_id="incident-1",
        success_rate=0.9,
    )

    result = await coordinator.simulate(event=event, action=action)

    assert result.simulation is not None
    assert result.simulation.requires_review is False
    assert result.simulation.predictions[0].active_value == 80.0


@pytest.mark.parametrize(
    "value",
    (
        "not-json",
        json.dumps({"actions": {}}),
        json.dumps({"actions": {}, "causal_receipt_digests": []}),
    ),
)
async def test_dynamic_binding_rejects_partial_or_invalid_config(value: str) -> None:
    with pytest.raises(ValueError):
        await bind_dynamic_evidence_from_env(
            default_container(_app_config()),
            state_store=InMemoryStateStore(),
            environ={DYNAMIC_CONFIG_ENV: value},
        )


def test_causal_verifier_accepts_only_configured_receipt() -> None:
    verifier = ConfiguredCausalEvidenceVerifier(frozenset({"a" * 64}))
    model = EffectModel(
        model_id="model-1",
        version="1.0.0",
        revision=1,
        action_type_id="ops.scale-out",
        metric="service_latency_ms",
        status=EffectModelStatus.ACTIVE,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="a" * 64,
        learned_at=datetime(2026, 8, 1, tzinfo=UTC),
        learned_through=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert verifier.verify(model) is True

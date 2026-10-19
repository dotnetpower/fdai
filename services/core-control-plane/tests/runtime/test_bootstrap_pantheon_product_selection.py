"""Pantheon composition hands the control loop's product selection to Forseti (#1541).

``initialize_pantheon`` reads ``governed_execution_selected`` from the composed control loop,
which derives it from the #1553 ``RuntimeProductSelection``. Driving the real initializer with
both values proves that Forseti receives exactly that value, so dropping the keyword argument or
hard-coding it fails here. Every backing store and transport is in memory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.agents import Forseti, PantheonRuntime
from fdai.composition import default_container
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.delivery.persistence.postgres_cloud_application import (
    PostgresCloudApplicationAuthorization,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime import bootstrap_pantheon as pantheon_bootstrap
from fdai.runtime import bootstrap_pantheon_evidence as evidence_bootstrap
from fdai.runtime.bootstrap_chaos_schedule import build_chaos_schedule
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness,
    build_runtime_saga,
    runtime_positive_integer,
    semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_pantheon import PantheonInitialization, initialize_pantheon
from fdai.runtime.providers import _build_operator_memory_store
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _DiscoveryActivation:
    """Discovery stays disabled; the initializer only binds and evaluates it."""

    def is_enabled(self) -> bool:
        return False

    def bind_shadow_decision_count(self, counter: Any) -> None:
        self.counter = counter

    async def evaluate(self) -> None:
        return None


def _control_loop(*, governed_execution_selected: bool) -> Any:
    """Expose only the composed control-loop facts that Pantheon initialization reads."""

    return SimpleNamespace(
        governed_execution_selected=governed_execution_selected,
        ontology_instance_store=None,
        ontology_release=None,
        process_runtime_store=None,
        action_types=(),
        alert_workflows=None,
        alert_plan_artifacts=None,
        bind_case_history_reuse=lambda materializer: None,
    )


async def _unused(*args: Any, **kwargs: Any) -> bool:
    raise AssertionError("Pantheon initialization must not invoke incident callbacks")


@pytest.mark.parametrize("selected", [True, False])
@pytest.mark.parametrize("document_dsn", [None, "postgresql://example.invalid/documents"])
async def test_initialize_pantheon_passes_the_product_selection_to_forseti(
    app_config: AppConfig,
    selected: bool,
    document_dsn: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=None, env={})
    original_build = PantheonRuntime.build
    captured: dict[str, Any] = {}
    sampler = object()
    mimir_maintenance = object()
    forseti_replay_source = object()
    bragi_training = object()
    bragi_runs: list[tuple[object, object]] = []
    operations = SimpleNamespace(
        authorize_review=AsyncMock(),
        active_revision=AsyncMock(),
        review=AsyncMock(),
        transition=AsyncMock(),
        apply=AsyncMock(),
        observe=AsyncMock(),
        rollback=AsyncMock(),
        pending=AsyncMock(return_value=()),
        published=AsyncMock(),
    )
    document_intent = SimpleNamespace(repository=operations)
    monkeypatch.setattr(pantheon_bootstrap, "build_capacity_sampler", lambda **kwargs: sampler)
    monkeypatch.setattr(
        evidence_bootstrap,
        "build_mimir_maintenance_source",
        lambda environment: mimir_maintenance,
    )
    monkeypatch.setattr(
        evidence_bootstrap,
        "build_forseti_historical_replay_source",
        lambda environment: forseti_replay_source,
    )
    monkeypatch.setattr(
        evidence_bootstrap,
        "build_bragi_intent_training_batch",
        lambda environment: bragi_training,
    )

    async def run_bragi(runtime: object, batch: object) -> None:
        bragi_runs.append((runtime, batch))

    monkeypatch.setattr(evidence_bootstrap, "run_bragi_intent_training_batch", run_bragi)
    monkeypatch.setattr(
        evidence_bootstrap,
        "build_loki_scenario_bindings",
        lambda **kwargs: loki_scenarios,
    )
    schedule = build_chaos_schedule(
        environment={"FDAI_LOKI_SCHEDULE_JSON": json.dumps(_schedule_declaration())},
        action_type_names=frozenset({"tool.run-chaos-experiment"}),
    )
    loki_scenarios = SimpleNamespace(generator=object(), corpus=(schedule,))
    monkeypatch.setattr(pantheon_bootstrap, "build_chaos_schedule", lambda **kwargs: schedule)

    def build(**kwargs: Any) -> PantheonRuntime:
        captured.update(kwargs)
        return original_build(**kwargs)

    monkeypatch.setattr(PantheonRuntime, "build", build)

    result = await initialize_pantheon(
        PantheonInitialization(
            container=default_container(app_config),
            http_client=None,
            identity=None,
            bus=InMemoryEventBus(),
            incident_audit_store=store,
            startup_readiness=RuntimeReadinessState(),
            runtime_saga=build_runtime_saga(store),
            runtime_values=settings.environment_values(),
            runtime_settings=settings,
            discovery_activation=_DiscoveryActivation(),  # type: ignore[arg-type]
            control_loop=_control_loop(governed_execution_selected=selected),
            rule_generation_reconciliation=None,
            rule_generation_binding=SimpleNamespace(activation_binder=None),  # type: ignore[arg-type]
            open_incident_candidate=_unused,
            resolve_verified_incident=_unused,  # type: ignore[arg-type]
            read_investigation_hook=None,
            runtime_symptom_index=build_from_entries(()),
            stage_topic="fdai.stage",
            environment=(
                {"FDAI_RCA_DOCUMENT_DSN": document_dsn} if document_dsn is not None else {}
            ),
            build_runtime_workload_identity=lambda *args, **kwargs: None,  # type: ignore[arg-type,return-value]
            build_operator_memory_store=_build_operator_memory_store,
            build_inventory_delta_projector=lambda: None,
            runtime_positive_integer=runtime_positive_integer,
            build_mutation_dependency_readiness=build_mutation_dependency_readiness,
            semantic_router_config_from_env=semantic_router_config_from_env,
            document_intent=document_intent,
        )
    )

    assert result.runtime is not None
    forseti = result.runtime.agents["Forseti"]
    assert isinstance(forseti, Forseti)
    assert forseti._governed_execution_selected is selected  # noqa: SLF001
    assert captured["ordered_poison_halt_state_store"] is store
    assert captured["document_intent"] is operations
    assert result.document_intent_ingress is not None
    assert result.document_intent_ingress.intent is document_intent
    assert captured["freyr_utilization_sampler"] is sampler
    assert captured["loki_recurring_schedule"] is schedule
    assert captured["loki_scenario_generator"] is loki_scenarios.generator
    assert captured["loki_scenario_corpus"] == loki_scenarios.corpus
    assert captured["mimir_promotion_outcome_reader"] is mimir_maintenance
    assert captured["mimir_regression_runner"] is mimir_maintenance
    assert captured["mimir_rule_deprecation_reader"] is mimir_maintenance
    assert captured["forseti_historical_replay_source"] is forseti_replay_source
    assert captured["conversation_intent_training_evaluator"] is bragi_training
    assert bragi_runs == [(result.runtime, bragi_training)]
    assert result.runtime.agents["Loki"]._recurring_schedule is schedule  # noqa: SLF001
    assert result.runtime.enforce is False
    var = result.runtime.agents["Var"]
    source = var._cloud_application_source
    if document_dsn is None:
        assert source is None
    else:
        assert isinstance(source, PostgresCloudApplicationAuthorization)
        assert source._dsn == document_dsn


def _schedule_declaration() -> dict[str, Any]:
    return {
        "schedule_id": "reviewed-schedule-example",
        "cadence_seconds": 3600,
        "targets": ["resource-example"],
        "action_type": "tool.run-chaos-experiment",
        "start_at": "2026-10-01T00:00:00+00:00",
        "causal_hypothesis_ref": "hypothesis-example",
        "refutation_query_ref": "query-example",
        "impact_envelope_id": "impact-example",
        "recovery_plan_id": "recovery-example",
        "dry_run_receipt": "dry-run-example",
    }


def test_explicit_loki_schedule_preserves_the_reviewed_definition() -> None:
    schedule = build_chaos_schedule(
        environment={"FDAI_LOKI_SCHEDULE_JSON": json.dumps(_schedule_declaration())},
        action_type_names=frozenset({"tool.run-chaos-experiment"}),
    )
    assert schedule is not None
    assert schedule.targets == ("resource-example",)
    assert schedule.cadence == timedelta(hours=1)
    assert schedule.start_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert schedule.dry_run_receipt == "dry-run-example"


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_at", "2026-10-01T00:00:00"),
        ("cadence_seconds", True),
        ("targets", ["resource-example", "resource-example"]),
        ("dry_run_receipt", ""),
        ("action_type", "unknown.action"),
        ("execution_authority", True),
        ("correlation_id", None),
        ("correlation_id", []),
        ("correlation_id", "x" * 257),
    ],
)
def test_loki_schedule_rejects_unsafe_or_incomplete_configuration(field: str, value: Any) -> None:
    payload = {**_schedule_declaration(), field: value}
    with pytest.raises(ValueError):
        build_chaos_schedule(
            environment={"FDAI_LOKI_SCHEDULE_JSON": json.dumps(payload)},
            action_type_names=frozenset({"tool.run-chaos-experiment"}),
        )


def test_no_loki_schedule_is_not_a_synthetic_schedule() -> None:
    assert build_chaos_schedule(environment={}, action_type_names=frozenset()) is None


def test_catalog_registration_cannot_turn_an_ops_action_into_a_chaos_schedule() -> None:
    payload = {**_schedule_declaration(), "action_type": "ops.restart-service"}
    with pytest.raises(ValueError, match="invalid_action_type"):
        build_chaos_schedule(
            environment={"FDAI_LOKI_SCHEDULE_JSON": json.dumps(payload)},
            action_type_names=frozenset({"ops.restart-service"}),
        )


def test_schedule_duplicate_keys_and_missing_evidence_fail_closed() -> None:
    payload = _schedule_declaration()
    encoded = json.dumps(payload)[:-1] + ', "schedule_id": "other-schedule"}'
    with pytest.raises(ValueError):
        build_chaos_schedule(
            environment={"FDAI_LOKI_SCHEDULE_JSON": encoded},
            action_type_names=frozenset({"tool.run-chaos-experiment"}),
        )
    payload.pop("recovery_plan_id")
    with pytest.raises(ValueError, match="incomplete"):
        build_chaos_schedule(
            environment={"FDAI_LOKI_SCHEDULE_JSON": json.dumps(payload)},
            action_type_names=frozenset({"tool.run-chaos-experiment"}),
        )

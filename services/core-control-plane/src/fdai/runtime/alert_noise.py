"""Explicit Azure reader and signed alert-quality agent binding for both venues."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
from fdai_service_contracts.alert_noise import NoisePolicy
from fdai_service_contracts.alert_noise_wire import (
    ALERT_NOISE_RESULT_TOPIC,
    AlertNoiseReadiness,
    SignedAlertReadiness,
    sign_alert_record,
)

from fdai.agents import Forseti, Heimdall, Huginn, PantheonRuntime
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.delivery.alert_noise_evidence import (
    AdmittedAlertEvidenceSource,
    StateStoreAlertEvaluationReader,
)
from fdai.delivery.alert_noise_handler import AlertNoiseAgentHandler, publish_alert_noise_results
from fdai.delivery.azure.alert_noise_http import AzureAlertReader
from fdai.delivery.azure.alert_noise_source import AlertScopeBinding, AzureAlertEvidenceSource
from fdai.runtime.alert_noise_config import alert_requester_ref, parse_alert_noise_config
from fdai.runtime.alert_noise_effects import bind_alert_effect_runtime
from fdai.shared.providers.alert_noise import AlertEvidenceSource, AlertPlanArtifacts
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


def bind_alert_noise(
    *,
    environment: Mapping[str, str],
    runtime: PantheonRuntime,
    store: StateStore,
    http: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    workflows: AlertWorkflowCoordinator | None = None,
    admissions: DecisionEvidenceAdmissionProvider | None = None,
    artifacts: AlertPlanArtifacts | None = None,
    processes: ProcessRuntimeStore | None = None,
) -> AlertNoiseAgentHandler | None:
    """Fail startup on partial explicit configuration; absence leaves reads unavailable."""
    config = parse_alert_noise_config(environment)
    if config is None:
        return None
    key = environment.get("FDAI_ALERT_NOISE_TRANSPORT_KEY", "").encode()
    pseudonym_key = environment.get("FDAI_ALERT_NOISE_PSEUDONYM_KEY", "").encode()
    if http is None or identity is None or len(key) < 32 or len(pseudonym_key) < 32:
        raise RuntimeError("alert noise reader configuration is incomplete")
    sources: dict[str, AlertEvidenceSource] = {}
    evaluations: dict[str, StateStoreAlertEvaluationReader] = {}

    def clock() -> datetime:
        return datetime.now(UTC)

    for values in config.scopes.values():
        binding = AlertScopeBinding(
            subscription_id=values.subscription_id,
            resource_group=values.resource_group,
            tenant_ref=values.tenant_ref,
            scope_ref=values.scope_ref,
            pseudonym_key=pseudonym_key,
        )
        source: AlertEvidenceSource = AzureAlertEvidenceSource(
            reader=AzureAlertReader(http=http, identity=identity),
            binding=binding,
        )
        if config.source_revision is not None:
            source = AdmittedAlertEvidenceSource(
                inner=source,
                store=store,
                admissions=admissions,
                tenant_ref=values.tenant_ref,
                scope_ref=values.scope_ref,
                source_revision=config.source_revision,
                clock=clock,
            )
            evaluations[values.scope_ref] = StateStoreAlertEvaluationReader(
                store=store,
                admissions=admissions,
                tenant_ref=values.tenant_ref,
                scope_ref=values.scope_ref,
                source_revision=config.source_revision,
                clock=clock,
            )
        sources[binding.scope_ref] = source
    principals: dict[str, frozenset[str]] = {}
    for subject, scopes in config.principal_scopes.items():
        for scope in scopes:
            principals[alert_requester_ref(subject, scope)] = frozenset({scope})
    handler = AlertNoiseAgentHandler(
        store=store,
        sources=sources,
        principals=principals,
        policy=NoisePolicy(),
        transport_key=key,
        workflows=workflows,
        evaluations=evaluations,
        artifacts=artifacts,
        ready=lambda: _agents_ready(runtime),
    )
    observer, judge = runtime.agents.get("Heimdall"), runtime.agents.get("Forseti")
    ingress = runtime.agents.get("Huginn")
    if (
        not isinstance(observer, Heimdall)
        or not isinstance(judge, Forseti)
        or not isinstance(ingress, Huginn)
    ):
        raise RuntimeError("alert noise requires Huginn, Heimdall and Forseti")
    ingress.bind_alert_noise_verifier(handler.verify_ingress)
    observer.bind_alert_noise_observer(handler.observe)
    judge.bind_alert_noise_planner(handler.plan)
    effects = bind_alert_effect_runtime(
        environment=environment,
        store=store,
        processes=processes,
        workflows=workflows,
        admissions=admissions,
        publish=runtime.bridge.publish,
        clock=handler.clock,
    )
    if effects is not None:
        observer.bind_alert_effect_observer(effects.observe)
        judge.bind_alert_effect_planner(effects.plan)
        handler.effect_tick = effects.tick
    return handler


async def run_alert_noise(
    *, handler: AlertNoiseAgentHandler, bus: EventBus, stop: asyncio.Event
) -> None:
    """Supervise outbox and short-lived availability; loss withdraws producer readiness."""

    async def announce() -> None:
        while not stop.is_set():
            now = handler.clock()
            readiness = AlertNoiseReadiness(
                scope_refs=tuple(sorted(handler.sources)) if handler.ready() else (),
                generated_at=now,
                valid_until=now + timedelta(seconds=60),
            )
            signed = SignedAlertReadiness(
                readiness=readiness,
                signature=sign_alert_record(readiness, handler.transport_key),
            )
            await bus.publish(
                ALERT_NOISE_RESULT_TOPIC, "alert-noise:readiness", signed.model_dump(mode="json")
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                continue

    async def effects() -> None:
        while not stop.is_set():
            if handler.effect_tick is not None:
                await handler.effect_tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                continue

    async with asyncio.TaskGroup() as group:
        group.create_task(announce())
        group.create_task(
            publish_alert_noise_results(
                handler=handler, bus=bus, stop=stop, topic=ALERT_NOISE_RESULT_TOPIC
            )
        )
        if handler.effect_tick is not None:
            group.create_task(effects())


def _agents_ready(runtime: PantheonRuntime) -> bool:
    state = runtime.health()
    required = {"Huginn", "Heimdall", "Forseti"}
    failed = {key.split(":", 1)[0] for key in state.get("continuity_failures", {})}
    unavailable = set(state.get("unavailable_agents", ())) | set(state.get("disabled", ())) | failed
    return bool(state.get("consumers_live", 0)) and not required.intersection(unavailable)

"""Compose the alert effect relay over actual dispatch, Process and admission stores.

Only the parent-authenticated Heimdall/Forseti callbacks may call observe/plan.
The tick relays retained Thor references, not decisions. No provider reader, executor,
recovery dispatcher, receipt producer, schema bootstrap or fallback is installed here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
)
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.outcome_verification import StateStoreWorkflowOutcomeLedger
from fdai.delivery.alert_noise_effects import (
    AlertEffectPublish,
    HeimdallAlertEffectHandler,
    StateStoreAlertEffectReader,
)
from fdai.delivery.persistence.postgres_post_release_closure import (
    PostgresPostReleaseClosureStore,
    PostgresPostReleaseClosureStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_safeguard_dispatch import (
    PostgresSafeguardDispatchEvidenceStore,
    PostgresSafeguardDispatchEvidenceStoreConfig,
)
from fdai.runtime.alert_noise_effect_config import _ENV_KEYS, _settings
from fdai.runtime.alert_noise_effect_config import (
    EFFECT_BINDINGS_ENV as EFFECT_BINDINGS_ENV,
)
from fdai.runtime.alert_noise_effect_runtime import (
    AlertEffectRuntime as AlertEffectRuntime,
)
from fdai.runtime.alert_noise_effect_runtime import (
    _envelope_valid as _envelope_valid,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.state_store import StateStore


def bind_alert_effect_runtime(
    *,
    environment: Mapping[str, str],
    store: StateStore,
    processes: ProcessRuntimeStore | None,
    workflows: AlertWorkflowCoordinator | None,
    admissions: DecisionEvidenceAdmissionProvider | None,
    publish: AlertEffectPublish,
    clock: Callable[[], datetime],
) -> AlertEffectRuntime | None:
    """Opt in explicitly; partial bindings fail startup without creating or contacting a source.

    Parent composition must share this StateStore, Process store, source revision and clock
    with the canonical workflow and executor. Identity maps grant no role or admission.
    All PostgreSQL adapters are their existing lazy constructors, not copied SQL/schema.
    """
    if EFFECT_BINDINGS_ENV not in environment:
        return None
    revision, dsn, rows = _settings(environment)
    if (
        processes is None
        or not isinstance(workflows, AlertWorkflowCoordinator)
        or admissions is None
        or not callable(publish)
    ):
        raise ValueError(
            "explicit alert effects require canonical workflow, Process, admission "
            "and owned bus bindings"
        )
    configuration = {key: environment.get(key) for key in _ENV_KEYS}

    async def checked_publish(principal: str, topic: str, payload: dict[str, Any]) -> object:
        if any(environment.get(key) != value for key, value in configuration.items()):
            raise AlertExecutionHeld("alert_effect_configuration_changed")
        if (principal, topic) not in {("Thor", "object.action-run"), ("Heimdall", "object.drift")}:
            raise AlertExecutionHeld("alert_effect_publisher_owner_mismatch")
        return await publish(principal, topic, payload)

    outcomes = StateStoreWorkflowOutcomeLedger(store, admissions, clock)
    holds = StateStoreAutomationHoldLedger(
        store,
        clock,
        PostgresAdvisoryResourceLock(config=PostgresAdvisoryResourceLockConfig(dsn=dsn)),
    )
    dispatches = PostgresSafeguardDispatchEvidenceStore(
        config=PostgresSafeguardDispatchEvidenceStoreConfig(dsn=dsn)
    )
    closures = PostgresPostReleaseClosureStore(
        config=PostgresPostReleaseClosureStoreConfig(dsn=dsn)
    )
    readers: dict[
        tuple[str, str], tuple[StateStoreAlertEffectReader, StateStoreAlertEffectReader]
    ] = {}
    handlers: dict[tuple[str, str], HeimdallAlertEffectHandler] = {}
    for row in rows:
        common = dict(
            store=store,
            admissions=admissions,
            dispatches=dispatches,
            closures=closures,
            processes=processes,
            source_revision=revision,
            clock=clock,
            **row,
        )
        forward = StateStoreAlertEffectReader(**common, purpose=ALERT_EFFECT_PURPOSE)
        recovery = StateStoreAlertEffectReader(**common, purpose=ALERT_RECOVERY_EFFECT_PURPOSE)
        key = (row["tenant_ref"], row["scope_ref"])
        readers[key] = (forward, recovery)
        handlers[key] = HeimdallAlertEffectHandler(
            store=store,
            processes=processes,
            reader=forward,
            recovery_reader=recovery,
            outcomes=outcomes,
            publish=checked_publish,
            clock=clock,
        )
    return AlertEffectRuntime(
        environment=environment,
        store=store,
        processes=processes,
        workflows=workflows,
        outcomes=outcomes,
        holds=holds,
        readers=readers,
        handlers=handlers,
        bindings={(row["tenant_ref"], row["scope_ref"]): row for row in rows},
        source_revision=revision,
        publish=checked_publish,
        clock=clock,
    )


__all__ = ["AlertEffectRuntime", "bind_alert_effect_runtime"]

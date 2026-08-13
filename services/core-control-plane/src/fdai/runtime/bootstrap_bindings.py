"""Runtime transport and workload identity binding helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from fdai.core.ontology_platform import (
    EffectReconciliationCoordinator,
    StateStoreReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_OUTBOX_TOPIC,
    RECONCILIATION_REQUEST_TOPIC,
    ObservationContextVerifier,
    ReconciliationArtifactResolver,
)
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    RuleGenerationOutboxPublisher,
    StateStoreRuleGenerationOutboxLedger,
)
from fdai.delivery.reconciliation_runtime import EffectReconciliationWorker
from fdai.shared.providers.catalog_search import CatalogSemanticIndex
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

RECONCILIATION_TOPICS = frozenset({RECONCILIATION_REQUEST_TOPIC, RECONCILIATION_OUTBOX_TOPIC})
RULE_GENERATION_TOPICS = frozenset(
    {RULE_GENERATION_ACTIVATION_COMMAND_TOPIC, RULE_GENERATION_ACTIVATION_RESULT_TOPIC}
)


@dataclass(frozen=True, slots=True)
class RuleGenerationRuntimeBinding:
    """Shared durable binding for activation command handling and result publication."""

    ledger: StateStoreRuleGenerationOutboxLedger
    activation_binder: RuleGenerationActivationBinder | None
    outbox_publisher: RuleGenerationOutboxPublisher


class WorkloadIdentityBuilder(Protocol):
    def __call__(
        self,
        http_client: httpx.AsyncClient,
        *,
        client_id_env: str,
        require_client_id: bool,
    ) -> WorkloadIdentity: ...


def operational_event_bus(primary: EventBus, auxiliary: EventBus | None) -> EventBus:
    """Select the isolated bus for raw inventory and canary traffic when configured."""

    return auxiliary or primary


def build_rule_generation_runtime_binding(
    *,
    state_store: StateStore,
    event_bus: EventBus,
    catalog_index: CatalogSemanticIndex | None,
    environment: Mapping[str, str],
) -> RuleGenerationRuntimeBinding:
    """Build one ledger, an index-gated binder, and a readiness-independent publisher."""

    ledger = StateStoreRuleGenerationOutboxLedger(store=state_store)
    binder = (
        RuleGenerationActivationBinder(index=catalog_index, ledger=ledger)
        if catalog_index is not None
        else None
    )
    publisher = RuleGenerationOutboxPublisher(
        ledger=ledger,
        event_bus=event_bus,
        claimant_id=environment.get("HOSTNAME", "").strip() or "fdai-core",
        clock=lambda: datetime.now(tz=UTC),
    )
    return RuleGenerationRuntimeBinding(
        ledger=ledger,
        activation_binder=binder,
        outbox_publisher=publisher,
    )


def build_effect_reconciliation_worker(
    *,
    state_store: StateStore,
    event_bus: EventBus,
    artifact_resolver: ReconciliationArtifactResolver | None,
    observation_verifier: ObservationContextVerifier | None,
    environment: Mapping[str, str],
) -> EffectReconciliationWorker | None:
    """Build effect reconciliation only when its complete evidence binding is available."""
    if artifact_resolver is None:
        return None
    if observation_verifier is None:
        raise RuntimeError("effect reconciliation requires an observation verifier")
    ledger = StateStoreReconciliationLedger(store=state_store)
    return EffectReconciliationWorker(
        coordinator=EffectReconciliationCoordinator(ledger=ledger),
        ledger=ledger,
        event_bus=event_bus,
        artifact_resolver=artifact_resolver,
        observation_verifier=observation_verifier,
        claimant_id=environment.get("HOSTNAME", "fdai-core"),
        group_id=environment.get(
            "FDAI_EFFECT_RECONCILIATION_GROUP_ID",
            "fdai-effect-reconciliation",
        ).strip(),
        clock=lambda: datetime.now(tz=UTC),
    )


def build_runtime_workload_identity(
    http_client: httpx.AsyncClient,
    *,
    client_id_env: str = "FDAI_MI_CLIENT_ID",
    require_client_id: bool = False,
) -> WorkloadIdentity:
    if (
        os.environ.get("RUNTIME_ENV", "").strip().lower() == "dev"
        and os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
    ):
        from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity

        return AsyncAzureCliWorkloadIdentity.from_env()

    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    if require_client_id and not os.environ.get(client_id_env, "").strip():
        raise RuntimeError(f"{client_id_env} MUST identify the dedicated workload identity")
    return ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env=client_id_env,
    )


def build_vertical_execution_identities(
    http_client: httpx.AsyncClient | None,
    *,
    identity_environment: Mapping[str, str],
    identity_builder: WorkloadIdentityBuilder = build_runtime_workload_identity,
) -> dict[str, WorkloadIdentity]:
    """Build only configured vertical identities through the shared workload-identity seam."""
    configured = {
        identity_ref: env_var
        for identity_ref, env_var in identity_environment.items()
        if os.environ.get(env_var, "").strip()
    }
    if not configured:
        return {}
    if http_client is None:
        raise RuntimeError("vertical execution identities require an HTTP client")
    return {
        identity_ref: identity_builder(
            http_client,
            client_id_env=env_var,
            require_client_id=True,
        )
        for identity_ref, env_var in configured.items()
    }


def case_history_identity_client_id(environment: Mapping[str, str]) -> str:
    client_id = environment.get("FDAI_CASE_HISTORY_MI_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "FDAI_CASE_HISTORY_MI_CLIENT_ID MUST identify the dedicated workload identity"
        )
    executor_client_id = environment.get("FDAI_MI_CLIENT_ID", "").strip()
    if executor_client_id and client_id == executor_client_id:
        raise RuntimeError("case history and executor workload identities MUST be distinct")
    return client_id


def human_access_identity_client_id(environment: Mapping[str, str]) -> str:
    client_id = environment.get("FDAI_HUMAN_ACCESS_MI_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "FDAI_HUMAN_ACCESS_MI_CLIENT_ID MUST identify the dedicated workload identity"
        )
    executor_client_id = environment.get("FDAI_MI_CLIENT_ID", "").strip()
    if executor_client_id and client_id == executor_client_id:
        raise RuntimeError("human access and executor workload identities MUST be distinct")
    return client_id

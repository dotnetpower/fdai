"""Operational Readiness runtime composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from fdai_service_contracts.model_provider_health import ConfiguredModelBindingV1
from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.composition import Container
from fdai.composition.readiness import (
    OperationalReadinessEventHandler,
    build_operational_readiness_event_handler,
)
from fdai.composition.readiness_catalog import load_runtime_best_practice_bindings
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import SelfHealthCatalog, load_self_health_catalog
from fdai.delivery.azure.llm.provider_observations import ConfiguredModelProviderScope
from fdai.delivery.readiness_remediation import EventBusReadinessRemediationPublisher
from fdai.delivery.self_health_disagreement import RuntimeMixedModelHealthSource
from fdai.delivery.self_health_event_lag import RuntimeEventLagSource
from fdai.delivery.self_health_verifier import RuntimeVerifierHealthSource
from fdai.delivery.startup_probe import OpaCompileStartupProbe
from fdai.runtime.configuration import _resolve_catalog_root, _resolve_policies_root
from fdai.shared.contracts.models import OntologyRelease, Rule
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.readiness import RemediationProposalBinding
from fdai.shared.providers.self_health import (
    ModelProviderObservationSource,
    ModelProviderObservedProvider,
    SelfHealthExporterUnavailableError,
)
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")

if TYPE_CHECKING:
    from fdai.runtime.bootstrap_resources import RuntimeResources


def load_runtime_self_health_catalog() -> SelfHealthCatalog:
    """Load self-health policy with the notification matrix's fallback routes."""

    config_root = _resolve_catalog_root().parent / "config"
    matrix = load_matrix_from_yaml(config_root / "notifications-matrix.yaml")
    route_fallbacks = {name: route.on_all_fail.value for name, route in matrix.routes.items()}
    return load_self_health_catalog(
        config_root / "self-health-signals.yaml",
        route_fallbacks=route_fallbacks,
    )


def build_runtime_model_provider_scope(
    container: Container, catalog: SelfHealthCatalog
) -> ConfiguredModelProviderScope:
    """Keep the full startup registration; a sub-provider never supplies global health."""
    llm_bindings = container.require_llm_bindings()
    age = catalog.policies[SelfHealthSignalName.ADAPTER_HEALTHCHECK].maximum_age_seconds
    roles = (
        tuple(sorted(cap.name for cap in container.resolved_models.capabilities))
        if container.resolved_models is not None
        else ()
    )
    sources: dict[str, ModelProviderObservationSource] = {}
    ambiguous: set[str] = set()
    for provider in (llm_bindings.embedding_model, *llm_bindings.cross_check_models):
        if not isinstance(provider, ModelProviderObservedProvider):
            continue
        try:
            source = provider.model_provider_observations(maximum_age_seconds=age)
        except SelfHealthExporterUnavailableError as exc:
            _LOGGER.info("model_provider_source_unavailable", extra={"reason": exc.reason})
            continue
        if source.role not in roles:
            _LOGGER.warning("model_provider_source_role_unregistered")
            continue
        if source.role in sources or source.role in ambiguous:
            sources.pop(source.role, None)
            ambiguous.add(source.role)
            _LOGGER.error("model_provider_source_role_ambiguous", extra={"role": source.role})
            continue
        sources[source.role] = source
    return ConfiguredModelProviderScope(
        configured_bindings=tuple(
            ConfiguredModelBindingV1(
                role=role,
                binding_digest=(sources[role].binding_digest if role in sources else None),
            )
            for role in roles
        ),
        registration_digest=(
            f"sha256:{container.resolved_models_artifact_digest}"
            if container.resolved_models_artifact_digest is not None
            else None
        ),
        sources=sources,
        maximum_age_seconds=age,
    )


class _CollectorSources(TypedDict):
    verifier_health_source: RuntimeVerifierHealthSource | None
    mixed_model_health_source: RuntimeMixedModelHealthSource | None
    event_lag_source: RuntimeEventLagSource | None


@dataclass(frozen=True, slots=True)
class RuntimeSelfHealthBindings:
    catalog: SelfHealthCatalog
    model_provider_scope: ConfiguredModelProviderScope
    verifier_health_source: RuntimeVerifierHealthSource | None = None
    mixed_model_health_source: RuntimeMixedModelHealthSource | None = None
    event_lag_source: RuntimeEventLagSource | None = None
    stage_publisher: StagePublisher | None = None

    @property
    def collector_sources(self) -> _CollectorSources:
        return {
            "verifier_health_source": self.verifier_health_source,
            "mixed_model_health_source": self.mixed_model_health_source,
            "event_lag_source": self.event_lag_source,
        }


def build_runtime_self_health_bindings(
    container: Container,
    *,
    resources: RuntimeResources | None = None,
    stage_publisher: StagePublisher | None = None,
) -> RuntimeSelfHealthBindings:
    """Bind model scope and verifier observation to one catalog and optional resource owner."""
    catalog = load_runtime_self_health_catalog()
    policy = catalog.policies[SelfHealthSignalName.VERIFIER_FAILURE_RATE]
    verifier_source = RuntimeVerifierHealthSource(
        metric=policy.metric, window_seconds=policy.maximum_age_seconds
    )
    mixed_policy = catalog.policies[SelfHealthSignalName.MIXED_MODEL_DISAGREEMENT_RATE]
    mixed_source = RuntimeMixedModelHealthSource(
        metric=mixed_policy.metric, window_seconds=mixed_policy.maximum_age_seconds
    )
    lag_policy = catalog.policies[SelfHealthSignalName.EVENT_LAG]
    lag_source = RuntimeEventLagSource(
        metric=lag_policy.metric, maximum_age_seconds=lag_policy.maximum_age_seconds
    )
    if stage_publisher is None and resources is not None and resources.messaging is not None:
        stage_publisher = resources.messaging.stage_publisher
    observed_publisher = lag_source.wrap(stage_publisher) if stage_publisher is not None else None
    if resources is not None:
        resources.verifier_health_source = verifier_source
        resources.mixed_model_health_source = mixed_source
        resources.event_lag_source = lag_source
    return RuntimeSelfHealthBindings(
        catalog=catalog,
        model_provider_scope=build_runtime_model_provider_scope(container, catalog),
        verifier_health_source=verifier_source,
        mixed_model_health_source=mixed_source,
        event_lag_source=lag_source,
        stage_publisher=observed_publisher,
    )


def build_runtime_policy_compile_probe() -> OpaCompileStartupProbe:
    """Build the required OPA probe against the same resolved runtime policy tree."""
    return OpaCompileStartupProbe(
        probe_id="policy.compile",
        policies_root=_resolve_policies_root(_resolve_catalog_root()),
    )


def select_runtime_readiness_remediation(
    *,
    configured: RemediationProposalBinding | None,
    event_bus: EventBus,
    active_rules: tuple[Rule, ...],
    ontology_release: OntologyRelease | None,
) -> RemediationProposalBinding | None:
    """Select the no-authority upstream adapter from exact active identities."""

    if configured is not None:
        return configured
    if ontology_release is None:
        return None
    rules_by_id = {rule.id: rule for rule in active_rules if rule.remediates is not None}
    if not rules_by_id:
        return None
    return RemediationProposalBinding(
        publisher=EventBusReadinessRemediationPublisher(
            event_bus=event_bus,
            target_revision=ontology_release.digest,
            rules_by_id=rules_by_id,
        ),
        levers={
            rule_id: rule.remediates
            for rule_id, rule in rules_by_id.items()
            if rule.remediates is not None
        },
    )


def build_runtime_operational_readiness(
    *,
    container: Container,
    state_store: StateStore,
    event_bus: EventBus,
    active_rules: tuple[Rule, ...],
    ontology_release: OntologyRelease | None,
) -> OperationalReadinessEventHandler | None:
    """Build the optional complete ORR runtime binding."""

    best_practices, checklist_evidence = load_runtime_best_practice_bindings(
        _resolve_catalog_root()
    )
    remediation_binding = select_runtime_readiness_remediation(
        configured=container.operational_readiness_remediation,
        event_bus=event_bus,
        active_rules=active_rules,
        ontology_release=ontology_release,
    )
    handler = build_operational_readiness_event_handler(
        posture=container.operational_readiness_posture,
        publisher=container.operational_readiness_report_publisher,
        feasibility_probes=container.feasibility_probes,
        event_validator=container.event_validator,
        state_store=state_store,
        decision_evidence=container.decision_evidence_admission_provider,
        best_practices=best_practices,
        checklist_evidence=checklist_evidence,
        remediation_binding=remediation_binding,
    )
    if handler is None:
        _LOGGER.info(
            "operational_readiness_unavailable",
            extra={"reason": "posture_and_report_publisher_absent"},
        )
    else:
        _LOGGER.info("operational_readiness_ready")
    return handler


__all__ = [
    "build_runtime_operational_readiness",
    "load_runtime_self_health_catalog",
    "select_runtime_readiness_remediation",
]

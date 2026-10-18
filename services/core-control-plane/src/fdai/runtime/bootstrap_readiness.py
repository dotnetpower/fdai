"""Operational Readiness runtime composition."""

from __future__ import annotations

import logging

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
from fdai.runtime.configuration import _resolve_catalog_root
from fdai.shared.contracts.models import OntologyRelease, Rule
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.readiness import RemediationProposalBinding
from fdai.shared.providers.self_health import ModelProviderObservedProvider
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")


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
    embedding = container.require_llm_bindings().embedding_model
    age = catalog.policies[SelfHealthSignalName.ADAPTER_HEALTHCHECK].maximum_age_seconds
    source = (
        embedding.model_provider_observations(maximum_age_seconds=age)
        if isinstance(embedding, ModelProviderObservedProvider)
        else None
    )
    roles = (
        tuple(sorted(cap.name for cap in container.resolved_models.capabilities))
        if container.resolved_models is not None
        else ()
    )
    return ConfiguredModelProviderScope(
        configured_bindings=tuple(
            ConfiguredModelBindingV1(
                role=role,
                binding_digest=(
                    source.binding_digest if role == "t1.embedding" and source is not None else None
                ),
            )
            for role in roles
        ),
        registration_digest=(
            f"sha256:{container.resolved_models_artifact_digest}"
            if container.resolved_models_artifact_digest is not None
            else None
        ),
        sources={"t1.embedding": source} if source is not None else {},
        maximum_age_seconds=age,
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

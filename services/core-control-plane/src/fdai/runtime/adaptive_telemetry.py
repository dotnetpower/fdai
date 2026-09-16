"""Production composition for Process-backed adaptive telemetry investigation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai_service_contracts.ontology_query import content_digest

from fdai.composition import Container
from fdai.core.ontology_platform.query_manifest import build_query_manifest
from fdai.core.rca.telemetry_evidence import TelemetryEvidenceProvider
from fdai.core.rca.telemetry_recipes import DEFAULT_TELEMETRY_RECIPE_CATALOG
from fdai.core.read_investigation.adaptive_contract import AdaptiveInvestigationBudget
from fdai.core.read_investigation.telemetry_adaptive import (
    TELEMETRY_ADAPTIVE_PURPOSE,
    AdaptiveTelemetryEvidenceResult,
    adaptive_telemetry_evidence_result,
    build_initial_telemetry_frame,
    build_telemetry_adaptive_bindings,
    telemetry_mechanisms_for_event,
)
from fdai.runtime.adaptive_investigation_runtime import AdaptiveInvestigationRuntime
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyActionType,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)
from fdai.shared.providers.process_runtime import ProcessRuntimeStore

ADAPTIVE_TELEMETRY_CONFIG_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class AdaptiveTelemetryRuntimeConfig:
    """Server-owned bounds for one shadow-only adaptive telemetry session."""

    enabled: bool = True
    max_rounds: int = 3
    max_queries: int = 3
    max_cost_units: int = 120
    deadline_seconds: int = 5

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("adaptive telemetry enabled MUST be boolean")
        if not 1 <= self.max_rounds <= 8:
            raise ValueError("adaptive telemetry max_rounds MUST be in [1, 8]")
        if not 1 <= self.max_queries <= 8:
            raise ValueError("adaptive telemetry max_queries MUST be in [1, 8]")
        if not 1 <= self.max_cost_units <= 1_000_000:
            raise ValueError("adaptive telemetry max_cost_units MUST be in [1, 1000000]")
        if not 1 <= self.deadline_seconds <= 300:
            raise ValueError("adaptive telemetry deadline_seconds MUST be in [1, 300]")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
    ) -> AdaptiveTelemetryRuntimeConfig:
        """Parse strict deployment settings; malformed values fail startup."""

        return cls(
            enabled=_boolean(
                environment.get("FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED", "true"),
                name="FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED",
            ),
            max_rounds=_integer(
                environment.get("FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_ROUNDS", "3"),
                name="FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_ROUNDS",
            ),
            max_queries=_integer(
                environment.get("FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_QUERIES", "3"),
                name="FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_QUERIES",
            ),
            max_cost_units=_integer(
                environment.get("FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_COST_UNITS", "120"),
                name="FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_COST_UNITS",
            ),
            deadline_seconds=_integer(
                environment.get("FDAI_RCA_ADAPTIVE_TELEMETRY_DEADLINE_SECONDS", "5"),
                name="FDAI_RCA_ADAPTIVE_TELEMETRY_DEADLINE_SECONDS",
            ),
        )

    @property
    def policy_digest(self) -> str:
        return content_digest(
            {
                "config_version": ADAPTIVE_TELEMETRY_CONFIG_VERSION,
                "enabled": self.enabled,
                "max_rounds": self.max_rounds,
                "max_queries": self.max_queries,
                "max_cost_units": self.max_cost_units,
                "deadline_seconds": self.deadline_seconds,
                "recipe_catalog_digest": DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
                "mode": "shadow",
            }
        )


class ConfiguredAdaptiveTelemetryInvestigator:
    """Build and run one exact-resource adaptive Process per novel RCA case."""

    def __init__(
        self,
        *,
        provider: TelemetryEvidenceProvider,
        process_store: ProcessRuntimeStore,
        ontology_release: OntologyRelease,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
        action_types: Sequence[OntologyActionType],
        interface_types: Sequence[OntologyInterfaceType],
        function_types: Sequence[OntologyFunctionType],
        config: AdaptiveTelemetryRuntimeConfig,
    ) -> None:
        self._provider = provider
        self._process_store = process_store
        self._release = ontology_release
        self._object_types = tuple(object_types)
        self._link_types = tuple(link_types)
        self._action_types = tuple(action_types)
        self._interface_types = tuple(interface_types)
        self._function_types = tuple(function_types)
        self._config = config

    async def investigate(
        self,
        *,
        incident_id: str,
        resource_ref: str,
        event_type: str,
        resource_type: str | None,
        evidence_cutoff: datetime,
        correlation_id: str,
    ) -> AdaptiveTelemetryEvidenceResult:
        """Run one shadow-only session and return complete receipt citations."""

        scope_digest = content_digest(
            {
                "caller_agent": "Forseti",
                "caller_role": CeilingRole.READER.value,
                "purpose": TELEMETRY_ADAPTIVE_PURPOSE,
                "resource_ref": resource_ref,
            }
        )
        manifest = build_query_manifest(
            release=self._release,
            principal_role=CeilingRole.READER,
            purposes=(TELEMETRY_ADAPTIVE_PURPOSE,),
            principal_scope_digest=scope_digest,
            object_types=self._object_types,
            link_types=self._link_types,
            interfaces=self._interface_types,
            action_types=self._action_types,
            functions=self._function_types,
            bound_function_names=(),
        )
        bindings = build_telemetry_adaptive_bindings(
            provider=self._provider,
            manifest=manifest,
            principal_scope_digest=scope_digest,
            resource_ref=resource_ref,
        )
        frame = build_initial_telemetry_frame(
            incident_id=incident_id,
            graph_revision=self._release.digest,
            evidence_cutoff=evidence_cutoff,
            mechanisms=telemetry_mechanisms_for_event(
                event_type,
                resource_type=resource_type,
            ),
        )
        runtime = AdaptiveInvestigationRuntime(
            process_store=self._process_store,
            round_source=bindings.round_source,
            reviser=bindings.reviser,
            gateway=bindings.gateway,
            active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        )
        session_id = "adaptive-telemetry:" + content_digest(
            {
                "incident_id": incident_id,
                "resource_ref": resource_ref,
                "evidence_cutoff": evidence_cutoff.astimezone(UTC).isoformat(),
                "catalog_digest": DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
            }
        ).removeprefix("sha256:")
        result = await runtime.run(
            session_id=session_id,
            target_resource_id=resource_ref,
            correlation_id=correlation_id,
            initial_frame=frame,
            budget=AdaptiveInvestigationBudget(
                max_rounds=self._config.max_rounds,
                max_queries=self._config.max_queries,
                max_cost_units=self._config.max_cost_units,
                deadline_at=evidence_cutoff.astimezone(UTC)
                + timedelta(seconds=self._config.deadline_seconds),
                policy_digest=self._config.policy_digest,
            ),
        )
        return adaptive_telemetry_evidence_result(result)


def build_adaptive_telemetry_investigator(
    *,
    provider: TelemetryEvidenceProvider | None,
    process_store: ProcessRuntimeStore,
    ontology_release: OntologyRelease,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    action_types: Sequence[OntologyActionType],
    interface_types: Sequence[OntologyInterfaceType],
    function_types: Sequence[OntologyFunctionType],
    environment: Mapping[str, str],
) -> ConfiguredAdaptiveTelemetryInvestigator | None:
    """Return the shadow runtime when available unless deployment disables it."""

    config = AdaptiveTelemetryRuntimeConfig.from_environment(environment)
    if not config.enabled or provider is None:
        return None
    return ConfiguredAdaptiveTelemetryInvestigator(
        provider=provider,
        process_store=process_store,
        ontology_release=ontology_release,
        object_types=object_types,
        link_types=link_types,
        action_types=action_types,
        interface_types=interface_types,
        function_types=function_types,
        config=config,
    )


def build_adaptive_telemetry_from_container(
    *,
    container: Container,
    process_store: ProcessRuntimeStore,
    ontology_release: OntologyRelease,
    action_types: Sequence[OntologyActionType],
    environment: Mapping[str, str],
) -> ConfiguredAdaptiveTelemetryInvestigator | None:
    """Compose adaptive telemetry from the immutable application container."""

    return build_adaptive_telemetry_investigator(
        provider=container.telemetry_evidence_provider,
        process_store=process_store,
        ontology_release=ontology_release,
        object_types=container.ontology_object_types,
        link_types=container.ontology_link_types,
        action_types=action_types,
        interface_types=container.ontology_interface_types,
        function_types=container.ontology_function_types,
        environment=environment,
    )


def _boolean(value: str, *, name: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} MUST be a boolean")


def _integer(value: str, *, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc


__all__ = [
    "ADAPTIVE_TELEMETRY_CONFIG_VERSION",
    "AdaptiveTelemetryRuntimeConfig",
    "ConfiguredAdaptiveTelemetryInvestigator",
    "build_adaptive_telemetry_from_container",
    "build_adaptive_telemetry_investigator",
]

"""One-shot scheduled WARA assessment over deployment-owned workload scopes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
import psycopg

from fdai.core.wara import (
    WaraAssessmentObservationRunner,
    WaraAssessmentRequest,
    WaraAssessmentRuntime,
    WaraAssessmentService,
    WaraScopedResource,
)
from fdai.core.wara.runtime import WARA_ASSESSMENT_TOPIC, WaraAssessmentResult
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.wara_observation import AzureResourceGraphWaraObservationProvider
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_wara_scope import (
    PostgresWaraScopeSource,
    PostgresWaraScopeSourceConfig,
    WaraResolvedScope,
    WaraScopeUnavailableError,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import (
    WaraAssessmentCatalog,
    WaraQueryCatalog,
    canonical_digest,
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    WaraEvaluatorBindingCatalog,
    load_wara_evaluator_bindings,
)
from fdai.runtime.venue import (
    bus_security_protocol,
    resolve_execution_venue,
    uses_developer_identity,
    uses_workload_identity,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.wara_assessment")
_REPO_ROOT = repo_asset_root()
_ASSESSMENT_ROOT = _REPO_ROOT / "rule-catalog/collected/wara-aprl/assessment"
_MAXIMUM_WORKLOADS = 1
_DEFAULT_TICK_TIMEOUT_SECONDS = 840
_DEFAULT_RUN_SLOT_SECONDS = 86_400


class WaraJobConfigurationError(ValueError):
    """Required WARA job bindings are missing or outside their bounds."""


class WaraScopeSource(Protocol):
    """Resolve one complete deployment-owned workload scope."""

    async def resolve(
        self,
        workload_id: str,
        *,
        now: datetime | None = None,
    ) -> WaraResolvedScope: ...


@dataclass(frozen=True, slots=True)
class WaraJobSettings:
    """Validated environment bindings for one scheduled assessment pass."""

    dsn: str
    bootstrap_servers: str
    physical_topic: str
    workload_ids: tuple[str, ...]
    workload_tags: Mapping[str, tuple[str, ...]]
    inventory_freshness_seconds: int = 86_400
    maximum_resources_per_workload: int = 1_000
    tick_timeout_seconds: int = _DEFAULT_TICK_TIMEOUT_SECONDS
    run_slot_seconds: int = _DEFAULT_RUN_SLOT_SECONDS

    def __post_init__(self) -> None:
        if (
            not self.dsn.strip()
            or not self.bootstrap_servers.strip()
            or not self.physical_topic.strip()
        ):
            raise WaraJobConfigurationError(
                "WARA DSN, Kafka bootstrap, and physical topic MUST be non-empty"
            )
        if (
            not self.workload_ids
            or len(self.workload_ids) > _MAXIMUM_WORKLOADS
            or self.workload_ids != tuple(sorted(set(self.workload_ids)))
        ):
            raise WaraJobConfigurationError(
                f"WARA workload ids MUST contain 1-{_MAXIMUM_WORKLOADS} unique ordered values"
            )
        if any(not value.strip() for value in self.workload_ids):
            raise WaraJobConfigurationError("WARA workload ids MUST be non-empty")
        if set(self.workload_tags) != set(self.workload_ids):
            raise WaraJobConfigurationError(
                "WARA workload tag keys MUST exactly match workload ids"
            )
        if any(tags != tuple(sorted(set(tags))) for tags in self.workload_tags.values()):
            raise WaraJobConfigurationError(
                "WARA workload tags MUST be unique and ordered per workload"
            )
        if not 1 <= self.inventory_freshness_seconds <= 604_800:
            raise WaraJobConfigurationError("WARA inventory freshness MUST be in [1, 604800]")
        if not 1 <= self.maximum_resources_per_workload <= 1_000:
            raise WaraJobConfigurationError(
                "WARA maximum resources per workload MUST be in [1, 1000]"
            )
        if not 1 <= self.tick_timeout_seconds <= 840:
            raise WaraJobConfigurationError("WARA tick timeout MUST be in [1, 840]")
        if not 60 <= self.run_slot_seconds <= 604_800:
            raise WaraJobConfigurationError("WARA run slot MUST be in [60, 604800]")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> WaraJobSettings:
        """Load required bindings without retaining or rendering secret values."""

        workload_ids = _json_string_set(
            environ.get("FDAI_WARA_WORKLOAD_IDS_JSON", ""),
            name="FDAI_WARA_WORKLOAD_IDS_JSON",
            maximum=_MAXIMUM_WORKLOADS,
            required=True,
        )
        return cls(
            dsn=_required_consistent(
                environ,
                "FDAI_WARA_DSN",
                "FDAI_STATE_STORE_DSN",
                "FDAI_INVENTORY_DSN",
            ).replace("postgresql+psycopg://", "postgresql://", 1),
            bootstrap_servers=_required(environ, "KAFKA_BOOTSTRAP_SERVERS"),
            physical_topic=_required(
                environ,
                "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC",
            ),
            workload_ids=workload_ids,
            workload_tags=_json_workload_tags(
                environ.get("FDAI_WARA_WORKLOAD_TAGS_JSON", "{}"),
                name="FDAI_WARA_WORKLOAD_TAGS_JSON",
                workload_ids=workload_ids,
            ),
            inventory_freshness_seconds=_bounded_integer(
                environ.get("FDAI_WARA_INVENTORY_FRESHNESS_SECONDS", ""),
                name="FDAI_WARA_INVENTORY_FRESHNESS_SECONDS",
                default=86_400,
                minimum=1,
                maximum=604_800,
            ),
            maximum_resources_per_workload=_bounded_integer(
                environ.get("FDAI_WARA_MAX_RESOURCES", ""),
                name="FDAI_WARA_MAX_RESOURCES",
                default=1_000,
                minimum=1,
                maximum=1_000,
            ),
            tick_timeout_seconds=_bounded_integer(
                environ.get("FDAI_WARA_TICK_TIMEOUT_SECONDS", ""),
                name="FDAI_WARA_TICK_TIMEOUT_SECONDS",
                default=_DEFAULT_TICK_TIMEOUT_SECONDS,
                minimum=1,
                maximum=840,
            ),
            run_slot_seconds=_bounded_integer(
                environ.get("FDAI_WARA_RUN_SLOT_SECONDS", ""),
                name="FDAI_WARA_RUN_SLOT_SECONDS",
                default=_DEFAULT_RUN_SLOT_SECONDS,
                minimum=60,
                maximum=604_800,
            ),
        )


@dataclass(frozen=True, slots=True)
class WaraTickReport:
    """Privacy-bounded summary for one scheduled assessment pass."""

    workload_count: int
    aggregate_counts: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "completed",
            "mode": "shadow",
            "execution_authority": False,
            "workload_count": self.workload_count,
            "aggregate_counts": dict(sorted(self.aggregate_counts.items())),
        }


async def execute_wara_assessment_tick(
    *,
    settings: WaraJobSettings,
    scope_source: WaraScopeSource,
    service: WaraAssessmentService,
    catalog: WaraAssessmentCatalog,
    evaluator_bindings: WaraEvaluatorBindingCatalog,
    now: datetime | None = None,
) -> WaraTickReport:
    """Resolve all configured scopes before publishing any shadow assessment."""

    evaluated_at = now or datetime.now(tz=UTC)
    if evaluated_at.tzinfo is None:
        raise ValueError("WARA assessment tick time MUST be timezone-aware")
    allowed_tags = {
        tag for recommendation in catalog.recommendations for tag in recommendation.workload_tags
    }
    configured_tags = {tag for tags in settings.workload_tags.values() for tag in tags}
    unknown_tags = configured_tags - allowed_tags
    if unknown_tags:
        raise WaraJobConfigurationError("WARA workload tags include unknown catalog values")

    async with asyncio.timeout(settings.tick_timeout_seconds):
        resolved_scopes = [
            await scope_source.resolve(workload_id, now=evaluated_at)
            for workload_id in settings.workload_ids
        ]
        scopes = tuple(resolved_scopes)
        results: list[WaraAssessmentResult] = []
        for scope in scopes:
            request = _assessment_request(
                settings=settings,
                scope=scope,
                catalog=catalog,
                evaluator_bindings=evaluator_bindings,
                workload_tags=settings.workload_tags[scope.workload_id],
                evaluated_at=evaluated_at,
            )
            results.append(await service.assess(request))

    counts: dict[str, int] = {}
    for result in results:
        for key, value in result.aggregate_counts.items():
            counts[key] = counts.get(key, 0) + value
    return WaraTickReport(workload_count=len(results), aggregate_counts=counts)


async def run_once(environ: Mapping[str, str] | None = None) -> WaraTickReport:
    """Compose PostgreSQL, Azure Resource Graph, and Event Hubs for one pass."""

    environment = os.environ if environ is None else environ
    settings = WaraJobSettings.from_environ(environment)
    catalog, queries, evaluator_bindings = _load_wara_assets()
    runtime = WaraAssessmentRuntime(catalog, evaluator_bindings)
    venue = resolve_execution_venue()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    ) as http_client:
        identity: WorkloadIdentity = (
            AsyncAzureCliWorkloadIdentity.from_env()
            if uses_developer_identity(venue)
            else ManagedIdentityWorkloadIdentity.from_env(
                http_client=http_client,
                client_id_env="FDAI_MI_CLIENT_ID",
            )
        )
        event_bus = _event_bus(
            settings=settings,
            identity=identity,
            use_workload_identity=uses_workload_identity(venue),
        )
        state_store: StateStore = PostgresStateStore(
            config=PostgresStateStoreConfig(dsn=settings.dsn)
        )
        provider = AzureResourceGraphWaraObservationProvider(
            identity=identity,
            http_client=http_client,
            queries=queries,
            evaluator_bindings=evaluator_bindings,
        )
        service = WaraAssessmentService(
            runtime,
            state_store,
            event_bus,
            WaraAssessmentObservationRunner(runtime=runtime, provider=provider),
        )
        try:
            return await execute_wara_assessment_tick(
                settings=settings,
                scope_source=PostgresWaraScopeSource(
                    config=PostgresWaraScopeSourceConfig(
                        dsn=settings.dsn,
                        freshness_budget_seconds=settings.inventory_freshness_seconds,
                        maximum_resources=settings.maximum_resources_per_workload,
                    )
                ),
                service=service,
                catalog=catalog,
                evaluator_bindings=evaluator_bindings,
            )
        finally:
            await event_bus.close()


def _assessment_request(
    *,
    settings: WaraJobSettings,
    scope: WaraResolvedScope,
    catalog: WaraAssessmentCatalog,
    evaluator_bindings: WaraEvaluatorBindingCatalog,
    workload_tags: tuple[str, ...],
    evaluated_at: datetime,
) -> WaraAssessmentRequest:
    resources = tuple(
        WaraScopedResource(
            resource_id=resource.provider_resource_id,
            provider_resource_type=resource.provider_resource_type,
            workload_tags=workload_tags,
        )
        for resource in scope.resources
    )
    return WaraAssessmentRequest(
        assessment_id=_assessment_id(
            scope,
            crosswalk_digest=catalog.crosswalk_digest,
            evaluator_bindings_digest=evaluator_bindings.overlay_digest,
            workload_tags=workload_tags,
            evaluated_at=evaluated_at,
            run_slot_seconds=settings.run_slot_seconds,
        ),
        framework_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=evaluator_bindings.overlay_digest,
        ontology_release=scope.ontology_release,
        inventory_generation=scope.inventory_generation,
        workload_id=scope.workload_id,
        resources=resources,
        evaluated_at=evaluated_at,
        recorded_at=evaluated_at,
    )


def _assessment_id(
    scope: WaraResolvedScope,
    *,
    crosswalk_digest: str,
    evaluator_bindings_digest: str,
    workload_tags: tuple[str, ...],
    evaluated_at: datetime,
    run_slot_seconds: int,
) -> str:
    slot = int(evaluated_at.timestamp()) // run_slot_seconds
    digest = canonical_digest(
        {
            "crosswalk_digest": crosswalk_digest,
            "evaluator_bindings_digest": evaluator_bindings_digest,
            "inventory_generation": scope.inventory_generation,
            "ontology_release": scope.ontology_release,
            "resources": [
                {
                    "provider_resource_id": item.provider_resource_id,
                    "provider_resource_type": item.provider_resource_type,
                }
                for item in scope.resources
            ],
            "slot": slot,
            "workload_id": scope.workload_id,
            "workload_tags": list(workload_tags),
        }
    ).removeprefix("sha256:")[:24]
    return f"wara-assessment:{slot}:{digest}"


def _load_wara_assets() -> tuple[
    WaraAssessmentCatalog,
    WaraQueryCatalog,
    WaraEvaluatorBindingCatalog,
]:
    framework_root = _REPO_ROOT / "rule-catalog/collected/wara-aprl"
    framework = load_framework_catalog(
        framework_root,
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        _ASSESSMENT_ROOT / "crosswalk.json",
        _ASSESSMENT_ROOT / "queries.json",
        framework=framework,
        framework_path=framework_root / "azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        _ASSESSMENT_ROOT / "evaluator-bindings.json",
        catalog=catalog,
        queries=queries,
    )
    return catalog, queries, bindings


def _event_bus(
    *,
    settings: WaraJobSettings,
    identity: WorkloadIdentity,
    use_workload_identity: bool,
) -> MultiplexedEventBus:
    bus = EventHubsKafkaBus(
        identity=identity if use_workload_identity else None,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=settings.bootstrap_servers,
            security_protocol=bus_security_protocol(resolve_execution_venue()),
            client_id="fdai-wara-assessment",
        ),
    )
    return MultiplexedEventBus(
        bus=bus,
        logical_topics=frozenset({WARA_ASSESSMENT_TOPIC}),
        physical_topic=settings.physical_topic,
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise WaraJobConfigurationError(f"{name} is required")
    return value


def _required_consistent(environ: Mapping[str, str], *names: str) -> str:
    configured = {name: environ[name].strip() for name in names if environ.get(name, "").strip()}
    if not configured:
        raise WaraJobConfigurationError(f"one of {', '.join(names)} is required")
    if len(set(configured.values())) > 1:
        raise WaraJobConfigurationError(f"configured aliases {', '.join(configured)} MUST agree")
    return next(iter(configured.values()))


def _json_string_set(
    raw: str,
    *,
    name: str,
    maximum: int,
    required: bool,
) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WaraJobConfigurationError(f"{name} MUST be a JSON string array") from exc
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise WaraJobConfigurationError(f"{name} MUST be a JSON string array")
    normalized = tuple(sorted(item.strip() for item in value))
    if len(normalized) != len(set(normalized)):
        raise WaraJobConfigurationError(f"{name} MUST contain unique values")
    if len(normalized) > maximum or (required and not normalized):
        raise WaraJobConfigurationError(f"{name} has an invalid item count")
    return normalized


def _json_workload_tags(
    raw: str,
    *,
    name: str,
    workload_ids: tuple[str, ...],
) -> Mapping[str, tuple[str, ...]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WaraJobConfigurationError(f"{name} MUST be a JSON object of string arrays") from exc
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
        for key, tags in value.items()
    ):
        raise WaraJobConfigurationError(f"{name} MUST be a JSON object of string arrays")
    if set(value) != set(workload_ids):
        raise WaraJobConfigurationError(f"{name} keys MUST exactly match configured workload ids")
    normalized: dict[str, tuple[str, ...]] = {}
    for workload_id in workload_ids:
        tags = tuple(sorted(tag.strip() for tag in value[workload_id]))
        if len(tags) > 16 or len(tags) != len(set(tags)):
            raise WaraJobConfigurationError(
                f"{name} tags MUST contain at most 16 unique values per workload"
            )
        normalized[workload_id] = tags
    return normalized


def _bounded_integer(
    raw: str,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise WaraJobConfigurationError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise WaraJobConfigurationError(f"{name} MUST be in [{minimum}, {maximum}]")
    return value


async def _main(argv: list[str]) -> int:
    if argv:
        print(json.dumps({"status": "invalid_arguments"}, sort_keys=True))
        return 2
    try:
        report = await run_once()
    except (WaraJobConfigurationError, WaraScopeUnavailableError) as exc:
        _LOGGER.error(
            "wara_assessment_configuration_unavailable",
            extra={"error_kind": type(exc).__name__},
        )
        print(json.dumps({"status": "configuration_required"}, sort_keys=True))
        return 2
    except (TimeoutError, psycopg.Error, OSError) as exc:
        _LOGGER.error("wara_assessment_failed", extra={"error_kind": type(exc).__name__})
        print(
            json.dumps(
                {"status": "retry_required", "error_kind": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    summary = report.to_dict()
    _LOGGER.info("wara_assessment_complete", extra=summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


def main() -> None:
    """Run one bounded shadow assessment pass and exit with a stable status."""

    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()


__all__ = [
    "WaraJobConfigurationError",
    "WaraJobSettings",
    "WaraScopeSource",
    "WaraTickReport",
    "execute_wara_assessment_tick",
    "main",
    "run_once",
]

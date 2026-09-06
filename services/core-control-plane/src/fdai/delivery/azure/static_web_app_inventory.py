"""Enrich Static Web App Resources with the exact default-environment state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.parse import unquote, urlparse

import httpx

from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_EQUAL_TIME_CONFLICT,
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

STATIC_WEB_APP_INVENTORY_SOURCE_NAME: Final = "azure_static_web_app_environment"
STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY: Final = "staticSiteEnvironmentStatus"
_RESOURCE_TYPE: Final = "static-web-app"
_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_API_VERSION: Final = "2023-12-01"
_SOURCE_IDENTITY: Final = "azure-static-web-app-default-environment"
_EVIDENCE_REF = re.compile(r"azure-static-web-app-environment:sha256:[0-9a-f]{64}")
_PREVIOUS_STATE_READ_BATCH = 1000
_STATES: Final = {
    "waitingfordeployment": "WaitingForDeployment",
    "uploading": "Uploading",
    "deploying": "Deploying",
    "ready": "Ready",
    "failed": "Failed",
    "deleting": "Deleting",
    "detached": "Detached",
}


@dataclass(frozen=True, slots=True)
class AzureStaticWebAppInventoryConfig:
    """Bound exact default-environment reads for one inventory generation."""

    subscription_ids: tuple[str, ...]
    endpoint: str = "https://management.azure.com"
    audience: str = _MANAGEMENT_AUDIENCE
    timeout_seconds: float = 10.0
    max_targets: int = 200
    max_concurrency: int = 8
    max_response_bytes: int = 64 * 1024
    freshness_ceiling_seconds: int = 300
    max_clock_skew_seconds: float = 10.0

    def __post_init__(self) -> None:
        normalized = tuple(sorted({item.casefold() for item in self.subscription_ids}))
        if not normalized or any(not item for item in normalized):
            raise ValueError("Static Web App subscriptions MUST be non-empty")
        object.__setattr__(self, "subscription_ids", normalized)
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("Static Web App endpoint MUST be an HTTPS origin")
        audience = urlparse(self.audience)
        if (
            audience.scheme != "https"
            or not audience.netloc
            or audience.path != "/.default"
            or audience.query
            or audience.fragment
        ):
            raise ValueError("Static Web App audience MUST be an HTTPS .default scope")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Static Web App timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.max_targets <= 1000:
            raise ValueError("Static Web App max_targets MUST be in [1, 1000]")
        if not 1 <= self.max_concurrency <= 8:
            raise ValueError("Static Web App max_concurrency MUST be in [1, 8]")
        if not 1024 <= self.max_response_bytes <= 1_048_576:
            raise ValueError("Static Web App max_response_bytes MUST be in [1024, 1048576]")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("Static Web App freshness ceiling MUST be positive")
        if not 0 <= self.max_clock_skew_seconds <= 30:
            raise ValueError("Static Web App clock skew MUST be in [0, 30]")


@dataclass(frozen=True, slots=True)
class _EnvironmentFact:
    state: str
    effective_at: datetime
    evidence_ref: str


class StaticWebAppPreviousStateReader(Protocol):
    """Read exact active Resources without granting write authority."""

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]: ...


class AzureStaticWebAppInventoryEnricher:
    """Add reviewed default-environment state without changing Resource identity."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureStaticWebAppInventoryConfig,
        previous_state_reader: StaticWebAppPreviousStateReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._previous_state_reader = previous_state_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        targets = tuple(
            sorted(
                (item for item in observation.resources if item.type == _RESOURCE_TYPE),
                key=lambda item: item.resource_id,
            )
        )
        if not observation.complete:
            return self._unavailable(observation, reason="inventory_generation_incomplete")
        base_generation, previous = (
            await self._read_previous(targets)
            if self._previous_state_reader is not None
            else (None, {})
        )
        base_observation = replace(
            observation,
            state_base_generation=base_generation,
            state_base_generation_checked=self._previous_state_reader is not None,
        )
        if not targets:
            return self._available(
                base_observation,
                observed_at=self._now(),
                coverage={"targets": 0},
            )
        if len(targets) > self._config.max_targets:
            return self._unavailable(
                _retain_previous_state(base_observation, previous),
                reason="static_web_app_target_limit",
                coverage={"targets": len(targets)},
            )
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception:  # noqa: BLE001 - identity details must not enter generation metadata
            return self._unavailable(
                _retain_previous_state(base_observation, previous),
                reason="static_web_app_identity_unavailable",
            )
        semaphore = asyncio.Semaphore(self._config.max_concurrency)

        async def collect(
            resource: ResourceRecord,
        ) -> tuple[ResourceRecord, _EnvironmentFact | str]:
            async with semaphore:
                return resource, await self._read(resource, token=token.token)

        results = await asyncio.gather(*(collect(resource) for resource in targets))
        completed_at = self._now()
        observed_facts = tuple(
            result for _, result in results if isinstance(result, _EnvironmentFact)
        )
        if observed_facts:
            max_effective_at = max(item.effective_at for item in observed_facts)
            skew_seconds = (max_effective_at - completed_at).total_seconds()
            if 0 < skew_seconds <= self._config.max_clock_skew_seconds:
                await asyncio.sleep(skew_seconds)
                completed_at = self._now()

        coverage: Counter[str] = Counter()
        facts: dict[str, _EnvironmentFact] = {}
        retained: dict[str, ResourceRecord] = {}
        for resource, result in results:
            prior = _prior_state_resource(previous.get(resource.resource_id))
            if isinstance(result, str):
                coverage[result] += 1
                if prior is not None:
                    retained[resource.resource_id] = _carry_prior_state(resource, prior)
            elif result.effective_at > completed_at:
                coverage["response_invalid"] += 1
                if prior is not None:
                    retained[resource.resource_id] = _carry_prior_state(resource, prior)
            elif prior is not None and result.effective_at < prior[1].effective_at:
                coverage["out_of_order"] += 1
                retained[resource.resource_id] = _carry_prior_state(resource, prior)
            elif (
                prior is not None
                and result.effective_at == prior[1].effective_at
                and (
                    prior[1].conflicts
                    or result.state
                    != prior[0].props.get(STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY)
                )
            ):
                coverage["conflicting_same_time"] += 1
                retained[resource.resource_id] = _carry_prior_state(
                    resource,
                    prior,
                    conflict=STATE_FACT_EQUAL_TIME_CONFLICT,
                )
            else:
                coverage["observed"] += 1
                facts[resource.resource_id] = result

        updated = tuple(
            self._with_fact(resource, facts[resource.resource_id], completed_at=completed_at)
            if resource.resource_id in facts
            else retained[resource.resource_id]
            if resource.resource_id in retained
            else resource
            for resource in observation.resources
        )
        counts = {"targets": len(targets), **dict(sorted(coverage.items()))}
        enriched = replace(
            base_observation,
            resources=updated,
            recorded_at=completed_at,
        )
        if len(facts) != len(targets):
            return self._unavailable(
                enriched,
                reason="static_web_app_partial",
                coverage=counts,
            )
        return self._available(enriched, observed_at=completed_at, coverage=counts)

    async def _read_previous(
        self,
        targets: tuple[ResourceRecord, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        if self._previous_state_reader is None:
            return None, {}
        generation: str | None = None
        previous: dict[str, ResourceRecord] = {}
        resource_ids = tuple(item.resource_id for item in targets)
        if not resource_ids:
            return await self._previous_state_reader.read_active_resources(resource_ids=())
        for index in range(0, len(resource_ids), _PREVIOUS_STATE_READ_BATCH):
            batch_generation, batch = await self._previous_state_reader.read_active_resources(
                resource_ids=resource_ids[index : index + _PREVIOUS_STATE_READ_BATCH]
            )
            if index > 0 and batch_generation != generation:
                return None, {}
            generation = batch_generation
            previous.update(batch)
        return generation, previous

    async def _read(self, resource: ResourceRecord, *, token: str) -> _EnvironmentFact | str:
        provider_ref = resource.provider_ref
        if provider_ref is None or not _allowed_arm_id(
            provider_ref,
            subscriptions=self._config.subscription_ids,
        ):
            return "target_unresolved"
        try:
            async with self._http.stream(
                "GET",
                f"{self._config.endpoint.rstrip('/')}{provider_ref}/builds/default",
                params={"api-version": _API_VERSION},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._config.timeout_seconds,
            ) as response:
                if response.status_code in {401, 403}:
                    return "unauthorized"
                if response.status_code == 404:
                    return "default_environment_not_found"
                if response.status_code != 200:
                    return "source_unavailable"
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self._config.max_response_bytes:
                        return "response_too_large"
        except (httpx.HTTPError, TimeoutError):
            return "transport_unavailable"
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return "response_invalid"
        return _fact(payload, resource_id=resource.resource_id)

    def _with_fact(
        self,
        resource: ResourceRecord,
        fact: _EnvironmentFact,
        *,
        completed_at: datetime,
    ) -> ResourceRecord:
        props = dict(resource.props)
        raw_metadata = props.get(STATE_FACT_METADATA_PROPERTY)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        metadata[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity=_SOURCE_IDENTITY,
            source_revision=fact.evidence_ref,
            effective_at=fact.effective_at,
            recorded_at=completed_at,
            evidence_cutoff=completed_at,
            freshness_ceiling_seconds=self._config.freshness_ceiling_seconds,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(fact.evidence_ref,),
        ).to_mapping()
        props.update(
            {
                STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY: fact.state,
                STATE_FACT_METADATA_PROPERTY: metadata,
            }
        )
        return replace(resource, props=props)

    def _available(
        self,
        observation: PromotedInventoryObservation,
        *,
        observed_at: datetime,
        coverage: Mapping[str, int],
    ) -> PromotedInventoryObservation:
        return replace(
            observation,
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=STATIC_WEB_APP_INVENTORY_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.AVAILABLE,
                    observed_at=observed_at,
                    reason=None,
                    coverage=coverage,
                ),
            ),
        )

    @staticmethod
    def _unavailable(
        observation: PromotedInventoryObservation,
        *,
        reason: str,
        coverage: Mapping[str, int] | None = None,
    ) -> PromotedInventoryObservation:
        return replace(
            observation,
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=STATIC_WEB_APP_INVENTORY_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.UNAVAILABLE,
                    observed_at=None,
                    reason=reason,
                    coverage=coverage or {},
                ),
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Static Web App clock MUST be timezone-aware")
        return value


def _fact(payload: object, *, resource_id: str) -> _EnvironmentFact | str:
    if not isinstance(payload, Mapping):
        return "response_invalid"
    name = payload.get("name")
    properties = payload.get("properties")
    if name != "default" or not isinstance(properties, Mapping):
        return "response_invalid"
    raw_state = properties.get("status")
    normalized = raw_state.strip().casefold() if isinstance(raw_state, str) else ""
    state = _STATES.get(normalized)
    effective_at = _timestamp(properties.get("lastUpdatedOn")) or _timestamp(
        properties.get("createdTimeUtc")
    )
    if state is None or effective_at is None:
        return "response_invalid"
    return _EnvironmentFact(
        state=state,
        effective_at=effective_at,
        evidence_ref=_evidence_ref(
            resource_id=resource_id,
            state=state,
            effective_at=effective_at,
        ),
    )


def _allowed_arm_id(value: str, *, subscriptions: tuple[str, ...]) -> bool:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    parsed = urlparse(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        return False
    raw_parts = value[1:].split("/")
    if not raw_parts or any(not part for part in raw_parts):
        return False
    decoded_parts = tuple(unquote(part) for part in raw_parts)
    if any(
        part in {".", ".."}
        or "/" in part
        or "\\" in part
        or any(ord(character) < 32 or ord(character) == 127 for character in part)
        for part in decoded_parts
    ):
        return False
    return (
        len(raw_parts) == 8
        and raw_parts[0].casefold() == "subscriptions"
        and raw_parts[1].casefold() in subscriptions
        and raw_parts[2].casefold() == "resourcegroups"
        and raw_parts[4].casefold() == "providers"
        and raw_parts[5].casefold() == "microsoft.web"
        and raw_parts[6].casefold() == "staticsites"
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (OverflowError, OSError, ValueError):
        return None


def _evidence_ref(*, resource_id: str, state: str, effective_at: datetime) -> str:
    material = f"{resource_id}|default|{state}|{effective_at.isoformat()}"
    digest = hashlib.sha256(material.encode()).hexdigest()
    return f"azure-static-web-app-environment:sha256:{digest}"


def _prior_state_resource(
    resource: ResourceRecord | None,
) -> tuple[ResourceRecord, StateFactMetadata] | None:
    if resource is None:
        return None
    state = resource.props.get(STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY)
    metadata_root = resource.props.get(STATE_FACT_METADATA_PROPERTY)
    metadata_value = (
        metadata_root.get(STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY)
        if isinstance(metadata_root, Mapping)
        else None
    )
    if (
        not isinstance(state, str)
        or state not in _STATES.values()
        or not isinstance(metadata_value, Mapping)
    ):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(metadata_value)
    except (OverflowError, TypeError, ValueError):
        return None
    expected_evidence_ref = _evidence_ref(
        resource_id=resource.resource_id,
        state=state,
        effective_at=metadata.effective_at,
    )
    if (
        metadata.source_identity != _SOURCE_IDENTITY
        or _EVIDENCE_REF.fullmatch(metadata.source_revision) is None
        or metadata.evidence_refs != (metadata.source_revision,)
        or metadata.source_revision != expected_evidence_ref
        or metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority is not StateFactAuthority.PROVIDER
        or metadata.synthetic
        or not (
            (metadata.completeness == 1.0 and not metadata.conflicts)
            or (
                metadata.completeness == 0.0
                and metadata.conflicts == (STATE_FACT_EQUAL_TIME_CONFLICT,)
            )
        )
    ):
        return None
    return resource, metadata


def _carry_prior_state(
    resource: ResourceRecord,
    prior: tuple[ResourceRecord, StateFactMetadata],
    *,
    conflict: str | None = None,
) -> ResourceRecord:
    prior_resource, prior_fact = prior
    props = dict(resource.props)
    metadata_root = props.get(STATE_FACT_METADATA_PROPERTY)
    metadata = dict(metadata_root) if isinstance(metadata_root, Mapping) else {}
    prior_metadata_root = prior_resource.props[STATE_FACT_METADATA_PROPERTY]
    if not isinstance(prior_metadata_root, Mapping):
        raise ValueError("prior Static Web App metadata is malformed")
    metadata[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] = (
        replace(
            prior_fact,
            completeness=0.0,
            conflicts=(conflict,),
        ).to_mapping()
        if conflict is not None
        else prior_metadata_root[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY]
    )
    props[STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY] = prior_resource.props[
        STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY
    ]
    props[STATE_FACT_METADATA_PROPERTY] = metadata
    return replace(resource, props=props)


def _retain_previous_state(
    observation: PromotedInventoryObservation,
    previous: Mapping[str, ResourceRecord],
) -> PromotedInventoryObservation:
    retained: list[ResourceRecord] = []
    for resource in observation.resources:
        prior = _prior_state_resource(previous.get(resource.resource_id))
        retained.append(_carry_prior_state(resource, prior) if prior is not None else resource)
    return replace(observation, resources=tuple(retained))


__all__ = [
    "AzureStaticWebAppInventoryConfig",
    "AzureStaticWebAppInventoryEnricher",
    "STATIC_WEB_APP_ENVIRONMENT_STATUS_PROPERTY",
    "STATIC_WEB_APP_INVENTORY_SOURCE_NAME",
    "StaticWebAppPreviousStateReader",
]

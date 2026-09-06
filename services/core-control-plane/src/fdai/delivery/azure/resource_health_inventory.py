"""Enrich reviewed inventory Resources with exact Azure Resource Health state."""

from __future__ import annotations

import asyncio
import hashlib
import json
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

RESOURCE_HEALTH_INVENTORY_SOURCE_NAME: Final = "azure_resource_health"
_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_API_VERSION: Final = "2025-05-01"
_RESOURCE_TYPES: Final = frozenset({"log-workspace"})
_STATES: Final = {
    "available": "Available",
    "degraded": "Degraded",
    "unavailable": "Unavailable",
    "unknown": "Unknown",
}


@dataclass(frozen=True, slots=True)
class AzureResourceHealthInventoryConfig:
    """Bound exact ARM reads used to enrich one promoted inventory generation."""

    subscription_ids: tuple[str, ...]
    endpoint: str = "https://management.azure.com"
    audience: str = _MANAGEMENT_AUDIENCE
    timeout_seconds: float = 10.0
    max_targets: int = 100
    max_concurrency: int = 4
    max_response_bytes: int = 64 * 1024
    freshness_ceiling_seconds: int = 300
    max_clock_skew_seconds: float = 10.0

    def __post_init__(self) -> None:
        normalized = tuple(sorted({item.casefold() for item in self.subscription_ids}))
        if not normalized or any(not item for item in normalized):
            raise ValueError("Resource Health subscriptions MUST be non-empty")
        object.__setattr__(self, "subscription_ids", normalized)
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("Resource Health endpoint MUST be an HTTPS origin")
        audience = urlparse(self.audience)
        if (
            audience.scheme != "https"
            or not audience.netloc
            or audience.path != "/.default"
            or audience.query
            or audience.fragment
        ):
            raise ValueError("Resource Health audience MUST be an HTTPS .default scope")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Resource Health timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.max_targets <= 1000:
            raise ValueError("Resource Health max_targets MUST be in [1, 1000]")
        if not 1 <= self.max_concurrency <= 8:
            raise ValueError("Resource Health max_concurrency MUST be in [1, 8]")
        if not 1024 <= self.max_response_bytes <= 1_048_576:
            raise ValueError("Resource Health max_response_bytes MUST be in [1024, 1048576]")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("Resource Health freshness ceiling MUST be positive")
        if not 0 <= self.max_clock_skew_seconds <= 30:
            raise ValueError("Resource Health clock skew MUST be in [0, 30]")


@dataclass(frozen=True, slots=True)
class _HealthFact:
    state: str
    reason_kind: str
    effective_at: datetime
    evidence_ref: str


class ResourceHealthPreviousStateReader(Protocol):
    """Read exact active Resources without granting write authority."""

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]: ...


class AzureResourceHealthInventoryEnricher:
    """Add exact workspace availability without changing Resource identity or configuration."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureResourceHealthInventoryConfig,
        previous_state_reader: ResourceHealthPreviousStateReader | None = None,
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
                (item for item in observation.resources if item.type in _RESOURCE_TYPES),
                key=lambda item: item.resource_id,
            )
        )
        if not observation.complete:
            return self._unavailable(observation, reason="inventory_generation_incomplete")
        base_resource_ids = (
            tuple(item.resource_id for item in targets)
            if len(targets) <= self._config.max_targets
            else ()
        )
        base_generation, previous = (
            await self._previous_state_reader.read_active_resources(resource_ids=base_resource_ids)
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
                base_observation,
                reason="resource_health_target_limit",
                coverage={"targets": len(targets)},
            )
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception:  # noqa: BLE001 - identity details must not enter generation metadata
            return self._unavailable(
                _retain_previous_health(base_observation, previous),
                reason="resource_health_identity_unavailable",
            )
        semaphore = asyncio.Semaphore(self._config.max_concurrency)

        async def collect(resource: ResourceRecord) -> tuple[ResourceRecord, _HealthFact | str]:
            async with semaphore:
                return resource, await self._read(resource, token=token.token)

        results = await asyncio.gather(*(collect(resource) for resource in targets))
        completed_at = self._now()
        observed_facts = tuple(result for _, result in results if isinstance(result, _HealthFact))
        if observed_facts:
            max_effective_at = max(item.effective_at for item in observed_facts)
            skew_seconds = (max_effective_at - completed_at).total_seconds()
            if 0 < skew_seconds <= self._config.max_clock_skew_seconds:
                await asyncio.sleep(skew_seconds)
                completed_at = self._now()
        coverage: Counter[str] = Counter()
        facts: dict[str, _HealthFact] = {}
        retained: dict[str, ResourceRecord] = {}
        for resource, result in results:
            if isinstance(result, str):
                coverage[result] += 1
                prior = _prior_health_resource(previous.get(resource.resource_id))
                if prior is not None:
                    retained[resource.resource_id] = _carry_prior_health(resource, prior)
            elif result.effective_at > completed_at:
                coverage["response_invalid"] += 1
                prior = _prior_health_resource(previous.get(resource.resource_id))
                if prior is not None:
                    retained[resource.resource_id] = _carry_prior_health(resource, prior)
            else:
                prior = _prior_health_resource(previous.get(resource.resource_id))
                if prior is not None and result.effective_at < prior[1].effective_at:
                    coverage["out_of_order"] += 1
                    retained[resource.resource_id] = _carry_prior_health(resource, prior)
                elif (
                    prior is not None
                    and result.effective_at == prior[1].effective_at
                    and (
                        prior[1].conflicts
                        or result.state != prior[0].props.get("availabilityState")
                        or result.reason_kind != prior[0].props.get("availabilityReasonKind")
                    )
                ):
                    coverage["conflicting_same_time"] += 1
                    retained[resource.resource_id] = _carry_prior_health(
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
        enriched_observation = replace(
            base_observation,
            resources=updated,
            recorded_at=completed_at,
        )
        if len(facts) != len(targets):
            return self._unavailable(
                enriched_observation,
                reason="resource_health_partial",
                coverage=counts,
            )
        return self._available(
            enriched_observation,
            observed_at=completed_at,
            coverage=counts,
        )

    async def _read(self, resource: ResourceRecord, *, token: str) -> _HealthFact | str:
        provider_ref = resource.provider_ref
        if provider_ref is None or not _allowed_arm_id(
            provider_ref,
            subscriptions=self._config.subscription_ids,
        ):
            return "target_unresolved"
        try:
            async with self._http.stream(
                "GET",
                f"{self._config.endpoint.rstrip('/')}{provider_ref}/providers/"
                "Microsoft.ResourceHealth/availabilityStatuses/current",
                params={"api-version": _API_VERSION},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._config.timeout_seconds,
            ) as response:
                if response.status_code in {401, 403}:
                    return "unauthorized"
                if response.status_code == 422:
                    return "not_modeled"
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
        fact: _HealthFact,
        *,
        completed_at: datetime,
    ) -> ResourceRecord:
        props = dict(resource.props)
        raw_metadata = props.get(STATE_FACT_METADATA_PROPERTY)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        metadata["availabilityState"] = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="azure-resource-health",
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
                "availabilityState": fact.state,
                "availabilityReasonKind": fact.reason_kind,
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
                    source=RESOURCE_HEALTH_INVENTORY_SOURCE_NAME,
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
                    source=RESOURCE_HEALTH_INVENTORY_SOURCE_NAME,
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
            raise ValueError("Resource Health clock MUST be timezone-aware")
        return value


def _fact(payload: object, *, resource_id: str) -> _HealthFact | str:
    if not isinstance(payload, Mapping):
        return "response_invalid"
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return "response_invalid"
    raw_state = properties.get("availabilityState")
    normalized = raw_state.strip().casefold() if isinstance(raw_state, str) else ""
    state = _STATES.get(normalized)
    effective_at = _timestamp(properties.get("reportedTime")) or _timestamp(
        properties.get("occurredTime")
    )
    if state is None or effective_at is None:
        return "response_invalid"
    reason_kind = _machine_token(properties.get("reasonType"), fallback="status_only")
    material = f"{resource_id}|{state}|{reason_kind}|{effective_at.isoformat()}"
    return _HealthFact(
        state=state,
        reason_kind=reason_kind,
        effective_at=effective_at,
        evidence_ref=f"azure-resource-health:sha256:{hashlib.sha256(material.encode()).hexdigest()}",
    )


def _allowed_arm_id(value: str, *, subscriptions: tuple[str, ...]) -> bool:
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
    if any(part in {".", ".."} or "/" in part or "\\" in part for part in decoded_parts):
        return False
    parts = tuple(raw_parts)
    return (
        len(parts) >= 8
        and parts[0].casefold() == "subscriptions"
        and parts[1].casefold() in subscriptions
        and parts[2].casefold() == "resourcegroups"
        and parts[4].casefold() == "providers"
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (OverflowError, OSError, ValueError):
        return None


def _machine_token(value: object, *, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return "_".join(value.casefold().replace("-", " ").split())[:64] or fallback


def _prior_health_resource(
    resource: ResourceRecord | None,
) -> tuple[ResourceRecord, StateFactMetadata] | None:
    if resource is None:
        return None
    metadata_root = resource.props.get(STATE_FACT_METADATA_PROPERTY)
    metadata_value = (
        metadata_root.get("availabilityState") if isinstance(metadata_root, Mapping) else None
    )
    state = resource.props.get("availabilityState")
    if not isinstance(state, str) or not isinstance(metadata_value, Mapping):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(metadata_value)
    except (TypeError, ValueError):
        return None
    if (
        metadata.source_identity != "azure-resource-health"
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


def _carry_prior_health(
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
        raise ValueError("prior Resource Health metadata is malformed")
    metadata["availabilityState"] = (
        replace(
            prior_fact,
            completeness=0.0,
            conflicts=(conflict,),
        ).to_mapping()
        if conflict is not None
        else prior_metadata_root["availabilityState"]
    )
    props["availabilityState"] = prior_resource.props["availabilityState"]
    if "availabilityReasonKind" in prior_resource.props:
        props["availabilityReasonKind"] = prior_resource.props["availabilityReasonKind"]
    props[STATE_FACT_METADATA_PROPERTY] = metadata
    return replace(resource, props=props)


def _retain_previous_health(
    observation: PromotedInventoryObservation,
    previous: Mapping[str, ResourceRecord],
) -> PromotedInventoryObservation:
    retained: list[ResourceRecord] = []
    for resource in observation.resources:
        prior = _prior_health_resource(previous.get(resource.resource_id))
        retained.append(_carry_prior_health(resource, prior) if prior is not None else resource)
    return replace(observation, resources=tuple(retained))


__all__ = [
    "AzureResourceHealthInventoryConfig",
    "AzureResourceHealthInventoryEnricher",
    "RESOURCE_HEALTH_INVENTORY_SOURCE_NAME",
    "ResourceHealthPreviousStateReader",
]

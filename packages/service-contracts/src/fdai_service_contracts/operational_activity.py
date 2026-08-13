"""Versioned activity evidence shared by Core and the Operator Service."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from fdai_service_contracts.executor_models import ContractBase

_OBSERVATION_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class OperationalActivityKind(StrEnum):
    """Read-only operational work visible on Agent Activity surfaces."""

    INVENTORY_SCAN = "inventory.scan"
    INVENTORY_ONTOLOGY_PROJECTION = "inventory.ontology-projection"
    CURRENT_STATE_READ = "current-state.read"
    OBSERVATION = "observation"


class ObservationDomain(StrEnum):
    """Registered evidence family without target or provider identity."""

    INVENTORY = "inventory"
    ACTIVITY_LOG = "activity-log"
    RESOURCE_HEALTH = "resource-health"
    SERVICE_HEALTH = "service-health"
    METRICS = "metrics"
    LOGS = "logs"
    GUEST_LOGS = "guest-logs"
    NETWORK_CONFIG = "network-config"
    COST = "cost"
    RECOVERY = "recovery"


class OperationalActivityStatus(StrEnum):
    """Bounded lifecycle state of one operational activity."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    DEGRADED = "degraded"


class OperationalFreshness(StrEnum):
    """Evidence freshness without provider or target identity."""

    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AgentOperationalActivity(ContractBase):
    """Carry bounded factual work evidence without action authority or target data."""

    type: Literal["agent.operational-activity"] = "agent.operational-activity"
    schema_version: Literal["1.0.0", "1.1.0"] = "1.0.0"
    activity_id: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    kind: OperationalActivityKind
    status: OperationalActivityStatus
    owner_agent: Literal["Huginn", "Heimdall", "Njord", "Freyr", "Vidar"]
    producer: Literal[
        "inventory-sync-job",
        "core-control-plane",
        "observation-campaign-job",
    ]
    observation_domain: ObservationDomain | None = None
    observed_at: datetime
    source: Annotated[str, Field(min_length=1, max_length=128)]
    freshness: OperationalFreshness
    evidence_count: Annotated[int, Field(strict=True, ge=0, le=1_000_000)] = 0
    duration_ms: Annotated[int | None, Field(strict=True, ge=0, le=86_400_000)] = None
    correlation_id: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    reason_codes: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...],
        Field(max_length=16),
    ] = ()
    execution_authority: Literal[False] = False

    @model_serializer(mode="wrap")
    def serialize_versioned(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        """Keep legacy v1.0 payloads byte-shape compatible with their schema."""
        payload = dict(handler(self))
        if self.schema_version == "1.0.0":
            payload.pop("observation_domain", None)
        return payload

    @model_validator(mode="after")
    def validate_ownership(self) -> AgentOperationalActivity:
        """Pin logical ownership independently from the process producing evidence."""
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at MUST include a timezone")
        if self.kind is OperationalActivityKind.OBSERVATION:
            if self.schema_version != "1.1.0" or self.observation_domain is None:
                raise ValueError("observation activity MUST use schema 1.1.0 with a domain")
            expected_owners = {
                ObservationDomain.INVENTORY: frozenset({"Huginn"}),
                ObservationDomain.ACTIVITY_LOG: frozenset({"Huginn"}),
                ObservationDomain.RESOURCE_HEALTH: frozenset({"Heimdall"}),
                ObservationDomain.SERVICE_HEALTH: frozenset({"Heimdall"}),
                ObservationDomain.METRICS: frozenset({"Heimdall", "Freyr"}),
                ObservationDomain.LOGS: frozenset({"Heimdall"}),
                ObservationDomain.GUEST_LOGS: frozenset({"Heimdall"}),
                ObservationDomain.NETWORK_CONFIG: frozenset({"Heimdall"}),
                ObservationDomain.COST: frozenset({"Njord"}),
                ObservationDomain.RECOVERY: frozenset({"Vidar"}),
            }
            if (
                self.owner_agent not in expected_owners[self.observation_domain]
                or self.producer != "observation-campaign-job"
            ):
                raise ValueError("observation activity owner and producer MUST match its domain")
            if any(not _OBSERVATION_REASON_CODE.fullmatch(code) for code in self.reason_codes):
                raise ValueError("observation reason_codes MUST be machine-safe identifiers")
        elif self.observation_domain is not None:
            raise ValueError("non-observation activity MUST NOT declare an observation domain")
        elif self.kind is OperationalActivityKind.INVENTORY_SCAN:
            if self.owner_agent != "Huginn" or self.producer != "inventory-sync-job":
                raise ValueError("inventory scans MUST be Huginn-owned job evidence")
        elif self.kind is OperationalActivityKind.CURRENT_STATE_READ:
            if self.owner_agent != "Heimdall" or self.producer != "core-control-plane":
                raise ValueError("current-state reads MUST be Heimdall-owned Core evidence")
        elif self.owner_agent != "Heimdall" or self.producer != "inventory-sync-job":
            raise ValueError("ontology projection MUST be Heimdall-owned job evidence")
        if (
            self.status
            in {
                OperationalActivityStatus.FAILED,
                OperationalActivityStatus.DEGRADED,
            }
            and not self.reason_codes
        ):
            raise ValueError("failed or degraded activity MUST include a reason code")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes MUST NOT contain duplicates")
        return self


__all__ = [
    "AgentOperationalActivity",
    "ObservationDomain",
    "OperationalActivityKind",
    "OperationalActivityStatus",
    "OperationalFreshness",
]

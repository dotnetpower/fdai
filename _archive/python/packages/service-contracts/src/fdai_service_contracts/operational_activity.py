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
    ASSURANCE_TWIN_POSTURE = "assurance-twin.posture"


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


class OperationalActivitySummaryKey(StrEnum):
    """Registered operator-facing summary without arbitrary producer prose."""

    INVENTORY_COLLECTION = "inventory_collection"
    ONTOLOGY_PROJECTION = "ontology_projection"
    CURRENT_STATE_OBSERVATION = "current_state_observation"
    SOURCE_OBSERVATION = "source_observation"
    ASSURANCE_POSTURE = "assurance_posture"


class OperationalActivityScopeClass(StrEnum):
    """Privacy-safe scope category without provider or target identifiers."""

    CONFIGURED_ESTATE = "configured-estate"
    SOURCE_DOMAIN = "source-domain"
    INVESTIGATION = "investigation"
    CHANGE_REVIEW = "change-review"


class OperationalActivityResultState(StrEnum):
    """Whether a count was measured, omitted, or could not be obtained."""

    MEASURED = "measured"
    NOT_RECORDED = "not-recorded"
    UNAVAILABLE = "unavailable"


class OperationalActivityResultUnit(StrEnum):
    """Registered unit for a measured operational result."""

    EVIDENCE_ITEMS = "evidence-items"
    RESOURCES = "resources"
    RECORDS = "records"
    SIGNALS = "signals"
    RECEIPTS = "receipts"


class AgentOperationalActivity(ContractBase):
    """Carry bounded factual work evidence without action authority or target data."""

    type: Literal["agent.operational-activity"] = "agent.operational-activity"
    schema_version: Literal["1.0.0", "1.1.0", "1.2.0", "1.3.0"] = "1.0.0"
    activity_id: Annotated[str, Field(min_length=1, max_length=512)]
    activity_instance_id: Annotated[str | None, Field(min_length=1, max_length=512)] = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    kind: OperationalActivityKind
    status: OperationalActivityStatus
    owner_agent: Literal["Huginn", "Heimdall", "Njord", "Freyr", "Vidar"]
    producer: Literal[
        "inventory-sync-job",
        "core-control-plane",
        "observation-campaign-job",
        "assurance-twin",
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
    summary_key: OperationalActivitySummaryKey | None = None
    scope_class: OperationalActivityScopeClass | None = None
    target_count: Annotated[int | None, Field(strict=True, ge=0, le=1_000_000)] = None
    result_state: OperationalActivityResultState | None = None
    result_count: Annotated[int | None, Field(strict=True, ge=0, le=1_000_000)] = None
    result_unit: OperationalActivityResultUnit | None = None
    source_cutoff: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
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
        if self.schema_version != "1.3.0":
            for field in (
                "activity_instance_id",
                "summary_key",
                "scope_class",
                "target_count",
                "result_state",
                "result_count",
                "result_unit",
                "source_cutoff",
                "started_at",
                "completed_at",
            ):
                payload.pop(field, None)
        return payload

    @model_validator(mode="after")
    def validate_ownership(self) -> AgentOperationalActivity:
        """Pin logical ownership independently from the process producing evidence."""
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at MUST include a timezone")
        self._validate_presentation()
        if any(not _OBSERVATION_REASON_CODE.fullmatch(code) for code in self.reason_codes):
            raise ValueError("activity reason_codes MUST be machine-safe identifiers")
        if self.kind is OperationalActivityKind.OBSERVATION:
            if self.schema_version not in {"1.1.0", "1.3.0"} or self.observation_domain is None:
                raise ValueError(
                    "observation activity MUST use schema 1.1.0 or 1.3.0 with a domain"
                )
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
        elif self.observation_domain is not None:
            raise ValueError("non-observation activity MUST NOT declare an observation domain")
        elif self.kind is OperationalActivityKind.INVENTORY_SCAN:
            if self.owner_agent != "Huginn" or self.producer != "inventory-sync-job":
                raise ValueError("inventory scans MUST be Huginn-owned job evidence")
        elif self.kind is OperationalActivityKind.CURRENT_STATE_READ:
            if self.owner_agent != "Heimdall" or self.producer != "core-control-plane":
                raise ValueError("current-state reads MUST be Heimdall-owned Core evidence")
        elif self.kind is OperationalActivityKind.ASSURANCE_TWIN_POSTURE:
            if self.schema_version not in {"1.2.0", "1.3.0"}:
                raise ValueError("assurance-twin posture activity MUST use schema 1.2.0 or 1.3.0")
            if self.owner_agent != "Heimdall" or self.producer != "assurance-twin":
                raise ValueError(
                    "assurance-twin posture activity MUST be Heimdall-owned twin evidence"
                )
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

    def _validate_presentation(self) -> None:
        presentation_values = (
            self.activity_instance_id,
            self.summary_key,
            self.scope_class,
            self.target_count,
            self.result_state,
            self.result_count,
            self.result_unit,
            self.source_cutoff,
            self.started_at,
            self.completed_at,
        )
        if self.schema_version != "1.3.0":
            if any(value is not None for value in presentation_values):
                raise ValueError("presentation facts require schema 1.3.0")
            return
        if self.activity_instance_id is None:
            raise ValueError("schema 1.3.0 activity_instance_id MUST be present")
        if self.summary_key is None or self.scope_class is None or self.result_state is None:
            raise ValueError("schema 1.3.0 presentation classification MUST be present")
        expected_presentation = {
            OperationalActivityKind.INVENTORY_SCAN: (
                OperationalActivitySummaryKey.INVENTORY_COLLECTION,
                OperationalActivityScopeClass.CONFIGURED_ESTATE,
            ),
            OperationalActivityKind.INVENTORY_ONTOLOGY_PROJECTION: (
                OperationalActivitySummaryKey.ONTOLOGY_PROJECTION,
                OperationalActivityScopeClass.CONFIGURED_ESTATE,
            ),
            OperationalActivityKind.CURRENT_STATE_READ: (
                OperationalActivitySummaryKey.CURRENT_STATE_OBSERVATION,
                OperationalActivityScopeClass.INVESTIGATION,
            ),
            OperationalActivityKind.OBSERVATION: (
                OperationalActivitySummaryKey.SOURCE_OBSERVATION,
                OperationalActivityScopeClass.SOURCE_DOMAIN,
            ),
            OperationalActivityKind.ASSURANCE_TWIN_POSTURE: (
                OperationalActivitySummaryKey.ASSURANCE_POSTURE,
                OperationalActivityScopeClass.CHANGE_REVIEW,
            ),
        }
        if (self.summary_key, self.scope_class) != expected_presentation[self.kind]:
            raise ValueError("schema 1.3.0 presentation classification MUST match activity kind")
        for field_name, value in (
            ("source_cutoff", self.source_cutoff),
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} MUST include a timezone")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at MUST NOT precede started_at")
        if self.status is OperationalActivityStatus.STARTED and self.completed_at is not None:
            raise ValueError("started activity MUST NOT include completed_at")
        if (
            self.status is OperationalActivityStatus.STARTED
            and self.result_state is not OperationalActivityResultState.NOT_RECORDED
        ):
            raise ValueError("started activity result MUST be not-recorded")
        if (
            self.status is OperationalActivityStatus.FAILED
            and self.result_state is not OperationalActivityResultState.UNAVAILABLE
        ):
            raise ValueError("failed activity result MUST be unavailable")
        if (
            self.status
            in {
                OperationalActivityStatus.COMPLETED,
                OperationalActivityStatus.SUPERSEDED,
            }
            and self.result_state is OperationalActivityResultState.UNAVAILABLE
        ):
            raise ValueError("completed activity result MUST NOT be unavailable")
        if self.result_state is OperationalActivityResultState.MEASURED:
            if self.result_count is None or self.result_unit is None:
                raise ValueError("measured result MUST include count and unit")
            if self.result_count != self.evidence_count:
                raise ValueError("measured result_count MUST match evidence_count")
        elif self.result_count is not None or self.result_unit is not None:
            raise ValueError("unmeasured result MUST NOT include count or unit")
        elif self.evidence_count != 0:
            raise ValueError("unmeasured result MUST keep evidence_count at zero")


__all__ = [
    "AgentOperationalActivity",
    "ObservationDomain",
    "OperationalActivityKind",
    "OperationalActivityResultState",
    "OperationalActivityResultUnit",
    "OperationalActivityScopeClass",
    "OperationalActivityStatus",
    "OperationalActivitySummaryKey",
    "OperationalFreshness",
]

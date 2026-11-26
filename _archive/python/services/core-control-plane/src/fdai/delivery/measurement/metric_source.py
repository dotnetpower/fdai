"""Bounded lifecycle and spend source facts for the protected measurement importer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.measurement_time import measurement_timestamp_input
from fdai_service_contracts.metric_observation import MetricIdentity, SourceReference
from fdai_service_contracts.ontology_query import content_digest
from pydantic import ConfigDict, Field, field_validator, model_validator

METRIC_SOURCE_PURPOSE = "measurement-metric-source"
MAX_METRIC_SOURCE_BYTES = 8 * 1024 * 1024


class _SourceRecord(ContractBase):
    model_config = ConfigDict(str_strip_whitespace=False)

    event_id: MetricIdentity
    mode: Literal["shadow", "enforce"]
    source_record_id: MetricIdentity
    source_refs: Annotated[tuple[SourceReference, ...], Field(min_length=1, max_length=30)]
    observed_at: datetime
    coverage: Literal["complete", "incomplete"]
    synthetic: bool = Field(strict=True)
    supersedes_observation_id: Digest | None = None

    @field_validator(
        "observed_at",
        "opened_at",
        "resolved_at",
        "change_requested_at",
        "merged_at",
        "period_start",
        "period_end",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _timestamp_shape(cls, value: object) -> object:
        return measurement_timestamp_input(value)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _ordered_references(self) -> _SourceRecord:
        if tuple(sorted(set(self.source_refs))) != self.source_refs:
            raise ValueError("metric source references MUST be unique and ordered")
        return self


class IncidentMetricSource(_SourceRecord):
    """Incident timestamps; only an independent exact-fact admission proves resolution."""

    kind: Literal["incident"] = "incident"
    opened_at: datetime
    resolved_at: datetime

    @field_validator("opened_at", "resolved_at")
    @classmethod
    def _aware_lifecycle(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _ordered_times(self) -> IncidentMetricSource:
        if not self.opened_at <= self.resolved_at <= self.observed_at:
            raise ValueError("incident measurement timestamps are out of order")
        return self


class ChangeMetricSource(_SourceRecord):
    """Authoritative request-to-merge timestamps, never commit-to-deployment DORA."""

    kind: Literal["change"] = "change"
    change_requested_at: datetime
    merged_at: datetime

    @field_validator("change_requested_at", "merged_at")
    @classmethod
    def _aware_lifecycle(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _ordered_times(self) -> ChangeMetricSource:
        if not self.change_requested_at <= self.merged_at <= self.observed_at:
            raise ValueError("change measurement timestamps are out of order")
        return self


class AttributedCostMetricSource(_SourceRecord):
    """Actual event-attributed spend; savings, estimates, and token counts do not fit."""

    kind: Literal["attributed_spend"] = "attributed_spend"
    amount: float = Field(strict=True, ge=0, allow_inf_nan=False)
    currency: Literal["USD"]
    period_start: datetime
    period_end: datetime

    @field_validator("period_start", "period_end")
    @classmethod
    def _aware_period(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _ordered_times(self) -> AttributedCostMetricSource:
        if not self.period_start < self.period_end <= self.observed_at:
            raise ValueError("spend measurement timestamps are out of order")
        return self


MetricSourceRecord = Annotated[
    IncidentMetricSource | ChangeMetricSource | AttributedCostMetricSource,
    Field(discriminator="kind"),
]


class _MetricSourceBatchBody(ContractBase):
    kind: Literal["metric_sources"] = "metric_sources"
    schema_version: Literal["1.0.0"] = "1.0.0"
    records: Annotated[tuple[MetricSourceRecord, ...], Field(min_length=1, max_length=1_000)]

    @model_validator(mode="after")
    def _unique_records(self) -> _MetricSourceBatchBody:
        keys = tuple((record.kind, record.event_id) for record in self.records)
        if len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise ValueError("metric source records MUST have unique ordered kind/event keys")
        return self


class MetricSourceBatch(_MetricSourceBatchBody):
    """Content-sealed source facts without an exporter identity or trust declaration."""

    batch_digest: Digest

    @model_validator(mode="after")
    def _sealed(self) -> MetricSourceBatch:
        if self.batch_digest != content_digest(
            self.model_dump(mode="json", exclude={"batch_digest"})
        ):
            raise ValueError("metric source batch digest does not match its content")
        return self


def metric_source_batch_digest(**values: object) -> str:
    """Return the source artifact digest before constructing its sealed batch."""

    body = dict(values)
    body.pop("batch_digest", None)
    return content_digest(_MetricSourceBatchBody.model_validate(body).model_dump(mode="json"))


def load_metric_source_batch(path: Path) -> MetricSourceBatch | None:
    """Load a bounded source artifact, or return None for the legacy cohort format."""

    with path.open("rb") as stream:
        payload = stream.read(MAX_METRIC_SOURCE_BYTES + 1)
    if len(payload) > MAX_METRIC_SOURCE_BYTES:
        raise ValueError("metric source batch exceeds the 8 MiB limit")
    raw = json.loads(payload, object_pairs_hook=_unique_json_object)
    if not isinstance(raw, dict):
        raise ValueError("measurement batch MUST be a JSON object")
    if raw.get("kind") != "metric_sources":
        return None
    return MetricSourceBatch.model_validate(raw)


def metric_source_scope_digest(source: MetricSourceRecord, *, source_id: str) -> str:
    """Bind independent verification to one exporter, event, and lifecycle record."""

    return content_digest(
        {
            "event_id": source.event_id,
            "kind": source.kind,
            "source_id": source_id,
            "source_record_id": source.source_record_id,
        }
    )


def metric_source_evidence_digest(source: MetricSourceRecord, *, source_id: str) -> str:
    """Seal every fact, including completeness and correction identity, for admission."""

    return content_digest({"source": source.model_dump(mode="json"), "source_id": source_id})


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("metric source timestamps MUST include a timezone")
    return value.astimezone(UTC)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("metric source batch repeats a JSON key")
        result[key] = value
    return result

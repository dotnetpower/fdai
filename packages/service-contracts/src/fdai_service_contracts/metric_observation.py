"""Versioned read-only measurement facts; source authentication is importer-owned."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.baseline_cohort import CommitRevision
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.measurement_time import measurement_timestamp_input
from fdai_service_contracts.ontology_query import content_digest

MetricId = Literal["mttr_seconds", "change_lead_time_seconds", "attributed_cost_usd"]
MetricIdentity = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S+$")]
SourceReference = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^\S+$")]
METRIC_OBSERVATION_ACTION_KIND = "measurement.metric.v1"
METRIC_OBSERVATION_ACTOR = "fdai.measurement"
_AUDIT_WRAPPER_FIELDS = frozenset(
    {"actor", "idempotency_key", "execution_authority", "claim_eligibility_authority"}
)


class _MetricObservationBody(ContractBase):
    model_config = ConfigDict(str_strip_whitespace=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
    action_kind: Literal["measurement.metric.v1"] = "measurement.metric.v1"
    metric_id: MetricId
    mode: Literal["shadow", "enforce"]
    arm: Literal["treatment"]
    measurement_protocol_digest: Digest
    source_revision: CommitRevision
    event_id: MetricIdentity
    source_id: MetricIdentity
    source_record_id: MetricIdentity
    source_refs: Annotated[tuple[SourceReference, ...], Field(min_length=1, max_length=32)]
    value: float = Field(strict=True, ge=0, allow_inf_nan=False)
    unit: Literal["seconds", "USD"]
    observed_at: datetime
    recorded_at: datetime
    synthetic: bool = Field(strict=True)
    complete: bool = Field(strict=True)
    supersedes_observation_id: Digest | None = None

    @field_validator("observed_at", "recorded_at", mode="before")
    @classmethod
    def _timestamp_shape(cls, value: object) -> object:
        return measurement_timestamp_input(value)

    @field_validator("observed_at", "recorded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("metric observation timestamps MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_facts(self) -> _MetricObservationBody:
        expected_unit = "USD" if self.metric_id == "attributed_cost_usd" else "seconds"
        if self.unit != expected_unit:
            raise ValueError("metric unit does not match its metric identifier")
        if self.recorded_at < self.observed_at:
            raise ValueError("metric observation MUST NOT be recorded before observation")
        if tuple(sorted(set(self.source_refs))) != self.source_refs:
            raise ValueError("metric source references MUST be unique and ordered")
        return self


class MetricObservationV1(_MetricObservationBody):
    """Immutable source facts, not claim eligibility or execution authority.

    ``observation_id`` seals all source facts except the importer recording time,
    so retries retain their identity. A correction names its immediate predecessor.
    Consumers must authenticate the producer, resolve corrections before filtering,
    and exclude synthetic or incomplete observations from live KPI values.
    ``mode`` is the source event's mode, not permission granted by this read model.
    Arm, protocol, and revision are injected by the protected importer, never taken
    from source artifacts. A latest ``complete=False`` correction withdraws the
    preceding usable value; readers MUST NOT fall back to older complete evidence.
    """

    observation_id: Digest

    @model_validator(mode="after")
    def _validate_identity(self) -> MetricObservationV1:
        expected = content_digest(
            self.model_dump(mode="json", exclude={"observation_id", "recorded_at"})
        )
        if self.observation_id != expected:
            raise ValueError("metric observation identity does not match its facts")
        return self

    @classmethod
    def from_audit_entry(cls, entry: Mapping[str, object]) -> MetricObservationV1:
        """Parse the exact canonical audit JSON object, not its database row.

        Pass ``row["entry"]``; keep the database sequence/snapshot metadata outside
        this model for correction ordering. The four wrapper fields are mandatory;
        unknown fields, authority flags, and a mismatched idempotency key are rejected.
        Mode and trusted source context remain inside the sealed canonical body.
        This shape validation does not authenticate the database writer.
        """

        if (
            entry.get("actor") != METRIC_OBSERVATION_ACTOR
            or entry.get("action_kind") != METRIC_OBSERVATION_ACTION_KIND
            or entry.get("schema_version") != "1.0.0"
            or entry.get("execution_authority") is not False
            or entry.get("claim_eligibility_authority") is not False
        ):
            raise ValueError("metric audit wrapper is not canonical authority-free evidence")
        observation = cls.model_validate(
            {key: value for key, value in entry.items() if key not in _AUDIT_WRAPPER_FIELDS}
        )
        if entry.get("idempotency_key") != observation.audit_idempotency_key:
            raise ValueError("metric audit idempotency key does not match its observation")
        return observation

    @property
    def audit_idempotency_key(self) -> str:
        """Return the stable audit identity, independent of stage rows and retries."""

        return f"measurement:metric:observation:{self.observation_id}"

    def to_audit_entry(self) -> dict[str, object]:
        """Serialize canonical facts and authority-free metadata; authenticate separately."""

        return {
            **self.model_dump(mode="json"),
            "actor": METRIC_OBSERVATION_ACTOR,
            "idempotency_key": self.audit_idempotency_key,
            "execution_authority": False,
            "claim_eligibility_authority": False,
        }


def metric_observation_id(**values: object) -> str:
    """Return a canonical source-fact digest, independent of recording retries."""

    body = dict(values)
    body.pop("observation_id", None)
    validated = _MetricObservationBody.model_validate(body)
    return content_digest(validated.model_dump(mode="json", exclude={"recorded_at"}))

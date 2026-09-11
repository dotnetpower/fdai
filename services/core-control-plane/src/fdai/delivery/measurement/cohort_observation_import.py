"""Trusted import boundary for normalized operational cohort observations.

The source artifact contains measurement facts only. A protected caller injects
the cohort arm, immutable revision, repository policy, and source-run identity.
Imports are idempotent by one protocol-bound observation identity and grant no
admission, claim eligibility, or execution authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fdai.core.measurement.cohort_claim_policy import (
    CohortClaimPolicy,
    CohortClaimPolicyError,
    require_commit_revision,
)
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.baseline_cohort import CohortArm
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.ontology_query import content_digest
from pydantic import Field, field_validator, model_validator

MAX_COHORT_OBSERVATION_BATCH_BYTES = 8 * 1024 * 1024
MAX_COHORT_OBSERVATIONS = 1_000
_MEASURE_ID = r"^[a-z][a-z0-9_]{0,63}$"
_WORKFLOW_PATH = re.compile(r"^\.github/workflows/[a-z0-9][a-z0-9-]{0,99}\.yml$")
_ARTIFACT_NAME = re.compile(r"^cohort-observations-[a-z0-9][a-z0-9-]{0,99}$")


class NormalizedCohortMetricObservation(ContractBase):
    """One finite metric contribution without importer-owned trust fields."""

    kind: Literal["metric"] = "metric"
    metric_id: Annotated[str, Field(pattern=_MEASURE_ID)]
    source_cluster_digest: Digest
    observed_at: datetime
    value: float = Field(strict=True, ge=0, allow_inf_nan=False)

    @field_validator("observed_at")
    @classmethod
    def _normalize_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "cohort observation time")


class NormalizedCohortGuardObservation(ContractBase):
    """One zero-threshold guard contribution without trust declarations."""

    kind: Literal["guard"] = "guard"
    guard_id: Annotated[str, Field(pattern=_MEASURE_ID)]
    source_cluster_digest: Digest
    observed_at: datetime
    observed_basis_points: int = Field(strict=True)
    breached: bool = Field(strict=True)

    @field_validator("observed_at")
    @classmethod
    def _normalize_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "cohort observation time")

    @field_validator("observed_basis_points")
    @classmethod
    def _validate_basis_points(cls, value: int) -> int:
        if value not in {0, 10_000}:
            raise ValueError("cohort guard observation MUST be zero or 10000 basis points")
        return value

    @model_validator(mode="after")
    def _validate_breach(self) -> NormalizedCohortGuardObservation:
        if self.breached != (self.observed_basis_points > 0):
            raise ValueError("cohort guard breach does not match its observed value")
        return self


NormalizedCohortObservation = Annotated[
    NormalizedCohortMetricObservation | NormalizedCohortGuardObservation,
    Field(discriminator="kind"),
]


class _CohortObservationBatchBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    observations: Annotated[
        tuple[NormalizedCohortObservation, ...],
        Field(min_length=1, max_length=MAX_COHORT_OBSERVATIONS),
    ]

    @model_validator(mode="after")
    def _validate_observations(self) -> _CohortObservationBatchBody:
        keys = tuple(_observation_key(item) for item in self.observations)
        if keys != tuple(sorted(keys)):
            raise ValueError("cohort observations MUST be in canonical order")
        if len(keys) != len(set(keys)):
            raise ValueError("cohort observations MUST have unique measure and cluster keys")
        return self


class CohortObservationBatch(_CohortObservationBatchBody):
    """One content-sealed normalized observation artifact."""

    batch_digest: Digest

    @model_validator(mode="after")
    def _validate_digest(self) -> CohortObservationBatch:
        expected = content_digest(self.model_dump(mode="json", exclude={"batch_digest"}))
        if self.batch_digest != expected:
            raise ValueError("cohort observation batch digest does not match its content")
        return self


def cohort_observation_batch_digest(**values: object) -> str:
    """Return the canonical digest for a normalized observation batch body."""

    body = dict(values)
    body.pop("batch_digest", None)
    candidate = _CohortObservationBatchBody.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


def load_cohort_observation_batch(path: Path) -> CohortObservationBatch:
    """Load one bounded normalized batch without accepting trust declarations."""

    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_COHORT_OBSERVATION_BATCH_BYTES + 1)
        if len(payload) > MAX_COHORT_OBSERVATION_BATCH_BYTES:
            raise ValueError("cohort observation batch exceeds the 8 MiB limit")
        raw = json.loads(payload, object_pairs_hook=_unique_json_object)
        return CohortObservationBatch.model_validate(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid cohort observation batch: {error}") from error


@dataclass(frozen=True, slots=True)
class CohortObservationImportContext:
    """Trusted workflow context injected independently from the source artifact."""

    arm: CohortArm
    fdai_revision: str
    source_workflow_path: str
    source_run_id: int
    source_run_attempt: int
    source_artifact_name: str
    imported_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.arm, CohortArm):
            raise ValueError("cohort import arm MUST use the CohortArm contract")
        require_commit_revision(self.fdai_revision)
        if (
            not isinstance(self.source_workflow_path, str)
            or _WORKFLOW_PATH.fullmatch(self.source_workflow_path) is None
        ):
            raise ValueError("cohort source workflow path is invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (self.source_run_id, self.source_run_attempt)
        ):
            raise ValueError("cohort source run identity MUST be positive")
        if (
            not isinstance(self.source_artifact_name, str)
            or _ARTIFACT_NAME.fullmatch(self.source_artifact_name) is None
        ):
            raise ValueError("cohort source artifact name is invalid")
        if not isinstance(self.imported_at, datetime):
            raise ValueError("cohort import time MUST use datetime")
        _aware_utc(self.imported_at, "cohort import time")


@dataclass(frozen=True, slots=True)
class CohortObservationImportReport:
    """Aggregate-only result of one idempotent import."""

    arm: CohortArm
    batch_digest: str
    accepted_count: int
    duplicate_count: int
    metric_count: int
    guard_count: int

    def to_mapping(self) -> dict[str, object]:
        """Return a portable result without operational identifiers."""

        return {
            "arm": self.arm.value,
            "batch_digest": self.batch_digest,
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "metric_count": self.metric_count,
            "guard_count": self.guard_count,
            "execution_authority": False,
            "claim_eligibility_authority": False,
        }


class CohortObservationConflictError(RuntimeError):
    """One measure and source cluster was reused with different content."""


async def import_cohort_observation_batch(
    batch: CohortObservationBatch,
    *,
    context: CohortObservationImportContext,
    policy: CohortClaimPolicy,
    store: StateStore,
) -> CohortObservationImportReport:
    """Validate and persist one normalized batch through trusted workflow context."""

    allowed = policy.allowed_exporters(context.arm.value)
    if not allowed:
        raise CohortClaimPolicyError(f"cohort {context.arm.value} exporter allowlist is empty")
    if context.source_workflow_path not in allowed:
        raise CohortClaimPolicyError(
            f"cohort {context.arm.value} source workflow is not authorized"
        )
    source_binding = policy.exporter_binding(
        context.arm.value,
        context.source_workflow_path,
    )
    for observation in batch.observations:
        if isinstance(observation, NormalizedCohortMetricObservation):
            if not source_binding.allows_metric(observation.metric_id):
                raise CohortClaimPolicyError(
                    f"cohort source workflow is not authorized for metric: {observation.metric_id}"
                )
        elif not source_binding.allows_guard(observation.guard_id):
            raise CohortClaimPolicyError(
                f"cohort source workflow is not authorized for guard: {observation.guard_id}"
            )

    imported_at = _aware_utc(context.imported_at, "cohort import time")
    earliest = imported_at - timedelta(seconds=policy.maximum_window_seconds)
    records = [
        _record(
            item,
            batch_digest=batch.batch_digest,
            context=context,
            policy=policy,
            source_binding_id=source_binding.source_id,
            earliest=earliest,
        )
        for item in batch.observations
    ]
    for key, state, _ in records:
        existing = await store.read_state(key)
        if existing is not None and existing != state:
            raise CohortObservationConflictError(
                "cohort observation identity was reused with different content"
            )

    accepted = 0
    duplicates = 0
    for key, state, audit_entry in records:
        created = await store.write_state_with_audit_if_absent(
            key,
            state,
            audit_entry,
        )
        if created:
            accepted += 1
            continue
        existing = await store.read_state(key)
        if existing != state:
            raise CohortObservationConflictError(
                "cohort observation changed during concurrent import"
            )
        duplicates += 1

    report = CohortObservationImportReport(
        arm=context.arm,
        batch_digest=batch.batch_digest,
        accepted_count=accepted,
        duplicate_count=duplicates,
        metric_count=sum(
            isinstance(item, NormalizedCohortMetricObservation) for item in batch.observations
        ),
        guard_count=sum(
            isinstance(item, NormalizedCohortGuardObservation) for item in batch.observations
        ),
    )
    await _record_import_summary(
        report,
        context=context,
        policy=policy,
        store=store,
    )
    return report


def _record(
    observation: NormalizedCohortObservation,
    *,
    batch_digest: str,
    context: CohortObservationImportContext,
    policy: CohortClaimPolicy,
    source_binding_id: str,
    earliest: datetime,
) -> tuple[str, dict[str, object], dict[str, object]]:
    observed_at = observation.observed_at.astimezone(UTC)
    imported_at = context.imported_at.astimezone(UTC)
    if observed_at < earliest or observed_at > imported_at:
        raise ValueError("cohort observation falls outside the frozen import window")
    if isinstance(observation, NormalizedCohortMetricObservation):
        measure_id = observation.metric_id
        if measure_id not in policy.required_metric_ids:
            raise ValueError(f"cohort metric is not required by policy: {measure_id}")
        measure = {"metric_id": measure_id, "value": observation.value}
        action_kind = "measurement.cohort.metric.v1"
    else:
        measure_id = observation.guard_id
        if measure_id not in policy.required_guard_ids:
            raise ValueError(f"cohort guard is not required by policy: {measure_id}")
        measure = {
            "guard_id": measure_id,
            "observed_basis_points": observation.observed_basis_points,
            "breached": observation.breached,
        }
        action_kind = "measurement.cohort.guard.v1"
    identity = {
        "arm": context.arm.value,
        "fdai_revision": context.fdai_revision,
        "kind": observation.kind,
        "measure_id": measure_id,
        "measurement_protocol_digest": policy.measurement_protocol_digest,
        "source_binding_id": source_binding_id,
        "source_cluster_digest": observation.source_cluster_digest,
    }
    identity_digest = content_digest(identity)
    facts: dict[str, object] = {
        "schema_version": "1.0.0",
        "arm": context.arm.value,
        "fdai_revision": context.fdai_revision,
        "measurement_protocol_version": policy.measurement_protocol_version,
        "measurement_protocol_digest": policy.measurement_protocol_digest,
        "source_binding_id": source_binding_id,
        "source_workflow_path": context.source_workflow_path,
        "source_cluster_digest": observation.source_cluster_digest,
        "observed_at": observed_at.isoformat(),
        "synthetic": False,
        **measure,
    }
    observation_digest = content_digest(facts)
    key = f"measurement:cohort:observation:{identity_digest.removeprefix('sha256:')}"
    state = {
        "schema_version": "1.0.0",
        "observation_digest": observation_digest,
        "execution_authority": False,
        "claim_eligibility_authority": False,
    }
    audit_entry = {
        "actor": "fdai.measurement",
        "action_kind": action_kind,
        "mode": "shadow",
        "idempotency_key": key,
        "observation_digest": observation_digest,
        "import_provenance": {
            "batch_digest": batch_digest,
            "source_binding_id": source_binding_id,
            "source_workflow_path": context.source_workflow_path,
            "source_run_id": context.source_run_id,
            "source_run_attempt": context.source_run_attempt,
            "source_artifact_name": context.source_artifact_name,
        },
        "execution_authority": False,
        "claim_eligibility_authority": False,
        **facts,
    }
    return key, state, audit_entry


async def _record_import_summary(
    report: CohortObservationImportReport,
    *,
    context: CohortObservationImportContext,
    policy: CohortClaimPolicy,
    store: StateStore,
) -> None:
    identity = content_digest(
        {
            "arm": context.arm.value,
            "batch_digest": report.batch_digest,
            "fdai_revision": context.fdai_revision,
            "measurement_protocol_digest": policy.measurement_protocol_digest,
        }
    )
    key = f"measurement:cohort:import:{identity.removeprefix('sha256:')}"
    result = report.to_mapping()
    value = {
        "arm": report.arm.value,
        "batch_digest": report.batch_digest,
        "metric_count": report.metric_count,
        "guard_count": report.guard_count,
        "execution_authority": False,
        "claim_eligibility_authority": False,
    }
    created = await store.write_state_with_audit_if_absent(
        key,
        value,
        {
            "actor": "fdai.measurement",
            "action_kind": "measurement.cohort.import.v1",
            "mode": "shadow",
            "idempotency_key": key,
            "source_workflow_path": context.source_workflow_path,
            "source_run_id": context.source_run_id,
            "source_run_attempt": context.source_run_attempt,
            **result,
        },
    )
    if not created and await store.read_state(key) != value:
        raise CohortObservationConflictError(
            "cohort import summary identity was reused with different content"
        )


def _observation_key(
    observation: NormalizedCohortObservation,
) -> tuple[str, str, str]:
    measure_id = (
        observation.metric_id
        if isinstance(observation, NormalizedCohortMetricObservation)
        else observation.guard_id
    )
    return observation.kind, measure_id, observation.source_cluster_digest


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST include a timezone")
    return value.astimezone(UTC)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"cohort observation batch repeats JSON key: {key}")
        result[key] = value
    return result


__all__ = [
    "MAX_COHORT_OBSERVATION_BATCH_BYTES",
    "CohortObservationBatch",
    "CohortObservationConflictError",
    "CohortObservationImportContext",
    "CohortObservationImportReport",
    "NormalizedCohortGuardObservation",
    "NormalizedCohortMetricObservation",
    "cohort_observation_batch_digest",
    "import_cohort_observation_batch",
    "load_cohort_observation_batch",
]

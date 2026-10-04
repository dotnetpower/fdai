"""Shadow-only segmentation registration and independent probe evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from fdai_service_contracts.cluster_connector import (
    ConnectorContract,
    Digest,
    Namespace,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest
from pydantic import Field, field_validator, model_validator

from fdai.shared.providers.state_store import StateStore

SEGMENTATION_PREFIX = "kubernetes-connector:segmentation-shadow:v1:"


class SegmentationRegistrationError(ValueError):
    """Reject segmentation state that could be mistaken for an executable capability."""


class ShadowSegmentationRegistration(ConnectorContract):
    """Local registration for analysis-only segmentation readiness evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    target_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    namespace: Namespace
    capability_ref: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    mode: Literal["shadow"] = "shadow"
    registered_at: datetime
    expires_at: datetime
    recovery_digest: Digest
    management_dependency_digests: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=8)]
    execution_authority: Literal[False] = False

    @field_validator("registered_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("shadow segmentation cannot grant execution authority")
        return value

    @model_validator(mode="after")
    def _window(self) -> Self:
        if not timedelta(0) < self.expires_at - self.registered_at <= timedelta(hours=1):
            raise ValueError("shadow segmentation registration must be short lived")
        if (
            tuple(sorted(set(self.management_dependency_digests)))
            != self.management_dependency_digests
        ):
            raise ValueError("management dependency digests must be sorted and unique")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class SegmentationProbe(ConnectorContract):
    """One independent connectivity observation for a proposed policy boundary."""

    target_ref: str
    namespace: Namespace
    probe_ref: str
    observer_ref: str
    kind: Literal["positive", "negative"]
    observed: Literal["connected", "blocked", "unknown"]
    observed_at: datetime
    expires_at: datetime
    evidence_digest: Digest | None = None

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(minutes=15):
            raise ValueError("segmentation probes must be short lived")
        if self.observed != "unknown" and self.evidence_digest is None:
            raise ValueError("segmentation probe conclusions require evidence")
        return self


@dataclass(frozen=True, slots=True)
class SegmentationProbeAssessment:
    status: Literal["ready_for_review", "needs_evidence", "blocked"]
    reason: str
    registration_digest: str
    execution_authority: Literal[False] = False


async def register_shadow_segmentation(
    store: StateStore,
    registration: ShadowSegmentationRegistration,
    *,
    now: Callable[[], datetime],
) -> bool:
    """Persist a shadow registration and audited recovery dependency, never an action."""
    registration = ShadowSegmentationRegistration.model_validate_json(
        registration.model_dump_json()
    )
    current = connector_time(now())
    if not registration.registered_at <= current < registration.expires_at:
        raise SegmentationRegistrationError("shadow segmentation registration is not current")
    key = SEGMENTATION_PREFIX + canonical_digest(
        {"target_ref": registration.target_ref, "namespace": registration.namespace}
    )
    value = {
        "revision": 1,
        "registration": registration.model_dump(mode="json"),
        "registration_digest": registration.digest,
    }
    previous = await store.read_state(key)
    if previous is not None:
        old = _decode(previous)
        if old == registration:
            return False
        raise SegmentationRegistrationError("shadow segmentation registration changed")
    return await store.write_state_with_audit_if_absent(
        key,
        value,
        {
            "kind": "kubernetes.segmentation.shadow.registered",
            "correlation_id": registration.digest,
            "target_ref": registration.target_ref,
            "namespace": registration.namespace,
            "mode": "shadow",
            "execution_authority": False,
            "recovery_digest": registration.recovery_digest,
        },
    )


def assess_segmentation_probes(
    registration: ShadowSegmentationRegistration,
    probes: tuple[SegmentationProbe, ...],
    *,
    now: datetime,
) -> SegmentationProbeAssessment:
    """Require independent current positive and negative probes before review readiness."""
    registration = ShadowSegmentationRegistration.model_validate_json(
        registration.model_dump_json()
    )
    current = connector_time(now)
    if not registration.registered_at <= current < registration.expires_at:
        return SegmentationProbeAssessment(
            "needs_evidence", "registration_expired", registration.digest
        )
    if len(probes) > 16:
        return SegmentationProbeAssessment(
            "needs_evidence", "probe_bound_exceeded", registration.digest
        )
    outcomes: dict[str, bool] = {}
    observers: set[str] = set()
    for raw_probe in probes:
        try:
            probe = SegmentationProbe.model_validate_json(raw_probe.model_dump_json())
        except ValueError:
            return SegmentationProbeAssessment(
                "needs_evidence", "invalid_probe", registration.digest
            )
        if (
            probe.target_ref != registration.target_ref
            or probe.namespace != registration.namespace
            or not probe.observed_at <= current < probe.expires_at
            or probe.observed == "unknown"
        ):
            return SegmentationProbeAssessment(
                "needs_evidence", "probe_evidence_unavailable", registration.digest
            )
        observers.add(probe.observer_ref)
        expected = "connected" if probe.kind == "positive" else "blocked"
        outcomes[probe.kind] = probe.observed == expected
    if len(observers) < 2:
        return SegmentationProbeAssessment(
            "needs_evidence", "independent_probe_evidence_missing", registration.digest
        )
    if not outcomes.get("positive") or not outcomes.get("negative"):
        return SegmentationProbeAssessment(
            "blocked", "probe_expectation_failed", registration.digest
        )
    return SegmentationProbeAssessment(
        "ready_for_review", "shadow_probes_passed", registration.digest
    )


def _decode(value: Mapping[str, object]) -> ShadowSegmentationRegistration:
    if set(value) != {"revision", "registration", "registration_digest"}:
        raise SegmentationRegistrationError("shadow segmentation checkpoint is invalid")
    registration = ShadowSegmentationRegistration.model_validate(value["registration"])
    if (
        value["revision"] != 1
        or value["registration_digest"] != registration.digest
        or registration.execution_authority is not False
        or registration.mode != "shadow"
    ):
        raise SegmentationRegistrationError("shadow segmentation checkpoint failed integrity")
    return registration

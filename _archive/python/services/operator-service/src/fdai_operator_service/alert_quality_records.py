"""Exact private alert-quality records, bindings and codecs; none grants authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Annotated, Protocol, Self

from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.executor_models import ContractBase, Digest
from pydantic import Field, model_validator

ALERT_QUALITY_PREFIX = "operator-alert-quality:"
MAX_ALERT_QUALITY_BYTES = 1_048_576
MAX_ALERT_QUALITY_PLANS = 32
_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


class AlertQualityUnavailableError(RuntimeError):
    """The owned source is absent, malformed, or cannot establish an exact snapshot."""


class AlertQualityConflictError(RuntimeError):
    """An immutable identity was reused for different content or an ambiguous cutoff."""


class AlertQualityStaleError(AlertQualityConflictError):
    """An older result or a plan for superseded evidence cannot advance the projection."""


class AlertQualityStateStore(Protocol):
    """Operator-owned durable primitives; create MUST be atomic insert-if-absent.

    Production binds PostgresFamilyStore using the Operator DSN and role. No Core
    state store, process-local fallback, or unconditional replacement is supported.
    """

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool: ...

    async def find_state(
        self, *, prefix: str, field: str, value: str
    ) -> dict[str, object] | None: ...


class AlertQualitySnapshot(ContractBase):
    """Private principal binding plus an immutable, internally consistent read model."""

    binding_digest: Digest
    assessment: NoiseAssessment
    plans: Annotated[tuple[AlertChangePlan, ...], Field(max_length=MAX_ALERT_QUALITY_PLANS)] = ()

    @model_validator(mode="after")
    def consistent_evidence(self) -> Self:
        report = self.assessment
        if report.observed_at >= report.valid_until:
            raise ValueError("alert quality report validity MUST be positive")
        if report.coverage != "complete" and not report.reasons:
            raise ValueError("incomplete alert quality reports MUST retain their reasons")
        if len(set(report.reasons)) != len(report.reasons):
            raise ValueError("alert quality report reasons MUST be unique")
        if len({digest_record(plan) for plan in self.plans}) != len(self.plans):
            raise ValueError("alert quality plans MUST be unique")
        for plan in self.plans:
            if (
                plan.scope_ref != report.scope_ref
                or plan.tenant_ref != report.tenant_ref
                or plan.evidence_digest != report.evidence_digest
                or plan.policy_digest != report.policy_digest
                or plan.created_at < report.observed_at
            ):
                raise ValueError("alert quality plan MUST bind the exact assessment")
        return self


class AlertQualitySource(Protocol):
    """Read one authenticated principal/scope snapshot, never an unscoped fallback."""

    async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot | None: ...


class _PlanRecord(ContractBase):
    """Bind an inert plan to its private principal/scope namespace."""

    binding_digest: Digest
    plan: AlertChangePlan


class _AssessmentRecord(ContractBase):
    """Retain the exact report and content digest in its private namespace."""

    binding_digest: Digest
    assessment_digest: Digest
    assessment: NoiseAssessment


def validate_alert_quality_scope(scope_ref: str) -> None:
    """Require an exact opaque scope token, without stripping or URL interpretation."""
    if not isinstance(scope_ref, str) or _REF.fullmatch(scope_ref) is None:
        raise ValueError("invalid alert quality scope")


def validate_alert_quality_principal(principal_id: str) -> None:
    """Allow the verified subject internally, including an original Entra subject."""
    if (
        not isinstance(principal_id, str)
        or not 1 <= len(principal_id) <= 256
        or principal_id != principal_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in principal_id)
    ):
        raise ValueError("invalid alert quality principal binding")


def alert_quality_binding_digest(principal_id: str, scope_ref: str) -> str:
    """Domain-separate private record keys by exact authenticated subject and scope."""
    validate_alert_quality_principal(principal_id)
    validate_alert_quality_scope(scope_ref)
    raw = json.dumps(["operator-alert-quality-v1", principal_id, scope_ref], separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def alert_quality_requester_ref(principal_id: str, scope_ref: str) -> str:
    """Return the opaque requester binding the trusted producer MUST put in plans."""
    return "principal:" + alert_quality_binding_digest(principal_id, scope_ref)[7:]


def _canonical(value: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > MAX_ALERT_QUALITY_BYTES:
            raise ValueError("projection exceeds its byte bound")
        return encoded
    except (TypeError, ValueError, RecursionError) as exc:
        raise AlertQualityUnavailableError("alert quality projection is unavailable") from exc


def _decode[T: ContractBase](model: type[T], value: Mapping[str, object]) -> T:
    """Check stored JSON without accepting coercion, missing defaults, or authority drift."""
    raw = _canonical(value)
    try:
        decoded = model.model_validate_json(raw, strict=True)
    except ValueError as exc:
        raise AlertQualityUnavailableError("alert quality projection is unavailable") from exc
    if _canonical(decoded.model_dump(mode="json")) != raw:
        raise AlertQualityUnavailableError("alert quality projection roundtrip failed")
    return decoded


def _contains_identity(value: object, principal_id: str) -> bool:
    if isinstance(value, str):
        return principal_id.casefold() in value.casefold()
    if isinstance(value, dict):
        return any(_contains_identity(item, principal_id) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_identity(item, principal_id) for item in value)
    return False


def verify_alert_quality_snapshot(
    snapshot: AlertQualitySnapshot, *, principal_id: str, scope_ref: str
) -> AlertQualitySnapshot:
    """Revalidate exact content and reject scope mismatches or identity disclosure.

    Producers must pseudonymize other subjects and provider references. No address,
    directory membership, or observation body is projected.
    """
    binding = alert_quality_binding_digest(principal_id, scope_ref)
    checked = _decode(AlertQualitySnapshot, snapshot.model_dump(mode="json"))
    if checked.binding_digest != binding or checked.assessment.scope_ref != scope_ref:
        raise AlertQualityUnavailableError("alert quality projection binding is invalid")
    for plan in checked.plans:
        if plan.requester_ref != alert_quality_requester_ref(principal_id, scope_ref):
            raise AlertQualityUnavailableError("alert quality plan binding is invalid")
    public = {
        "assessment": checked.assessment.model_dump(mode="json"),
        "plans": [plan.model_dump(mode="json") for plan in checked.plans],
    }
    if _contains_identity(public, principal_id):
        raise AlertQualityUnavailableError("alert quality projection disclosure is invalid")
    return checked


def _artifact_key(binding: str, kind: str, digest: str) -> str:
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("invalid alert quality artifact digest")
    return f"{ALERT_QUALITY_PREFIX}{binding[7:]}:{kind}:{digest[7:]}"

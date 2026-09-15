"""Versioned alert-quality ingress and projection envelopes; authority is always absent."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from fdai_service_contracts.alert_noise import NoiseAssessment, Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase as ContractBase
from fdai_service_contracts.alert_noise_base import AlertTime as AwareDatetime
from fdai_service_contracts.alert_noise_base import FalseOnly
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertTreatment
from fdai_service_contracts.alert_noise_projection import AlertProposalDetail
from fdai_service_contracts.executor_models import Digest

ALERT_NOISE_RESULT_TOPIC = "fdai.alert-noise.results"
ALERT_NOISE_EVENT_TYPES = frozenset({"alert_noise.assess", "alert_noise.propose"})


def sign_alert_record(record: ContractBase, key: bytes) -> str:
    """Authenticate canonical record bytes under a deployment-owned service key."""
    if len(key) < 32:
        raise ValueError("alert transport key MUST contain at least 32 bytes")
    return "sha256:" + hmac.new(key, record.model_dump_json().encode(), hashlib.sha256).hexdigest()


def verify_alert_record(record: ContractBase, signature: str, key: bytes) -> None:
    """Reject forged transport data before admitting principal or evidence claims."""
    if not hmac.compare_digest(sign_alert_record(record, key), signature):
        raise ValueError("alert transport authentication failed")


class AlertNoiseCommand(ContractBase):
    """A principal-bound request with no supplied facts, approvals or provider endpoints."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: Literal["alert_noise.assess", "alert_noise.propose"]
    request_ref: Ref
    requester_ref: Ref
    scope_ref: Ref
    requested_at: AwareDatetime
    expires_at: AwareDatetime
    evidence_digest: Digest | None = None
    treatment: AlertTreatment | None = None
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def shape(self) -> Self:
        if not 0 < (self.expires_at - self.requested_at).total_seconds() <= 300:
            raise ValueError("alert request MUST have a bounded positive deadline")
        if (self.operation == "alert_noise.propose") != (
            self.evidence_digest is not None and self.treatment is not None
        ):
            raise ValueError("alert proposal MUST bind evidence and one treatment")
        if self.operation == "alert_noise.assess" and (self.evidence_digest or self.treatment):
            raise ValueError("assessment MUST NOT include proposal data")
        return self


class AlertNoiseResult(ContractBase):
    """Exact command result consumed only by the matching Operator durable request."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    producer: Literal["Forseti"] = "Forseti"
    command: AlertNoiseCommand
    command_digest: Digest
    recorded_at: AwareDatetime
    status: Literal["assessment_ready", "proposal_ready", "held"]
    reason: Ref | None = None
    assessment: NoiseAssessment | None = None
    plan: AlertChangePlan | None = None
    detail: AlertProposalDetail | None = None
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def bindings(self) -> Self:
        if self.command_digest != digest_record(self.command):
            raise ValueError("alert result command commitment mismatch")
        if self.recorded_at < self.command.requested_at:
            raise ValueError("alert result predates its request")
        if self.status == "held":
            if self.reason is None or self.plan is not None:
                raise ValueError("held alert result MUST explain why and contain no plan")
        elif self.reason is not None or self.assessment is None:
            raise ValueError("ready alert result MUST contain observed evidence")
        if (self.status == "proposal_ready") != (self.plan is not None):
            raise ValueError("only proposal results may contain a plan")
        if self.assessment is not None and self.assessment.scope_ref != self.command.scope_ref:
            raise ValueError("alert result scope mismatch")
        if self.plan is not None and (
            self.plan.requester_ref != self.command.requester_ref
            or self.plan.scope_ref != self.command.scope_ref
            or self.plan.evidence_digest != self.command.evidence_digest
            or self.plan.treatment != self.command.treatment
            or self.assessment is None
            or self.plan.evidence_digest != self.assessment.evidence_digest
        ):
            raise ValueError("alert plan result MUST match its exact request")
        if self.detail is not None:
            if self.plan is None or self.detail.recorded_at > self.recorded_at:
                raise ValueError("alert proposal details require a preceding retained plan")
            self.detail.require_plan(self.plan)
        return self


class SignedAlertCommand(ContractBase):
    """Only the authenticated Operator outbox signs a principal-bound command."""

    command: AlertNoiseCommand
    signature: Digest


def validate_alert_ingress(raw: Mapping[str, object], key: bytes) -> SignedAlertCommand:
    """Authenticate the signed request AND its routing envelope before deduplication."""
    if len(json.dumps(dict(raw), allow_nan=False).encode()) > 16_384:
        raise ValueError("alert ingress exceeds its bound")
    payload = raw.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"alert_noise"}:
        raise ValueError("alert ingress payload is not canonical")
    signed = SignedAlertCommand.model_validate(payload["alert_noise"])
    command = signed.command
    verify_alert_record(command, signed.signature, key)
    if (
        raw.get("schema_version") != "1.0.0"
        or raw.get("mode") != "shadow"
        or raw.get("incident_correlation") != "none"
        or raw.get("source") != "operator-alert-noise"
        or raw.get("event_type") != command.operation
        or raw.get("event_id") != str(uuid5(NAMESPACE_URL, command.request_ref))
        or raw.get("idempotency_key") != command.request_ref
        or raw.get("correlation_id") != command.request_ref
        or raw.get("resource_ref") != command.scope_ref
    ):
        raise ValueError("alert ingress routing differs from its signed command")
    return signed


class SignedAlertResult(ContractBase):
    """A signed no-authority result, independently matched to the original request."""

    result: AlertNoiseResult
    signature: Digest


class AlertNoiseReadiness(ContractBase):
    """Short-lived signed producer binding state; not provider/effect health evidence."""

    kind: Literal["alert-noise.readiness"] = "alert-noise.readiness"
    scope_refs: Annotated[tuple[Ref, ...], Field(max_length=64)]
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    execution_authority: FalseOnly = False

    @model_validator(mode="after")
    def lifetime(self) -> Self:
        if not 0 < (self.valid_until - self.generated_at).total_seconds() <= 120:
            raise ValueError("alert readiness lifetime MUST be at most 120 seconds")
        if self.scope_refs != tuple(sorted(set(self.scope_refs))):
            raise ValueError("alert readiness scopes MUST be sorted and unique")
        return self


class SignedAlertReadiness(ContractBase):
    """A signed short-lived producer announcement on the no-authority projection lane."""

    readiness: AlertNoiseReadiness
    signature: Digest


__all__ = [
    "ALERT_NOISE_EVENT_TYPES",
    "ALERT_NOISE_RESULT_TOPIC",
    "AlertNoiseCommand",
    "AlertNoiseReadiness",
    "AlertNoiseResult",
    "SignedAlertCommand",
    "SignedAlertReadiness",
    "SignedAlertResult",
    "sign_alert_record",
    "validate_alert_ingress",
    "verify_alert_record",
]

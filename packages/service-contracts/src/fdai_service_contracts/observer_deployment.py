"""Evidence-bound observer deployment recommendations without installation authority."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.cluster_connector import ConnectorContract, Digest, connector_time
from fdai_service_contracts.compatibility import canonical_digest

InstallMethod = Literal["gitops", "existing_host", "managed_host", "run_command"]
ConstraintName = Literal[
    "azure_policy",
    "kubernetes_read",
    "admission",
    "capacity",
    "artifact_verified",
    "persistent_storage",
    "mtls_gateway",
    "ownership_known",
    "public_egress",
    "private_egress",
    "gitops_authorized",
    "existing_host_authorized",
    "managed_host_authorized",
    "run_command_authorized",
    "managed_host_budget",
    "managed_host_plan_feasible",
]
TargetRef = Annotated[
    str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
]
ConstraintBlocker = (
    ConstraintName
    | Literal[
        "existing_owner_preserved",
        "operator_method_pinned",
        "run_command_requires_explicit_selection",
    ]
)


class ObserverDeploymentFact(ConnectorContract):
    """One target-bound preflight result; unknown never satisfies a deployment prerequisite."""

    target_ref: TargetRef
    name: ConstraintName
    state: Literal["allowed", "denied", "unknown"]
    source: Literal[
        "azure_management",
        "kubernetes_api",
        "deployment_profile",
        "network_probe",
        "operator_review",
    ]
    evidence_digest: Digest | None = None
    observed_at: datetime
    expires_at: datetime

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _window(self) -> Self:
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(hours=1):
            raise ValueError("observer constraint evidence must expire within one hour")
        if self.state != "unknown" and self.evidence_digest is None:
            raise ValueError("observer constraint conclusion requires evidence")
        return self


class ObserverDeploymentContext(ConnectorContract):
    """Input assembled by authenticated read adapters, never a permission grant."""

    target_ref: TargetRef
    discovery_digest: Digest
    observed_at: datetime
    expires_at: datetime
    private_cluster: Annotated[bool, Field(strict=True)]
    facts: Annotated[tuple[ObserverDeploymentFact, ...], Field(max_length=16)] = ()
    existing_method: InstallMethod | None = None
    requested_method: InstallMethod | None = None

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(hours=1):
            raise ValueError("observer deployment context has an invalid freshness window")
        names = [fact.name for fact in self.facts]
        if len(set(names)) != len(names) or any(
            fact.target_ref != self.target_ref for fact in self.facts
        ):
            raise ValueError("observer constraint facts must be unique and target-bound")
        return self


class ObserverDeploymentCandidate(ConnectorContract):
    """A supported snapshot profile evaluated against named evidence requirements."""

    method: InstallMethod
    egress: Literal["private", "public"]
    profile: Literal["observer.snapshot.mtls-pvc.v1"] = "observer.snapshot.mtls-pvc.v1"
    state: Literal["eligible", "blocked", "unknown"]
    blockers: Annotated[tuple[ConstraintBlocker, ...], Field(max_length=19)]
    missing: Annotated[tuple[ConstraintName, ...], Field(max_length=16)]

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        if (
            tuple(sorted(set(self.blockers))) != self.blockers
            or tuple(sorted(set(self.missing))) != self.missing
        ):
            raise ValueError("observer candidate reasons must be sorted and unique")
        if set(self.blockers) & set(self.missing):
            raise ValueError(
                "observer candidate cannot have denied and unknown evidence for one constraint"
            )
        expected = "blocked" if self.blockers else "unknown" if self.missing else "eligible"
        if self.state != expected:
            raise ValueError("observer candidate state does not match its evidence")
        return self


class ObserverDeploymentProposal(ConnectorContract):
    """Read-only recommendation; acceptance, approval and execution are separate contracts."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    proposal_digest: Digest
    target_ref: TargetRef
    context_digest: Digest
    evaluated_at: datetime
    expires_at: datetime
    status: Literal["ready_for_review", "needs_evidence", "blocked", "not_applicable"]
    candidates: Annotated[tuple[ObserverDeploymentCandidate, ...], Field(max_length=8)]
    recommended: ObserverDeploymentCandidate | None
    approval_required: Literal[True] = True
    execution_authority: Literal[False] = False

    @field_validator("approval_required", "execution_authority", mode="before")
    @classmethod
    def _authority(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("observer proposal authority fields must be boolean")
        return value

    @field_validator("evaluated_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if not timedelta(0) < self.expires_at - self.evaluated_at <= timedelta(hours=1):
            raise ValueError("observer proposal must have a current validity interval")
        identities = [(candidate.method, candidate.egress) for candidate in self.candidates]
        if len(set(identities)) != len(identities):
            raise ValueError("observer proposal contains duplicate candidates")
        if self.status == "not_applicable":
            if self.candidates:
                raise ValueError("non-private observer proposal must not contain candidates")
        else:
            if len(self.candidates) != 8:
                raise ValueError("observer proposal must evaluate every supported combination")
            expected = (
                "ready_for_review"
                if any(item.state == "eligible" for item in self.candidates)
                else "needs_evidence"
                if any(item.state == "unknown" for item in self.candidates)
                else "blocked"
            )
            if self.status != expected:
                raise ValueError("observer proposal status does not match its candidates")
        if (self.recommended is not None) != (self.status == "ready_for_review"):
            raise ValueError("observer recommendation must match proposal status")
        if self.recommended is not None and (
            self.recommended.state != "eligible" or self.recommended not in self.candidates
        ):
            raise ValueError("observer recommendation must be an eligible candidate")
        if self.proposal_digest != canonical_digest(
            self.model_dump(mode="json", exclude={"proposal_digest"})
        ):
            raise ValueError("observer proposal digest does not match its content")
        return self

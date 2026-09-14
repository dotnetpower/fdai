"""Async injected alert-quality sources; reads, authority and dispatch stay distinct."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.alert_noise import AlertEvidence, Audience, NoiseAssessment
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
    AlertEffectObservation,
)


class AlertEvidenceSource(Protocol):
    """Collect a server-bound scope using a reader identity, never caller endpoints."""

    async def collect(self, *, now: datetime) -> AlertEvidence: ...


class AlertAudienceResolver(Protocol):
    """Resolve only authorized private bindings to purpose-scoped pseudonyms."""

    async def resolve(self, *, binding_ref: str, kind: str, private_value: str) -> Audience: ...


class AlertAuthorityReader(Protocol):
    """Read current Var approvals and risk/safeguard admission, not user assertions."""

    async def approvals(self, plan: AlertChangePlan) -> tuple[AlertApproval, ...]: ...

    async def dispatch_evidence(self, plan: AlertChangePlan) -> AlertDispatchEvidence: ...


class AlertGovernedDispatcher(Protocol):
    """Submit one registered action to the existing Thor path; never apply from a report."""

    async def submit(self, plan: AlertChangePlan, *, idempotency_key: str) -> str: ...


class AlertEffectReader(Protocol):
    """Read independently authenticated observed effects outside executor credentials."""

    async def observe(
        self, plan: AlertChangePlan, *, dispatch_ref: str
    ) -> AlertEffectObservation | None: ...


class AlertAssessmentPublisher(Protocol):
    """Publish the immutable principal-scoped read model through a typed outbox."""

    async def publish(self, assessment: NoiseAssessment, *, principal_ref: str) -> None: ...


class AlertPlanPublisher(Protocol):
    """Retain a review-only exact IaC plan without approval or merge authority."""

    async def publish(self, plan: AlertChangePlan, *, changes: Mapping[str, object]) -> str: ...


class AlertPlanArtifacts(Protocol):
    """Prepare the exact private IaC candidate, without approval or external publication."""

    async def prepare(self, *, plan: AlertChangePlan, evidence: AlertEvidence) -> None: ...

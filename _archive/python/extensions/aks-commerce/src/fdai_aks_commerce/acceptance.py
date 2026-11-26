"""Receipt-gated order-acceptance detection without fulfillment or execution claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Literal, Protocol

from fdai.core.investigation import AnalyzerFinding, FindingAssessment
from fdai.shared.contracts.models import Severity


@dataclass(frozen=True, slots=True)
class OrderAcceptanceIntent:
    """Reviewed, expiring target and service floor; not an execution authorization."""

    policy_ref: str
    resource_ref: str
    service_resource_ref: str
    cluster_ref: str
    namespace: str
    deployment_name: str
    deployment_uid: str
    valid_from: datetime
    valid_until: datetime
    minimum_replicas: int = 1
    failure_threshold: int = 2
    max_age_seconds: int = 30

    def __post_init__(self) -> None:
        for value in (
            self.policy_ref,
            self.resource_ref,
            self.service_resource_ref,
            self.cluster_ref,
            self.namespace,
            self.deployment_name,
            self.deployment_uid,
        ):
            if not value or len(value) > 512 or value != value.strip():
                raise ValueError("order-acceptance intent requires bounded exact references")
        if not _aware(self.valid_from) or not _aware(self.valid_until):
            raise ValueError("order-acceptance intent requires timezone-aware bounds")
        if not timedelta(0) < self.valid_until - self.valid_from <= timedelta(hours=2):
            raise ValueError("order-acceptance intent duration must be within two hours")
        for threshold, lower, upper in (
            (self.minimum_replicas, 1, 10),
            (self.failure_threshold, 2, 10),
            (self.max_age_seconds, 1, 300),
        ):
            if type(threshold) is not int or not lower <= threshold <= upper:
                raise ValueError("order-acceptance intent threshold is outside its bounds")
        for name in (self.namespace, self.deployment_name):
            if re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", name) is None:
                raise ValueError("order-acceptance target requires exact DNS labels")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", self.deployment_uid) is None:
            raise ValueError("order-acceptance target requires an immutable Deployment UID")


@dataclass(frozen=True, slots=True)
class OrderAcceptanceProbe:
    """Payload-free completed acceptance observation; unknown is never a failed order."""

    evidence_ref: str
    observed_at: datetime
    accepted: bool | None
    authorization_ref: str
    synthetic_traffic: bool = True


@dataclass(frozen=True, slots=True)
class OrderAcceptanceEvidence:
    """Source-normalized observations whose trust requires an independent receipt verifier."""

    resource_ref: str
    service_resource_ref: str
    cluster_ref: str
    namespace: str
    deployment_name: str
    deployment_uid: str
    resource_version: str
    observed_at: datetime
    desired_replicas: int | None
    ready_replicas: int | None
    ready_endpoints: int | None
    probes: tuple[OrderAcceptanceProbe, ...]
    kubernetes_evidence_ref: str
    verification_ref: str
    complete: bool
    maintenance_active: bool | None = None
    hpa_managed: bool | None = None
    competing_writer: bool | None = None
    sample: bool = True


@dataclass(frozen=True, slots=True)
class OrderAcceptanceScaleProposal:
    """Inert exact-target scale candidate; shared policy and Thor admission remain required."""

    intent: OrderAcceptanceIntent
    resource_version: str

    @property
    def action_type(self) -> Literal["ops.scale-out"]:
        return "ops.scale-out"

    @property
    def execution_authority(self) -> Literal[False]:
        return False

    @property
    def arguments(self) -> Mapping[str, object]:
        """Return scale arguments without approval, promotion, or execution authority."""
        return MappingProxyType(
            {
                "target_resource_ref": self.intent.resource_ref,
                "target_platform": "kubernetes",
                "target_kind": "Deployment",
                "cluster_ref": self.intent.cluster_ref,
                "namespace": self.intent.namespace,
                "resource_name": self.intent.deployment_name,
                "target_uid": self.intent.deployment_uid,
                "resource_version": self.resource_version,
                "replica_count": self.intent.minimum_replicas,
                "reason": "Restore the reviewed order-acceptance replica floor.",
            }
        )


@dataclass(frozen=True, slots=True)
class OrderAcceptanceAssessment:
    """Acceptance-only classification, immutable evidence identity, and optional inert candidate."""

    status: Literal["held", "accepting", "unavailable"]
    evidence_digest: str
    evidence_refs: tuple[str, ...]
    observed_at: datetime
    evidence_gaps: tuple[str, ...] = ()
    proposal: OrderAcceptanceScaleProposal | None = None


class OrderAcceptanceSource(Protocol):
    """Read bounded source observations; normalization alone does not authenticate them."""

    async def observe(self, intent: OrderAcceptanceIntent) -> OrderAcceptanceEvidence | None: ...


class OrderAcceptanceReceiptVerifier(Protocol):
    """Authenticate a retained receipt binding the exact intent, observations, and probe authority.

    The deployment-owned adapter must validate source identity, authorization, expiry, and the
    supplied digest independently of payload claims. No permissive implementation is provided.
    """

    async def verify(self, *, verification_ref: str, evidence_digest: str) -> bool: ...


def evaluate_order_acceptance(
    intent: OrderAcceptanceIntent,
    evidence: OrderAcceptanceEvidence,
    *,
    now: datetime,
    window_seconds: float,
) -> OrderAcceptanceAssessment:
    """Reduce qualified facts only; the caller must authenticate the resulting digest separately."""
    if not _aware(now) or not 1 <= window_seconds <= 86400:
        raise ValueError("order-acceptance evaluation requires a current bounded window")
    if len(evidence.probes) > 10:
        raise ValueError("order-acceptance observations exceed the probe bound")
    canonical = {"intent": asdict(intent), "evidence": asdict(evidence)}
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                canonical, default=_timestamp, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    refs = (
        intent.policy_ref,
        evidence.kubernetes_evidence_ref,
        *(probe.evidence_ref for probe in evidence.probes),
    )

    def held(reason: str) -> OrderAcceptanceAssessment:
        return OrderAcceptanceAssessment("held", digest, refs, evidence.observed_at, (reason,))

    if not intent.valid_from <= now < intent.valid_until:
        return held("intent_not_current")
    for field_name in (
        "resource_ref",
        "service_resource_ref",
        "cluster_ref",
        "namespace",
        "deployment_name",
        "deployment_uid",
    ):
        if getattr(intent, field_name) != getattr(evidence, field_name):
            return held("target_mismatch")
    if evidence.complete is not True or evidence.sample is not False:
        return held("evidence_not_qualified")
    counts = (evidence.desired_replicas, evidence.ready_replicas, evidence.ready_endpoints)
    if any(type(value) is not int or value < 0 for value in counts if value is not None) or any(
        value is None for value in counts
    ):
        return held("resource_state_unknown")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", evidence.resource_version):
        return held("resource_version_unknown")
    if not intent.failure_threshold <= len(evidence.probes) <= 10:
        return held("insufficient_probes")
    if any(
        not reference or len(reference) > 512 for reference in (*refs, evidence.verification_ref)
    ):
        return held("evidence_reference_invalid")
    if len(set(refs)) != len(refs):
        return held("duplicate_evidence")
    cutoff = max(
        intent.valid_from, now - timedelta(seconds=min(window_seconds, intent.max_age_seconds))
    )
    times = (evidence.observed_at, *(probe.observed_at for probe in evidence.probes))
    if any(not _aware(value) or not cutoff <= value <= now for value in times):
        return held("observation_not_current")
    if any(
        current.observed_at <= previous.observed_at
        for previous, current in zip(evidence.probes[:-1], evidence.probes[1:], strict=True)
    ):
        return held("probe_order_conflict")
    if any(
        type(probe.accepted) is not bool
        or type(probe.synthetic_traffic) is not bool
        or not probe.authorization_ref
        or len(probe.authorization_ref) > 512
        for probe in evidence.probes
    ):
        return held("probe_result_unknown")
    selected = evidence.probes[-intent.failure_threshold :]
    if all(probe.accepted is False for probe in selected) and counts == (0, 0, 0):
        candidate = None
        if all(
            value is False
            for value in (
                evidence.maintenance_active,
                evidence.hpa_managed,
                evidence.competing_writer,
            )
        ):
            candidate = OrderAcceptanceScaleProposal(intent, evidence.resource_version)
        return OrderAcceptanceAssessment(
            "unavailable", digest, refs, selected[-1].observed_at, proposal=candidate
        )
    if (
        all(probe.accepted is True for probe in selected)
        and evidence.desired_replicas is not None
        and evidence.ready_replicas is not None
        and evidence.ready_endpoints is not None
        and evidence.desired_replicas >= intent.minimum_replicas
        and evidence.ready_replicas >= intent.minimum_replicas
        and evidence.ready_endpoints > 0
    ):
        return OrderAcceptanceAssessment("accepting", digest, refs, max(times))
    return held("acceptance_not_proven")


class OrderAcceptanceAnalyzer:
    """Publish no-authority acceptance findings only after independent receipt verification."""

    def __init__(
        self,
        *,
        intent: OrderAcceptanceIntent,
        source: OrderAcceptanceSource,
        verifier: OrderAcceptanceReceiptVerifier,
        resource_kind: str,
        severity: Severity,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not resource_kind or len(resource_kind) > 128 or not isinstance(severity, Severity):
            raise ValueError(
                "order-acceptance analyzer requires a typed severity and resource kind"
            )
        self.resource_kind = resource_kind
        self._intent = intent
        self._source = source
        self._verifier = verifier
        self._severity = severity
        self._clock = clock or (lambda: datetime.now(UTC))

    async def assess(
        self, *, resource_ref: str, window_seconds: float
    ) -> OrderAcceptanceAssessment:
        """Collect and authenticate one result within a five-second source/verification budget."""
        if resource_ref != self._intent.resource_ref:
            raise ValueError("order-acceptance target is not configured")
        async with asyncio.timeout(5):
            evidence = await self._source.observe(self._intent)
            if evidence is None:
                raise ValueError("order-acceptance observation is unavailable")
            assessment = evaluate_order_acceptance(
                self._intent,
                evidence,
                now=self._clock(),
                window_seconds=window_seconds,
            )
            if assessment.status == "held":
                return assessment
            verified = await self._verifier.verify(
                verification_ref=evidence.verification_ref,
                evidence_digest=assessment.evidence_digest,
            )
            if verified is not True:
                raise ValueError("order-acceptance receipt is not verified")
            return evaluate_order_acceptance(
                self._intent,
                evidence,
                now=self._clock(),
                window_seconds=window_seconds,
            )

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> tuple[AnalyzerFinding, ...]:
        """Adapt authenticated failure to shared ingress without dispatching a candidate."""
        assessment = await self.assess(resource_ref=resource_ref, window_seconds=window_seconds)
        if assessment.status == "held":
            raise ValueError("order-acceptance observation is not qualified")
        if assessment.status == "accepting":
            return ()
        return (
            AnalyzerFinding(
                resource_ref=resource_ref,
                resource_kind=self.resource_kind,
                signal="aks_commerce.order_acceptance_unavailable",
                observation=(
                    "Order acceptance failed repeatedly while the reviewed Deployment "
                    "had zero replicas and no ready endpoints."
                ),
                severity=self._severity,
                occurred_at=assessment.observed_at,
                evidence_refs=(assessment.evidence_digest, *assessment.evidence_refs),
                metadata={
                    "service_scope": "order-acceptance",
                    "policy_ref": self._intent.policy_ref,
                },
                assessment=FindingAssessment(
                    assessed_by="fdai.aks_commerce.order_acceptance.v1",
                    evidence_complete=True,
                    recovery_closed=None,
                    status="order_acceptance_unavailable",
                ),
            ),
        )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("order-acceptance evidence contains an unsupported value")
    return value.isoformat()

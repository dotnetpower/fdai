"""Agent-owned, evidence-gated Assurance Twin report and review ingress."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypeVar

from fdai_service_contracts import OperationalFreshness
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.core.assurance_twin.report import (
    PostureAssessmentReport,
    build_posture_assessment_report,
)
from fdai.delivery.assurance_twin_inventory import AssuranceTwinInventoryChangedError
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    _change_review_body,
    evidence_body_digest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding

REQUEST_TOPIC = "fdai.assurance-twin.requests"
_LOG = logging.getLogger(__name__)
_DIGEST_PREFIX = "sha256:"
_FenceResult = TypeVar("_FenceResult")


class AssuranceTwinPublishRequest(BaseModel):
    """Content-free trigger; only a retained source can provide findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["posture", "review"]
    source_key: str = Field(min_length=1, max_length=256)
    source_revision: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class RuleFindingAssessment:
    """Trusted evaluator's complete rule pass at the exact Resource revision.

    A Resource projection alone cannot attest to a zero-finding result.
    """

    source_revision: str
    rule_set_digest: str
    rule_membership_digest: str
    rule_generation_digest: str
    inventory_revision: str
    evaluated_rule_ids: tuple[str, ...]
    findings_digest: str
    coverage_refs: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class ProposedIacAssessment:
    """Trusted proposed-change readback, not a browser or request payload."""

    source_revision: str
    pr_ref: str
    proposal_digest: str
    evidence_refs: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class RetainedTwinEvidence:
    """Read-only snapshot pinned to one revision and positive coverage."""

    record: PostureAssessmentReport | IacReview
    source_revision: str
    evidence_digest: str
    fresh_until: datetime
    coverage_refs: tuple[str, ...]
    complete: bool
    conflict: bool = False
    rule_assessment: RuleFindingAssessment | None = None
    proposed_iac: ProposedIacAssessment | None = None


class RetainedTwinEvidenceSource(Protocol):
    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None: ...

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None: ...


class AssuranceTwinRuleGenerationFence(Protocol):
    async def run_assurance_twin_if_current(
        self,
        *,
        rule_generation_revision: str,
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult | None: ...


class AssuranceTwinInventoryFence(Protocol):
    async def run_assurance_twin_inventory_if_current(
        self,
        *,
        inventory_revision: str,
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult | None: ...


@dataclass(frozen=True, slots=True)
class _InventoryWriterResult:
    request: AssuranceTwinPublishRequest
    succeeded: bool


class AssuranceTwinAgentWriter:
    """Run a single owner's subscription; never judge from the trigger payload."""

    def __init__(
        self,
        *,
        owner: Literal["Heimdall", "Forseti"],
        source: RetainedTwinEvidenceSource,
        recorder: AssuranceTwinPostureRecorder,
        posture_generation_fence: AssuranceTwinRuleGenerationFence | None = None,
        posture_inventory_fence: AssuranceTwinInventoryFence | None = None,
    ) -> None:
        self.owner = owner
        self._source = source
        self._recorder = recorder
        self._posture_generation_fence = posture_generation_fence
        self._posture_inventory_fence = posture_inventory_fence

    async def process(self, request: AssuranceTwinPublishRequest) -> bool:
        """Persist only a complete, fresh, conflict-free exact source revision."""

        if (request.kind == "posture") != (
            self.owner == "Heimdall"
        ) or request.idempotency_key != request_key(
            request.kind, request.source_key, request.source_revision
        ):
            return False
        try:
            snapshot = (
                await self._source.read_posture(request.source_key, request.source_revision)
                if self.owner == "Heimdall"
                else await self._source.read_review(request.source_key, request.source_revision)
            )
            if snapshot is None:
                return False
        except Exception:  # noqa: BLE001 - source outage never manufactures a verdict
            _LOG.warning("assurance_twin_evidence_source_unavailable", extra={"kind": request.kind})
            return False
        if snapshot.conflict:
            await self._mark_source_conflict(request, snapshot)
            return False
        if not _admissible(snapshot, request):
            return False
        if self.owner == "Heimdall" and self._posture_generation_fence is not None:
            posture_assessment = snapshot.rule_assessment
            if posture_assessment is None:
                return False
            fenced = await self._posture_generation_fence.run_assurance_twin_if_current(
                rule_generation_revision=posture_assessment.rule_generation_digest,
                operation=lambda: self._persist_with_inventory_fence(
                    request,
                    snapshot,
                    posture_assessment.inventory_revision,
                ),
            )
            return fenced is True
        assessment = snapshot.rule_assessment
        return await self._persist_with_inventory_fence(
            request,
            snapshot,
            assessment.inventory_revision if assessment is not None else "",
        )

    async def _persist_with_inventory_fence(
        self,
        request: AssuranceTwinPublishRequest,
        snapshot: RetainedTwinEvidence,
        inventory_revision: str,
    ) -> bool:
        if self.owner == "Heimdall" and self._posture_inventory_fence is not None:
            try:
                fenced = (
                    await self._posture_inventory_fence.run_assurance_twin_inventory_if_current(
                        inventory_revision=inventory_revision,
                        operation=lambda: self._persist_inventory_snapshot(
                            request,
                            snapshot,
                        ),
                    )
                )
            except AssuranceTwinInventoryChangedError:
                await self._mark_source_conflict(request, snapshot)
                return False
            if not isinstance(fenced, _InventoryWriterResult) or not fenced.succeeded:
                return False
            return True
        return await self._persist_snapshot(request, snapshot)

    async def _persist_inventory_snapshot(
        self,
        request: AssuranceTwinPublishRequest,
        snapshot: RetainedTwinEvidence,
    ) -> _InventoryWriterResult:
        return _InventoryWriterResult(
            request=request,
            succeeded=await self._persist_snapshot(request, snapshot),
        )

    async def _persist_snapshot(
        self,
        request: AssuranceTwinPublishRequest,
        snapshot: RetainedTwinEvidence,
    ) -> bool:
        confirm_writer = getattr(self._source, "confirm_writer", None)
        requires_confirmation = callable(confirm_writer)
        if self.owner == "Heimdall":
            report = snapshot.record
            if (
                not isinstance(report, PostureAssessmentReport)
                or report.scope != request.source_key
            ):
                return False
            result = await self._recorder.record_posture_report(
                report,
                correlation_id=request.correlation_id,
                freshness=OperationalFreshness.FRESH,
                evidence_source_revision=snapshot.source_revision,
                source_confirmed=not requires_confirmation,
            )
        else:
            review = snapshot.record
            if not isinstance(review, IacReview) or review.review_key != request.source_key:
                return False
            result = await self._recorder.record_change_review(
                review,
                correlation_id=request.correlation_id,
                freshness=OperationalFreshness.FRESH,
                evidence_source_revision=snapshot.source_revision,
                source_confirmed=not requires_confirmation,
            )
        try:
            confirmed = (
                await self._source.read_posture(request.source_key, request.source_revision)
                if self.owner == "Heimdall"
                else await self._source.read_review(request.source_key, request.source_revision)
            )
        except ValueError:
            await self._mark_source_conflict(request, snapshot)
            return False
        except Exception:  # noqa: BLE001 - a later relay pass independently retries readback
            return False
        if confirmed != snapshot:
            await self._mark_source_conflict(request, snapshot)
            return False
        if requires_confirmation and callable(confirm_writer):
            try:
                source_confirmed = await confirm_writer(
                    request,
                    evidence_digest=snapshot.evidence_digest,
                )
            except Exception as exc:  # noqa: BLE001 - durable request remains pending
                _LOG.warning(
                    "assurance_twin_source_confirmation_unavailable",
                    extra={"kind": request.kind, "error_type": type(exc).__name__},
                )
                return False
            if not source_confirmed:
                return False
        return not result.conflict and result.activity.status.value != "superseded"

    async def _mark_source_conflict(
        self,
        request: AssuranceTwinPublishRequest,
        snapshot: RetainedTwinEvidence,
    ) -> None:
        generated_at = getattr(snapshot.record, "generated_at", "")
        await self._recorder.mark_source_conflict(
            owner=self.owner,
            source_key=request.source_key,
            generated_at=generated_at,
            source_revision=snapshot.source_revision,
            rejected_evidence_digest=snapshot.evidence_digest,
            correlation_id=request.correlation_id,
        )

    async def run(self, bus: EventBus, stop: asyncio.Event) -> None:
        """Subscribe independently; a poisoned trigger carries no evidence."""

        group = f"fdai-assurance-twin-{self.owner.casefold()}"
        while not stop.is_set():
            async with subscription(bus, REQUEST_TOPIC, group) as stream:
                async for envelope in stream:
                    if stop.is_set():
                        break
                    try:
                        request = AssuranceTwinPublishRequest.model_validate(envelope.payload)
                    except ValidationError:
                        await bus.dead_letter(
                            REQUEST_TOPIC, envelope.key, envelope.payload, "invalid_request"
                        )
                        continue
                    if envelope.key != request.idempotency_key:
                        await bus.dead_letter(
                            REQUEST_TOPIC, envelope.key, envelope.payload, "identity_mismatch"
                        )
                        continue
                    if (request.kind == "posture") == (self.owner == "Heimdall"):
                        if not await self.process(request):
                            await bus.dead_letter(
                                REQUEST_TOPIC,
                                envelope.key,
                                envelope.payload,
                                "evidence_unavailable",
                            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass


def _admissible(snapshot: RetainedTwinEvidence, request: AssuranceTwinPublishRequest) -> bool:
    record = snapshot.record
    assessment = snapshot.rule_assessment
    if (
        not isinstance(record, (PostureAssessmentReport, IacReview))
        or not _digest(snapshot.source_revision)
        or snapshot.source_revision != request.source_revision
        or snapshot.complete is not True
        or snapshot.conflict is not False
        or not snapshot.coverage_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in snapshot.coverage_refs)
        or not isinstance(snapshot.fresh_until, datetime)
        or snapshot.fresh_until.tzinfo is None
        or snapshot.fresh_until <= datetime.now(UTC)
        or record.mode is not Mode.SHADOW
        or not isinstance(assessment, RuleFindingAssessment)
        or assessment.complete is not True
        or assessment.source_revision != snapshot.source_revision
        or not _digest(assessment.rule_set_digest)
        or not _digest(assessment.rule_membership_digest)
        or not _digest(assessment.rule_generation_digest)
        or not _digest(assessment.inventory_revision)
        or not _digest(assessment.findings_digest)
        or not assessment.coverage_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in assessment.coverage_refs)
        or not assessment.evaluated_rule_ids
        or any(
            not isinstance(rule, str) or not rule.strip() for rule in assessment.evaluated_rule_ids
        )
        or assessment.evaluated_rule_ids != tuple(sorted(set(assessment.evaluated_rule_ids)))
        or assessment.rule_membership_digest != rule_set_digest(assessment.evaluated_rule_ids)
        or assessment.rule_set_digest not in assessment.coverage_refs
        or assessment.findings_digest != findings_digest(record.findings)
        or any(
            finding.rule_id not in assessment.evaluated_rule_ids or not finding.evidence_refs
            for finding in record.findings
        )
    ):
        return False
    try:
        generated_at = datetime.fromisoformat(record.generated_at.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        if (
            generated_at.tzinfo is None
            or generated_at > now
            or now - generated_at > timedelta(minutes=30)
            or snapshot.fresh_until - generated_at > timedelta(minutes=30)
        ):
            return False
        body = (
            {
                **record.to_dict(),
                "generated_at": generated_at.astimezone(UTC).isoformat(),
                "freshness": "fresh",
                "reason_codes": [],
            }
            if isinstance(record, PostureAssessmentReport)
            else _change_review_body(record, freshness="fresh", reason_codes=())
        )
        if evidence_body_digest(body) != snapshot.evidence_digest:
            return False
        if isinstance(record, IacReview):
            proposed = snapshot.proposed_iac
            if (
                not isinstance(proposed, ProposedIacAssessment)
                or proposed.complete is not True
                or proposed.source_revision != snapshot.source_revision
                or proposed.pr_ref != record.pr_ref
                or not _digest(proposed.proposal_digest)
                or not proposed.evidence_refs
                or any(
                    not isinstance(ref, str) or not ref.strip() for ref in proposed.evidence_refs
                )
            ):
                return False
            judged = build_posture_assessment_report(
                scope=record.pr_ref,
                generated_at=record.generated_at,
                mode=Mode.SHADOW,
                findings=record.findings,
            )
            if record.verdict != judged.verdict.value:
                return False
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _digest(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_DIGEST_PREFIX)
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def findings_digest(findings: tuple[Finding, ...]) -> str:
    """Content-address the full ordered rule output, including an empty result."""

    body = [
        [
            finding.rule_id,
            finding.resource.resource_type,
            finding.resource.ref,
            finding.severity,
            finding.reason,
            list(finding.evidence_refs),
        ]
        for finding in findings
    ]
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def rule_set_digest(rule_ids: tuple[str, ...]) -> str:
    """Bind an evaluator's declared ordered rule coverage to its content."""

    encoded = json.dumps(rule_ids, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def request_key(kind: str, source_key: str, source_revision: str) -> str:
    """Privacy-safe stable request identity, independent of consumer retries."""

    encoded = json.dumps([kind, source_key, source_revision], separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


__all__ = [
    "REQUEST_TOPIC",
    "AssuranceTwinAgentWriter",
    "AssuranceTwinInventoryFence",
    "AssuranceTwinPublishRequest",
    "AssuranceTwinRuleGenerationFence",
    "ProposedIacAssessment",
    "RetainedTwinEvidence",
    "RetainedTwinEvidenceSource",
    "RuleFindingAssessment",
    "findings_digest",
    "rule_set_digest",
    "request_key",
]

"""Agent-owned, evidence-gated Assurance Twin report and review ingress."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fdai_service_contracts import OperationalFreshness
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.core.assurance_twin.report import (
    PostureAssessmentReport,
    build_posture_assessment_report,
)
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    _change_review_body,
    evidence_body_digest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.iac_review import IacReview

REQUEST_TOPIC = "fdai.assurance-twin.requests"
_LOG = logging.getLogger(__name__)


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
class RetainedTwinEvidence:
    """Read-only snapshot pinned to one revision and positive coverage."""

    record: PostureAssessmentReport | IacReview
    source_revision: str
    evidence_digest: str
    fresh_until: datetime
    coverage_refs: tuple[str, ...]
    complete: bool
    conflict: bool = False


class RetainedTwinEvidenceSource(Protocol):
    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None: ...

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None: ...


class AssuranceTwinAgentWriter:
    """Run a single owner's subscription; never judge from the trigger payload."""

    def __init__(
        self,
        *,
        owner: Literal["Heimdall", "Forseti"],
        source: RetainedTwinEvidenceSource,
        recorder: AssuranceTwinPostureRecorder,
    ) -> None:
        self.owner = owner
        self._source = source
        self._recorder = recorder

    async def process(self, request: AssuranceTwinPublishRequest) -> bool:
        """Persist only a complete, fresh, conflict-free exact source revision."""

        if (request.kind == "posture") != (self.owner == "Heimdall"):
            return False
        try:
            snapshot = (
                await self._source.read_posture(request.source_key, request.source_revision)
                if self.owner == "Heimdall"
                else await self._source.read_review(request.source_key, request.source_revision)
            )
        except Exception:  # noqa: BLE001 - source outage never manufactures a verdict
            _LOG.warning("assurance_twin_evidence_source_unavailable", extra={"kind": request.kind})
            return False
        if snapshot is None or not _admissible(snapshot, request):
            return False
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
            )
        return not result.conflict and result.activity.status.value != "superseded"

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
    if (
        not isinstance(record, (PostureAssessmentReport, IacReview))
        or snapshot.source_revision != request.source_revision
        or snapshot.complete is not True
        or snapshot.conflict is not False
        or not snapshot.coverage_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in snapshot.coverage_refs)
        or not isinstance(snapshot.fresh_until, datetime)
        or snapshot.fresh_until.tzinfo is None
        or snapshot.fresh_until <= datetime.now(UTC)
        or record.mode is not Mode.SHADOW
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
            if not all(finding.evidence_refs for finding in record.findings):
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


def request_key(kind: str, source_key: str, source_revision: str) -> str:
    """Privacy-safe stable request identity, independent of consumer retries."""

    encoded = json.dumps([kind, source_key, source_revision], separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


__all__ = [
    "REQUEST_TOPIC",
    "AssuranceTwinAgentWriter",
    "AssuranceTwinPublishRequest",
    "RetainedTwinEvidence",
    "RetainedTwinEvidenceSource",
    "request_key",
]

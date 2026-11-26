"""Request-scoped server bindings and independently observed technical reuse counts."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import Event
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

from .contextual_reuse import (
    CurrentReuseVerification,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from .tier import SimilarityMatch

if TYPE_CHECKING:
    from .retained_patterns import RetainedPatternRequest

_MAX_STATISTICS_AGE = timedelta(minutes=5)
FINAL_QUALIFICATION_PURPOSE = "retained-pattern-final-qualification"


@dataclass(frozen=True, slots=True)
class RetainedPatternQualification:
    """Immutable exact tuple for a trusted coherent source fence, not a readiness claim."""

    descriptor_json: str

    @property
    def descriptor(self) -> dict[str, Any]:
        return json.loads(self.descriptor_json)  # type: ignore[no-any-return]

    @property
    def evidence_digest(self) -> str:
        return content_digest(self.descriptor)

    @property
    def scope_digest(self) -> str:
        value = self.descriptor
        return content_digest({"event": value["event"], "read": value["read"]})


class RetainedPatternFinalQualifier(Protocol):
    """Atomically reauthorize the COMPLETE tuple under a real snapshot/lease/fence.

    This is NOT implemented by an ordinary admission lookup or sequential rereads.
    The issuer must cover all cohort artifacts and projection versions, the current
    measurement reference, principal read authorization, and current reuse/policy
    authorization in one coherent cut. Reject changed tuples and invalidated fences.
    The fence must remain valid through the caller's immediate receipt acceptance;
    a released transaction or time-valid cached admission alone is insufficient.
    The request is ephemeral and MUST NOT create a separate copied-evidence lifecycle.
    Its no-authority admission binds the tuple digest as evidence AND source revision,
    with FINAL_QUALIFICATION_PURPOSE and the exact request scope. No default issuer exists.
    """

    async def qualify(
        self, request: RetainedPatternQualification
    ) -> DecisionEvidenceAdmission | None: ...


def qualification_request(
    *,
    event: Event,
    arguments: Mapping[str, Any],
    principal: Mapping[str, Any],
    read_source_revision: str,
    cohort: Mapping[str, Any],
    match: SimilarityMatch,
    statistics: RetainedReuseStatistics,
    verification: CurrentReuseVerification,
) -> RetainedPatternQualification:
    action = match.action
    measurement = asdict(statistics)
    for key in ("observed_at", "valid_until"):
        measurement[key] = measurement[key].isoformat()
    descriptor = {
        "schema_version": "1.0.0",
        "event": event.model_dump(mode="json"),
        "read": {
            "arguments": dict(arguments),
            "principal": dict(principal),
            "purpose_id": "case-history-read",
            "source_revision": read_source_revision,
        },
        "cohort": dict(cohort),
        "match": {
            "score": match.score,
            "signature": action.signature,
            "rule_id": action.rule_id,
            "action_type": action.action_type,
            "params": dict(action.params),
            "incident_id": action.incident_id,
            "success_rate": action.success_rate,
            "reuse_count": action.reuse_count,
            "context": action.operational_case.to_mapping() if action.operational_case else None,
        },
        "measurement": measurement,
        "reuse": {
            "evidence_digest": current_reuse_evidence_digest(verification),
            "scope_digest": current_reuse_scope_digest(
                event=event,
                action=action,
                context=action.operational_case,  # type: ignore[arg-type]
            ),
            "admission": (
                verification.decision_evidence.to_mapping()
                if verification.decision_evidence is not None
                else None
            ),
        },
    }
    return RetainedPatternQualification(
        json.dumps(descriptor, allow_nan=False, sort_keys=True, separators=(",", ":"))
    )


@dataclass(frozen=True, slots=True)
class RetainedReuseStatistics:
    """Independent measured outcomes, NOT Pattern cohort or approval counts.

    Only verified technical successes and technical failures form the denominator.
    A safe approval refusal or rollback is not a technical failure. The server-owned
    source must retain and reauthorize the cited measurement before supplying this DTO.
    These counts establish comparison input validity, never operational proof.
    """

    action_signature: str
    case_ref: str
    access_scope_digest: str
    source_revision: str
    evidence_ref: str
    verified_successes: int
    technical_failures: int
    observed_at: datetime
    valid_until: datetime

    def matches(self, match: SimilarityMatch, *, now: datetime) -> bool:
        action = match.action
        context = action.operational_case
        counts = (self.verified_successes, self.technical_failures)
        if (
            context is None
            or any(type(count) is not int or not 0 <= count <= 1_000_000 for count in counts)
            or sum(counts) < 1
            or self.action_signature != action.signature
            or self.case_ref != context.case_ref
            or self.access_scope_digest != context.access_scope_digest
            or self.source_revision != context.graph_digest
            or re.fullmatch(r"[a-f0-9]{64}", self.evidence_ref) is None
            or self.observed_at.utcoffset() is None
            or self.valid_until.utcoffset() is None
            or not self.observed_at <= now < self.valid_until
            or self.valid_until > self.observed_at + _MAX_STATISTICS_AGE
            or action.reuse_count != sum(counts)
            or isinstance(action.success_rate, bool)
            or not isinstance(action.success_rate, (int, float))
        ):
            return False
        return abs(action.success_rate - self.verified_successes / sum(counts)) < 1e-12


@dataclass(frozen=True, slots=True)
class BoundRetainedPatternRequest:
    """Concrete per-request DI binding; an unrelated Event receives no principal."""

    event_id: str
    request: RetainedPatternRequest

    async def __call__(self, event: Event) -> RetainedPatternRequest | None:
        return self.request if str(event.event_id) == self.event_id else None


@dataclass(frozen=True, slots=True)
class BoundRetainedPatternAction:
    """Concrete bounded binding for independently resolved action/measurement inputs.

    Construct at the authenticated server boundary from current authoritative sources,
    not Event payload fields. The tier still validates registration, arguments, source
    lineage, measurement freshness, and independent current-case admission.
    Measurement reads MUST resolve and reauthorize the pinned evidence reference
    each time; absence of that provider never qualifies a captured snapshot.
    """

    event_id: str
    pattern_id: str
    match: SimilarityMatch
    statistics_ref: str
    statistics_provider: (
        Callable[[Event, SimilarityMatch, str], Awaitable[RetainedReuseStatistics | None]] | None
    ) = None

    async def resolve(self, event: Event, summary: Mapping[str, Any]) -> SimilarityMatch | None:
        if str(event.event_id) != self.event_id or summary.get("pattern_id") != self.pattern_id:
            return None
        return self.match

    async def read_statistics(
        self, event: Event, match: SimilarityMatch
    ) -> RetainedReuseStatistics | None:
        if (
            str(event.event_id) != self.event_id
            or match != self.match
            or self.statistics_provider is None
        ):
            return None
        current = await self.statistics_provider(event, match, self.statistics_ref)
        if not isinstance(current, RetainedReuseStatistics) or (
            current.evidence_ref != self.statistics_ref
        ):
            return None
        return current

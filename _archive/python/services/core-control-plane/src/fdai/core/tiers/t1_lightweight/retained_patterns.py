"""On-demand authorized Pattern intake, isolated from the baseline similarity index."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import Unresolvable

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_learning.patterns import OperatingPatternCompiler, PatternCase
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import (
    RetainedPatternLeasedQualifier,
    RetainedPatternLeaseEvidence,
    retained_pattern_lease_current,
)
from fdai.shared.contracts.models import Event, OntologyActionType
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

from .contextual_reuse import contextual_reuse_reasons
from .retained_pattern_bindings import (
    FINAL_QUALIFICATION_PURPOSE,
    RetainedPatternFinalQualifier,
    RetainedReuseStatistics,
    qualification_request,
)
from .tier import (
    SimilarityMatch,
    T1CandidateEligibility,
    T1Decision,
    T1Outcome,
)

_LIMIT = 5
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class RetainedPatternRequest:
    """Server-bound principal and mechanism; an Event never supplies read authority."""

    context: FunctionInvocationContext
    access_scope_digest: str
    purpose: str
    failure_fingerprint: str

    def __post_init__(self) -> None:
        if (
            _DIGEST.fullmatch(self.access_scope_digest) is None
            or _DIGEST.fullmatch(self.failure_fingerprint) is None
            or not self.purpose.strip()
            or len(self.purpose) > 128
        ):
            raise ValueError("retained Pattern request scope, fingerprint, or purpose is invalid")

    def arguments(self) -> dict[str, Any]:
        return {
            "access_scope_digest": self.access_scope_digest,
            "purpose": self.purpose,
            "failure_fingerprint": self.failure_fingerprint,
            "limit": _LIMIT,
        }


@dataclass(frozen=True, slots=True)
class RetainedPatternComparison:
    """Bounded SHADOW observations, never an execution or operational-proof receipt."""

    candidates: tuple[T1CandidateEligibility, ...] = ()
    challenger_match: SimilarityMatch | None = None
    stop_reason: str | None = None
    pattern_ids: tuple[str, ...] = ()
    statistics_refs: tuple[str, ...] = ()
    final_qualification: DecisionEvidenceAdmission | None = None
    final_lease: RetainedPatternLeaseEvidence | None = None

    def audit_mapping(self) -> dict[str, object]:
        """Project digest-only lineage; exclude params, evidence, and principal contents."""
        return {
            "mode": "shadow",
            "pattern_ids": list(self.pattern_ids),
            "statistics_refs": list(self.statistics_refs),
            "candidate_count": len(self.candidates),
            "eligible_count": (
                sum(candidate.eligible for candidate in self.candidates)
                if self.final_qualification is not None or self.final_lease is not None
                else 0
            ),
            "stop_reason": self.stop_reason,
            "execution_authority": False,
            "promotion_authority": False,
            "operationally_proven": False,
        }


RequestSource = Callable[[Event], Awaitable[RetainedPatternRequest | None]]
ActionResolver = Callable[[Event, Mapping[str, Any]], Awaitable[SimilarityMatch | None]]
CandidateScreen = Callable[..., Awaitable[T1Decision]]
StatisticsSource = Callable[[Event, SimilarityMatch], Awaitable[RetainedReuseStatistics | None]]


class RetainedPatternSource:
    """Read current retained projections without copying evidence or building an index.

    The resolver must supply real action parameters, contextual facts, similarity, and
    observed reuse statistics. Cohort success/negative counts are NOT reuse statistics.
    The registered ActionType argument schema and existing current-case admission still
    apply. Availability requires this explicit binding; no runtime source is inferred.
    """

    def __init__(
        self,
        *,
        query: OperatingPatternQuery,
        request_source: RequestSource,
        action_resolver: ActionResolver,
        action_types: Callable[[], Mapping[str, OntologyActionType]],
        store: StateStore,
        materializer: Callable[[], CaseHistoryMaterializer | None],
        statistics_source: StatisticsSource | None = None,
        final_qualifier: RetainedPatternFinalQualifier | None = None,
        leased_qualifier: RetainedPatternLeasedQualifier | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._query = query
        self._request_source = request_source
        self._resolve = action_resolver
        self._action_types = action_types
        self._store, self._materializer = store, materializer
        self._statistics_source = statistics_source
        self._final_qualifier = final_qualifier
        self._leased_qualifier = leased_qualifier
        self._clock = clock or (lambda: datetime.now(UTC))

    async def compare(self, *, event: Event, screen: CandidateScreen) -> RetainedPatternComparison:
        """Use the caller's cooperative deadline; cancellation is never swallowed."""
        try:
            return await self._compare(event=event, screen=screen)
        except Exception as exc:  # noqa: BLE001 - optional provider boundary
            return RetainedPatternComparison(
                stop_reason=f"retained_pattern_error:{type(exc).__name__}"
            )

    async def _compare(self, *, event: Event, screen: CandidateScreen) -> RetainedPatternComparison:
        request = await self._request_source(event)
        if request is None:
            return RetainedPatternComparison(stop_reason="retained_pattern_source_unavailable")
        if not isinstance(request, RetainedPatternRequest):
            raise ValueError("retained Pattern source returned an invalid request")
        summaries = await self._read(request)
        if summaries is None:
            return RetainedPatternComparison(stop_reason="retained_pattern_projection_unavailable")
        materializer = self._materializer()
        if materializer is None:
            return RetainedPatternComparison(stop_reason="retained_pattern_source_unavailable")
        projections = CaseHistoryProjectionStore(
            store=self._store,
            materializer=materializer,
            access_scope_digest=request.access_scope_digest,
            clock=self._clock,
        )
        records = {
            record["pattern_id"]: record
            for record in await projections.pattern_records()
            if record.get("purpose") == request.purpose
        }
        checks: list[T1CandidateEligibility] = []
        ids: list[str] = []
        statistics_refs: list[str] = []
        selected: SimilarityMatch | None = None
        selected_statistics: RetainedReuseStatistics | None = None
        stop_reason = "no_retained_pattern" if not summaries else None
        for summary in summaries:
            ids.append(summary["pattern_id"])
            match = await self._resolve(event, summary)
            if match is None:
                stop_reason = "retained_pattern_action_unavailable"
                break
            reasons = self._binding_reasons(match, summary, request)
            record = records.get(summary["pattern_id"])
            if record is None:
                return RetainedPatternComparison(stop_reason="retained_pattern_source_changed")
            cases = tuple(PatternCase.from_mapping(item) for item in record["cases"])
            compiled = OperatingPatternCompiler().compile(cases, reviewed_at=self._clock())
            if (
                compiled is None
                or compiled.pattern_id != summary["pattern_id"]
                or compiled.to_rule_candidate_mapping() != record["candidate"]
                or record.get("execution_authority") is not False
                or record.get("promotion_authority") is not False
            ):
                return RetainedPatternComparison(stop_reason="retained_pattern_source_changed")
            if match.action.operational_case is not None and not any(
                case.reusable
                and case.immutable_case_ref == match.action.operational_case.case_ref
                and case.event_time_cutoff == match.action.operational_case.evidence_cutoff
                for case in cases
            ):
                reasons = ("retained_pattern_positive_case_required",)
            if reasons:
                checks.append(T1CandidateEligibility(match, False, reasons))
                stop_reason = reasons[0]
                break
            statistics = (
                await self._statistics_source(event, match)
                if self._statistics_source is not None
                else None
            )
            if not isinstance(statistics, RetainedReuseStatistics) or not statistics.matches(
                match, now=self._clock()
            ):
                checks.append(
                    T1CandidateEligibility(
                        match, False, ("retained_pattern_statistics_unavailable",)
                    )
                )
                stop_reason = "retained_pattern_statistics_unavailable"
                break
            statistics_refs.append(statistics.evidence_ref)
            result = await screen(event=event, match=match)
            eligible = result.outcome is T1Outcome.REUSED
            checks.append(
                T1CandidateEligibility(
                    match, eligible, result.reasons, result.current_reuse_verification
                )
            )
            if eligible:
                selected = match
                selected_statistics = statistics
                break
            # A new library must never bypass a denied current admission or policy.
            stop_reason = result.reason or "retained_pattern_admission_unavailable"
            break
        # Reauthorize and recheck EVERY cohort member, not just the selected positive.
        # No reference or resolved candidate survives a source change during verification.
        current = None
        if selected is not None:
            current = (
                await self._statistics_source(event, selected)
                if self._statistics_source is not None
                else None
            )
        if await self._read(request) != summaries:
            return RetainedPatternComparison(stop_reason="retained_pattern_source_changed")
        if selected is not None:
            # Re-read the authoritative safety/admission boundary AFTER the other
            # provider awaits; a captured successful verification cannot survive
            # a policy change or admission withdrawal during those reads.
            final = await screen(event=event, match=selected)
            verification = final.current_reuse_verification
            context = selected.action.operational_case
            if (
                final.outcome is not T1Outcome.REUSED
                or current != selected_statistics
                or current is None
                or not current.matches(selected, now=self._clock())
                or context is None
                or self._binding_reasons(selected, summaries[0], request)
                or verification is None
                or contextual_reuse_reasons(
                    event=event,
                    action=selected.action,
                    context=context,
                    verification=verification,
                    evaluated_at=self._clock(),
                )
            ):
                return RetainedPatternComparison(stop_reason="retained_pattern_evidence_changed")
            checks[-1] = replace(checks[-1], current_reuse_verification=verification)
            if self._final_qualifier is None and self._leased_qualifier is None:
                return RetainedPatternComparison(
                    stop_reason="retained_pattern_qualification_unavailable"
                )
            bound = qualification_request(
                event=event,
                arguments=request.arguments(),
                principal=request.context.model_dump(mode="json"),
                read_source_revision=self._query._source_revision,
                cohort=records[summaries[0]["pattern_id"]],
                match=selected,
                statistics=current,
                verification=verification,
            )
            digest, scope = bound.evidence_digest, bound.scope_digest
            if self._leased_qualifier is not None:
                async with self._leased_qualifier.lease(bound) as lease:
                    now = self._clock()
                    if not isinstance(lease, RetainedPatternLeaseEvidence):
                        return RetainedPatternComparison(
                            stop_reason="retained_pattern_qualification_rejected"
                        )
                    if not retained_pattern_lease_current(lease, bound, now=now):
                        return RetainedPatternComparison(
                            stop_reason="retained_pattern_qualification_rejected"
                        )
                    if not current.matches(selected, now=now) or contextual_reuse_reasons(
                        event=event,
                        action=selected.action,
                        context=context,
                        verification=verification,
                        evaluated_at=now,
                    ):
                        return RetainedPatternComparison(
                            stop_reason="retained_pattern_qualification_rejected"
                        )
                    # Positive acceptance happens synchronously while the actual
                    # owner transaction still prevents every dependency mutation.
                    return self._accept_leased(
                        tuple(checks), selected, tuple(ids), tuple(statistics_refs), lease
                    )
            if self._final_qualifier is None:
                return RetainedPatternComparison(
                    stop_reason="retained_pattern_qualification_unavailable"
                )
            # This is the final awaited authority boundary. Sequential readers above
            # provide inputs only; they cannot establish coherent tuple eligibility.
            admission = await self._final_qualifier.qualify(bound)
            now = self._clock()
            if admission is None:
                return RetainedPatternComparison(
                    stop_reason="retained_pattern_qualification_rejected"
                )

            if (
                not isinstance(admission, DecisionEvidenceAdmission)
                or now >= admission.valid_until
                or not current.matches(selected, now=now)
                or contextual_reuse_reasons(
                    event=event,
                    action=selected.action,
                    context=context,
                    verification=verification,
                    evaluated_at=now,
                )
            ):
                return RetainedPatternComparison(
                    stop_reason="retained_pattern_qualification_rejected"
                )
            if assess_decision_evidence_admission(
                admission,
                expected_evidence_digest=digest,
                expected_scope_digest=scope,
                expected_purpose_id=FINAL_QUALIFICATION_PURPOSE,
                expected_source_revision=digest,
                evaluated_at=now,
            ):
                return RetainedPatternComparison(
                    stop_reason="retained_pattern_qualification_rejected"
                )
            return RetainedPatternComparison(
                tuple(checks),
                selected,
                stop_reason,
                tuple(ids),
                tuple(statistics_refs),
                admission,
            )
        return RetainedPatternComparison(
            tuple(checks), None, stop_reason, tuple(ids), tuple(statistics_refs), None
        )

    def _accept_leased(
        self,
        checks: tuple[T1CandidateEligibility, ...],
        selected: SimilarityMatch,
        ids: tuple[str, ...],
        statistics_refs: tuple[str, ...],
        lease: RetainedPatternLeaseEvidence,
    ) -> RetainedPatternComparison:
        return RetainedPatternComparison(
            candidates=checks,
            challenger_match=selected,
            pattern_ids=ids,
            statistics_refs=statistics_refs,
            final_lease=lease,
        )

    async def _read(self, request: RetainedPatternRequest) -> tuple[Mapping[str, Any], ...] | None:
        result = await self._query.read(request.arguments(), request.context)
        if (
            not isinstance(result, dict)
            or set(result) != {"patterns", "unavailable", "truncated", "execution_authority"}
            or result["execution_authority"] is not False
            or type(result["unavailable"]) is not bool
            or type(result["truncated"]) is not bool
            or not isinstance(result["patterns"], list)
            or len(result["patterns"]) > _LIMIT
        ):
            raise ValueError("retained Pattern query returned an invalid response")
        if result["unavailable"]:
            return None
        ids: set[str] = set()
        for summary in result["patterns"]:
            if (
                not isinstance(summary, dict)
                or set(summary)
                != {
                    "pattern_id",
                    "action_type",
                    "resource_type",
                    "sample_size",
                    "success_count",
                    "negative_count",
                    "case_refs",
                    "fdai_revision",
                }
                or not isinstance(summary["pattern_id"], str)
                or _DIGEST.fullmatch(summary["pattern_id"]) is None
                or summary["pattern_id"] in ids
                or any(
                    type(summary[key]) is not int or not 1 <= summary[key] <= 100
                    for key in ("sample_size", "success_count", "negative_count")
                )
                or summary["success_count"] + summary["negative_count"] != summary["sample_size"]
                or not isinstance(summary["case_refs"], list)
                or len(summary["case_refs"]) != summary["sample_size"]
                or any(not isinstance(ref, str) for ref in summary["case_refs"])
                or len(set(summary["case_refs"])) != summary["sample_size"]
            ):
                raise ValueError("retained Pattern query returned an invalid summary")
            ids.add(summary["pattern_id"])
        return tuple(result["patterns"])

    def _binding_reasons(
        self,
        match: SimilarityMatch,
        summary: Mapping[str, Any],
        request: RetainedPatternRequest,
    ) -> tuple[str, ...]:
        if not isinstance(match, SimilarityMatch):
            raise ValueError("retained Pattern action resolver returned an invalid match")
        action = match.action
        context = action.operational_case
        if (
            context is None
            or context.case_ref not in summary["case_refs"]
            or context.access_scope_digest != request.access_scope_digest
            or context.purpose != request.purpose
            or context.failure_fingerprint != request.failure_fingerprint
            or context.resource_type != summary["resource_type"]
            or context.action_type != summary["action_type"]
            or action.action_type != summary["action_type"]
            or action.incident_id != context.case_ref.split(":")[1]
        ):
            return ("retained_pattern_context_mismatch",)
        registered = self._action_types().get(action.action_type)
        if registered is None or registered.name != action.action_type:
            return ("retained_pattern_action_unregistered",)
        if registered.argument_schema is None:
            return ("retained_pattern_argument_schema_unavailable",)
        Draft202012Validator.check_schema(registered.argument_schema)
        if not isinstance(action.params, Mapping):
            return ("retained_pattern_arguments_invalid",)
        if len(json.dumps(dict(action.params), allow_nan=False).encode()) > 65536:
            return ("retained_pattern_arguments_invalid",)
        try:
            valid = Draft202012Validator(registered.argument_schema, registry=Registry()).is_valid(
                dict(action.params)
            )
        except Unresolvable:
            return ("retained_pattern_argument_schema_unavailable",)
        if not valid:
            return ("retained_pattern_arguments_invalid",)
        if (
            isinstance(match.score, bool)
            or not isinstance(match.score, (int, float))
            or not isfinite(match.score)
            or not -1 <= match.score <= 1
        ):
            return ("retained_pattern_similarity_invalid",)
        if summary["success_count"] < 2:
            return ("retained_pattern_insufficient_positive_cases",)
        if type(action.reuse_count) is not int or action.reuse_count < 1:
            return ("retained_pattern_reuse_statistics_unavailable",)
        return ()

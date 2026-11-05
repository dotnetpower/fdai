"""Deterministic retained-source -> next T1 SHADOW comparison regressions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    OperationalOutcomeClass,
    OperationalReceiptType,
)
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_learning.patterns import (
    OperatingPatternCompiler,
    PatternCase,
    pattern_case_from_operational_case,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    FINAL_QUALIFICATION_PURPOSE,
    BoundRetainedPatternAction,
    BoundRetainedPatternRequest,
    RetainedPatternQualification,
    RetainedReuseStatistics,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import (
    LeaseGuard,
    RetainedPatternLeaseEvidence,
)
from fdai.core.tiers.t1_lightweight.retained_patterns import (
    RetainedPatternRequest,
    RetainedPatternSource,
)
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
    T1Config,
    T1Decision,
    T1Outcome,
    T1Tier,
)
from fdai.shared.contracts.models import (
    Event,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

from tests.core.case_history.test_operational_case import T0, _case_input, _receipt

from .test_contextual_reuse import _event, _Verifier
from .test_eligibility_audit import _audit
from .test_eligibility_comparison import _Library

NOW = T0 + timedelta(seconds=3)


class _ReadAdmission:
    def __init__(self) -> None:
        self.allowed = True

    async def admit(self, **values: Any) -> DecisionEvidenceAdmission | None:
        if not self.allowed:
            return None
        return DecisionEvidenceAdmission(
            **values,
            receipt_digest="sha256:" + "a" * 64,
            verification_bundle_digest="sha256:" + "b" * 64,
            verified_at=T0,
            valid_until=T0 + timedelta(days=1),
        )


@dataclass
class _Harness:
    source: RetainedPatternSource
    materializer: CaseHistoryMaterializer
    metadata: InMemoryCaseHistoryMetadataStore
    artifacts: InMemoryCaseHistoryArtifactStore
    durable: InMemoryStateStore
    query: OperatingPatternQuery
    admission: _ReadAdmission
    request: RetainedPatternRequest
    action: LearnedAction
    cases: tuple[PatternCase, ...]
    registry: dict[str, OntologyActionType]
    statistics: RetainedReuseStatistics | None = None
    now: datetime = NOW
    calls: int = 0

    async def resolve(self, event: Event, summary: Mapping[str, Any]) -> SimilarityMatch | None:
        self.calls += 1
        return SimilarityMatch(self.action, 0.98)

    async def request_for(self, event: Event) -> RetainedPatternRequest:
        return self.request

    async def read_statistics(
        self, event: Event, match: SimilarityMatch, evidence_ref: str | None = None
    ) -> RetainedReuseStatistics | None:
        current = self.statistics
        if current is None or (evidence_ref is not None and current.evidence_ref != evidence_ref):
            return None
        return current

    def restart(self) -> None:
        self.materializer = CaseHistoryMaterializer(
            metadata=self.metadata, artifacts=self.artifacts
        )
        self.query = OperatingPatternQuery(
            store=self.durable,
            materializer=lambda: self.materializer,
            admission=self.admission,
            source_revision="a" * 40,
            clock=lambda: self.now,
        )
        self.source = RetainedPatternSource(
            query=self.query,
            request_source=self.request_for,
            action_resolver=self.resolve,
            action_types=lambda: self.registry,
            store=self.durable,
            materializer=lambda: self.materializer,
            statistics_source=self.read_statistics,
            clock=lambda: self.now,
        )

    def tier(
        self,
        *,
        compare: bool = True,
        library: _Library | None = None,
        verifier: Any = None,
        timeout: float = 5,
    ) -> T1Tier:
        return T1Tier(
            embedding_model=DeterministicEmbeddingModel(),
            pattern_library=library or _Library(()),
            current_reuse_verifier=verifier or _Verifier(),
            config=T1Config(compare_eligibility=compare, timeout_seconds=timeout),
            case_history=self.materializer,
            retained_pattern_source=self.source,
            clock=lambda: self.now,
        )


async def _retained(*, positives: int = 2) -> _Harness:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    durable = InMemoryStateStore()
    cases: list[PatternCase] = []
    for index in range(positives + 1):
        outcome = (
            OperationalOutcomeClass.SUCCESS
            if index < positives
            else OperationalOutcomeClass.ROLLBACK
        )
        raw = _case_input(outcome_class=outcome)
        receipts = tuple(
            replace(
                receipt,
                facts=tuple(
                    (key, "enforce") if key == "mode" else (key, value)
                    for key, value in receipt.facts
                ),
            )
            for receipt in raw.receipts
        )
        raw = replace(raw, case_identity_digest=f"{index + 1:x}" * 64, receipts=receipts)
        sealed = await materializer.seal_operational_case(
            raw, retention_until=T0 + timedelta(days=30), deletion_due_at=T0 + timedelta(days=60)
        )
        pattern_case = pattern_case_from_operational_case(raw, sealed.projection)
        assert pattern_case is not None
        cases.append(pattern_case)
    compiled = OperatingPatternCompiler().compile(cases, reviewed_at=NOW)
    assert compiled is not None
    projections = CaseHistoryProjectionStore(
        store=durable, materializer=materializer, access_scope_digest="f" * 64, clock=lambda: NOW
    )
    assert await projections.write_state_if_absent(
        f"cohort:pattern:{compiled.pattern_id}",
        {
            "schema_version": "1.0.0",
            "pattern_id": compiled.pattern_id,
            "access_scope_digest": "f" * 64,
            "purpose": "operational-learning",
            "cohort_key": "cohort",
            "candidate": compiled.to_rule_candidate_mapping(),
            "cases": [case.to_mapping() for case in cases],
            "execution_authority": False,
            "promotion_authority": False,
        },
    )
    c0, scope = cases[0], "f" * 64
    f_ctx = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="example-operator",
        principal_scope_digest="sha256:" + scope,
        authentication_receipt_ref="sha256:" + "e" * 64,
        authentication_request_ref="example-request",
        purposes=("operations-review",),
    )
    request = RetainedPatternRequest(f_ctx, scope, "operational-learning", c0.failure_fingerprint)
    c_args = (c0.immutable_case_ref, c0.failure_fingerprint, c0.resource_type, c0.action_type)
    context = OperationalCaseContext(
        *c_args, "serves", "b" * 64, "c" * 64, T0, scope, request.purpose
    )
    a_args = (compiled.pattern_id, "learned.operational.example", compiled.action_type)
    action = LearnedAction(*a_args, {"count": 2}, c0.case_id, 0.95, 20, context)
    p = {"count": {"type": "integer"}}
    gate = PromotionGate(min_shadow_days=1, min_samples=1, min_accuracy=1.0, max_policy_escapes=0)
    registered = OntologyActionType(
        schema_version="1.0.0",
        name=action.action_type,
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=gate,
        argument_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["count"],
            "properties": p,
        },
    )
    admission = _ReadAdmission()
    query = OperatingPatternQuery(
        store=durable,
        materializer=lambda: materializer,
        admission=admission,
        source_revision="a" * 40,
        clock=lambda: NOW,
    )
    h_args = (None, materializer, metadata, artifacts, durable, query, admission)
    reg = {action.action_type: registered}
    harness = _Harness(*h_args, request, action, tuple(cases), reg)  # type: ignore[arg-type]
    s_args = (action.signature, context.case_ref, scope, context.graph_digest, "9" * 64, 19, 1)
    t_obs, t_exp = T0 + timedelta(seconds=2), T0 + timedelta(minutes=5)
    harness.statistics = RetainedReuseStatistics(*s_args, t_obs, t_exp)
    harness.restart()
    return harness


def _actual(result: T1Decision) -> T1Decision:
    return replace(result, eligibility_comparison=None, retained_pattern_comparison=None)


async def test_retained_source_enters_next_comparison_and_restarts_without_copying() -> None:
    harness = await _retained()
    before = await harness.durable.read_state("case-history-derived:v1:" + "f" * 64)
    for _ in range(2):
        result = await harness.tier().evaluate(event=_event())
        comparison = result.retained_pattern_comparison
        assert comparison is not None and result.outcome is T1Outcome.ABSTAIN
        assert result.reason == "no_neighbour_found" and result.best_match is None
        assert comparison.challenger_match is None and not comparison.candidates
        assert comparison.stop_reason == "retained_pattern_qualification_unavailable"
        assert comparison.audit_mapping()["operationally_proven"] is False
        assert comparison.audit_mapping()["execution_authority"] is False
        assert "params" not in str(comparison.audit_mapping())
        row = await _audit(result)
        persisted = row["t1_retained_pattern_comparison"]
        assert persisted["schema_version"] == "1.0.0"
        assert not persisted["actual_selection_changed"] and not persisted["operationally_proven"]
        assert persisted["statistics_refs"] == [] and persisted["candidates"] == []
        assert persisted["challenger"]["match_identity_digest"] is None
        assert row["t1_outcome"] == "abstain" and row["t1_best_match"] is None
        assert all("params" not in candidate for candidate in persisted["candidates"])
        harness.restart()
    assert harness.calls == 2
    assert await harness.durable.read_state("case-history-derived:v1:" + "f" * 64) == before
    assert harness.action.success_rate == 0.95 and harness.action.reuse_count == 20


async def test_default_off_has_no_intake_io_and_exact_baseline() -> None:
    harness = await _retained()
    library = _Library(())
    result = await harness.tier(compare=False, library=library).evaluate(event=_event())
    expected = T1Tier(embedding_model=DeterministicEmbeddingModel(), pattern_library=_Library(()))
    assert result == await expected.evaluate(event=_event())
    assert harness.calls == 0 and library.calls == [5]


@pytest.mark.parametrize("mutation", ["revision", "artifact", "deletion", "scope", "purpose"])
async def test_source_drift_deletion_and_scope_abstain(mutation: str) -> None:
    harness = await _retained()
    if mutation == "revision":
        raw = _case_input(outcome_class=OperationalOutcomeClass.ROLLBACK)
        receipts = tuple(
            replace(
                receipt,
                facts=tuple(
                    (key, "enforce") if key == "mode" else (key, value)
                    for key, value in receipt.facts
                ),
            )
            for receipt in raw.receipts
        )
        changed = replace(
            raw,
            case_identity_digest="3" * 64,
            receipts=(
                *receipts,
                _receipt(
                    OperationalReceiptType.EVALUATION,
                    "5",
                    (("validation_status", "rejected"), ("evidence_digest", "7" * 64)),
                ),
            ),
        )
        await harness.materializer.seal_operational_case(
            changed,
            retention_until=T0 + timedelta(days=30),
            deletion_due_at=T0 + timedelta(days=60),
        )
    elif mutation == "artifact":
        record = await harness.metadata.latest(
            harness.cases[-1].case_id, access_scope_digest="f" * 64
        )
        assert record is not None and record.storage_ref is not None
        await harness.artifacts.delete(record.storage_ref)
    elif mutation == "deletion":
        record = await harness.metadata.latest(
            harness.cases[-1].case_id, access_scope_digest="f" * 64
        )
        assert record is not None and record.storage_ref is not None
        await harness.metadata.mark_deletion_started(
            record.case_id,
            access_scope_digest="f" * 64,
            revision=record.revision,
            storage_refs=(record.storage_ref,),
            started_at=record.deletion_due_at,
        )
    else:
        harness.request = (
            replace(harness.request, access_scope_digest="e" * 64)
            if mutation == "scope"
            else replace(harness.request, purpose="other")
        )
    harness.restart()
    result = await harness.tier().evaluate(event=_event())
    assert result.retained_pattern_comparison is not None
    assert result.retained_pattern_comparison.challenger_match is None and harness.calls == 0


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"params": {}}, "retained_pattern_arguments_invalid"),
        ({"params": ["not-a-mapping"]}, "retained_pattern_arguments_invalid"),
        ({"params": {"count": "x" * 70000}}, "retained_pattern_arguments_invalid"),
        ({"operational_case": None}, "retained_pattern_context_mismatch"),
        ({"reuse_count": 0}, "retained_pattern_reuse_statistics_unavailable"),
    ],
)
async def test_missing_action_grounding_is_explicit(change: dict[str, Any], reason: str) -> None:
    harness = await _retained()
    harness.action = replace(harness.action, **change)
    result = await harness.tier().evaluate(event=_event())
    assert result.retained_pattern_comparison is not None
    assert result.retained_pattern_comparison.stop_reason == reason


async def test_one_positive_one_negative_is_not_proven_even_with_resolver_statistics() -> None:
    harness = await _retained(positives=1)
    comparison = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
    assert comparison is not None and comparison.challenger_match is None
    assert comparison.stop_reason == "retained_pattern_insufficient_positive_cases"
    assert comparison.audit_mapping()["operationally_proven"] is False


@pytest.mark.parametrize("missing", ["registration", "read_admission", "reuse_admission"])
async def test_registration_and_independent_admissions_are_required(missing: str) -> None:
    harness = await _retained()
    if missing == "registration":
        harness.registry.clear()
    elif missing == "read_admission":
        harness.admission.allowed = False
    verifier = _Verifier(decision_evidence=None) if missing == "reuse_admission" else _Verifier()
    result = await harness.tier(verifier=verifier).evaluate(event=_event())
    comparison = result.retained_pattern_comparison
    assert comparison is not None and comparison.challenger_match is None
    assert comparison.stop_reason is not None and result.reason == "no_neighbour_found"


async def test_negative_member_deleted_during_current_verification_clears_candidates() -> None:
    harness = await _retained()

    class _DeleteDuring(_Verifier):
        async def verify(self, **values: Any) -> Any:
            record = await harness.metadata.latest(
                harness.cases[-1].case_id, access_scope_digest="f" * 64
            )
            assert record is not None and record.storage_ref is not None
            await harness.artifacts.delete(record.storage_ref)
            return await super().verify(**values)  # type: ignore[no-untyped-call]

    comparison = (
        await harness.tier(verifier=_DeleteDuring()).evaluate(event=_event())
    ).retained_pattern_comparison
    assert comparison is not None and comparison.stop_reason == "retained_pattern_source_changed"
    assert not comparison.candidates and comparison.challenger_match is None


@pytest.mark.parametrize("failure", [LookupError, PermissionError, RuntimeError])
async def test_baseline_provider_failure_never_uses_retained_source(
    failure: type[Exception],
) -> None:
    harness = await _retained()

    class _Failing(_Library):
        async def search(self, *args: Any, **kwargs: Any) -> Any:
            raise failure("provider failed")

    result = await harness.tier(library=_Failing(())).evaluate(event=_event())
    assert result.reason == f"t1_provider_error:{failure.__name__}" and harness.calls == 0
    assert result.retained_pattern_comparison is not None
    assert result.retained_pattern_comparison.stop_reason == "baseline_comparison_stopped"


async def test_source_timeout_preserves_completed_baseline_and_existing_comparison() -> None:
    harness = await _retained()
    library = _Library((SimilarityMatch(replace(harness.action, operational_case=None), 0.99),))
    library.matches = (
        replace(library.matches[0], action=replace(library.matches[0].action, rule_id="baseline")),
    )
    baseline = await harness.tier(compare=False, library=library).evaluate(event=_event())

    async def blocked(event: Event) -> RetainedPatternRequest:
        await asyncio.Event().wait()
        return harness.request

    harness.source._request_source = blocked
    result = await harness.tier(library=library, timeout=0.02).evaluate(event=_event())
    assert _actual(result) == baseline and result.eligibility_comparison is not None
    assert result.eligibility_comparison.challenger_match is library.matches[0]
    assert result.retained_pattern_comparison is not None
    assert result.retained_pattern_comparison.stop_reason == "t1_deadline_exceeded"


async def test_caller_cancellation_propagates_from_intake() -> None:
    harness = await _retained()

    async def cancelled(event: Event) -> RetainedPatternRequest:
        raise asyncio.CancelledError

    harness.source._request_source = cancelled
    with pytest.raises(asyncio.CancelledError):
        await harness.tier().evaluate(event=_event())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"patterns": [None]},
        None,
        {
            "patterns": [{}],
            "unavailable": False,
            "truncated": False,
            "execution_authority": False,
        },
    ],
)
async def test_malformed_query_is_bounded_and_does_not_change_baseline(response: Any) -> None:
    harness = await _retained()

    async def malformed(
        arguments: Mapping[str, Any], context: FunctionInvocationContext
    ) -> dict[str, Any]:
        return cast(dict[str, Any], response)

    harness.query.read = malformed  # type: ignore[method-assign]
    result = await harness.tier().evaluate(event=_event())
    comparison = result.retained_pattern_comparison
    assert comparison is not None
    assert comparison.stop_reason == "retained_pattern_error:ValueError"
    assert result.reason == "no_neighbour_found"


async def test_concrete_server_bindings_are_event_and_pattern_scoped() -> None:
    harness = await _retained()
    assert harness.statistics is not None
    bound = BoundRetainedPatternAction(
        str(_event().event_id),
        harness.action.signature,
        SimilarityMatch(harness.action, 0.98),
        harness.statistics.evidence_ref,
        harness.read_statistics,
    )
    request = BoundRetainedPatternRequest(str(_event().event_id), harness.request)
    harness.source = RetainedPatternSource(
        query=harness.query,
        request_source=request,
        action_resolver=bound.resolve,
        action_types=lambda: harness.registry,
        store=harness.durable,
        materializer=lambda: harness.materializer,
        statistics_source=bound.read_statistics,
        clock=lambda: harness.now,
    )
    result = await harness.tier().evaluate(event=_event())
    assert result.retained_pattern_comparison is not None
    assert result.retained_pattern_comparison.challenger_match is None
    assert (
        result.retained_pattern_comparison.stop_reason
        == "retained_pattern_qualification_unavailable"
    )
    changed_event = _event().model_copy(update={"event_id": _event().event_id.__class__(int=2)})
    assert await request(changed_event) is None
    assert await bound.resolve(_event(), {"pattern_id": "0" * 64}) is None
    assert await bound.read_statistics(changed_event, bound.match) is None
    no_prov = replace(bound, statistics_provider=None)
    assert await no_prov.read_statistics(_event(), bound.match) is None
    assert await bound.read_statistics(_event(), bound.match) is harness.statistics
    harness.statistics = None
    assert await bound.read_statistics(_event(), bound.match) is None


@pytest.mark.parametrize("change", ["absent", "expired", "counts", "scope", "denominator"])
async def test_independent_measured_statistics_are_required(change: str) -> None:
    harness = await _retained()
    assert harness.statistics is not None
    if change == "absent":
        harness.statistics = None
    elif change == "expired":
        harness.now = T0 + timedelta(minutes=6)
    elif change == "counts":
        harness.statistics = replace(harness.statistics, technical_failures=2)
    elif change == "scope":
        harness.statistics = replace(harness.statistics, access_scope_digest="e" * 64)
    else:
        harness.action = replace(harness.action, success_rate=2 / 3, reuse_count=3)
    comparison = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
    assert comparison is not None and comparison.challenger_match is None
    assert comparison.stop_reason == "retained_pattern_statistics_unavailable"


async def test_negative_case_cannot_be_the_reusable_action_origin() -> None:
    harness = await _retained()
    assert harness.action.operational_case is not None
    negative = harness.cases[-1]
    harness.action = replace(
        harness.action,
        incident_id=negative.case_id,
        operational_case=replace(
            harness.action.operational_case, case_ref=negative.immutable_case_ref
        ),
    )
    comparison = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
    assert comparison is not None and comparison.challenger_match is None
    assert comparison.stop_reason == "retained_pattern_positive_case_required"


@pytest.mark.parametrize("failure_stage", ["request", "resolver", "statistics"])
async def test_optional_provider_failures_are_typed_without_provider_text(
    failure_stage: str,
) -> None:
    harness = await _retained()

    async def failed(*args: Any) -> Any:
        raise PermissionError("private provider text")

    if failure_stage == "request":
        harness.source._request_source = failed
    elif failure_stage == "resolver":
        harness.source._resolve = failed
    else:
        harness.source._statistics_source = failed
    result = await harness.tier().evaluate(event=_event())
    comparison = result.retained_pattern_comparison
    assert comparison is not None and not comparison.candidates
    assert comparison.stop_reason == "retained_pattern_error:PermissionError"
    assert "private" not in str((await _audit(result))["t1_retained_pattern_comparison"])


@pytest.mark.parametrize("withdrawal", ["read_admission", "statistics", "registry"])
async def test_withdrawn_source_or_admission_cannot_survive_final_read(withdrawal: str) -> None:
    harness = await _retained()

    class _Withdraw(_Verifier):
        async def verify(self, **values: Any) -> Any:
            result = await super().verify(**values)  # type: ignore[no-untyped-call]
            if withdrawal == "read_admission":
                harness.admission.allowed = False
            elif withdrawal == "statistics":
                harness.statistics = None
            else:
                harness.registry.clear()
            return result

    result = await harness.tier(verifier=_Withdraw()).evaluate(event=_event())
    comparison = result.retained_pattern_comparison
    assert (
        comparison is not None and not comparison.candidates and comparison.challenger_match is None
    )
    assert comparison.stop_reason in (
        "retained_pattern_error:PermissionError",
        "retained_pattern_evidence_changed",
    )


async def test_baseline_policy_denial_cannot_be_bypassed_by_the_isolated_source() -> None:
    harness = await _retained()
    library = _Library((SimilarityMatch(harness.action, 0.99),))
    result = await harness.tier(library=library, verifier=_Verifier(policy_allowed=False)).evaluate(
        event=_event()
    )
    assert result.outcome is T1Outcome.ABSTAIN and "current_policy_denied" in result.reasons
    assert result.retained_pattern_comparison is not None and harness.calls == 0
    assert result.retained_pattern_comparison.stop_reason == "baseline_comparison_stopped"


async def test_baseline_timeout_does_not_start_any_optional_intake() -> None:
    harness = await _retained()

    class _Blocked(_Library):
        async def search(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.Event().wait()

    for compare in (False, True):
        result = await harness.tier(compare=compare, library=_Blocked(()), timeout=0.01).evaluate(
            event=_event()
        )
        assert (
            result.reason == "t1_deadline_exceeded" and result.retained_pattern_comparison is None
        )
    assert harness.calls == 0


async def test_registered_argument_schema_never_resolves_remote_references() -> None:
    harness = await _retained()
    registered = harness.registry[harness.action.action_type]
    for schema in ({"$ref": "https://example.com/action-schema"}, None):
        harness.registry[registered.name] = registered.model_copy(
            update={"argument_schema": schema}
        )
        comparison = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
        assert (
            comparison is not None
            and comparison.stop_reason == "retained_pattern_argument_schema_unavailable"
        )


async def test_measurement_expiry_during_final_authorized_read_clears_eligibility() -> None:
    harness = await _retained()
    reads = 0

    async def statistics(event: Event, match: SimilarityMatch) -> RetainedReuseStatistics | None:
        nonlocal reads
        reads += 1
        if reads == 2:
            harness.now += timedelta(minutes=6)
        return harness.statistics

    harness.source._statistics_source = statistics
    comparison = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
    assert comparison is not None and comparison.stop_reason == "retained_pattern_evidence_changed"
    assert not comparison.candidates and comparison.challenger_match is None


def _lease_for(
    bound: RetainedPatternQualification, *, active: bool = True
) -> RetainedPatternLeaseEvidence:
    val = bound.descriptor
    read, reuse = val["read"], val["reuse"]
    args, principal = read["arguments"], read["principal"]
    raw_reuse = dict(reuse["admission"])
    raw_reuse["verified_at"] = datetime.fromisoformat(raw_reuse["verified_at"])
    raw_reuse["valid_until"] = datetime.fromisoformat(raw_reuse["valid_until"])
    scope = {
        "principal_scope": principal["principal_scope_digest"],
        "case_scope": args["access_scope_digest"],
        "purpose": args["purpose"],
    }
    ev_dig = content_digest({"arguments": args, "principal": principal})
    adm_args = ("sha256:" + "a" * 64, "sha256:" + "b" * 64, ev_dig, content_digest(scope))
    read_adm = DecisionEvidenceAdmission(
        *adm_args, "case-history-read", read["source_revision"], T0, T0 + timedelta(days=1)
    )
    l_args = (bound.evidence_digest, bound.scope_digest, "sha256:" + "d" * 64)
    return RetainedPatternLeaseEvidence(
        *l_args,
        T0 + timedelta(minutes=10),
        read_adm,
        DecisionEvidenceAdmission(**raw_reuse),
        LeaseGuard(active=active),
    )


class _LeasedStub:
    def __init__(self, mode: str, harness: _Harness) -> None:
        self._mode, self._harness = mode, harness

    @asynccontextmanager
    async def lease(self, req: RetainedPatternQualification) -> AsyncIterator[Any]:
        if self._mode == "lease_stale":
            self._harness.now = T0 + timedelta(minutes=6)
        yield (
            None
            if self._mode == "lease_none"
            else _lease_for(req, active=self._mode != "lease_inactive")
        )


class _FinalStub:
    def __init__(self, mode: str) -> None:
        self._mode = mode

    async def qualify(self, req: RetainedPatternQualification) -> Any:
        if self._mode == "final_none":
            return None
        purpose = "wrong" if self._mode == "final_bad_purpose" else FINAL_QUALIFICATION_PURPOSE
        exp = T0 + timedelta(seconds=1) if self._mode == "final_expired" else T0 + timedelta(days=1)
        f_args = ("sha256:" + "a" * 64, "sha256:" + "b" * 64, req.evidence_digest, req.scope_digest)
        return DecisionEvidenceAdmission(*f_args, purpose, req.evidence_digest, T0, exp)


@pytest.mark.parametrize(
    "mode",
    (
        "lease_ok lease_none lease_inactive lease_stale final_ok final_none "
        "final_expired final_bad_purpose no_request bad_request no_materializer "
        "no_match bad_match bad_score"
    ).split(),
)
async def test_leased_and_final_qualifiers_and_boundary_guards(mode: str) -> None:
    harness = await _retained()
    with pytest.raises(ValueError):
        RetainedPatternRequest(harness.request.context, "bad", "purpose", "f" * 64)
    src = harness.source
    if mode.startswith("lease"):
        src._leased_qualifier = _LeasedStub(mode, harness)
    elif mode.startswith("final"):
        src._final_qualifier = _FinalStub(mode)
    elif mode in ("no_request", "bad_request"):
        res = None if mode == "no_request" else cast(Any, "bad")
        src._request_source = lambda _e: asyncio.sleep(0, result=res)
    elif mode == "no_materializer":
        src._materializer = lambda: None
    else:
        res_m = (
            None
            if mode == "no_match"
            else (cast(Any, "bad") if mode == "bad_match" else SimilarityMatch(harness.action, 2.0))
        )
        src._resolve = lambda _e, _s: asyncio.sleep(0, result=res_m)
    comp = (await harness.tier().evaluate(event=_event())).retained_pattern_comparison
    assert comp is not None
    if mode in ("lease_ok", "final_ok"):
        assert comp.challenger_match is not None and comp.audit_mapping()["eligible_count"] == 1
    else:
        assert comp.challenger_match is None and comp.stop_reason is not None

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest
from fdai.core.ontology_platform.query_execution import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.rca.discrimination import (
    ExpectedObservationOutcome,
    HypothesisOutcomePrediction,
    build_discriminating_observation_candidate,
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.read_investigation.adaptive import (
    AdaptiveInvestigationCoordinator,
    AdaptiveRoundProposal,
    VerifiedObservationGateway,
)
from fdai.core.read_investigation.adaptive_codec import (
    adaptive_result_from_mapping,
    adaptive_result_to_mapping,
)
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    AdaptiveQueryAuthorityContext,
    build_adaptive_investigation_iteration,
    build_adaptive_investigation_result,
    build_hypothesis_revision_set,
    build_verified_observation_plan_binding,
    execution_result_digest,
    validate_query_manifest_snapshot,
)
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    StructuralCoverageReceipt,
    TaskStatus,
    content_digest,
)

NOW = datetime(2026, 8, 30, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"


def _frame(
    *,
    hypotheses: tuple[str, ...] = ("hypothesis-a", "hypothesis-b"),
    active_set_digest: str = DIGEST_A,
):
    return build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision="graph-1",
        evidence_cutoff=NOW,
        active_hypothesis_ids=hypotheses,
        active_set_receipt_digest=active_set_digest,
        cost_model_digest=DIGEST_B,
    )


def _plan(
    *,
    role: str = "reader",
    manifest: QueryManifest | None = None,
) -> OntologyQueryPlan:
    selected_manifest = manifest or _manifest(role=CeilingRole(role))
    node = OntologyQueryNode(
        node_id="observe",
        kind=QueryNodeKind.FUNCTION,
        arguments_json="{}",
        output_kind="query.table",
    )
    material = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST_A,
        "semantic_catalog_digest": selected_manifest.manifest_digest,
        "problem_frame_digest": DIGEST_A,
        "purpose": "operations-review",
        "caller_role": role,
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": ("observe",),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=DIGEST_A,
        semantic_catalog_digest=selected_manifest.manifest_digest,
        problem_frame_digest=DIGEST_A,
        purpose="operations-review",
        caller_role=role,
        nodes=(node,),
        output_node_ids=("observe",),
        plan_digest=content_digest(material),
    )


def _manifest(*, role: CeilingRole = CeilingRole.READER) -> QueryManifest:
    manifest_digest = content_digest(
        {
            "release_digest": DIGEST_A,
            "principal_role": role.value,
            "purposes": ("operations-review",),
            "descriptors": (),
            "unavailable": (),
            "mutation_authority": False,
        }
    )
    coverage = StructuralCoverageReceipt(
        ontology_release_digest=DIGEST_A,
        principal_scope_digest=DIGEST_A,
        readable_declaration_count=0,
        descriptor_count=0,
        unavailable_declaration_ids=(),
        manifest_digest=manifest_digest,
        complete=True,
        receipt_digest=content_digest(
            {
                "schema_version": "1.0.0",
                "ontology_release_digest": DIGEST_A,
                "principal_scope_digest": DIGEST_A,
                "readable_declaration_count": 0,
                "descriptor_count": 0,
                "unavailable_declaration_ids": (),
                "manifest_digest": manifest_digest,
                "complete": True,
            }
        ),
    )
    return QueryManifest(
        release_digest=DIGEST_A,
        principal_role=role,
        purposes=("operations-review",),
        descriptors=(),
        unavailable=(),
        manifest_digest=manifest_digest,
        coverage_receipt=coverage,
    )


def _proposal(frame, *, cost_units: int = 10) -> AdaptiveRoundProposal:
    manifest = _manifest()
    binding = build_verified_observation_plan_binding(
        frame_digest=frame.frame_digest,
        plan=_plan(manifest=manifest),
        manifest=manifest,
        principal_scope_digest=DIGEST_A,
        cost_units=cost_units,
    )
    candidate = build_discriminating_observation_candidate(
        frame=frame,
        observation_ref="query:resource-health",
        verified_query_receipt_digest=binding.verification_receipt_digest,
        cost_units=cost_units,
        predictions=tuple(
            HypothesisOutcomePrediction(
                hypothesis_id=hypothesis_id,
                outcome=(
                    ExpectedObservationOutcome.SUPPORTS
                    if index == 0
                    else ExpectedObservationOutcome.REFUTES
                ),
            )
            for index, hypothesis_id in enumerate(frame.active_hypothesis_ids)
        ),
    )
    return AdaptiveRoundProposal(
        frame_digest=frame.frame_digest,
        candidates=(candidate,),
        bindings=(binding,),
    )


class _RoundSource:
    async def propose(self, frame):
        return _proposal(frame)


class _Verifier:
    def verify(self, plan, *, manifest):
        assert manifest.release_digest == plan.ontology_release_digest
        return plan


class _Executor:
    async def execute(self, plan, **kwargs):
        assert kwargs["cancelled"].is_set() is False
        receipt = GoalTaskReceipt(
            task_id="task-1",
            goal_id="observe",
            intent="investigate",
            evidence_mode=GoalEvidenceMode.OPERATIONAL,
            status=TaskStatus.COMPLETED,
            duration_ms=10,
            evidence_refs=("evidence:health",),
            started_at=NOW,
            completed_at=NOW,
        )
        return QueryPlanExecution(
            plan_digest=plan.plan_digest,
            status="completed",
            results=MappingProxyType({}),
            receipts=(receipt,),
            output_node_ids=plan.output_node_ids,
        )


class _StatusExecutor(_Executor):
    def __init__(self, status: str, after_execute: object | None = None) -> None:
        self.status = status
        self.after_execute = after_execute

    async def execute(self, plan, **kwargs):
        result = await super().execute(plan, **kwargs)
        if callable(self.after_execute):
            self.after_execute()
        return QueryPlanExecution(
            plan_digest=result.plan_digest,
            status=self.status,
            results=result.results,
            receipts=result.receipts,
            output_node_ids=result.output_node_ids,
        )


class _Reviser:
    def __init__(
        self,
        dispositions: tuple[AdaptiveInvestigationDisposition, ...],
    ) -> None:
        self.dispositions = list(dispositions)

    async def revise(self, *, frame, execution):
        disposition = self.dispositions.pop(0)
        active = (
            ("hypothesis-a",)
            if disposition is AdaptiveInvestigationDisposition.CONVERGED
            else frame.active_hypothesis_ids
        )
        return build_hypothesis_revision_set(
            prior_active_set_receipt_digest=frame.active_set_receipt_digest,
            prior_frame_digest=frame.frame_digest,
            observation_result_digest=execution.result_digest,
            scorer_version="forseti-scorer-v1",
            graph_revision="graph-2",
            evidence_cutoff=NOW + timedelta(seconds=1),
            active_hypothesis_ids=active,
            active_set_receipt_digest=content_digest({"active": active}),
            evidence_refs=("evidence:health",),
            complete=True,
            truncated=False,
            disposition=disposition,
        )


class _ShadowSink:
    def __init__(self) -> None:
        self.comparisons = []

    async def record(self, comparison) -> None:
        self.comparisons.append(comparison)


class _FailingShadowSink:
    async def record(self, comparison) -> None:
        raise RuntimeError("shadow sink unavailable")


class _CancelledShadowSink:
    async def record(self, comparison) -> None:
        raise asyncio.CancelledError


class _HangingShadowSink:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def record(self, comparison) -> None:
        self.started.set()
        await self.release.wait()


def _coordinator(reviser, **kwargs):
    return AdaptiveInvestigationCoordinator(
        round_source=_RoundSource(),
        reviser=reviser,
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_Executor(),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=kwargs.pop("clock", lambda: NOW),
        **kwargs,
    )


def _budget(**overrides):
    values = {
        "max_rounds": 3,
        "max_queries": 3,
        "max_cost_units": 100,
        "deadline_at": NOW + timedelta(minutes=5),
        "policy_digest": DIGEST_B,
    }
    values.update(overrides)
    return AdaptiveInvestigationBudget(**values)


async def test_converges_after_verified_observation() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,))
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CONVERGED
    assert result.used_queries == 1
    assert result.used_cost_units == 10
    assert result.iterations[0].execution is not None
    assert result.iterations[0].revision is not None
    assert result.terminal_active_set_receipt_digest == (
        result.iterations[0].revision.active_set_receipt_digest
    )
    assert result.execution_authority is False


async def test_continues_with_exact_revision_then_converges() -> None:
    result = await _coordinator(
        _Reviser(
            (
                AdaptiveInvestigationDisposition.CONTINUE,
                AdaptiveInvestigationDisposition.CONVERGED,
            )
        )
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    assert len(result.iterations) == 2
    assert result.iterations[1].frame.frame_digest != result.iterations[0].frame.frame_digest
    assert result.used_queries == 2


async def test_shadow_comparison_is_recorded_but_active_selection_executes() -> None:
    sink = _ShadowSink()
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        challenger_strategy_digest=DIGEST_B,
        challenger_selector=select_discriminating_observation,
        shadow_sink=sink,
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    await asyncio.sleep(0)
    assert len(sink.comparisons) == 1
    assert result.iterations[0].shadow_comparison_digest == (sink.comparisons[0].comparison_digest)
    assert result.iterations[0].execution is not None
    assert sink.comparisons[0].active_recommendation is not None
    assert result.iterations[0].execution.selection_digest == (
        sink.comparisons[0].active_recommendation.selection_digest
    )


async def test_shadow_sink_failure_does_not_block_active_selection() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        challenger_strategy_digest=DIGEST_B,
        challenger_selector=select_discriminating_observation,
        shadow_sink=_FailingShadowSink(),
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    await asyncio.sleep(0)
    assert result.disposition is AdaptiveInvestigationDisposition.CONVERGED
    assert result.iterations[0].execution is not None
    assert result.iterations[0].shadow_comparison_digest is None


async def test_shadow_sink_task_cancellation_does_not_block_active_selection() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        challenger_strategy_digest=DIGEST_B,
        challenger_selector=select_discriminating_observation,
        shadow_sink=_CancelledShadowSink(),
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CONVERGED
    assert result.iterations[0].execution is not None
    assert result.iterations[0].shadow_comparison_digest is None


async def test_parent_cancellation_is_not_swallowed_while_waiting_for_shadow() -> None:
    sink = _HangingShadowSink()
    investigation = asyncio.create_task(
        _coordinator(
            _Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
            challenger_strategy_digest=DIGEST_B,
            challenger_selector=select_discriminating_observation,
            shadow_sink=sink,
        ).investigate(
            session_id="session-1",
            initial_frame=_frame(),
            budget=_budget(),
        )
    )
    await sink.started.wait()

    investigation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await investigation
    sink.release.set()
    await asyncio.sleep(0)


async def test_cancelled_before_round_performs_no_query() -> None:
    cancelled = asyncio.Event()
    cancelled.set()

    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,))
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
        cancelled=cancelled,
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CANCELLED
    assert result.iterations == ()
    assert result.used_queries == 0


async def test_cancellation_during_proposal_consumes_no_query_or_cost() -> None:
    cancelled = asyncio.Event()

    class CancellingSource:
        async def propose(self, frame):
            cancelled.set()
            return _proposal(frame)

    coordinator = AdaptiveInvestigationCoordinator(
        round_source=CancellingSource(),
        reviser=_Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_Executor(),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await coordinator.investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
        cancelled=cancelled,
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CANCELLED
    assert result.used_queries == 0
    assert result.used_cost_units == 0
    assert result.iterations == ()


async def test_expired_deadline_times_out_without_provider_io() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        clock=lambda: NOW + timedelta(minutes=10),
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.TIMED_OUT
    assert result.used_queries == 0


async def test_deadline_bounds_hanging_round_source() -> None:
    class HangingSource:
        async def propose(self, frame):
            await asyncio.sleep(1)
            return _proposal(frame)

    coordinator = AdaptiveInvestigationCoordinator(
        round_source=HangingSource(),
        reviser=_Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_Executor(),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await coordinator.investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(deadline_at=NOW + timedelta(milliseconds=10)),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.TIMED_OUT
    assert result.used_queries == 0


async def test_cost_is_reserved_before_dispatch() -> None:
    class ExpensiveSource:
        async def propose(self, frame):
            return _proposal(frame, cost_units=11)

    coordinator = AdaptiveInvestigationCoordinator(
        round_source=ExpensiveSource(),
        reviser=_Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_Executor(),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await coordinator.investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(max_cost_units=10),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.COST_EXHAUSTED
    assert result.used_queries == 0


async def test_non_completed_query_holds_without_hypothesis_revision() -> None:
    coordinator = AdaptiveInvestigationCoordinator(
        round_source=_RoundSource(),
        reviser=_Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_StatusExecutor("partial"),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await coordinator.investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    assert result.iterations[0].execution is not None
    assert result.iterations[0].revision is None


async def test_cancellation_after_query_blocks_revision() -> None:
    cancelled = asyncio.Event()
    coordinator = AdaptiveInvestigationCoordinator(
        round_source=_RoundSource(),
        reviser=_Reviser((AdaptiveInvestigationDisposition.CONVERGED,)),
        gateway=VerifiedObservationGateway(
            verifier=_Verifier(),  # type: ignore[arg-type]
            executor=_StatusExecutor("completed", cancelled.set),  # type: ignore[arg-type]
            authority=AdaptiveQueryAuthorityContext(
                manifest=_manifest(),
                principal_scope_digest=DIGEST_A,
                caller_role="reader",
                purpose="operations-review",
            ),
        ),
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await coordinator.investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
        cancelled=cancelled,
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CANCELLED
    assert result.iterations[0].revision is None


async def test_round_exhaustion_is_terminal_and_bounded() -> None:
    result = await _coordinator(_Reviser((AdaptiveInvestigationDisposition.CONTINUE,))).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(max_rounds=1),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.ROUND_EXHAUSTED
    assert len(result.iterations) == 1


def test_round_proposal_rejects_substituted_binding_set() -> None:
    frame = _frame()
    proposal = _proposal(frame)
    other = _proposal(_frame(active_set_digest=content_digest({"other": True})))

    with pytest.raises(ValueError, match="does not match the frame"):
        AdaptiveRoundProposal(
            frame_digest=frame.frame_digest,
            candidates=proposal.candidates,
            bindings=other.bindings,
        )


def test_round_proposal_rejects_candidate_cost_substitution() -> None:
    frame = _frame()
    proposal = _proposal(frame, cost_units=10)
    candidate = build_discriminating_observation_candidate(
        frame=frame,
        observation_ref="query:discounted",
        verified_query_receipt_digest=(proposal.bindings[0].verification_receipt_digest),
        cost_units=1,
        predictions=proposal.candidates[0].predictions,
    )

    with pytest.raises(ValueError, match="candidate cost"):
        AdaptiveRoundProposal(
            frame_digest=frame.frame_digest,
            candidates=(candidate,),
            bindings=proposal.bindings,
        )


async def test_revision_must_descend_from_prior_active_set() -> None:
    class BadReviser(_Reviser):
        async def revise(self, *, frame, execution):
            revision = await super().revise(frame=frame, execution=execution)
            return build_hypothesis_revision_set(
                prior_active_set_receipt_digest=DIGEST_B,
                prior_frame_digest=revision.prior_frame_digest,
                observation_result_digest=revision.observation_result_digest,
                scorer_version=revision.scorer_version,
                graph_revision=revision.graph_revision,
                evidence_cutoff=revision.evidence_cutoff,
                active_hypothesis_ids=revision.active_hypothesis_ids,
                active_set_receipt_digest=revision.active_set_receipt_digest,
                evidence_refs=revision.evidence_refs,
                complete=revision.complete,
                truncated=revision.truncated,
                disposition=revision.disposition,
            )

    with pytest.raises(ValueError, match="prior active set"):
        await _coordinator(BadReviser((AdaptiveInvestigationDisposition.CONVERGED,))).investigate(
            session_id="session-1",
            initial_frame=_frame(),
            budget=_budget(),
        )


def test_binding_rejects_principal_scope_substitution() -> None:
    with pytest.raises(ValueError, match="principal scope"):
        build_verified_observation_plan_binding(
            frame_digest=_frame().frame_digest,
            plan=_plan(),
            manifest=_manifest(),
            principal_scope_digest=DIGEST_B,
            cost_units=1,
        )


def test_query_result_digest_binds_observed_values() -> None:
    first = QueryPlanExecution(
        plan_digest=DIGEST_A,
        status="completed",
        results=MappingProxyType({"observe": QueryNodeResult(value={"state": "healthy"})}),
        receipts=(),
        output_node_ids=("observe",),
    )
    changed = QueryPlanExecution(
        plan_digest=DIGEST_A,
        status="completed",
        results=MappingProxyType({"observe": QueryNodeResult(value={"state": "degraded"})}),
        receipts=(),
        output_node_ids=("observe",),
    )

    assert execution_result_digest(first) != execution_result_digest(changed)


def test_query_result_digest_accepts_large_valid_query_table() -> None:
    table = QueryTable(
        rows=(
            QueryRow.from_values("row-1", {"payload": "a" * 40_000}),
            QueryRow.from_values("row-2", {"payload": "b" * 40_000}),
        ),
        complete=True,
    )
    execution = QueryPlanExecution(
        plan_digest=DIGEST_A,
        status="completed",
        results=MappingProxyType({"observe": QueryNodeResult(value=table)}),
        receipts=(),
        output_node_ids=("observe",),
    )

    assert execution_result_digest(execution).startswith("sha256:")


def test_query_manifest_mutation_is_detected_before_reuse() -> None:
    descriptor = {"kind": "function", "name": "observe"}
    manifest_digest = content_digest(
        {
            "release_digest": DIGEST_A,
            "principal_role": "reader",
            "purposes": ("operations-review",),
            "descriptors": (descriptor,),
            "unavailable": (),
            "mutation_authority": False,
        }
    )
    coverage = StructuralCoverageReceipt(
        ontology_release_digest=DIGEST_A,
        principal_scope_digest=DIGEST_A,
        readable_declaration_count=1,
        descriptor_count=1,
        unavailable_declaration_ids=(),
        manifest_digest=manifest_digest,
        complete=True,
        receipt_digest=content_digest(
            {
                "schema_version": "1.0.0",
                "ontology_release_digest": DIGEST_A,
                "principal_scope_digest": DIGEST_A,
                "readable_declaration_count": 1,
                "descriptor_count": 1,
                "unavailable_declaration_ids": (),
                "manifest_digest": manifest_digest,
                "complete": True,
            }
        ),
    )
    manifest = QueryManifest(
        release_digest=DIGEST_A,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        descriptors=(descriptor,),
        unavailable=(),
        manifest_digest=manifest_digest,
        coverage_receipt=coverage,
    )
    AdaptiveQueryAuthorityContext(
        manifest=manifest,
        principal_scope_digest=DIGEST_A,
        caller_role="reader",
        purpose="operations-review",
    )

    descriptor["name"] = "substituted"

    with pytest.raises(ValueError, match="manifest digest"):
        validate_query_manifest_snapshot(manifest)


async def test_gateway_rejects_substituted_principal_before_verifier_or_io() -> None:
    frame = _frame()
    owner_manifest = _manifest(role=CeilingRole.OWNER)
    binding = build_verified_observation_plan_binding(
        frame_digest=frame.frame_digest,
        plan=_plan(role="owner", manifest=owner_manifest),
        manifest=owner_manifest,
        principal_scope_digest=DIGEST_A,
        cost_units=1,
    )
    candidate = build_discriminating_observation_candidate(
        frame=frame,
        observation_ref="query:owner-only",
        verified_query_receipt_digest=binding.verification_receipt_digest,
        cost_units=1,
        predictions=(
            HypothesisOutcomePrediction(
                "hypothesis-a",
                ExpectedObservationOutcome.SUPPORTS,
            ),
            HypothesisOutcomePrediction(
                "hypothesis-b",
                ExpectedObservationOutcome.REFUTES,
            ),
        ),
    )
    selection = select_discriminating_observation(frame, (candidate,))
    calls = {"verify": 0, "execute": 0}

    class SpyVerifier:
        def verify(self, plan, *, manifest):
            calls["verify"] += 1
            return plan

    class SpyExecutor:
        async def execute(self, plan, **kwargs):
            calls["execute"] += 1
            raise AssertionError("provider I/O must not start")

    gateway = VerifiedObservationGateway(
        verifier=SpyVerifier(),  # type: ignore[arg-type]
        executor=SpyExecutor(),  # type: ignore[arg-type]
        authority=AdaptiveQueryAuthorityContext(
            manifest=_manifest(),
            principal_scope_digest=DIGEST_A,
            caller_role="reader",
            purpose="operations-review",
        ),
    )

    with pytest.raises((PermissionError, ValueError), match="query manifest|caller role"):
        await gateway.execute(
            round_index=1,
            frame=frame,
            selection=selection,
            candidate=candidate,
            binding=binding,
            cancelled=asyncio.Event(),
        )

    assert calls == {"verify": 0, "execute": 0}


async def test_terminal_result_rejects_mutable_history_and_counter_substitution() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,))
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    with pytest.raises(ValueError, match="immutable typed tuple"):
        replace(result, iterations=list(result.iterations))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query count"):
        replace(result, used_queries=0)
    with pytest.raises(ValueError, match="cost does not match"):
        replace(result, used_cost_units=0)
    with pytest.raises(ValueError, match="terminal active-set"):
        replace(result, terminal_active_set_receipt_digest=DIGEST_A)
    execution = result.iterations[0].execution
    assert execution is not None
    with pytest.raises(ValueError, match="execution digest"):
        replace(execution, evidence_refs=("evidence:forged",))


async def test_terminal_result_codec_revalidates_complete_execution_lineage() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,))
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    restored = adaptive_result_from_mapping(adaptive_result_to_mapping(result))

    assert restored == result


def test_iteration_rejects_boolean_round_identity() -> None:
    frame = _frame()
    selection = select_discriminating_observation(frame, ())

    with pytest.raises(ValueError, match="round_index"):
        build_adaptive_investigation_iteration(
            round_index=True,  # type: ignore[arg-type]
            frame=frame,
            selection=selection,
            execution=None,
            revision=None,
        )


def test_converged_result_requires_terminal_hypothesis_revision() -> None:
    frame = _frame()

    with pytest.raises(ValueError, match="matching hypothesis revision"):
        build_adaptive_investigation_result(
            session_id="session-1",
            incident_id="incident-1",
            workflow_version="1.0.0",
            active_strategy_digest=DIGEST_A,
            challenger_strategy_digest=None,
            budget=_budget(),
            iterations=(),
            disposition=AdaptiveInvestigationDisposition.CONVERGED,
            terminal_frame_digest=frame.frame_digest,
            terminal_active_set_receipt_digest=frame.active_set_receipt_digest,
            used_queries=0,
            used_cost_units=0,
        )

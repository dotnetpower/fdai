"""Tests for review, projection, reconciliation, and retirement planning."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.rule_catalog.pipeline.distill.freshness import RetirementRequest
from fdai.rule_catalog.pipeline.distill.ontology_lifecycle import (
    ProjectionPlan,
    ProposalLifecycleRecord,
    ReconciliationOutcome,
    SourceProjectionRecord,
    advance_lifecycle,
    build_projection_plan,
    plan_access_revocation,
    plan_source_retirement,
    reconcile_projection,
    record_projection,
    record_reconciliation,
    start_lifecycle,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    EntityResolution,
    GateOutcome,
    GateReceipt,
    OntologyChangeProposal,
    OntologyOperation,
    OntologyTargetKind,
    ProposalState,
    SourceEvidence,
    VerifiedOntologyProposal,
)


def _verified() -> VerifiedOntologyProposal:
    evidence = SourceEvidence(
        "doc:a",
        "a",
        "rev-1",
        "a" * 64,
        1,
        1,
        "b" * 64,
        "manual",
        "line-1",
        "line:1",
    )
    proposal = OntologyChangeProposal(
        proposal_id="odp-1",
        extraction_run_id="run-1",
        candidate_id="candidate-1",
        claim_id="claim-1",
        operation=OntologyOperation.UPDATE,
        target_kind=OntologyTargetKind.OBJECT,
        target_type="BusinessService",
        target_identity="service:a",
        ontology_release="a" * 64,
        expected_graph_revision="graph-1",
        authority=AuthorityClass.DECLARED_INTENT,
        evidence=evidence,
        entity_resolution=EntityResolution("service:a", ("service:a",), "exact"),
    )
    return VerifiedOntologyProposal(
        proposal=proposal,
        state=ProposalState.REVIEW_REQUIRED,
        receipts=(
            GateReceipt("shape", GateOutcome.PASS),
            GateReceipt("promotion_policy", GateOutcome.REVIEW, ("review_only",)),
        ),
    )


def _approved():
    verified = _verified()
    started = start_lifecycle(verified, graph_revision="graph-1")
    return verified, advance_lifecycle(
        started,
        target=ProposalState.APPROVED,
        transition_ref="approval:1",
    )


def test_projection_requires_exact_current_revision() -> None:
    verified, approved = _approved()
    stale = type(approved)(
        proposal_digest=approved.proposal_digest,
        state=approved.state,
        revision=approved.revision,
        current_graph_revision="graph-2",
        transition_refs=approved.transition_refs,
    )
    with pytest.raises(ValueError, match="stale graph revision"):
        build_projection_plan(
            verified,
            stale,
            next_graph_revision="graph-3",
            transition_ref="projection:1",
        )


def test_projection_records_exact_rollback_revision() -> None:
    verified, approved = _approved()
    plan = build_projection_plan(
        verified,
        approved,
        next_graph_revision="graph-2",
        transition_ref="projection:1",
    )
    projected = record_projection(approved, plan)
    assert projected.state is ProposalState.PROJECTED
    assert projected.current_graph_revision == "graph-2"
    assert projected.rollback_graph_revision == "graph-1"


def test_failed_reconciliation_builds_rollback_plan() -> None:
    verified, approved = _approved()
    projected = record_projection(
        approved,
        build_projection_plan(
            verified,
            approved,
            next_graph_revision="graph-2",
            transition_ref="projection:1",
        ),
    )
    result = reconcile_projection(
        projected,
        outcome=ReconciliationOutcome.MISMATCHED,
        evidence_ref="inventory:2",
    )
    assert result.next_state is ProposalState.ROLLED_BACK
    assert result.rollback is not None
    assert result.rollback.restore_graph_revision == "graph-1"
    rolled_back = record_reconciliation(projected, result)
    assert rolled_back.state is ProposalState.ROLLED_BACK
    assert rolled_back.transition_refs[-1] == "inventory:2"
    assert rolled_back.current_graph_revision == "graph-1"


def test_reconciliation_result_cannot_cross_proposal_lifecycle() -> None:
    verified, approved = _approved()
    projected = record_projection(
        approved,
        build_projection_plan(
            verified,
            approved,
            next_graph_revision="graph-2",
            transition_ref="projection:1",
        ),
    )
    result = reconcile_projection(
        projected,
        outcome=ReconciliationOutcome.MATCHED,
        evidence_ref="inventory:2",
    )
    other = replace(projected, proposal_digest="f" * 64)
    with pytest.raises(ValueError, match="MUST match lifecycle proposal"):
        record_reconciliation(other, result)


def test_invalid_lifecycle_transition_is_rejected() -> None:
    lifecycle = start_lifecycle(_verified(), graph_revision="graph-1")
    with pytest.raises(ValueError, match="invalid proposal lifecycle transition"):
        advance_lifecycle(
            lifecycle,
            target=ProposalState.PROJECTED,
            transition_ref="projection:1",
        )


def test_approval_cannot_rewrite_graph_revision() -> None:
    lifecycle = start_lifecycle(_verified(), graph_revision="graph-1")
    with pytest.raises(ValueError, match="only during projection or rollback"):
        advance_lifecycle(
            lifecycle,
            target=ProposalState.APPROVED,
            transition_ref="approval:1",
            graph_revision="graph-2",
        )


def test_source_retirement_is_bounded_and_review_only() -> None:
    retirements = (RetirementRequest("doc:a", "removed"),)
    records = tuple(
        SourceProjectionRecord(
            "doc:a",
            f"{index + 1:064x}",
            f"service:{index}",
            f"{index + 11:064x}",
            "g1",
        )
        for index in range(3)
    )
    held = plan_source_retirement(
        retirements,
        records,
        current_graph_revision="g2",
        max_tombstones=2,
    )
    assert held.held is True
    assert held.tombstones == ()

    planned = plan_source_retirement(
        retirements,
        records,
        current_graph_revision="g2",
        max_tombstones=3,
    )
    assert planned.held is False
    assert len(planned.tombstones) == 3
    assert all(item.expected_graph_revision == "g2" for item in planned.tombstones)


def test_access_change_blocks_unique_artifacts_in_stable_order() -> None:
    plan = plan_access_revocation(
        source_ref="doc:a",
        prior_acl_digest="a" * 64,
        new_acl_digest="b" * 64,
        artifact_refs=("chunk:2", "chunk:1"),
    )
    assert plan.block_artifact_refs == ("chunk:1", "chunk:2")


def test_access_change_rejects_duplicate_artifacts() -> None:
    with pytest.raises(ValueError, match="MUST be unique"):
        plan_access_revocation(
            source_ref="doc:a",
            prior_acl_digest="a" * 64,
            new_acl_digest="b" * 64,
            artifact_refs=("chunk:1", "chunk:1"),
        )


def test_retirement_rejects_duplicate_projection_records() -> None:
    record = SourceProjectionRecord(
        "doc:a",
        "a" * 64,
        "service:a",
        "b" * 64,
        "g1",
    )
    with pytest.raises(ValueError, match="records MUST be unique"):
        plan_source_retirement(
            (RetirementRequest("doc:a", "removed"),),
            (record, record),
            current_graph_revision="g2",
            max_tombstones=2,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"proposal_digest": "bad"}, "lifecycle digest"),
        ({"revision": 0}, "revision MUST be positive"),
        ({"current_graph_revision": ""}, "graph revision MUST be non-empty"),
        ({"transition_refs": ("",)}, "transition refs MUST be non-empty"),
        ({"transition_refs": ("ref:1", "ref:1")}, "transition refs MUST be unique"),
    ],
)
def test_lifecycle_record_rejects_invalid_identity(overrides, message: str) -> None:  # noqa: ANN001
    values = {
        "proposal_digest": "a" * 64,
        "state": ProposalState.REVIEW_REQUIRED,
        "revision": 1,
        "current_graph_revision": "graph-1",
        "transition_refs": (),
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        ProposalLifecycleRecord(**values)


def test_source_projection_record_rejects_invalid_identity_and_digest() -> None:
    with pytest.raises(ValueError, match="identity fields"):
        SourceProjectionRecord("", "a" * 64, "service:a", "b" * 64, "g1")
    with pytest.raises(ValueError, match="digests"):
        SourceProjectionRecord("doc:a", "bad", "service:a", "b" * 64, "g1")


def test_lifecycle_rejects_empty_transition_and_invalid_rollback_assignment() -> None:
    lifecycle = start_lifecycle(_verified(), graph_revision="graph-1")
    with pytest.raises(ValueError, match="transition_ref"):
        advance_lifecycle(lifecycle, target=ProposalState.APPROVED, transition_ref="")
    with pytest.raises(ValueError, match="only during projection"):
        advance_lifecycle(
            lifecycle,
            target=ProposalState.APPROVED,
            transition_ref="approval:1",
            rollback_graph_revision="graph-0",
        )


def test_projection_plan_rejects_wrong_state_digest_revision_and_ref() -> None:
    verified = _verified()
    review = start_lifecycle(verified, graph_revision="graph-1")
    with pytest.raises(ValueError, match="only an approved"):
        build_projection_plan(
            verified,
            review,
            next_graph_revision="graph-2",
            transition_ref="projection:1",
        )

    approved = advance_lifecycle(
        review,
        target=ProposalState.APPROVED,
        transition_ref="approval:1",
    )
    with pytest.raises(ValueError, match="digest MUST match"):
        build_projection_plan(
            verified,
            replace(approved, proposal_digest="f" * 64),
            next_graph_revision="graph-2",
            transition_ref="projection:1",
        )
    with pytest.raises(ValueError, match="new and non-empty"):
        build_projection_plan(
            verified,
            approved,
            next_graph_revision="graph-1",
            transition_ref="projection:1",
        )
    with pytest.raises(ValueError, match="transition_ref"):
        build_projection_plan(
            verified,
            approved,
            next_graph_revision="graph-2",
            transition_ref="",
        )


def test_record_projection_rejects_mismatched_plan() -> None:
    verified, approved = _approved()
    plan = build_projection_plan(
        verified,
        approved,
        next_graph_revision="graph-2",
        transition_ref="projection:1",
    )
    with pytest.raises(ValueError, match="MUST match lifecycle"):
        record_projection(approved, replace(plan, proposal_digest="f" * 64))
    stale_plan = ProjectionPlan(
        proposal_digest=plan.proposal_digest,
        expected_graph_revision="graph-0",
        next_graph_revision=plan.next_graph_revision,
        rollback_graph_revision=plan.rollback_graph_revision,
        transition_ref=plan.transition_ref,
    )
    with pytest.raises(ValueError, match="expected graph revision is stale"):
        record_projection(approved, stale_plan)


def test_reconciliation_and_retirement_reject_invalid_inputs() -> None:
    verified, approved = _approved()
    with pytest.raises(ValueError, match="only a projected"):
        reconcile_projection(
            approved,
            outcome=ReconciliationOutcome.MATCHED,
            evidence_ref="inventory:1",
        )
    projected = record_projection(
        approved,
        build_projection_plan(
            verified,
            approved,
            next_graph_revision="graph-2",
            transition_ref="projection:1",
        ),
    )
    with pytest.raises(ValueError, match="evidence_ref"):
        reconcile_projection(
            projected,
            outcome=ReconciliationOutcome.MATCHED,
            evidence_ref="",
        )
    with pytest.raises(ValueError, match="max_tombstones"):
        plan_source_retirement((), (), current_graph_revision="g1", max_tombstones=0)
    with pytest.raises(ValueError, match="current_graph_revision"):
        plan_source_retirement((), (), current_graph_revision="", max_tombstones=1)


def test_access_revocation_rejects_empty_source_invalid_and_unchanged_acl() -> None:
    with pytest.raises(ValueError, match="source_ref"):
        plan_access_revocation(
            source_ref="",
            prior_acl_digest="a" * 64,
            new_acl_digest="b" * 64,
            artifact_refs=(),
        )
    with pytest.raises(ValueError, match="ACL digests"):
        plan_access_revocation(
            source_ref="doc:a",
            prior_acl_digest="invalid",
            new_acl_digest="b" * 64,
            artifact_refs=(),
        )
    with pytest.raises(ValueError, match="requires an ACL change"):
        plan_access_revocation(
            source_ref="doc:a",
            prior_acl_digest="a" * 64,
            new_acl_digest="a" * 64,
            artifact_refs=(),
        )

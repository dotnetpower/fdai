"""Tests for the authority-free adaptive-investigation planning handoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fdai.core.operational_planning.investigation_handoff import (
    MAX_HANDOFF_ACTION_TYPE_REFS,
    MAX_HANDOFF_EVIDENCE_REFS,
    InvestigationPlanningHandoff,
    InvestigationTerminalDisposition,
    build_investigation_planning_handoff,
    planning_handoff_from_adaptive_result,
)
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationDisposition,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyTypeRef
from pydantic import ValidationError
from tests.core.read_investigation.test_adaptive_session import (
    _budget,
    _coordinator,
    _frame,
    _Reviser,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
CUTOFF = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)


def _action_ref(
    name: str = "ops.scale-out",
    *,
    kind: OntologyDeclarationKind = OntologyDeclarationKind.ACTION,
    catalog_digest: str = DIGEST_B,
) -> OntologyTypeRef:
    return OntologyTypeRef(
        kind=kind,
        name=name,
        version="1.0.0",
        catalog_digest=catalog_digest,
    )


def _handoff(
    *,
    disposition: InvestigationTerminalDisposition = (
        InvestigationTerminalDisposition.MATERIALLY_SUPPORTED
    ),
    evidence_refs: tuple[str, ...] = ("evidence:observation", "evidence:revision"),
    action_type_refs: tuple[OntologyTypeRef, ...] = (),
    evidence_cutoff: datetime = CUTOFF,
) -> InvestigationPlanningHandoff:
    return build_investigation_planning_handoff(
        terminal_session_digest=DIGEST_A,
        incident_id="incident-42",
        correlation_id="correlation-42",
        target_resource_ref="resource:workload-42",
        evidence_cutoff=evidence_cutoff,
        graph_revision="graph-revision-7",
        evidence_refs=evidence_refs,
        terminal_disposition=disposition,
        action_type_refs=action_type_refs,
    )


def test_handoff_is_canonical_content_addressed_and_replay_stable() -> None:
    first = _handoff(
        evidence_refs=("evidence:revision", "evidence:observation"),
        action_type_refs=(_action_ref("ops.restart"), _action_ref()),
    )
    replay = _handoff(
        evidence_refs=("evidence:observation", "evidence:revision"),
        action_type_refs=(_action_ref(), _action_ref("ops.restart")),
    )

    assert replay == first
    assert replay.handoff_id == (
        f"investigation-planning-handoff:{replay.handoff_digest.removeprefix('sha256:')}"
    )
    assert replay.evidence_refs == ("evidence:observation", "evidence:revision")
    assert tuple(item.name for item in replay.action_type_refs) == (
        "ops.restart",
        "ops.scale-out",
    )
    assert InvestigationPlanningHandoff.model_validate_json(first.model_dump_json()) == first


def test_handoff_is_explicit_proposal_only_forseti_input() -> None:
    handoff = _handoff()

    assert handoff.recipient_agent == "forseti"
    assert handoff.proposal_only is True
    assert handoff.starts_separate_planning_process is True
    assert handoff.refresh_context_required is True
    assert handoff.no_action_baseline_required is True
    assert handoff.mutation_authority is False
    assert handoff.query_authority is False
    assert handoff.approval_authority is False
    assert handoff.execution_authority is False
    assert handoff.promotion_authority is False
    assert isinstance(handoff.evidence_refs, tuple)
    assert isinstance(handoff.action_type_refs, tuple)
    assert not hasattr(handoff, "constraints")
    assert not hasattr(handoff, "simulations")
    assert not hasattr(handoff, "candidates")


@pytest.mark.parametrize(
    "disposition",
    [
        InvestigationTerminalDisposition.CANCELLED,
        InvestigationTerminalDisposition.TIMED_OUT,
        InvestigationTerminalDisposition.ALL_REFUTED,
        InvestigationTerminalDisposition.INCOMPLETE,
        InvestigationTerminalDisposition.TRUNCATED,
        InvestigationTerminalDisposition.HELD,
        InvestigationTerminalDisposition.BUDGET_EXHAUSTED,
        InvestigationTerminalDisposition.COST_EXHAUSTED,
    ],
)
def test_ineligible_terminal_sessions_cannot_request_planning(
    disposition: InvestigationTerminalDisposition,
) -> None:
    with pytest.raises(ValidationError, match="only a materially_supported investigation"):
        _handoff(disposition=disposition)


def test_content_substitution_invalidates_digest_and_stable_id() -> None:
    raw = _handoff().model_dump(mode="json")
    raw["target_resource_ref"] = "resource:substituted"

    with pytest.raises(ValidationError, match="digest does not match"):
        InvestigationPlanningHandoff.model_validate(raw)

    raw = _handoff().model_dump(mode="json")
    raw["handoff_id"] = "investigation-planning-handoff:" + "f" * 64
    with pytest.raises(ValidationError, match="id does not match"):
        InvestigationPlanningHandoff.model_validate(raw)


def test_schema_version_substitution_is_rejected() -> None:
    raw = _handoff().model_dump(mode="json")
    raw["schema_version"] = "1.0.1"

    with pytest.raises(ValidationError, match="Input should be '1.0.0'"):
        InvestigationPlanningHandoff.model_validate(raw)


def test_equivalent_timezone_offsets_have_same_canonical_identity() -> None:
    utc = _handoff(evidence_cutoff=CUTOFF)
    offset = _handoff(evidence_cutoff=CUTOFF.astimezone(tz=timezone(timedelta(hours=9))))

    assert offset == utc


def test_naive_evidence_cutoff_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _handoff(evidence_cutoff=CUTOFF.replace(tzinfo=None))


def test_evidence_refs_are_required_unique_and_bounded() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        _handoff(evidence_refs=())
    with pytest.raises(ValidationError, match="sorted and unique"):
        _handoff(evidence_refs=("evidence:z", "evidence:z"))
    with pytest.raises(ValidationError, match="at most 256"):
        _handoff(
            evidence_refs=tuple(
                f"evidence:{index:03d}" for index in range(MAX_HANDOFF_EVIDENCE_REFS + 1)
            )
        )


def test_canonical_handoff_bytes_are_bounded() -> None:
    evidence_refs = tuple(
        f"evidence:{index:03d}:" + "x" * 499 for index in range(MAX_HANDOFF_EVIDENCE_REFS)
    )

    with pytest.raises(ValidationError, match="canonical byte limit"):
        _handoff(evidence_refs=evidence_refs)


def test_action_type_refs_are_catalog_backed_actions() -> None:
    handoff = _handoff(action_type_refs=(_action_ref(),))
    assert handoff.action_type_refs == (_action_ref(),)

    with pytest.raises(ValidationError, match="only catalog-backed ActionType refs"):
        _handoff(action_type_refs=(_action_ref(kind=OntologyDeclarationKind.OBJECT),))


def test_action_type_refs_are_unique_and_bounded() -> None:
    duplicate = _action_ref()
    raw = _handoff(action_type_refs=(duplicate,)).model_dump(mode="json")
    raw["action_type_refs"] = [duplicate.model_dump(mode="json")] * 2
    with pytest.raises(ValidationError, match="sorted, unique, and bounded"):
        InvestigationPlanningHandoff.model_validate(raw)

    refs = tuple(_action_ref(f"ops.action-{index:02d}") for index in range(33))
    assert len(refs) == MAX_HANDOFF_ACTION_TYPE_REFS + 1
    with pytest.raises(ValidationError, match="at most 32"):
        _handoff(action_type_refs=refs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mutation_authority", True),
        ("query_authority", True),
        ("approval_authority", True),
        ("execution_authority", True),
        ("promotion_authority", True),
        ("proposal_only", False),
        ("no_action_baseline_required", False),
        ("refresh_context_required", False),
        ("starts_separate_planning_process", False),
    ],
)
def test_authority_and_planning_markers_cannot_be_changed(
    field: str,
    value: bool,
) -> None:
    raw = _handoff().model_dump(mode="json")
    raw[field] = value

    with pytest.raises(ValidationError):
        InvestigationPlanningHandoff.model_validate(raw)


def test_unknown_planning_content_is_rejected() -> None:
    raw = _handoff().model_dump(mode="json")
    raw["constraints"] = []
    raw["simulations"] = []
    raw["planning_request"] = {}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InvestigationPlanningHandoff.model_validate(raw)


async def test_converged_adaptive_result_maps_to_proposal_only_handoff() -> None:
    result = await _coordinator(
        _Reviser((AdaptiveInvestigationDisposition.CONVERGED,))
    ).investigate(
        session_id="session-1",
        initial_frame=_frame(),
        budget=_budget(),
    )

    handoff = planning_handoff_from_adaptive_result(
        result,
        correlation_id="correlation-42",
        target_resource_ref="resource:workload-42",
        action_type_refs=(_action_ref(),),
    )

    assert handoff.terminal_session_digest == result.result_digest
    assert handoff.no_action_baseline_required is True
    assert handoff.evidence_refs


def test_structural_fake_cannot_request_planning() -> None:
    result = SimpleNamespace(
        disposition=AdaptiveInvestigationDisposition.CONVERGED,
        iterations=(SimpleNamespace(),),
        result_digest=DIGEST_A,
        incident_id="incident-42",
    )

    with pytest.raises(TypeError, match="AdaptiveInvestigationResult"):
        planning_handoff_from_adaptive_result(
            result,  # type: ignore[arg-type]
            correlation_id="correlation-42",
            target_resource_ref="resource:workload-42",
        )


def test_contract_is_deeply_immutable() -> None:
    handoff = _handoff(action_type_refs=(_action_ref(),))

    with pytest.raises(ValidationError, match="Instance is frozen"):
        handoff.incident_id = "incident-substituted"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        handoff.action_type_refs[0].name = "ops.substituted"

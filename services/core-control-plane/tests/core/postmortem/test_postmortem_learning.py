"""Postmortem knowledge extractor - M9 reusable-lesson mining.

Verifies the extractor is evidence-backed and fail-closed: it emits a
grounded, deterministic learning only when a resolved incident carries a
recorded root cause *and* a successfully executed action, and abstains
otherwise. No fabrication.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.postmortem import (
    AuditRow,
    PostmortemKnowledgeExtractor,
    PostmortemLearning,
)
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


def _incident(**overrides) -> Incident:  # noqa: ANN003
    base = dict(
        schema_version="1.0.0",
        incident_id=UUID("00000000-0000-0000-0000-000000000001"),
        state=IncidentState.RESOLVED,
        severity=IncidentSeverity.SEV2,
        opened_at=T0,
        mitigated_at=T0 + timedelta(minutes=30),
        resolved_at=T0 + timedelta(hours=1),
        correlation_keys=("resource:vm-a", "deployment:api-v3"),
        member_event_ids=(UUID("00000000-0000-0000-0000-00000000000a"),),
    )
    base.update(overrides)
    return Incident(**base)


def _resolving_action_row(
    *,
    action_type: str = "remediate.enable-backup-protection",
    mode: str = "enforce",
    outcome: str = "success",
) -> AuditRow:
    return AuditRow(
        kind="action.remediate",
        at=T0 + timedelta(minutes=20),
        actor_oid="oid-executor",
        body={"action_type": action_type, "mode": mode, "outcome": outcome},
    )


def _root_cause_row(cause: str = "backup protection was disabled by drift") -> AuditRow:
    return AuditRow(
        kind="rca.finding",
        at=T0 + timedelta(minutes=10),
        actor_oid="system",
        body={"root_cause": cause},
    )


# ---------------------------------------------------------------------------
# Happy path - grounded lesson
# ---------------------------------------------------------------------------


def test_extracts_grounded_learning_when_evidence_complete() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[_root_cause_row(), _resolving_action_row()],
    )
    assert isinstance(learning, PostmortemLearning)
    assert learning.root_cause == "backup protection was disabled by drift"
    assert learning.resolving_action_types == ("remediate.enable-backup-protection",)
    # Anchors generalize away from specific resource ids.
    assert "deployment" in learning.signature
    assert "resource" in learning.signature
    assert "vm-a" not in learning.signature  # specific id must not leak into the pattern
    # Grounded provenance so CandidateGuard can validate it.
    assert learning.provenance["source"] == "postmortem-learning"
    assert learning.provenance["incident_id"] == str(_incident().incident_id)
    assert 0.0 < learning.confidence <= 1.0


def test_signature_is_deterministic_across_reprocessing() -> None:
    extractor = PostmortemKnowledgeExtractor()
    rows = [_root_cause_row(), _resolving_action_row()]
    first = extractor.extract(incident=_incident(), audit_rows=rows)
    second = extractor.extract(incident=_incident(), audit_rows=list(reversed(rows)))
    assert first is not None
    assert second is not None
    assert first.signature == second.signature


def test_duplicate_actions_collapse_in_signature() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[
            _root_cause_row(),
            _resolving_action_row(),
            _resolving_action_row(),  # re-fire of the same action
        ],
    )
    assert learning is not None
    assert learning.resolving_action_types == ("remediate.enable-backup-protection",)


# ---------------------------------------------------------------------------
# Fail-closed abstain paths
# ---------------------------------------------------------------------------


def test_abstains_when_incident_not_resolved() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(state=IncidentState.TRIAGING, resolved_at=None),
        audit_rows=[_root_cause_row(), _resolving_action_row()],
    )
    assert learning is None


def test_abstains_when_no_root_cause_recorded() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[_resolving_action_row()],
    )
    assert learning is None


def test_abstains_when_no_successful_enforce_action() -> None:
    extractor = PostmortemKnowledgeExtractor()
    # Shadow-mode action is not evidence that it resolved the incident.
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[_root_cause_row(), _resolving_action_row(mode="shadow")],
    )
    assert learning is None


def test_abstains_when_action_failed() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[_root_cause_row(), _resolving_action_row(outcome="rolled_back")],
    )
    assert learning is None


def test_empty_root_cause_string_is_treated_as_absent() -> None:
    extractor = PostmortemKnowledgeExtractor()
    learning = extractor.extract(
        incident=_incident(),
        audit_rows=[_root_cause_row(cause="   "), _resolving_action_row()],
    )
    assert learning is None


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def test_confidence_rises_with_more_anchors_and_timeline() -> None:
    extractor = PostmortemKnowledgeExtractor()
    thin = extractor.extract(
        incident=_incident(correlation_keys=("resource:vm-a",)),
        audit_rows=[_root_cause_row(), _resolving_action_row()],
    )
    rich = extractor.extract(
        incident=_incident(
            correlation_keys=("resource:vm-a", "deployment:api-v3", "trace:abc"),
        ),
        audit_rows=[
            _root_cause_row(),
            _resolving_action_row(),
            AuditRow(kind="slo.error_budget_burn", at=T0, actor_oid=None, body={}),
            AuditRow(kind="action.notify", at=T0, actor_oid=None, body={}),
        ],
    )
    assert thin is not None
    assert rich is not None
    assert rich.confidence > thin.confidence

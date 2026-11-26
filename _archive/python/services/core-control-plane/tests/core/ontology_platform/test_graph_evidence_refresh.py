"""Focused graph evidence refresh policy tests."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.ontology_platform.archive_retention import ArchiveHistoryStatus
from fdai.core.ontology_platform.graph_evidence_refresh import (
    GraphEvidenceFreshness,
    GraphEvidenceRefreshInput,
    GraphEvidenceRefreshOutcome,
    GraphQueryIntent,
    decide_graph_evidence_refresh,
)

_RELEASE = "sha256:" + "a" * 64


def _evidence(**changes: object) -> GraphEvidenceRefreshInput:
    values: dict[str, object] = {
        "query_intent": GraphQueryIntent.CURRENT,
        "requested_ontology_release_digest": _RELEASE,
        "graph_ontology_release_digest": _RELEASE,
        "graph_available": True,
        "graph_freshness": GraphEvidenceFreshness.CURRENT,
        "graph_complete": True,
        "graph_truncated": False,
        "graph_synthetic": False,
        "graph_conflict_count": 0,
        "explicit_live_read": False,
        "live_read_permitted": False,
        "verified_live_receipt": False,
        "live_receipt_principal_scoped": False,
        "deadline_remaining_ms": 10_000,
        "live_read_budget_ms": 2_000,
        "projection_budget_ms": 2_000,
        "archive_status": ArchiveHistoryStatus.UNAVAILABLE,
        "archive_principal_scoped": False,
    }
    values.update(changes)
    return GraphEvidenceRefreshInput(**values)  # type: ignore[arg-type]


def test_current_complete_graph_is_used_without_live_read() -> None:
    decision = decide_graph_evidence_refresh(_evidence())

    assert decision.outcome is GraphEvidenceRefreshOutcome.USE_GRAPH
    assert decision.reason_codes == ("graph_verified",)
    assert decision.execution_authority is False


def test_stale_graph_selects_bounded_refresh_when_deadline_fits() -> None:
    decision = decide_graph_evidence_refresh(
        _evidence(
            graph_freshness=GraphEvidenceFreshness.STALE,
            live_read_permitted=True,
        )
    )

    assert decision.outcome is GraphEvidenceRefreshOutcome.REFRESH_THEN_QUERY
    assert "graph_stale" in decision.reason_codes


def test_verified_live_receipt_is_used_while_projection_catches_up() -> None:
    decision = decide_graph_evidence_refresh(
        _evidence(
            graph_complete=False,
            live_read_permitted=True,
            verified_live_receipt=True,
            live_receipt_principal_scoped=True,
        )
    )

    assert decision.outcome is GraphEvidenceRefreshOutcome.USE_LIVE_EVIDENCE
    assert "graph_incomplete" in decision.reason_codes


def test_explicit_historical_query_uses_verified_archive() -> None:
    decision = decide_graph_evidence_refresh(
        _evidence(
            query_intent=GraphQueryIntent.HISTORICAL,
            archive_status=ArchiveHistoryStatus.ARCHIVED,
            archive_principal_scoped=True,
        )
    )

    assert decision.outcome is GraphEvidenceRefreshOutcome.QUERY_ARCHIVE


def test_conflict_or_insufficient_deadline_holds_without_substitution() -> None:
    conflicting = decide_graph_evidence_refresh(
        _evidence(graph_conflict_count=1, deadline_remaining_ms=1_000)
    )
    wrong_release = decide_graph_evidence_refresh(
        replace(
            _evidence(),
            graph_ontology_release_digest="sha256:" + "b" * 64,
        )
    )

    assert conflicting.outcome is GraphEvidenceRefreshOutcome.HOLD
    assert "graph_conflicting" in conflicting.reason_codes
    assert wrong_release.outcome is GraphEvidenceRefreshOutcome.HOLD
    assert "ontology_release_mismatch" in wrong_release.reason_codes

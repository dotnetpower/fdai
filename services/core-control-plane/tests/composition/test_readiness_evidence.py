"""Architecture-review evidence projection for checklist controls."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.composition.readiness_evidence import ArchitectureReviewChecklistEvidenceProvider
from fdai.shared.contracts.models import RequirementKind, RequirementStatus

_ROOT = Path(__file__).resolve().parents[4]


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load((_ROOT / "config" / "architecture-review.yaml").read_text())
    assert isinstance(raw, dict)
    return raw


async def test_projects_artifact_status_and_missing_bindings() -> None:
    outcomes = await ArchitectureReviewChecklistEvidenceProvider(_manifest()).outcomes_for_scope(
        "scope-example"
    )
    by_key = {(outcome.kind, outcome.ref): outcome for outcome in outcomes}

    assert by_key[(RequirementKind.ARTIFACT, "target-architecture")].status is (
        RequirementStatus.SATISFIED
    )
    assert by_key[(RequirementKind.ARTIFACT, "reliability-and-dr")].status is (
        RequirementStatus.FAILED
    )
    assert by_key[(RequirementKind.DRILL, "restore-failover-drill")].status is (
        RequirementStatus.UNKNOWN
    )
    assert by_key[(RequirementKind.APPROVAL, "reliability-owner")].status is (
        RequirementStatus.UNKNOWN
    )


async def test_bound_evidence_carries_time_and_reference() -> None:
    manifest = deepcopy(_manifest())
    review = manifest["architecture_review"]
    assert isinstance(review, dict)
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["checklist_evidence_bindings"] = {
        "restore-failover-drill": {
            "kind": "drill",
            "scope": "scope-example",
            "uri": "evidence://restore-failover-drill",
            "observed_at": "2026-07-29T00:00:00Z",
            "recorded_at": "2026-07-29T00:01:00Z",
            "expires_at": "2027-07-29T00:00:00Z",
            "source_identity": "observer@example.com",
            "sha256": f"sha256:{'a' * 64}",
        }
    }

    outcomes = await ArchitectureReviewChecklistEvidenceProvider(
        manifest,
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    ).outcomes_for_scope("scope-example")
    drill = next(
        outcome
        for outcome in outcomes
        if outcome.kind is RequirementKind.DRILL and outcome.ref == "restore-failover-drill"
    )

    assert drill.status is RequirementStatus.SATISFIED
    assert drill.observed_at is not None
    assert drill.evidence_refs == ("evidence://restore-failover-drill",)


async def test_expired_bound_evidence_is_failed() -> None:
    manifest = deepcopy(_manifest())
    review = manifest["architecture_review"]
    assert isinstance(review, dict)
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["checklist_evidence_bindings"] = {
        "restore-failover-drill": {
            "kind": "drill",
            "scope": "scope-example",
            "uri": "evidence://restore-failover-drill",
            "observed_at": "2026-07-01T00:00:00Z",
            "recorded_at": "2026-07-01T00:01:00Z",
            "expires_at": "2026-07-15T00:00:00Z",
            "source_identity": "observer@example.com",
            "sha256": f"sha256:{'b' * 64}",
        }
    }

    outcomes = await ArchitectureReviewChecklistEvidenceProvider(
        manifest,
        clock=lambda: datetime(2026, 7, 29, tzinfo=UTC),
    ).outcomes_for_scope("scope-example")
    drill = next(
        outcome
        for outcome in outcomes
        if outcome.kind is RequirementKind.DRILL and outcome.ref == "restore-failover-drill"
    )

    assert drill.status is RequirementStatus.FAILED


async def test_owner_assignment_does_not_count_as_approval() -> None:
    manifest = deepcopy(_manifest())
    review = manifest["architecture_review"]
    assert isinstance(review, dict)
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["owner_bindings"] = {"reliability-owner": "owner@example.com"}

    outcomes = await ArchitectureReviewChecklistEvidenceProvider(manifest).outcomes_for_scope(
        "scope-example"
    )
    approval = next(
        outcome
        for outcome in outcomes
        if outcome.kind is RequirementKind.APPROVAL and outcome.ref == "reliability-owner"
    )

    assert approval.status is RequirementStatus.UNKNOWN


async def test_rejects_evidence_bound_to_another_scope() -> None:
    manifest = deepcopy(_manifest())
    review = manifest["architecture_review"]
    assert isinstance(review, dict)
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["checklist_evidence_bindings"] = {
        "restore-failover-drill": {
            "kind": "drill",
            "scope": "another-scope",
            "uri": "evidence://restore-failover-drill",
            "observed_at": "2026-07-29T00:00:00Z",
            "recorded_at": "2026-07-29T00:01:00Z",
            "expires_at": "2027-07-29T00:00:00Z",
            "source_identity": "observer@example.com",
            "sha256": f"sha256:{'c' * 64}",
        }
    }

    with pytest.raises(ValueError, match="scope does not match"):
        await ArchitectureReviewChecklistEvidenceProvider(manifest).outcomes_for_scope(
            "scope-example"
        )

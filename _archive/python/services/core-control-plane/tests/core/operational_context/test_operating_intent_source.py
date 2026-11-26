"""Fail-closed admission for the deployment-owned six-type operating-intent source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.operational_context.operating_intent_source import (
    OperatingIntentSourceBinding,
    OperatingIntentSourceError,
    validate_operating_intent_source_document,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.operating_model import (
    OperatingIntentSourceDocument,
    OperatingIntentSourceProvenance,
    OperatingModelSnapshot,
    operating_intent_source_document_digest,
)

_NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
_EFFECTIVE_FROM = "2026-08-27T00:00:00+00:00"
_REVISION = "operating-intent-revision-1"
_SOURCE_URL = "https://example.invalid/operating-intent-source"


def _objective(
    object_id: str, object_type: str, *, effective_from: str = _EFFECTIVE_FROM
) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=object_id,
        object_type=object_type,
        properties={
            "id": object_id,
            "objective_kind": "availability",
            "metric": "availability",
            "unit": "ratio",
            "target": 0.999,
            "window_seconds": 2592000,
            "measurement_source_ref": "source:service-objectives",
            "freshness_seconds": 86400,
            "effective_from": effective_from,
        },
    )


def _recovery_objective(effective_from: str = _EFFECTIVE_FROM) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="recovery-objective-1",
        object_type="RecoveryObjective",
        properties={
            "id": "recovery-objective-1",
            "rto_seconds": 3600,
            "rpo_seconds": 300,
            "measurement_source_ref": "source:recovery-objectives",
            "freshness_seconds": 86400,
            "effective_from": effective_from,
        },
    )


def _cost_objective(effective_from: str = _EFFECTIVE_FROM) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="cost-objective-1",
        object_type="CostObjective",
        properties={
            "id": "cost-objective-1",
            "objective_kind": "monthly_budget",
            "currency": "USD",
            "target": 1000,
            "period_seconds": 2592000,
            "measurement_source_ref": "source:cost-objectives",
            "freshness_seconds": 86400,
            "effective_from": effective_from,
        },
    )


def _architecture_constraint(effective_from: str = _EFFECTIVE_FROM) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="architecture-constraint-1",
        object_type="ArchitectureConstraint",
        properties={
            "id": "architecture-constraint-1",
            "constraint_kind": "network_isolation",
            "expression_ref": "policy:network-isolation",
            "severity": "high",
            "effective_from": effective_from,
        },
    )


def _ownership(effective_from: str = _EFFECTIVE_FROM) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="ownership-1",
        object_type="Ownership",
        properties={
            "id": "ownership-1",
            "owner_ref": "group:operations-owner",
            "escalation_ref": "route:on-call",
            "effective_from": effective_from,
            "source_ref": "source:service-catalog",
        },
    )


def _change_window(
    effective_from: str = _EFFECTIVE_FROM,
    effective_to: str = "2026-09-30T00:00:00+00:00",
) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="change-window-1",
        object_type="ChangeWindow",
        properties={
            "id": "change-window-1",
            "window_kind": "maintenance",
            "scope_ref": "scope:example",
            "status": "approved",
            "effective_from": effective_from,
            "effective_to": effective_to,
            "policy_ref": "policy:change-window",
        },
    )


def _complete_objects() -> tuple[OntologyObjectRecord, ...]:
    return (
        _objective("service-objective-1", "ServiceObjective"),
        _recovery_objective(),
        _cost_objective(),
        _architecture_constraint(),
        _ownership(),
        _change_window(),
    )


def _document(
    objects: tuple[OntologyObjectRecord, ...] | None = None,
    *,
    revision: str = _REVISION,
    resolved_ref: str | None = None,
    source_url: str = _SOURCE_URL,
    retrieved_at: datetime | None = None,
) -> OperatingIntentSourceDocument:
    return OperatingIntentSourceDocument(
        snapshot=OperatingModelSnapshot(
            source_revision=revision,
            objects=_complete_objects() if objects is None else objects,
            links=(),
        ),
        provenance=OperatingIntentSourceProvenance(
            source_url=source_url,
            resolved_ref=resolved_ref if resolved_ref is not None else revision,
            retrieved_at=retrieved_at if retrieved_at is not None else _NOW,
        ),
    )


def _binding(
    document: OperatingIntentSourceDocument,
    *,
    expected_revision: str = _REVISION,
    expected_instance_counts: dict[str, int] | None = None,
) -> OperatingIntentSourceBinding:
    return OperatingIntentSourceBinding(
        expected_revision=expected_revision,
        expected_sha256=operating_intent_source_document_digest(document),
        expected_instance_counts=expected_instance_counts or {},
    )


def test_complete_current_source_passes() -> None:
    document = _document()
    validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_missing_required_type_fails_closed() -> None:
    document = _document(_complete_objects()[:-1])  # drop ChangeWindow
    with pytest.raises(OperatingIntentSourceError, match="missing required type 'ChangeWindow'"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_duplicate_required_type_fails_closed() -> None:
    extra = _objective("service-objective-2", "ServiceObjective")
    document = _document((*_complete_objects(), extra))
    with pytest.raises(OperatingIntentSourceError, match="expected exactly 1 \\(duplicate\\)"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_non_operating_intent_type_fails_closed() -> None:
    extra = _objective("resource-1", "Resource")
    document = _document((*_complete_objects(), extra))

    with pytest.raises(OperatingIntentSourceError, match="non-operating-intent ObjectTypes"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_below_pinned_instance_count_fails_closed() -> None:
    """A pinned count is exact in both directions, not just an upper bound.

    An operator who reviewed and pinned two `ServiceObjective` instances is asserting
    that both are present; a later source carrying only one has silently dropped an
    approved objective, which is a fail-closed defect rather than a safe subset.
    """

    document = _document()
    binding = _binding(document, expected_instance_counts={"ServiceObjective": 2})
    with pytest.raises(OperatingIntentSourceError, match="expected exactly 2 \\(incomplete\\)"):
        validate_operating_intent_source_document(document, binding=binding, now=_NOW)


def test_expected_instance_counts_permit_a_reviewed_extra_instance() -> None:
    extra = _objective("service-objective-2", "ServiceObjective")
    document = _document((*_complete_objects(), extra))
    binding = _binding(document, expected_instance_counts={"ServiceObjective": 2})
    validate_operating_intent_source_document(document, binding=binding, now=_NOW)


def test_stale_change_window_fails_closed() -> None:
    objects = (
        *_complete_objects()[:-1],
        _change_window(effective_to="2026-08-27T06:00:00+00:00"),
    )
    document = _document(objects)
    with pytest.raises(OperatingIntentSourceError, match="not currently effective"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_not_yet_effective_fails_closed() -> None:
    objects = (
        *_complete_objects()[:-1],
        _change_window(
            effective_from="2026-12-01T00:00:00+00:00", effective_to="2026-12-02T00:00:00+00:00"
        ),
    )
    document = _document(objects)
    with pytest.raises(OperatingIntentSourceError, match="not currently effective"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_long_lived_objective_from_a_current_retrieval_is_fresh() -> None:
    """Effective age is not staleness: a years-old objective just re-read is fresh.

    `effective_from` records when the intent started applying. Judging freshness from
    it would reject every durable objective a deployment actually operates against.
    """

    objects = (
        _objective(
            "service-objective-1", "ServiceObjective", effective_from="2020-01-01T00:00:00+00:00"
        ),
        *_complete_objects()[1:],
    )
    document = _document(objects, retrieved_at=_NOW - timedelta(minutes=5))
    validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_newly_effective_instance_from_a_stale_retrieval_fails_closed() -> None:
    """A just-effective instance does not launder an old retrieval.

    `freshness_seconds` is 86400 here, so a source last retrieved three days ago is
    stale even though its objective only became effective minutes before `now`.
    """

    objects = (
        _objective(
            "service-objective-1",
            "ServiceObjective",
            effective_from=(_NOW - timedelta(minutes=1)).isoformat(),
        ),
        *_complete_objects()[1:],
    )
    document = _document(objects, retrieved_at=_NOW - timedelta(days=3))
    with pytest.raises(OperatingIntentSourceError, match="freshness_seconds"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_future_retrieval_time_fails_closed() -> None:
    document = _document(retrieved_at=_NOW + timedelta(hours=1))
    with pytest.raises(OperatingIntentSourceError, match="retrieved_at is in the future"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_cross_release_revision_mismatch_fails_closed() -> None:
    document = _document()
    binding = _binding(document, expected_revision="operating-intent-revision-2")
    with pytest.raises(OperatingIntentSourceError, match="revision does not match"):
        validate_operating_intent_source_document(document, binding=binding, now=_NOW)


def test_cross_release_provenance_mismatch_fails_closed() -> None:
    document = _document(resolved_ref="operating-intent-revision-2")
    with pytest.raises(OperatingIntentSourceError, match="resolved_ref does not match"):
        validate_operating_intent_source_document(document, binding=_binding(document), now=_NOW)


def test_cross_release_digest_mismatch_fails_closed() -> None:
    document = _document()
    binding = _binding(_document(_complete_objects()[:-1]))
    with pytest.raises(OperatingIntentSourceError, match="content digest does not match"):
        validate_operating_intent_source_document(document, binding=binding, now=_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "https://example.invalid/other-operating-intent-source"),
        ("resolved_ref", "operating-intent-revision-2"),
        ("retrieved_at", _NOW - timedelta(days=30)),
    ],
)
def test_every_provenance_field_is_covered_by_the_document_digest(
    field: str, value: object
) -> None:
    """Attribution and observation time are pinned content, not free-text decoration."""

    baseline = operating_intent_source_document_digest(_document())
    assert operating_intent_source_document_digest(_document(**{field: value})) != baseline


def test_rewritten_source_url_fails_the_pinned_digest() -> None:
    document = _document(source_url="https://example.invalid/other-operating-intent-source")
    binding = _binding(_document())
    with pytest.raises(OperatingIntentSourceError, match="content digest does not match"):
        validate_operating_intent_source_document(document, binding=binding, now=_NOW)


def test_rewritten_retrieved_at_fails_the_pinned_digest() -> None:
    """Back-dating a retrieval to defeat the freshness check fails the pin first."""

    document = _document(retrieved_at=_NOW - timedelta(minutes=1))
    binding = _binding(_document(retrieved_at=_NOW - timedelta(days=30)))
    with pytest.raises(OperatingIntentSourceError, match="content digest does not match"):
        validate_operating_intent_source_document(document, binding=binding, now=_NOW)


def test_binding_rejects_malformed_sha256() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        OperatingIntentSourceBinding(expected_revision=_REVISION, expected_sha256="not-a-digest")


def test_binding_rejects_non_hex_digest() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        OperatingIntentSourceBinding(
            expected_revision=_REVISION,
            expected_sha256=f"sha256:{'g' * 64}",
        )


def test_binding_rejects_empty_revision() -> None:
    with pytest.raises(ValueError, match="expected_revision"):
        OperatingIntentSourceBinding(
            expected_revision="   ",
            expected_sha256=f"sha256:{'0' * 64}",
        )


def test_binding_rejects_unknown_expected_count_type() -> None:
    with pytest.raises(ValueError, match="not a required"):
        OperatingIntentSourceBinding(
            expected_revision=_REVISION,
            expected_sha256=f"sha256:{'0' * 64}",
            expected_instance_counts={"Resource": 1},
        )


def test_binding_rejects_non_positive_expected_count() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        OperatingIntentSourceBinding(
            expected_revision=_REVISION,
            expected_sha256=f"sha256:{'0' * 64}",
            expected_instance_counts={"ServiceObjective": 0},
        )


def test_binding_rejects_non_integer_expected_count() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        OperatingIntentSourceBinding(
            expected_revision=_REVISION,
            expected_sha256=f"sha256:{'0' * 64}",
            expected_instance_counts={"ServiceObjective": "1"},  # type: ignore[dict-item]
        )


def test_naive_now_is_rejected() -> None:
    document = _document()
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_operating_intent_source_document(
            document,
            binding=_binding(document),
            now=datetime(2026, 8, 27, 12, 0, 0),  # noqa: DTZ001
        )

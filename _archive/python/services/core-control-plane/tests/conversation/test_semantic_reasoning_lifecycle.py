"""Lifecycle values read as a union within one property and restrict across properties."""

from __future__ import annotations

from fdai.core.conversation.semantic_reasoning_lifecycle import (
    lifecycle_predicates,
    parse_lifecycle,
)


def test_values_of_one_property_unite_and_distinct_properties_restrict_together() -> None:
    predicates, reason = lifecycle_predicates(
        (
            "lifecycle:Incident.status=open",
            "lifecycle:Incident.severity=sev2",
            "lifecycle:Incident.status=triaging",
        ),
        "Incident",
    )

    assert reason is None
    assert predicates == [
        {"property": "severity", "operator": "equals", "equals": "sev2"},
        {"property": "status", "operator": "in", "values": ["open", "triaging"]},
    ]


def test_another_subject_or_a_mixed_state_never_reads_a_lifecycle_value() -> None:
    assert lifecycle_predicates(("lifecycle:Incident.status=open",), "Resource") == (
        [],
        "state_filter_subject_mismatch",
    )
    assert lifecycle_predicates(
        ("lifecycle:Incident.status=open", "resource_state.running"), "Incident"
    ) == ([], "state_filter_domain_unsupported")
    # A malformed concept names no lifecycle value rather than a wider one.
    assert parse_lifecycle("lifecycle:Incident.status=") is None
    assert parse_lifecycle("lifecycle:incident.status=open") is None

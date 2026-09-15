"""Private semantic retention cannot revive sources, evade legal hold, or slide expiry."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from fdai.rule_catalog.pipeline.distill.handover_retention import retention_decision

AT = datetime(2026, 9, 15, tzinfo=UTC)


def inputs():
    document = {
        "document_id": "document:example",
        "version_id": "version:example",
        "source_sha256": "a" * 64,
        "access": {"reference": "access:example"},
        "retention": {
            "policy_version": "example:1",
            "derived_expires_at": (AT + timedelta(days=1)).isoformat(),
            "legal_hold": False,
        },
    }
    current = {
        **copy.deepcopy(document),
        "active": True,
        "available": True,
        "state": "ready",
        "disposition": "governed_knowledge",
        "index_state": "active",
        "retention_state": "live",
        "purposes": ["manual_distillation"],
    }
    return {"documents": [document]}, {"source_current": True, "documents": [current]}


def test_current_source_is_not_retired_or_erased():
    descriptor, policies = inputs()
    assert retention_decision(descriptor, policies, at=AT, withdrawn=False, retired=False) == (
        False,
        False,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("active", False),
        ("available", "true"),
        ("state", "held"),
        ("disposition", "workspace_draft"),
        ("index_state", "tombstoned"),
        ("retention_state", "purged"),
        ("source_sha256", "b" * 64),
        ("purposes", ["knowledge_base"]),
        ("access", {"reference": "access:other"}),
    ],
)
def test_source_drift_retires_without_waiting_for_a_new_candidate(field, value):
    descriptor, policies = inputs()
    policies["documents"][0][field] = value
    assert retention_decision(descriptor, policies, at=AT, withdrawn=False, retired=False) == (
        True,
        True,
    )


@pytest.mark.parametrize("expiry_owner", ["original", "current"])
def test_either_expiry_is_authoritative_and_replay_cannot_extend_it(expiry_owner):
    descriptor, policies = inputs()
    target = descriptor if expiry_owner == "original" else policies
    target["documents"][0]["retention"]["derived_expires_at"] = AT.isoformat()
    assert retention_decision(descriptor, policies, at=AT, withdrawn=False, retired=False) == (
        True,
        True,
    )


@pytest.mark.parametrize("hold", [True, None, "false", 0])
def test_missing_ambiguous_or_active_legal_hold_keeps_retired_bytes(hold):
    descriptor, policies = inputs()
    policies["documents"][0]["retention"]["legal_hold"] = hold
    assert retention_decision(descriptor, policies, at=AT, withdrawn=True, retired=False) == (
        True,
        False,
    )


@pytest.mark.parametrize("change", ["missing_row", "wrong_version", "policy_absent", "naive"])
def test_incomplete_current_policy_can_never_authorize_content_erasure(change):
    descriptor, policies = inputs()
    if change == "missing_row":
        policies["documents"] = []
    elif change == "wrong_version":
        policies["documents"][0]["version_id"] = "version:other"
    elif change == "policy_absent":
        policies["documents"][0]["retention"] = None
    else:
        policies["documents"][0]["retention"]["derived_expires_at"] = "2026-09-15T00:00:00"
    assert retention_decision(descriptor, policies, at=AT, withdrawn=True, retired=False) == (
        True,
        False,
    )


def test_retired_package_never_revives_after_source_recovery():
    descriptor, policies = inputs()
    assert retention_decision(descriptor, policies, at=AT, withdrawn=False, retired=True) == (
        True,
        True,
    )

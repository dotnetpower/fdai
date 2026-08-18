"""Every constitutional condition on an A3-E delegation has a failing case.

FDAI-CONST-008 lists eleven conditions that must all hold. A test suite that only proves
the happy path would let any one of them be deleted silently, so each condition here has a
negative case asserting its exact reason code.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai.core.standing_authority.evaluator import (
    AuthorizationRequest,
    AutonomyClass,
    Eligibility,
    evaluate_standing_authorization,
)
from fdai.core.standing_authority.record import (
    StandingAuthorization,
    StandingAuthorizationError,
)

NOW = datetime(2026, 7, 5, 8, 0, tzinfo=UTC)
SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "sa.example-scale-out",
        "authorization_revision": "rev-1",
        "status": "active",
        "mode": "shadow",
        "requested_by": "example-requester",
        "approvals": [
            {
                "principal": "example-service-owner",
                "role": "service_owner",
                "approved_at": "2026-07-01T08:00:00Z",
            },
            {
                "principal": "example-owner",
                "role": "owner",
                "approved_at": "2026-07-01T09:00:00Z",
            },
        ],
        "quorum_required": 2,
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2026-08-01T00:00:00Z",
        "service_ref": "service:example-expense",
        "scope": {"level": "resource_group", "value": "rg:example-expense"},
        "pins": {
            "policy_digest": "sha256:policy",
            "target_revision": "rev-target-1",
            "action_type_versions": ["ops.scale-out@1.0.0"],
            "evidence_revisions": ["evidence-1"],
        },
        "envelope": {
            "action_types": ["ops.scale-out"],
            "max_blast_radius": 3,
            "max_duration_seconds": 600,
            "reversible": True,
            "rollback_contract": "scripted",
            "stop_conditions": ["provider_api_error_streak"],
        },
        "incident_classes": ["capacity_saturation"],
        "responders": {
            "primary": "example-primary",
            "backup": "example-backup",
            "confirmed_at": "2026-07-04T08:00:00Z",
        },
        "evidence": {
            "history_reviewed": True,
            "precedent_ref": "case:example-precedent",
            "scenario_evidence_ref": None,
        },
    }
    document.update(overrides)
    return document


def _authorization(**overrides: Any) -> StandingAuthorization:
    return StandingAuthorization.from_mapping(_document(**overrides))


def _request(**overrides: Any) -> AuthorizationRequest:
    base: dict[str, Any] = {
        "autonomy_class": AutonomyClass.A3_E,
        "service_ref": "service:example-expense",
        "incident_class": "capacity_saturation",
        "action_type": "ops.scale-out",
        "action_type_version": "1.0.0",
        "scope_value": "rg:example-expense",
        "target_revision": "rev-target-1",
        "policy_digest": "sha256:policy",
        "evidence_revisions": ("evidence-1",),
        "blast_radius": 2,
        "max_duration_seconds": 300,
        "reversible": True,
        "rollback_contract": "scripted",
        "executor_principal": "identity:thor-executor",
        "requester_principal": "example-requester",
    }
    base.update(overrides)
    return AuthorizationRequest(**base)


def test_a_complete_delegation_is_eligible() -> None:
    decision = evaluate_standing_authorization(_authorization(), _request(), now=NOW)

    assert decision.eligibility is Eligibility.ELIGIBLE
    assert decision.is_eligible
    assert decision.reason_code == "eligible"
    assert decision.authorization_id == "sa.example-scale-out"
    assert decision.authorization_revision == "rev-1"


def test_silence_is_not_authority() -> None:
    decision = evaluate_standing_authorization(None, _request(), now=NOW)

    assert decision.eligibility is Eligibility.INELIGIBLE
    assert decision.reason_code == "authorization_absent"


def test_a_naive_clock_is_a_missing_time_authority() -> None:
    decision = evaluate_standing_authorization(
        _authorization(),
        _request(),
        now=datetime(2026, 7, 5, 8, 0),
    )

    assert decision.reason_code == "clock_not_trusted"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"status": "revoked"}, "authorization_not_active"),
        ({"status": "expired"}, "authorization_not_active"),
        ({"status": "superseded"}, "authorization_not_active"),
        ({"valid_from": "2026-07-06T00:00:00Z"}, "outside_validity_interval"),
        ({"service_ref": "service:example-other"}, "service_mismatch"),
        ({"scope": {"level": "resource_group", "value": "rg:example-other"}}, "scope_mismatch"),
        (
            {
                "approvals": [
                    {
                        "principal": "example-service-owner",
                        "role": "service_owner",
                        "approved_at": "2026-07-01T08:00:00Z",
                    },
                    {
                        "principal": "example-service-owner",
                        "role": "owner",
                        "approved_at": "2026-07-01T09:00:00Z",
                    },
                ]
            },
            "quorum_not_met",
        ),
        (
            {
                "approvals": [
                    {
                        "principal": "example-approver-a",
                        "role": "approver",
                        "approved_at": "2026-07-01T08:00:00Z",
                    },
                    {
                        "principal": "example-owner",
                        "role": "owner",
                        "approved_at": "2026-07-01T09:00:00Z",
                    },
                ]
            },
            "service_owner_approval_missing",
        ),
        (
            {
                "approvals": [
                    {
                        "principal": "example-service-owner",
                        "role": "service_owner",
                        "approved_at": "2026-07-01T08:00:00Z",
                    },
                    {
                        "principal": "example-approver-b",
                        "role": "approver",
                        "approved_at": "2026-07-01T09:00:00Z",
                    },
                ]
            },
            "owner_authority_approval_missing",
        ),
        (
            {
                "approvals": [
                    {
                        "principal": "example-requester",
                        "role": "service_owner",
                        "approved_at": "2026-07-01T08:00:00Z",
                    },
                    {
                        "principal": "example-owner",
                        "role": "owner",
                        "approved_at": "2026-07-01T09:00:00Z",
                    },
                ]
            },
            "self_approval",
        ),
        (
            {
                "pins": {
                    "policy_digest": "sha256:other",
                    "target_revision": "rev-target-1",
                    "action_type_versions": ["ops.scale-out@1.0.0"],
                    "evidence_revisions": ["evidence-1"],
                }
            },
            "policy_digest_mismatch",
        ),
        (
            {
                "pins": {
                    "policy_digest": "sha256:policy",
                    "target_revision": "rev-target-2",
                    "action_type_versions": ["ops.scale-out@1.0.0"],
                    "evidence_revisions": ["evidence-1"],
                }
            },
            "target_revision_mismatch",
        ),
        (
            {
                "pins": {
                    "policy_digest": "sha256:policy",
                    "target_revision": "rev-target-1",
                    "action_type_versions": ["ops.scale-out@2.0.0"],
                    "evidence_revisions": ["evidence-1"],
                }
            },
            "action_type_version_not_pinned",
        ),
        (
            {
                "pins": {
                    "policy_digest": "sha256:policy",
                    "target_revision": "rev-target-1",
                    "action_type_versions": ["ops.scale-out@1.0.0"],
                    "evidence_revisions": ["evidence-2"],
                }
            },
            "evidence_revision_mismatch",
        ),
        (
            {
                "responders": {
                    "primary": "example-primary",
                    "backup": "example-backup",
                    "confirmed_at": "2026-05-01T08:00:00Z",
                }
            },
            "responder_confirmation_stale",
        ),
        (
            {
                "responders": {
                    "primary": "example-primary",
                    "backup": "example-backup",
                    "confirmed_at": "2026-07-20T08:00:00Z",
                }
            },
            "responder_confirmation_in_the_future",
        ),
        (
            {"evidence": {"history_reviewed": False, "precedent_ref": "case:example-precedent"}},
            "history_not_reviewed",
        ),
        (
            {
                "evidence": {
                    "history_reviewed": True,
                    "precedent_ref": None,
                    "scenario_evidence_ref": None,
                }
            },
            "no_precedent_or_scenario_evidence",
        ),
    ],
)
def test_each_authorization_condition_has_a_failing_case(
    overrides: dict[str, Any],
    reason_code: str,
) -> None:
    decision = evaluate_standing_authorization(_authorization(**overrides), _request(), now=NOW)

    assert decision.eligibility is Eligibility.INELIGIBLE
    assert decision.reason_code == reason_code


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"autonomy_class": AutonomyClass.A4}, "a4_never_delegable"),
        ({"autonomy_class": AutonomyClass.A3_H}, "autonomy_class_not_a3e"),
        ({"autonomy_class": AutonomyClass.A1}, "autonomy_class_not_a3e"),
        ({"action_type": "ops.delete-resource"}, "action_type_version_not_pinned"),
        ({"incident_class": "data_loss"}, "incident_class_outside_envelope"),
        ({"blast_radius": 4}, "blast_radius_exceeds_envelope"),
        ({"max_duration_seconds": 900}, "duration_exceeds_envelope"),
        ({"reversible": False}, "action_not_reversible"),
        ({"rollback_contract": None}, "rollback_contract_mismatch"),
        ({"rollback_contract": "state_forward_only"}, "rollback_contract_mismatch"),
        ({"executor_principal": "example-owner"}, "self_approval"),
    ],
)
def test_each_request_condition_has_a_failing_case(
    overrides: dict[str, Any],
    reason_code: str,
) -> None:
    decision = evaluate_standing_authorization(_authorization(), _request(**overrides), now=NOW)

    assert decision.eligibility is Eligibility.INELIGIBLE
    assert decision.reason_code == reason_code


def test_a_run_that_would_outlive_the_authorization_is_ineligible() -> None:
    authorization = _authorization(valid_until="2026-07-05T08:02:00Z")
    decision = evaluate_standing_authorization(
        authorization,
        _request(max_duration_seconds=300),
        now=NOW,
    )

    assert decision.reason_code == "run_would_outlive_authorization"


def test_the_validity_interval_end_is_exclusive() -> None:
    authorization = _authorization(valid_until="2026-07-05T08:00:00Z")

    decision = evaluate_standing_authorization(authorization, _request(), now=NOW)

    assert decision.reason_code == "outside_validity_interval"


def test_a_run_that_ends_exactly_at_expiry_is_still_eligible() -> None:
    authorization = _authorization(valid_until="2026-07-05T08:05:00Z")

    decision = evaluate_standing_authorization(
        authorization,
        _request(max_duration_seconds=300),
        now=NOW,
    )

    assert decision.is_eligible


def test_enforce_mode_cannot_be_parsed() -> None:
    with pytest.raises(StandingAuthorizationError, match="invalid"):
        StandingAuthorization.from_mapping(_document(mode="enforce"))


def test_a_wider_than_resource_group_scope_cannot_be_parsed() -> None:
    with pytest.raises(StandingAuthorizationError, match="invalid"):
        StandingAuthorization.from_mapping(
            _document(scope={"level": "subscription", "value": "sub:example"})
        )


def test_the_evaluator_is_not_wired_into_any_decision_path() -> None:
    """The absence of wiring is a deliberate contract, so it is pinned, not remembered.

    Wiring this evaluator would raise autonomy. FDAI-CONST-007 and FDAI-CONST-008 require a
    governed shadow cohort with zero envelope escapes and an independent promotion review
    first, and neither exists.
    """

    guarded = ("risk_gate", "executor", "hil_resume", "control_loop")
    offenders: list[str] = []
    for subsystem in guarded:
        subsystem_root = SOURCE_ROOT / "core" / subsystem
        # Non-vacuity: a renamed subsystem would make rglob silently scan nothing.
        assert subsystem_root.is_dir(), f"guarded subsystem {subsystem!r} no longer exists"
        modules = sorted(subsystem_root.rglob("*.py"))
        assert modules, f"guarded subsystem {subsystem!r} has no modules to scan"
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "fdai.core.standing_authority"
                ):
                    offenders.append(f"{path}:{node.lineno}")
                if isinstance(node, ast.Import):
                    offenders.extend(
                        f"{path}:{node.lineno}"
                        for alias in node.names
                        if alias.name.startswith("fdai.core.standing_authority")
                    )

    assert not offenders, f"standing authority is wired into a decision path: {offenders}"

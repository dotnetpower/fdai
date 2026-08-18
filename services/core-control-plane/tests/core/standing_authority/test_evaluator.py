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


#: Every authorization-side condition, paired with the exact reason code it must produce.
#: `test_every_reason_code_the_evaluator_can_return_has_a_case` reads this table, so a new
#: condition in the evaluator cannot ship without a case here.
_AUTHORIZATION_CASES: list[tuple[dict[str, Any], str]] = [
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
]


@pytest.mark.parametrize(("overrides", "reason_code"), _AUTHORIZATION_CASES)
def test_each_authorization_condition_has_a_failing_case(
    overrides: dict[str, Any],
    reason_code: str,
) -> None:
    decision = evaluate_standing_authorization(_authorization(**overrides), _request(), now=NOW)

    assert decision.eligibility is Eligibility.INELIGIBLE
    assert decision.reason_code == reason_code


#: Every request-side condition, paired with the exact reason code it must produce.
_REQUEST_CASES: list[tuple[dict[str, Any], str]] = [
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
]


@pytest.mark.parametrize(("overrides", "reason_code"), _REQUEST_CASES)
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


def test_an_action_type_outside_the_envelope_is_ineligible() -> None:
    """Needs both sides overridden: the pin check runs first and would mask the envelope.

    Pinning a version for an action type the envelope never allowed is the shape that makes
    this condition reachable, and it is exactly the mistake a delegation edit can make.
    """

    authorization = _authorization(
        pins={
            "policy_digest": "sha256:policy",
            "target_revision": "rev-target-1",
            "action_type_versions": ["ops.scale-out@1.0.0", "ops.delete-resource@1.0.0"],
            "evidence_revisions": ["evidence-1"],
        }
    )
    decision = evaluate_standing_authorization(
        authorization,
        _request(action_type="ops.delete-resource"),
        now=NOW,
    )

    assert decision.eligibility is Eligibility.INELIGIBLE
    assert decision.reason_code == "action_type_outside_envelope"


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


#: Reason codes produced outside the two case tables, each asserted by its own test above.
_STANDALONE_REASON_CODES = frozenset(
    {
        "eligible",
        "authorization_absent",
        "clock_not_trusted",
        "outside_validity_interval",
        "run_would_outlive_authorization",
        "action_type_outside_envelope",
        # Unreachable through `from_mapping`, which rejects an enforce mode and a wider scope
        # before the evaluator sees them. Both are defense in depth against direct
        # construction and have their parse-time tests above.
        "mode_not_shadow",
        "scope_too_wide",
    }
)


def _declared_reason_codes() -> set[str]:
    """Return every reason code the evaluator source can return.

    Reading the source rather than a hand-kept list is the point: a new condition added to
    the evaluator without a case below fails this test instead of shipping unmeasured.
    """

    tree = ast.parse(
        (SOURCE_ROOT / "core" / "standing_authority" / "evaluator.py").read_text(encoding="utf-8")
    )
    codes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                codes.add(node.value.value)
        if isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Name) and called.id == "_deny" and len(node.args) >= 2:
                argument = node.args[1]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    codes.add(argument.value)
            for keyword in node.keywords:
                if keyword.arg == "reason_code" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        codes.add(keyword.value.value)
    return codes


def test_every_reason_code_the_evaluator_can_return_has_a_case() -> None:
    """The eleven-condition claim in this module's docstring is enforced, not remembered."""

    declared = _declared_reason_codes()
    # Non-vacuity: an extraction that finds nothing would make the subset check trivially true.
    assert len(declared) >= 20, f"the reason-code scan looks vacuous: {sorted(declared)}"
    assert "quorum_not_met" in declared

    covered = (
        {code for _, code in _AUTHORIZATION_CASES}
        | {code for _, code in _REQUEST_CASES}
        | _STANDALONE_REASON_CODES
    )

    assert not declared - covered, f"reason codes with no case: {sorted(declared - covered)}"
    assert not covered - declared, (
        f"cases for reason codes the evaluator cannot return: {sorted(covered - declared)}"
    )

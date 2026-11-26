"""Regression tests for the workload RBAC least-privilege rule pack.

Covers the five authored rules that close the identity / least-privilege
coverage gap (Phase A):

* ``managed-identity.role-assignment.no-privileged-subscription-scope``
* ``managed-identity.role-assignment.no-wildcard-action``
* ``subscription.role-assignment.no-guest-privileged``
* ``subscription.role-assignment.no-standing-privileged-access``
* ``resource-group.role-assignment.owner-count-within-limit``

Each rule is exercised through the real OPA subprocess evaluator with a
violating input (deny + cited reason) and a compliant input (no deny), so a
regression in the Rego or a schema drift in the rule YAML fails here. The
tests skip when the ``opa`` binary is not on ``PATH``; CI installs OPA so the
merge gate always runs them.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator, PolicyResult
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[6]
POLICIES_ROOT = REPO_ROOT / "policies"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT, reason="opa binary not found on PATH; skip subprocess tests"
)


def _rules_by_id() -> Mapping[str, Rule]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        RULES_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
    )
    return {r.id: r for r in rules}


def _evaluate(rule_id: str, props: Mapping[str, object]) -> PolicyResult:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    result = evaluator.evaluate(_rules_by_id()[rule_id], props)
    assert isinstance(result, PolicyResult)
    return result


# ---------------------------------------------------------------------------
# managed-identity.role-assignment.no-privileged-subscription-scope
# ---------------------------------------------------------------------------


@requires_opa
def test_workload_identity_subscription_owner_denied() -> None:
    result = _evaluate(
        "managed-identity.role-assignment.no-privileged-subscription-scope",
        {"role_assignments": [{"scope": "subscription", "role_name": "Owner"}]},
    )
    assert result.denied is True
    assert result.context.get("deny_reason") == "workload_identity_privileged_at_subscription_scope"


@requires_opa
def test_workload_identity_scoped_reader_not_denied() -> None:
    result = _evaluate(
        "managed-identity.role-assignment.no-privileged-subscription-scope",
        {"role_assignments": [{"scope": "resource-group", "role_name": "Reader"}]},
    )
    assert result.denied is False


@requires_opa
def test_workload_identity_missing_scope_fails_closed() -> None:
    result = _evaluate(
        "managed-identity.role-assignment.no-privileged-subscription-scope",
        {"role_assignments": [{"role_name": "Reader"}]},
    )
    assert result.denied is True


# ---------------------------------------------------------------------------
# managed-identity.role-assignment.no-wildcard-action
# ---------------------------------------------------------------------------


@requires_opa
def test_wildcard_action_denied() -> None:
    result = _evaluate(
        "managed-identity.role-assignment.no-wildcard-action",
        {"role_assignments": [{"scope": "resource", "role_name": "Custom", "actions": ["*"]}]},
    )
    assert result.denied is True
    assert result.context.get("deny_reason") == "workload_identity_role_grants_wildcard_action"


@requires_opa
def test_scoped_actions_not_denied() -> None:
    result = _evaluate(
        "managed-identity.role-assignment.no-wildcard-action",
        {
            "role_assignments": [
                {
                    "scope": "resource",
                    "role_name": "Custom",
                    "actions": ["Microsoft.Storage/*/read"],
                }
            ]
        },
    )
    assert result.denied is False


# ---------------------------------------------------------------------------
# subscription.role-assignment.no-guest-privileged
# ---------------------------------------------------------------------------


@requires_opa
def test_guest_owner_denied() -> None:
    result = _evaluate(
        "subscription.role-assignment.no-guest-privileged",
        {"role_assignments": [{"principal_type": "Guest", "role_name": "Owner"}]},
    )
    assert result.denied is True
    assert result.context.get("deny_reason") == "guest_principal_privileged_at_subscription_scope"


@requires_opa
def test_member_owner_not_denied_by_guest_rule() -> None:
    result = _evaluate(
        "subscription.role-assignment.no-guest-privileged",
        {"role_assignments": [{"principal_type": "User", "role_name": "Owner"}]},
    )
    assert result.denied is False


# ---------------------------------------------------------------------------
# subscription.role-assignment.no-standing-privileged-access
# ---------------------------------------------------------------------------


@requires_opa
def test_standing_owner_denied() -> None:
    result = _evaluate(
        "subscription.role-assignment.no-standing-privileged-access",
        {"role_assignments": [{"role_name": "Owner", "standing": True}]},
    )
    assert result.denied is True
    assert result.context.get("deny_reason") == "standing_privileged_subscription_access"


@requires_opa
def test_eligible_owner_not_denied() -> None:
    result = _evaluate(
        "subscription.role-assignment.no-standing-privileged-access",
        {"role_assignments": [{"role_name": "Owner", "standing": False}]},
    )
    assert result.denied is False


@requires_opa
def test_missing_standing_flag_fails_closed() -> None:
    result = _evaluate(
        "subscription.role-assignment.no-standing-privileged-access",
        {"role_assignments": [{"role_name": "Owner"}]},
    )
    assert result.denied is True


# ---------------------------------------------------------------------------
# resource-group.role-assignment.owner-count-within-limit
# ---------------------------------------------------------------------------


@requires_opa
def test_owner_count_over_limit_denied() -> None:
    result = _evaluate(
        "resource-group.role-assignment.owner-count-within-limit",
        {
            "role_assignments": [
                {"role_name": "Owner"},
                {"role_name": "Owner"},
                {"role_name": "Owner"},
                {"role_name": "Owner"},
            ]
        },
    )
    assert result.denied is True
    assert result.context.get("deny_reason") == "resource_group_owner_count_exceeds_limit"


@requires_opa
def test_owner_count_within_limit_not_denied() -> None:
    result = _evaluate(
        "resource-group.role-assignment.owner-count-within-limit",
        {"role_assignments": [{"role_name": "Owner"}, {"role_name": "Reader"}]},
    )
    assert result.denied is False

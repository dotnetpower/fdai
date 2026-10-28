"""Pure shared Settings policy validation without provider/storage dependencies."""

from __future__ import annotations

import ast
import inspect

import pytest
from fdai.core.readiness import resource_availability_settings as schema
from fdai.core.readiness.resource_availability_settings import (
    RESOURCE_AVAILABILITY_RESOURCE_TYPES,
    validate_resource_availability_setting,
)

REF = "scope-example/resource-group/example/compute/example"


def _policy(**changes):
    return {
        "enabled": True,
        "resource_types": ["compute.vm"],
        "resources": {},
        **changes,
    }


def _declared(**changes):
    return {
        "resource_type": "compute.vm",
        "reference": "policy:example",
        **changes,
    }


def test_pure_schema_has_no_delivery_or_provider_sdk_imports() -> None:
    tree = ast.parse(inspect.getsource(schema))
    imports = [
        module
        for node in ast.walk(tree)
        for module in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else []
        )
    ]
    assert not any(
        name.startswith(("fdai.delivery", "azure", "httpx", "psycopg")) for name in imports
    )


def test_disabled_default_and_unspecified_expectation_are_preserved() -> None:
    default = validate_resource_availability_setting({})
    assert default == dict(schema.DEFAULT_RESOURCE_AVAILABILITY_SETTINGS)
    declared = validate_resource_availability_setting(_policy(resources={REF: _declared()}))
    assert declared["resources"][REF]["expected_state"] is None


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_AVAILABILITY_RESOURCE_TYPES))
def test_all_existing_canonical_resource_types_remain_accepted(resource_type) -> None:
    result = validate_resource_availability_setting(_policy(resource_types=[resource_type]))
    assert result["resource_types"] == [resource_type]


@pytest.mark.parametrize("age", [float("inf"), float("-inf"), float("nan"), 0, -1, 86_401, True])
def test_freshness_remains_finite_positive_bounded_and_not_boolean(age) -> None:
    with pytest.raises(ValueError, match="setting is invalid"):
        validate_resource_availability_setting(_policy(max_age_seconds=age))


@pytest.mark.parametrize(
    "reference",
    [
        "/subscriptions/example/providers/example/resource",
        "https://example.com/policy",
        "policy:",
        "policy:example/child",
        "policy:" + "x" * 448,
        "unreviewed:example",
    ],
)
def test_references_remain_bounded_opaque_handles(reference) -> None:
    with pytest.raises(ValueError, match="setting is invalid"):
        validate_resource_availability_setting(
            _policy(
                resources={
                    REF: _declared(reference=reference),
                }
            )
        )


@pytest.mark.parametrize(
    ("since", "until"),
    [
        ("2026-10-28T12:00:00", "2026-10-28T13:00:00Z"),
        ("2026-10-28T12:00:00Z", "2026-10-28T13:00:00"),
        ("2026-10-28T13:00:00Z", "2026-10-28T12:00:00Z"),
        ("2026-10-28T12:00:00Z", "2026-10-28T12:00:00Z"),
        (float("inf"), "2026-10-28T13:00:00Z"),
    ],
)
def test_planned_windows_remain_finite_aware_and_ordered(since, until) -> None:
    with pytest.raises(ValueError, match="setting is invalid"):
        validate_resource_availability_setting(
            _policy(
                resources={
                    REF: _declared(
                        planned_stops=[
                            {
                                "since": since,
                                "until": until,
                                "reference": "maintenance:example",
                            }
                        ]
                    ),
                }
            )
        )


def test_explicit_intent_and_maintenance_round_trip_as_json_native_values() -> None:
    result = validate_resource_availability_setting(
        _policy(
            resources={
                REF: _declared(
                    expected_state="running",
                    planned_stops=[
                        {
                            "since": "2026-10-28T12:00:00Z",
                            "until": "2026-10-28T13:00:00Z",
                            "reference": "maintenance:example",
                            "maintenance": True,
                        }
                    ],
                ),
            }
        )
    )
    assert validate_resource_availability_setting(result) == result
    assert result["resources"][REF]["expected_state"] == "running"

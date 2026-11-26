"""Governance-level parameter-relaxation bounds policy."""

from __future__ import annotations

import pytest
from fdai.rule_catalog.schema.parameter_relaxation_policy import (
    ParameterBound,
    parameter_relaxation_policies_from_mapping,
)


def test_numeric_bound_allows_within_range() -> None:
    bound = ParameterBound(key="min_retention_days", minimum=1, maximum=30)
    assert bound.allows("3")
    assert bound.allows("1")
    assert bound.allows("30")


def test_numeric_bound_rejects_outside_range() -> None:
    bound = ParameterBound(key="min_retention_days", minimum=1, maximum=30)
    assert not bound.allows("0")
    assert not bound.allows("31")


def test_numeric_bound_rejects_non_numeric_value() -> None:
    bound = ParameterBound(key="min_retention_days", minimum=1, maximum=30)
    assert not bound.allows("not-a-number")


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_numeric_bound_rejects_non_finite_value(value: str) -> None:
    bound = ParameterBound(key="min_retention_days", minimum=1, maximum=30)
    assert not bound.allows(value)


def test_enumerated_bound_allows_listed_values_only() -> None:
    bound = ParameterBound(key="mode", allowed_values=frozenset({"full", "incremental"}))
    assert bound.allows("full")
    assert not bound.allows("differential")


def test_bound_requires_range_or_allowed_values() -> None:
    with pytest.raises(ValueError, match="numeric range or allowed_values"):
        ParameterBound(key="x")


def test_bound_rejects_combining_range_and_allowed_values() -> None:
    with pytest.raises(ValueError, match="MUST NOT combine"):
        ParameterBound(key="x", minimum=1, allowed_values=frozenset({"a"}))


def test_bound_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="minimum MUST NOT exceed maximum"):
        ParameterBound(key="x", minimum=10, maximum=1)


def test_policy_allows_only_the_declared_key_and_bound() -> None:
    policies = parameter_relaxation_policies_from_mapping(
        {
            "rules": {
                "postgresql-server.point-in-time-restore": {
                    "min_retention_days": {"minimum": 1, "maximum": 30}
                }
            }
        }
    )
    policy = policies["postgresql-server.point-in-time-restore"]
    assert policy.allows("min_retention_days", "3")
    assert not policy.allows("min_retention_days", "999")
    assert not policy.allows("unlisted_key", "anything")


def test_rule_without_policy_entry_allows_nothing() -> None:
    policies = parameter_relaxation_policies_from_mapping({"rules": {}})
    assert policies == {}


def test_malformed_rules_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="'rules' MUST be a mapping"):
        parameter_relaxation_policies_from_mapping({"rules": ["not", "a", "mapping"]})


def test_malformed_rule_bounds_is_rejected() -> None:
    with pytest.raises(ValueError, match="MUST be a mapping"):
        parameter_relaxation_policies_from_mapping({"rules": {"rule.x": ["not", "a", "mapping"]}})

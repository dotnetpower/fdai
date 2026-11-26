"""Correlation-id context propagation."""

from __future__ import annotations

import pytest
from fdai.shared.telemetry import current_correlation_id, with_correlation


def test_default_is_none() -> None:
    assert current_correlation_id() is None


def test_scope_binds_and_unbinds() -> None:
    assert current_correlation_id() is None
    with with_correlation("evt-1"):
        assert current_correlation_id() == "evt-1"
    assert current_correlation_id() is None


def test_nested_scopes_restore_outer_value() -> None:
    with with_correlation("outer"):
        assert current_correlation_id() == "outer"
        with with_correlation("inner"):
            assert current_correlation_id() == "inner"
        assert current_correlation_id() == "outer"
    assert current_correlation_id() is None


def test_empty_string_is_rejected() -> None:
    with pytest.raises(ValueError):
        with with_correlation(""):
            pass

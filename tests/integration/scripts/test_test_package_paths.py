"""Regression coverage for repository and service test package composition."""

from tests.core.case_history.test_operational_case import _case_input
from tests.persistence.test_state_store_case_history import _record


def test_root_tests_package_exposes_core_service_helpers() -> None:
    assert callable(_case_input)
    assert callable(_record)

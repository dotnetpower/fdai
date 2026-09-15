"""Compatibility and bounded diagnostic metadata for metric failures."""

from typing import cast

import pytest
from fdai.shared.providers.metric import MetricFailureReason, MetricProviderError


def test_legacy_error_preserves_message_and_defaults_to_unknown() -> None:
    error = MetricProviderError("legacy failure")

    assert isinstance(error, RuntimeError)
    assert str(error) == "legacy failure"
    assert error.args == ("legacy failure",)
    assert error.reason is MetricFailureReason.UNKNOWN
    assert error.http_status is None
    assert error.safe_context == "reason=unknown"


@pytest.mark.parametrize("reason", list(MetricFailureReason))
def test_safe_context_never_renders_exception_message(reason: MetricFailureReason) -> None:
    error = MetricProviderError("private provider response", reason=reason, http_status=429)

    assert error.reason is reason
    assert error.http_status == 429
    assert error.safe_context == f"reason={reason.value}, http_status=429"
    assert "private" not in error.safe_context


@pytest.mark.parametrize("status", [100, 200, 403, 429, 503, 599])
def test_http_status_accepts_only_bounded_integers(status: int) -> None:
    assert MetricProviderError("failure", http_status=status).http_status == status


@pytest.mark.parametrize("status", [True, False, 99, 600, "429", 429.0, "private response"])
def test_invalid_http_status_is_rejected_without_echoing_input(status: object) -> None:
    with pytest.raises(ValueError) as captured:
        MetricProviderError("failure", http_status=cast(int, status))

    assert str(captured.value) == ("metric failure HTTP status MUST be an integer from 100 to 599")


@pytest.mark.parametrize("reason", ["timeout", "private response", None, 429])
def test_untyped_reason_is_rejected_without_echoing_input(reason: object) -> None:
    with pytest.raises(ValueError) as captured:
        MetricProviderError("failure", reason=cast(MetricFailureReason, reason))

    assert str(captured.value) == "metric failure reason MUST be a MetricFailureReason"

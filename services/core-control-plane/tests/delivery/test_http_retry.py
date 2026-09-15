"""Provider cooldown hints preserve time and never cause an immediate retry."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.http_retry import InvalidRetryAfterError, retry_after_seconds, retry_not_before

NOW = datetime(2026, 9, 15, 8, tzinfo=UTC)


def test_retry_deadline_uses_latest_standard_and_provider_hint() -> None:
    result = retry_not_before(
        {"Retry-After": "120", "x-provider-retry": "600"},
        now=NOW,
        extra_headers=("x-provider-retry",),
    )
    assert result == NOW + timedelta(seconds=600)
    assert retry_not_before({"Retry-After": "Tue, 15 Sep 2026 08:10:00 GMT"}, now=NOW) == result


def test_missing_and_expired_hints_preserve_the_configured_schedule() -> None:
    assert retry_not_before({}, now=NOW) is None
    assert retry_not_before({"Retry-After": "0"}, now=NOW) == NOW
    assert retry_not_before({"Retry-After": "Tue, 15 Sep 2026 07:00:00 GMT"}, now=NOW) == NOW


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "invalid", "Tue, 15 Sep 2026 08:10:00"])
def test_invalid_retry_hints_are_explicit_errors(value: str) -> None:
    with pytest.raises(ValueError, match="Retry-After"):
        retry_not_before({"Retry-After": value}, now=NOW)


def test_unrepresentable_positive_delay_never_becomes_an_early_retry() -> None:
    assert retry_not_before({"Retry-After": "9" * 40}, now=NOW) == datetime.max.replace(tzinfo=UTC)


def test_numeric_parser_keeps_existing_arg_behavior() -> None:
    assert retry_after_seconds("0.5") == 0.5
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("NaN") is None


@pytest.mark.parametrize("standard", ["invalid", "172800"])
def test_malformed_companion_hint_keeps_the_valid_cooldown(standard: str) -> None:
    headers = {
        "Retry-After": standard,
        "x-provider-retry": "172800" if standard == "invalid" else "invalid",
    }
    with pytest.raises(InvalidRetryAfterError) as error:
        retry_not_before(headers, now=NOW, extra_headers=("x-provider-retry",))
    assert error.value.retry_not_before == NOW + timedelta(days=2)

"""Read-only Azure AI model deployment summary tests."""

from __future__ import annotations

from fdai.delivery.azure.model_deployment import model_deployment_summary


def _row(
    *,
    token_count: int,
    renewal_period: int = 60,
    current_capacity: int = 50,
) -> dict[str, object]:
    return {
        "name": "gpt-example",
        "sku": {"name": "GlobalStandard", "capacity": 50},
        "properties": {
            "provisioningState": "Succeeded",
            "currentCapacity": current_capacity,
            "model": {
                "format": "OpenAI",
                "name": "gpt-5.4",
                "version": "2026-09-01",
            },
            "rateLimits": [
                {"key": "request", "count": 50, "renewalPeriod": 60},
                {
                    "key": "token",
                    "count": token_count,
                    "renewalPeriod": renewal_period,
                },
            ],
        },
    }


def test_provider_token_rate_is_normalized_to_tpm() -> None:
    summary = model_deployment_summary(_row(token_count=25_000, renewal_period=30))

    assert summary["capacity_units"] == 50
    assert summary["capacity_tpm"] == 50_000
    assert summary["capacity_tpm_source"] == "properties.rateLimits"


def test_changed_provider_token_rate_changes_observed_tpm() -> None:
    before = model_deployment_summary(_row(token_count=50_000))
    after = model_deployment_summary(_row(token_count=60_000))

    assert before["capacity_tpm"] == 50_000
    assert after["capacity_tpm"] == 60_000


def test_capacity_transition_separates_requested_and_current_units() -> None:
    summary = model_deployment_summary(_row(token_count=50_000, current_capacity=40))

    assert summary["capacity_units"] == 50
    assert summary["current_capacity_units"] == 40
    assert summary["capacity_transitioning"] is True


def test_equal_requested_and_current_capacity_is_not_transitioning() -> None:
    summary = model_deployment_summary(_row(token_count=50_000))

    assert summary["current_capacity_units"] == 50
    assert summary["capacity_transitioning"] is False


def test_conflicting_token_rates_do_not_publish_a_tpm_value() -> None:
    row = _row(token_count=50_000)
    properties = row["properties"]
    assert isinstance(properties, dict)
    rate_limits = properties["rateLimits"]
    assert isinstance(rate_limits, list)
    rate_limits.append({"key": "TPM", "count": 60_000, "renewalPeriod": 60})

    summary = model_deployment_summary(row)

    assert summary["capacity_units"] == 50
    assert "capacity_tpm" not in summary
    assert "capacity_tpm_source" not in summary


def test_malformed_recognized_token_rate_invalidates_tpm_evidence() -> None:
    row = _row(token_count=50_000)
    properties = row["properties"]
    assert isinstance(properties, dict)
    rate_limits = properties["rateLimits"]
    assert isinstance(rate_limits, list)
    rate_limits.append({"key": "tokens", "count": "60000", "renewalPeriod": 60})

    summary = model_deployment_summary(row)

    assert summary["capacity_units"] == 50
    assert "capacity_tpm" not in summary
    assert "capacity_tpm_source" not in summary


def test_non_object_rate_rule_invalidates_tpm_evidence() -> None:
    row = _row(token_count=50_000)
    properties = row["properties"]
    assert isinstance(properties, dict)
    rate_limits = properties["rateLimits"]
    assert isinstance(rate_limits, list)
    rate_limits.append("malformed")

    summary = model_deployment_summary(row)

    assert summary["capacity_units"] == 50
    assert "capacity_tpm" not in summary


def test_oversized_rate_limit_collection_does_not_publish_tpm() -> None:
    row = _row(token_count=50_000)
    properties = row["properties"]
    assert isinstance(properties, dict)
    properties["rateLimits"] = [
        {"key": "token", "count": 50_000, "renewalPeriod": 60} for _ in range(65)
    ]

    summary = model_deployment_summary(row)

    assert summary["capacity_units"] == 50
    assert "capacity_tpm" not in summary


def test_capacity_units_alone_do_not_invent_tpm() -> None:
    row = _row(token_count=50_000)
    properties = row["properties"]
    assert isinstance(properties, dict)
    properties.pop("rateLimits")

    summary = model_deployment_summary(row)

    assert summary["capacity_units"] == 50
    assert "capacity_tpm" not in summary

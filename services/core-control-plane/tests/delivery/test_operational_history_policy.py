"""Deployment-owned operational history retention policy tests."""

from __future__ import annotations

import json

import pytest
from fdai.delivery.operational_history_policy import (
    RETENTION_POLICY_PATH_ENV,
    load_operational_history_retention_policies,
)


def test_missing_deployment_policy_keeps_safe_retain_default() -> None:
    assert load_operational_history_retention_policies({}) == ()


def test_deployment_policy_file_is_typed_and_content_addressed(tmp_path) -> None:
    path = tmp_path / "retention.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "policies": [
                    {
                        "policy_id": "full-v1",
                        "fact_family": "full_observation",
                        "purpose": "bounded-exact-replay",
                        "hot_retention_seconds": 3600,
                        "warm_retention_seconds": 86400,
                        "archive_class": "operational-history",
                        "deletion_method": "partition_purge",
                        "review_at": "2026-10-05T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (policy,) = load_operational_history_retention_policies({RETENTION_POLICY_PATH_ENV: str(path)})

    assert policy.fact_family == "full_observation"
    assert policy.digest.startswith("sha256:")


def test_malformed_deployment_policy_fails_closed(tmp_path) -> None:
    path = tmp_path / "retention.json"
    path.write_text('{"schema_version":"1.0.0","policies":"bad"}', encoding="utf-8")

    with pytest.raises(ValueError, match="MUST be an array"):
        load_operational_history_retention_policies({RETENTION_POLICY_PATH_ENV: str(path)})

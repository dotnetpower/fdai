"""Protected cohort observation import CLI tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicyError
from fdai.delivery.measurement import cohort_observation_import_cli
from fdai.delivery.measurement.cohort_observation_import import (
    cohort_observation_batch_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
REVISION = "0123456789abcdef0123456789abcdef01234567"


def _batch(tmp_path: Path) -> Path:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "observations": [
            {
                "kind": "metric",
                "metric_id": "auto_resolution_rate",
                "source_cluster_digest": "sha256:" + "1" * 64,
                "observed_at": datetime(2026, 9, 11, tzinfo=UTC).isoformat(),
                "value": 1,
            }
        ],
    }
    values["batch_digest"] = cohort_observation_batch_digest(**values)
    path = tmp_path / "cohort-observation-batch.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def _args(tmp_path: Path) -> list[str]:
    return [
        "--batch",
        str(_batch(tmp_path)),
        "--policy",
        str(REPO_ROOT / "config/sre-cohort-claim-policy.json"),
        "--arm",
        "treatment",
        "--revision",
        REVISION,
        "--source-workflow-path",
        ".github/workflows/cohort-treatment-export.yml",
        "--source-run-id",
        "123",
        "--source-run-attempt",
        "1",
        "--source-artifact-name",
        "cohort-observations-treatment",
        "--imported-at",
        "2026-09-11T00:00:00Z",
    ]


def test_cli_requires_the_private_state_store_dsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)

    with pytest.raises(ValueError, match="MUST be configured"):
        cohort_observation_import_cli.main(_args(tmp_path))


def test_cli_fails_closed_while_exporter_allowlist_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")

    with pytest.raises(CohortClaimPolicyError, match="allowlist is empty"):
        cohort_observation_import_cli.main(_args(tmp_path))

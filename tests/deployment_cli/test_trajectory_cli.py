from __future__ import annotations

import io
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.trajectory import TrajectoryValidationReport


def test_fdaictl_trajectory_validate_requires_and_forwards_purpose_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def validate(**kwargs: object) -> TrajectoryValidationReport:
        captured.update(kwargs)
        return TrajectoryValidationReport(
            dataset_id="dataset-1",
            record_count=3,
            dataset_checksum="a" * 64,
            manifest_checksum="b" * 64,
        )

    monkeypatch.setattr("fdai.deployment_cli.cli.validate_trajectory_dataset", validate)
    output = io.StringIO()
    dataset = tmp_path / "dataset.jsonl"
    manifest = tmp_path / "dataset.manifest.json"

    exit_code = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset),
            "--manifest",
            str(manifest),
            "--purpose",
            "quality-review",
            "--access-scope",
            "scope-example",
        ],
        stdout=output,
    )

    assert exit_code == 0
    assert captured == {
        "dataset_path": dataset,
        "manifest_path": manifest,
        "purpose": "quality-review",
        "access_scope": "scope-example",
    }
    assert output.getvalue() == "VALID dataset-1: 3 records\n"

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.configuration_drift_cli import main

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _docx(path: Path, text: str = "Configuration baseline") -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def _observation(path: Path, *, sku: str = "Standard") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scope": "example-scope",
                "observed_at": _NOW.isoformat(),
                "source": "authoritative inventory",
                "completeness": "complete",
                "resources": [
                    {
                        "local_name": "service-a",
                        "resource_type": "example/service",
                        "region": "korea central",
                        "attributes": {"sku": sku},
                        "unknown_attributes": [],
                        "unauthorized_attributes": [],
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )


def test_freeze_validate_and_check_round_trip(tmp_path: Path, capsys: object) -> None:
    document = tmp_path / "baseline.docx"
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    _docx(document)
    _observation(observation)

    assert (
        main(
            [
                "freeze",
                "--observation",
                str(observation),
                "--document",
                str(document),
                "--version",
                "s13-v1",
                "--source",
                "reviewed inventory snapshot",
                "--created-at",
                _NOW.isoformat(),
                "--output",
                str(baseline),
                "--unknown-item",
                "certificate metadata unavailable",
            ]
        )
        == 0
    )
    frozen = json.loads(baseline.read_text())
    baseline_sha256 = json.loads(capsys.readouterr().out)["baseline_sha256"]  # type: ignore[attr-defined]
    assert frozen["scope"] == "example-scope"
    assert frozen["unknown_items"] == ["certificate metadata unavailable"]

    assert (
        main(
            [
                "validate",
                "--baseline",
                str(baseline),
                "--document",
                str(document),
            ]
        )
        == 0
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    assert (
        main(
            [
                "check",
                "--baseline",
                str(baseline),
                "--observation",
                str(observation),
                "--expected-version",
                "s13-v1",
                "--expected-sha256",
                baseline_sha256,
                "--expected-scope",
                "example-scope",
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["verdict"] == "blocked"
    assert any(finding["field"] == "unknown_item" for finding in report["findings"])
    assert report["mutation_count"] == 0


def test_check_reports_changed_configuration(tmp_path: Path, capsys: object) -> None:
    document = tmp_path / "baseline.docx"
    baseline_observation = tmp_path / "baseline-observation.json"
    current_observation = tmp_path / "current-observation.json"
    baseline = tmp_path / "baseline.json"
    _docx(document)
    _observation(baseline_observation)
    _observation(current_observation, sku="Premium")

    assert (
        main(
            [
                "freeze",
                "--observation",
                str(baseline_observation),
                "--document",
                str(document),
                "--version",
                "s13-v1",
                "--source",
                "reviewed inventory snapshot",
                "--created-at",
                _NOW.isoformat(),
                "--output",
                str(baseline),
            ]
        )
        == 0
    )
    baseline_sha256 = json.loads(capsys.readouterr().out)["baseline_sha256"]  # type: ignore[attr-defined]

    assert (
        main(
            [
                "check",
                "--baseline",
                str(baseline),
                "--observation",
                str(current_observation),
                "--expected-version",
                "s13-v1",
                "--expected-sha256",
                baseline_sha256,
                "--expected-scope",
                "example-scope",
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["verdict"] == "failed"
    assert any(finding["drift_type"] == "changed" for finding in report["findings"])


def test_freeze_rejects_visible_sensitive_identifiers(tmp_path: Path, capsys: object) -> None:
    document = tmp_path / "baseline.docx"
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    _docx(document, "subscription id 00000000-0000-0000-0000-000000000000")
    _observation(observation)

    assert (
        main(
            [
                "freeze",
                "--observation",
                str(observation),
                "--document",
                str(document),
                "--version",
                "s13-v1",
                "--source",
                "reviewed inventory snapshot",
                "--created-at",
                _NOW.isoformat(),
                "--output",
                str(baseline),
            ]
        )
        == 2
    )
    assert not baseline.exists()
    assert "ValueError" in capsys.readouterr().err  # type: ignore[attr-defined]

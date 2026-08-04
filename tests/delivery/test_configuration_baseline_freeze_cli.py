from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.detection.configuration_drift_codec import (
    baseline_from_dict,
    observation_from_dict,
)
from fdai.delivery.configuration_baseline_docx import (
    render_configuration_baseline_docx,
    validate_configuration_baseline_docx,
)
from fdai.delivery.configuration_baseline_freeze_cli import main
from fdai.shared.providers.local.document_structure import extract_ooxml

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _observation(path: Path, *, scope: str = "example-scope") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scope": scope,
                "observed_at": _NOW.isoformat(),
                "source": "authoritative inventory",
                "completeness": "complete",
                "resources": [
                    {
                        "local_name": "service-a",
                        "resource_type": "example/service",
                        "region": "korea central",
                        "attributes": {
                            "sku": "Standard",
                            "provisioning_state": "Succeeded",
                        },
                        "unknown_attributes": [],
                        "unauthorized_attributes": ["certificate_expiry"],
                    }
                ],
                "links": [
                    {
                        "source": "service-a",
                        "relation": "depends_on",
                        "target": "service-b",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_freeze_generates_matching_json_and_real_docx(tmp_path: Path, capsys: object) -> None:
    observation = tmp_path / "observation.json"
    output_json = tmp_path / "baseline.json"
    output_docx = tmp_path / "baseline.docx"
    _observation(observation)

    assert (
        main(
            [
                "--observation",
                str(observation),
                "--scope",
                "example-scope",
                "--version",
                "s13-v1",
                "--source",
                "reviewed inventory snapshot",
                "--created-at",
                _NOW.isoformat(),
                "--output-json",
                str(output_json),
                "--output-docx",
                str(output_docx),
                "--allowed-exception",
                "generated child names may change",
                "--unknown-item",
                "certificate metadata inaccessible",
            ]
        )
        == 0
    )

    receipt = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    baseline = baseline_from_dict(json.loads(output_json.read_text()))
    units = extract_ooxml(output_docx.read_bytes())
    text = "\n".join(unit.text for unit in units)

    assert baseline.sha256 == receipt["baseline_sha256"]
    assert baseline.document_sha256 == receipt["document_sha256"]
    assert len(output_docx.read_bytes()) < 16 * 1024 * 1024
    for heading in (
        "1. Document purpose and scope",
        "4. Expected resource inventory",
        "5. Workload topology",
        "6. Network baseline",
        "7. Observability baseline",
        "8. Certificate baseline",
        "9. Allowed exceptions and intended differences",
        "10. Unknown or insufficient-access items",
        "11. Drift decision rules",
    ):
        assert heading in text
    assert "certificate metadata inaccessible" in text
    assert "service-a depends_on service-b" in text


def test_freeze_rejects_out_of_scope_observation_without_outputs(
    tmp_path: Path,
    capsys: object,
) -> None:
    observation = tmp_path / "observation.json"
    output_json = tmp_path / "baseline.json"
    output_docx = tmp_path / "baseline.docx"
    _observation(observation, scope="another-scope")

    assert (
        main(
            [
                "--observation",
                str(observation),
                "--scope",
                "example-scope",
                "--version",
                "s13-v1",
                "--source",
                "reviewed inventory snapshot",
                "--created-at",
                _NOW.isoformat(),
                "--output-json",
                str(output_json),
                "--output-docx",
                str(output_docx),
            ]
        )
        == 2
    )
    assert not output_json.exists()
    assert not output_docx.exists()
    assert "PermissionError" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_docx_validator_rejects_different_resource_facts(tmp_path: Path) -> None:
    observation_path = tmp_path / "observation.json"
    _observation(observation_path)
    raw = json.loads(observation_path.read_text())
    baseline = baseline_from_dict(
        {
            "schema_version": "1.0.0",
            "version": "s13-v1",
            "created_at": _NOW.isoformat(),
            "scope": "example-scope",
            "source": "reviewed inventory snapshot",
            "document_sha256": "a" * 64,
            "resources": [
                {
                    **raw["resources"][0],
                    "attributes": {"sku": "Premium"},
                }
            ],
            "links": raw["links"],
            "allowed_exceptions": [],
            "unknown_items": [],
        }
    )
    document = render_configuration_baseline_docx(
        observation=observation_from_dict(raw),
        version="s13-v1",
        created_at=_NOW,
        source="reviewed inventory snapshot",
    )

    with pytest.raises(ValueError, match="does not match"):
        validate_configuration_baseline_docx(baseline, document)

"""Executable checks for the provider-schema Core baseline gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify-provider-schema-core-baseline.sh"
_SOURCE_REVISION = "a" * 40
_IMAGE_DIGEST = "sha256:" + "b" * 64


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    source_revision: str = _SOURCE_REVISION,
    image_digest: str = _IMAGE_DIGEST,
    max_inactive_revisions: int = 2,
    health_state: str = "Healthy",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    app = tmp_path / "app.json"
    revision = tmp_path / "revision.json"
    output = tmp_path / "receipt.json"
    app.write_text(
        json.dumps(
            {
                "properties": {
                    "configuration": {
                        "maxInactiveRevisions": max_inactive_revisions,
                    },
                    "latestRevisionName": "core--current",
                    "latestReadyRevisionName": "core--current",
                }
            }
        ),
        encoding="utf-8",
    )
    revision.write_text(
        json.dumps(
            {
                "name": "core--current",
                "properties": {
                    "active": True,
                    "healthState": health_state,
                    "provisioningState": "Provisioned",
                    "template": {
                        "containers": [
                            {
                                "name": "core-control-plane",
                                "image": "ghcr.io/example/core@" + image_digest,
                                "env": [
                                    {
                                        "name": "FDAI_SOURCE_REVISION",
                                        "value": source_revision,
                                    }
                                ],
                            }
                        ]
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "terraform",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"output -raw resource_group_name" ]]; then
  printf 'rg-fdai-dev-krc'
elif [[ "$*" == *"output -raw core_app_name" ]]; then
  printf 'ca-fdai-dev-krc-core'
else
  exit 90
fi
""",
    )
    _write_executable(
        bin_dir / "az",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "containerapp show"* ]]; then
  cat "$APP_EVIDENCE"
elif [[ "$*" == "containerapp revision show"* ]]; then
  cat "$REVISION_EVIDENCE"
else
  exit 91
fi
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "APP_EVIDENCE": str(app),
        "REVISION_EVIDENCE": str(revision),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = subprocess.run(  # noqa: S603 - fixed repository script and test PATH
        [
            "/usr/bin/bash",
            str(_SCRIPT),
            _SOURCE_REVISION,
            _IMAGE_DIGEST,
            str(tmp_path),
            str(output),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output


def test_verifies_exact_healthy_retained_core_baseline(tmp_path: Path) -> None:
    result, output = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "fdai.provider-schema-core-baseline.v1"
    assert receipt["source_revision"] == _SOURCE_REVISION
    assert receipt["image_digest"] == _IMAGE_DIGEST
    assert receipt["max_inactive_revisions"] == 2
    assert receipt["health_state"] == "Healthy"
    assert receipt["grants_authority"] is False
    assert "rg-fdai" not in json.dumps(receipt)
    verification = subprocess.run(  # noqa: S603 - fixed repository script
        [
            "/usr/bin/bash",
            str(_SCRIPT),
            "--verify-receipt",
            str(output),
            _SOURCE_REVISION,
            _IMAGE_DIGEST,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert verification.returncode == 0, verification.stderr


def test_rejects_mismatched_core_source_revision(tmp_path: Path) -> None:
    result, output = _run(tmp_path, source_revision="c" * 40)

    assert result.returncode == 1
    assert "source revision does not match" in result.stderr
    assert not output.exists()


def test_rejects_missing_rollback_retention(tmp_path: Path) -> None:
    result, output = _run(tmp_path, max_inactive_revisions=0)

    assert result.returncode != 0
    assert not output.exists()


def test_rejects_unhealthy_core_revision(tmp_path: Path) -> None:
    result, output = _run(tmp_path, health_state="Unhealthy")

    assert result.returncode == 1
    assert "not active, healthy, and provisioned" in result.stderr
    assert not output.exists()


def test_rejects_tampered_plan_baseline_receipt(tmp_path: Path) -> None:
    result, output = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    receipt["max_inactive_revisions"] = 0
    output.write_text(json.dumps(receipt), encoding="utf-8")

    verification = subprocess.run(  # noqa: S603 - fixed repository script
        [
            "/usr/bin/bash",
            str(_SCRIPT),
            "--verify-receipt",
            str(output),
            _SOURCE_REVISION,
            _IMAGE_DIGEST,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert verification.returncode == 1
    assert "receipt is invalid" in verification.stderr

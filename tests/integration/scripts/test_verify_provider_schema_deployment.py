"""Executable checks for provider-schema evidence persistence and resume."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify-provider-schema-deployment.sh"
_SOURCE_COMMIT = "a" * 40
_RUNTIME_REVISION = "b" * 40
_PLAN_ID = "plan-123-1"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _evidence(*, source: str = _SOURCE_COMMIT) -> dict[str, object]:
    return {
        "schema_version": "fdai.provider-schema-deployment-evidence.v1",
        "application_source_commit": source,
        "runtime_image_revision": _RUNTIME_REVISION,
        "plan_id": _PLAN_ID,
        "grants_authority": False,
    }


def _run(
    tmp_path: Path,
    *,
    resume: bool,
    stored: dict[str, object] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / _SCRIPT.name
    shutil.copy2(_SCRIPT, wrapper)
    calls = tmp_path / "calls"
    output = tmp_path / "evidence.json"
    uploaded = tmp_path / "uploaded.json"
    stored_path = tmp_path / "stored.json"
    if stored is not None:
        stored_path.write_text(json.dumps(stored), encoding="utf-8")
    _write_executable(
        tools / "verify-provider-schema-job.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'job\n' >> "$CALLS"
{
    printf '{"schema_version":"fdai.provider-schema-deployment-evidence.v1",'
    printf '"application_source_commit":"%s","runtime_image_revision":"%s",' "$1" "$2"
    printf '"plan_id":"%s","grants_authority":false}\n' "$3"
} > "$4"
""",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "az",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'az %s\n' "$*" >> "$CALLS"
if [[ "$*" == "storage blob exists"* ]]; then
  printf '%s' "$BLOB_EXISTS"
elif [[ "$*" == "storage blob download"* ]]; then
  destination=""
  while (( $# > 0 )); do
    [[ "$1" != "--file" ]] || { destination="$2"; break; }
    shift
  done
  cp "$STORED_EVIDENCE" "$destination"
elif [[ "$*" == "storage blob upload"* ]]; then
  source=""
  while (( $# > 0 )); do
    [[ "$1" != "--file" ]] || { source="$2"; break; }
    shift
  done
  cp "$source" "$UPLOADED_EVIDENCE"
else
  exit 91
fi
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "BLOB_EXISTS": str(stored is not None).lower(),
        "STORED_EVIDENCE": str(stored_path),
        "UPLOADED_EVIDENCE": str(uploaded),
    }
    result = subprocess.run(  # noqa: S603 - isolated copy of fixed repository script
        [
            "/usr/bin/bash",
            str(wrapper),
            _SOURCE_COMMIT,
            _RUNTIME_REVISION,
            _PLAN_ID,
            str(output),
            "stfdaitest123",
            "dev",
            str(resume).lower(),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, calls, output, uploaded


def test_fresh_verification_runs_job_and_uploads_immutable_evidence(tmp_path: Path) -> None:
    result, calls, output, uploaded = _run(tmp_path, resume=False)

    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == uploaded.read_bytes()
    assert json.loads(output.read_text(encoding="utf-8")) == _evidence()
    log = calls.read_text(encoding="utf-8")
    assert "job\n" in log
    assert "storage blob upload" in log
    assert "--overwrite false" in log


def test_resume_reuses_matching_evidence_without_rerunning_job(tmp_path: Path) -> None:
    result, calls, output, uploaded = _run(tmp_path, resume=True, stored=_evidence())

    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == _evidence()
    log = calls.read_text(encoding="utf-8")
    assert "storage blob download" in log
    assert "job\n" not in log
    assert not uploaded.exists()


def test_resume_rejects_evidence_from_another_source(tmp_path: Path) -> None:
    result, calls, _, uploaded = _run(
        tmp_path,
        resume=True,
        stored=_evidence(source="c" * 40),
    )

    assert result.returncode == 1
    assert "does not match the exact plan" in result.stderr
    assert "job\n" not in calls.read_text(encoding="utf-8")
    assert not uploaded.exists()

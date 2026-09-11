from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "deployment" / "azure" / "verify-runtime-call-evidence-job.sh"
_SOURCE_COMMIT = "1" * 40
_PLAN_ID = "plan-123-456"
_JOB = "ca-fdai-dev-krc-core-inventory"
_IMAGE_DIGEST = f"sha256:{'a' * 64}"
_IMAGE = f"example.azurecr.io/fdai@{_IMAGE_DIGEST}"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    enabled: str,
    deployed_image: str = _IMAGE,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "terraform",
        "#!/usr/bin/env bash\n"
        "[[ \"$*\" == 'output -raw inventory_job_name' ]]\n"
        f"printf '%s' '{_JOB}'\n",
    )
    _write_executable(
        bin_dir / "az",
        "#!/usr/bin/env bash\n"
        '[[ "$*" == *"containerapp job show"* ]]\n'
        'if [[ "$*" == *"FDAI_RUNTIME_CALL_EVIDENCE_ENABLED"* ]]; then '
        f"printf '%s\\n' '{enabled}'; else printf '%s\\n' '{deployed_image}'; fi\n",
    )
    return subprocess.run(  # noqa: S603 - fixed local script and synthetic arguments.
        ["/usr/bin/bash", str(_SCRIPT), _SOURCE_COMMIT, _PLAN_ID, str(tmp_path / "receipt.json")],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "TF_VAR_env": "dev",
            "TF_VAR_core_image": _IMAGE,
            "TF_VAR_region_short": "krc",
        },
        check=False,
        capture_output=True,
        text=True,
    )


def test_verified_binding_writes_sanitized_receipt(tmp_path: Path) -> None:
    result = _run(tmp_path, enabled="1")

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt == {
        "schema_version": "fdai.runtime-call-evidence-job-readback.v1",
        "source_commit": _SOURCE_COMMIT,
        "plan_id": _PLAN_ID,
        "resource_ref_digest": hashlib.sha256(_JOB.encode()).hexdigest(),
        "binding": "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED",
        "value": "1",
        "image_digest": _IMAGE_DIGEST,
        "verified_at": receipt["verified_at"],
    }
    assert datetime.fromisoformat(receipt["verified_at"]).utcoffset() is not None
    assert _JOB not in result.stdout + result.stderr


def test_disabled_binding_fails_without_receipt(tmp_path: Path) -> None:
    result = _run(tmp_path, enabled="0")

    assert result.returncode == 1
    assert result.stderr == "runtime-call evidence Inventory Job binding is not enabled\n"
    assert not (tmp_path / "receipt.json").exists()


def test_mismatched_image_fails_without_receipt(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        enabled="1",
        deployed_image=f"example.azurecr.io/fdai@sha256:{'b' * 64}",
    )

    assert result.returncode == 1
    assert result.stderr == (
        "runtime-call evidence Inventory Job image does not match the protected digest\n"
    )
    assert not (tmp_path / "receipt.json").exists()

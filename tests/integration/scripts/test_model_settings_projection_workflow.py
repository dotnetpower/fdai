from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/model-settings-projection.yml"
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
PROTECTED_WORKFLOW_ACTION = (
    ROOT / ".github/actions/verify-protected-workflow-source/action.yml"
).read_text(encoding="utf-8")


def test_projection_workflow_is_protected_and_exact_revision() -> None:
    parsed = yaml.safe_load(WORKFLOW)

    assert isinstance(parsed, dict)
    assert "workflow_dispatch" in parsed[True]
    assert "commit_sha" in parsed[True]["workflow_dispatch"]["inputs"]
    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in WORKFLOW
    assert "target-commit-sha: ${{ inputs.commit_sha }}" in WORKFLOW
    assert "workflow-path: .github/workflows/model-settings-projection.yml" in WORKFLOW
    assert 'git -C "$guard_repo" diff --quiet' in PROTECTED_WORKFLOW_ACTION


def test_projection_workflow_requires_three_way_active_digest_cas() -> None:
    assert "artifact_digest" in WORKFLOW
    assert "runtime_digest" in WORKFLOW
    assert "attested_digest" in WORKFLOW
    assert '"$artifact_digest" == "$runtime_digest"' in WORKFLOW
    assert '"$artifact_digest" == "$attested_digest"' in WORKFLOW
    assert "verify_active_core_revision.py" in WORKFLOW
    assert "--require-model-binding" in WORKFLOW
    assert "verify_active_model_attestation.py" in WORKFLOW


def test_projection_workflow_writes_only_model_projection_and_reads_it_back() -> None:
    assert "materialize-authoritative-settings.py --model-only" in WORKFLOW
    assert "SET TRANSACTION READ ONLY" in WORKFLOW
    assert "operator-projection:iam:model-settings" in WORKFLOW
    assert "operator-projection:iam:runtime-settings" not in WORKFLOW
    assert "provider mutation" not in WORKFLOW.lower()
    assert "::add-mask::$migration_dsn" in WORKFLOW
    assert "^https://([a-z0-9-]{3,24})[.]vault[.]azure[.]net/?$" in WORKFLOW
    assert 'vault_name="${BASH_REMATCH[1]}"' in WORKFLOW
    assert '"postgresql+psycopg://", "postgresql://", 1' in WORKFLOW
    assert WORKFLOW.index("model Settings projection digest is incorrect") < WORKFLOW.index(
        "unset FDAI_STATE_STORE_DSN migration_dsn"
    )


def test_projection_workflow_run_blocks_are_valid_bash() -> None:
    parsed = yaml.safe_load(WORKFLOW)
    bash = shutil.which("bash")

    assert bash is not None
    for step in parsed["jobs"]["project"]["steps"]:
        script = step.get("run")
        if not isinstance(script, str):
            continue
        script = re.sub(r"\$\{\{[^\n}]+\}\}", "placeholder", script)
        completed = subprocess.run(  # noqa: S603 - resolved Bash with repository script input.
            [bash, "-n"],
            input=script,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, f"{step['name']}: {completed.stderr}"

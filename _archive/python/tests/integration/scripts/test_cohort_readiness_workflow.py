"""Protected SRE cohort readiness workflow contract tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/cohort-readiness.yml").read_text(encoding="utf-8")


def test_workflow_is_exact_revision_read_only_and_protected() -> None:
    parsed = yaml.safe_load(WORKFLOW)

    assert "workflow_dispatch" in parsed[True]
    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in WORKFLOW
    assert "workflow-path: .github/workflows/cohort-readiness.yml" in WORKFLOW
    assert 'git merge-base --is-ancestor "$TARGET_COMMIT_SHA" origin/main' in WORKFLOW
    assert (
        'git rev-list --first-parent origin/main | grep -Fx "$TARGET_COMMIT_SHA" >/dev/null'
        in WORKFLOW
    )
    assert '"$(git rev-parse HEAD)" == "$TARGET_COMMIT_SHA"' in WORKFLOW
    assert '.name == "required" and .conclusion == "success"' in WORKFLOW
    assert "length >= 1" in WORKFLOW
    assert "mutation_performed" in WORKFLOW
    assert "terraform apply" not in WORKFLOW
    assert "az containerapp job start" not in WORKFLOW
    assert "kubectl " not in WORKFLOW


def test_workflow_reads_private_state_and_emits_aggregate_receipt() -> None:
    parsed = yaml.safe_load(WORKFLOW)
    job = parsed["jobs"]["inspect"]
    azure_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Authenticate and bind private platform state"
    )

    assert "ARM_SUBSCRIPTION_ID" not in job["env"]
    assert "AZURE_TENANT_ID" not in job["env"]
    assert "ARM_SUBSCRIPTION_ID" in azure_step["env"]
    assert "AZURE_TENANT_ID" in azure_step["env"]
    assert "login-deploy-identity.sh" in WORKFLOW
    assert "::add-mask::$migration_dsn" in WORKFLOW
    assert "PostgresCohortEvidenceInventorySource" in WORKFLOW
    assert 'expected_revision=os.environ["TARGET_COMMIT_SHA"]' in WORKFLOW
    assert "fdai.cohort-readiness-receipt.v2" in WORKFLOW
    assert "except psycopg.OperationalError as error:" in WORKFLOW
    assert "if error.sqlstate is not None:" in WORKFLOW
    assert '"availability": "unavailable"' in WORKFLOW
    assert '"reason_code": "state_store_connection_failed"' in WORKFLOW
    assert '"missing": ["state_store_unavailable"]' in WORKFLOW
    assert '"claim_eligibility_authority": False' in WORKFLOW
    assert '"execution_authority": False' in WORKFLOW
    assert '"mutation_performed": False' in WORKFLOW
    assert "actions/attest@" in WORKFLOW
    assert "retention-days: 90" in WORKFLOW
    assert "secrets." not in WORKFLOW


def test_require_ready_is_an_explicit_fail_closed_gate() -> None:
    assert '[[ "$REQUIRE_READY" == "true" || "$REQUIRE_READY" == "false" ]]' in WORKFLOW
    assert 'if [[ "$REQUIRE_READY" == "true" ]]; then' in WORKFLOW
    assert "jq -e '.ready == true'" in WORKFLOW


def test_every_workflow_shell_block_is_valid_bash() -> None:
    parsed = yaml.safe_load(WORKFLOW)
    bash = shutil.which("bash")

    assert bash is not None
    for step in parsed["jobs"]["inspect"]["steps"]:
        script = step.get("run")
        if not isinstance(script, str):
            continue
        sanitized = re.sub(r"\$\{\{[^\n}]+\}\}", "placeholder", script)
        completed = subprocess.run(  # noqa: S603 - validates repository workflow syntax
            [bash, "-n"],
            input=sanitized,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, f"{step['name']}: {completed.stderr}"

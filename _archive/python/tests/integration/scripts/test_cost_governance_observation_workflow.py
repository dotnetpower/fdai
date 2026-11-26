from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github/workflows/cost-governance-observation-export.yml").read_text(
    encoding="utf-8"
)
_ROUTES = (_ROOT / "scripts/lib/design-routes.json").read_text(encoding="utf-8")
_PYTHON_HEREDOC = re.compile(r"<<'PY'\n(?P<body>.*?)\nPY(?:\n|$)", re.DOTALL)


def test_observation_workflow_is_scheduled_protected_and_exact_revision_bound() -> None:
    assert 'cron: "17 2 * * *"' in _WORKFLOW
    assert "verify-protected-workflow-source" in _WORKFLOW
    assert "workflow-path: .github/workflows/cost-governance-observation-export.yml" in (_WORKFLOW)
    assert "git rev-list --first-parent origin/main" in _WORKFLOW
    assert 'select(.name == "required" and .conclusion == "success")' in _WORKFLOW


def test_required_ci_waits_for_success_with_a_bounded_deadline() -> None:
    steps = yaml.safe_load(_WORKFLOW)["jobs"]["observe-import-evaluate"]["steps"]
    step = next(
        step
        for step in steps
        if step.get("name") == "Verify exact revision, required CI, and campaign bounds"
    )
    run = step["run"]

    assert "required_ci_deadline=$((SECONDS + 1200))" in run
    assert "while :; do" in run
    assert (
        'gh api "repos/$GITHUB_REPOSITORY/commits/$TARGET_COMMIT_SHA/check-runs?per_page=100"'
        in run
    )
    assert "sleep 30" in run
    assert "Required CI did not succeed for $TARGET_COMMIT_SHA within 20 minutes." in run
    assert '.check_runs | type == "array"' in run


def test_required_ci_wait_accepts_success_that_appears_after_initial_poll(
    tmp_path: Path,
) -> None:
    steps = yaml.safe_load(_WORKFLOW)["jobs"]["observe-import-evaluate"]["steps"]
    step = next(
        step
        for step in steps
        if step.get("name") == "Verify exact revision, required CI, and campaign bounds"
    )
    commit_sha = "a" * 40
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_count = tmp_path / "gh-call-count"
    gh_arguments = tmp_path / "gh-arguments"
    sleep_arguments = tmp_path / "sleep-arguments"

    git = bin_dir / "git"
    git.write_text(
        """#!/bin/sh
case "$1" in
  rev-parse|rev-list) printf '%s\\n' "$TARGET_COMMIT_SHA" ;;
esac
""",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_ARGUMENTS"
count=0
test ! -f "$GH_CALL_COUNT" || count="$(cat "$GH_CALL_COUNT")"
count=$((count + 1))
printf '%s' "$count" > "$GH_CALL_COUNT"
if [ "$count" -eq 1 ]; then
  printf '%s\\n' '{"check_runs":[{"name":"required","status":"in_progress","conclusion":null}]}'
else
  printf '%s\\n' '{"check_runs":[{"name":"required","status":"completed","conclusion":"success"}]}'
fi
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$SLEEP_ARGUMENTS"
""",
        encoding="utf-8",
    )
    sleep.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "dotnetpower/fdai",
        "GITHUB_RUN_ID": "1",
        "GITHUB_RUN_ATTEMPT": "1",
        "RUNNER_TEMP": str(tmp_path),
        "TARGET_COMMIT_SHA": commit_sha,
        "CAMPAIGN_ID": "test-campaign",
        "WINDOW_HOURS": "48",
        "SOURCE_ARTIFACT_NAME": "cost-governance-observations-test-campaign-1",
        "REQUIRE_READY": "false",
        "GH_ARGUMENTS": str(gh_arguments),
        "GH_CALL_COUNT": str(call_count),
        "SLEEP_ARGUMENTS": str(sleep_arguments),
    }
    bash = shutil.which("bash")
    assert bash is not None
    # This executes repository-owned workflow text with fake, network-free commands.
    result = subprocess.run(  # noqa: S603
        [bash, "-e", "-o", "pipefail", "-c", step["run"]],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert call_count.read_text(encoding="utf-8") == "2"
    assert all(commit_sha in line for line in gh_arguments.read_text(encoding="utf-8").splitlines())
    assert sleep_arguments.read_text(encoding="utf-8").splitlines() == ["30"]


def test_source_is_attested_and_uploaded_before_trusted_import() -> None:
    attest = _WORKFLOW.index("- name: Attest normalized source observations")
    upload = _WORKFLOW.index("- name: Upload immutable source observations")
    importer = _WORKFLOW.index("- name: Import observations and evaluate every review target")

    assert attest < upload < importer
    assert "fdai_cost_governance.campaign_export" in _WORKFLOW
    assert "fdai_cost_governance.validation_cli import" in _WORKFLOW
    assert "fdai_cost_governance.validation_cli evaluate" in _WORKFLOW
    assert "FDAI_OPERATOR_STORE_DSN" in _WORKFLOW
    assert "cost-governance-ontology-qualification.txt" in _WORKFLOW
    assert "cost-governance-parity-qualification.txt" in _WORKFLOW


def test_exact_release_qualification_installs_the_root_dev_extra() -> None:
    assert "uv run --frozen --extra dev python" in _WORKFLOW
    assert "uv run --frozen --extra dev pytest" in _WORKFLOW


def test_review_is_non_authoritative_and_cannot_promote() -> None:
    assert '(.ready | type == "boolean")' in _WORKFLOW
    assert "(.targets | length == 6)" in _WORKFLOW
    assert "promote-action-type" not in _WORKFLOW
    assert "terraform apply" not in _WORKFLOW
    assert "--require-ready" not in _WORKFLOW


def test_embedded_python_is_syntactically_valid() -> None:
    steps = yaml.safe_load(_WORKFLOW)["jobs"]["observe-import-evaluate"]["steps"]
    snippets = [
        match.group("body")
        for step in steps
        if isinstance(step.get("run"), str)
        for match in _PYTHON_HEREDOC.finditer(step["run"])
    ]

    assert snippets
    for index, snippet in enumerate(snippets):
        compile(snippet, f"cost-governance-observation-export:{index}", "exec")


def test_cost_governance_design_route_owns_observation_workflow() -> None:
    route = _ROUTES.split('"id": "cost-governance-package"', 1)[1].split('"must_read"', 1)[0]

    assert '".github/workflows/cost-governance-observation-export.yml"' in route

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "operational-history-certification.yml").read_text(
    encoding="utf-8"
)
_REQUEST = (_ROOT / ".github" / "workflows" / "request-protected-operation.yml").read_text(
    encoding="utf-8"
)


def test_certification_is_bot_requested_and_human_approved() -> None:
    assert "operational-history-certification" in _REQUEST
    assert "operational-history-certification.yml/dispatches" in _REQUEST
    assert "environment: ${{ inputs.environment }}" in _WORKFLOW
    assert "github.actor == 'github-actions[bot]'" in _WORKFLOW


def test_certification_binds_every_authoritative_revision() -> None:
    for value in (
        "commit_sha",
        "runtime_image_revision",
        "deployment_revision",
        "deployment_receipt_digest",
        "deployment_apply_run_id",
        "deployment_plan_id",
        "Verify required CI for exact revision",
        "Verify exact attested runtime image",
        "Verify OI-15 durable apply receipt",
    ):
        assert value in _WORKFLOW
    assert "Install pinned GitHub CLI" in _WORKFLOW
    assert "scripts/deployment/azure/install-pinned-github-cli.sh" in _WORKFLOW


def test_certification_uses_the_exact_durable_receipt_after_artifact_expiry() -> None:
    login = _WORKFLOW.index("- name: Bind stable deployment identity")
    receipt = _WORKFLOW.index("- name: Verify OI-15 durable apply receipt")
    assert receipt > login
    assert '--name "${TARGET_ENVIRONMENT}/${DEPLOYMENT_PLAN_ID}/apply-receipt.json"' in _WORKFLOW
    assert "--container-name deployment-plans" in _WORKFLOW
    assert "--auth-mode login" in _WORKFLOW
    assert ".plan_id == $plan_id" in _WORKFLOW
    assert "(.workflow_run_id | tonumber) == $run_id" in _WORKFLOW
    assert 'case "$apply_artifact_count" in' in _WORKFLOW
    assert "Operational-history deployment plan id is invalid." in _REQUEST
    assert '-f "inputs[deployment_plan_id]=$DEPLOYMENT_PLAN_ID"' in _REQUEST


def test_certification_is_dev_only_and_fail_closed() -> None:
    assert "inputs.environment == 'dev'" in _WORKFLOW
    assert "operationally_validated" in _WORKFLOW
    assert "scenario_evidence_unavailable" in _WORKFLOW
    assert "continue-on-error" not in _WORKFLOW


def test_campaign_derives_canonical_release_and_reads_final_summary_after_restart() -> None:
    assert "git archive" not in _WORKFLOW
    assert "--ontology-release-digest" not in _WORKFLOW
    after = _WORKFLOW.index("- name: Run after-restart campaign and persist certification")
    summary = _WORKFLOW.index('summary="$RUNNER_TEMP/oi16-certification-summary.json"')
    assert summary > after
    assert "az containerapp job replica list" in _WORKFLOW
    assert '--replica "$replica" --container "$container"' in _WORKFLOW
    assert "--container operational-history-lifecycle" not in _WORKFLOW


def test_campaign_job_arguments_are_one_azure_cli_value() -> None:
    assert "--args -m" not in _WORKFLOW
    assert _WORKFLOW.count("--command fdai-operational-history-certification") == 2
    assert _WORKFLOW.count('--args "$CAMPAIGN_PHASE" "$CAMPAIGN_REQUEST_ID"') == 2


def test_campaign_resolves_the_exact_acr_revision_instead_of_trusting_job_configuration() -> None:
    assert "contains(tags, 'sha-${TARGET_COMMIT_SHA}')" in _WORKFLOW
    assert 'runtime_image="${registry}/fdai@${runtime_image_digest}"' in _WORKFLOW
    assert 'source_repository="${GITHUB_REPOSITORY,,}/fdai-core-control-plane"' in _WORKFLOW
    assert '[[ "$runtime_image_digest" == "$source_digest" ]]' in _WORKFLOW
    assert 'runtime_image_digest="${runtime_image##*@}"' not in _WORKFLOW
    assert "az acr login" not in _WORKFLOW


def test_campaign_replays_the_exact_active_projection_before_synthetic_evidence() -> None:
    replay = _WORKFLOW.index("- name: Migrate active inventory projection to exact release")
    campaign = _WORKFLOW.index("- name: Run bounded synthetic campaign before restart")
    assert replay < campaign
    assert "--command fdai-inventory-projection-replay" in _WORKFLOW
    assert '--args "$TARGET_COMMIT_SHA"' in _WORKFLOW
    assert "inventory projection release migration exceeded its 600-second deadline" in _WORKFLOW

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "operational-instance-certification.yml").read_text(
    encoding="utf-8"
)


def test_oi12_workflow_binds_exact_source_and_required_ci() -> None:
    for value in (
        "commit_sha",
        "request_id",
        "window_seconds",
        "promote_runtime_image",
        "Verify protected workflow source",
        "Verify exact source and required CI",
        'select(.name == "required" and .conclusion == "success")',
        "bind_core_runtime_image.sh",
        "GH_TOKEN: ${{ github.token }}",
        "GHCR_TOKEN: ${{ github.token }}",
        "PROMOTE_RUNTIME_IMAGE: ${{ inputs.promote_runtime_image }}",
        "FDAI_ACR_LOGIN_SERVER=${deployed_image%%/*}",
        "Verify exact runtime image provenance",
        "Bind exact runtime image to ACR",
        "bind_core_runtime_image.sh --verify-only infra",
        "bind_core_runtime_image.sh --bind-verified infra",
    ):
        assert value in _WORKFLOW


def test_oi12_workflow_refreshes_inventory_before_seven_axis_measurement() -> None:
    refresh = _WORKFLOW.index("- name: Refresh authoritative inventory with exact runtime")
    certify = _WORKFLOW.index("- name: Run protected seven-axis certification")
    assert refresh < certify
    assert '--image "$TF_VAR_core_image"' in _WORKFLOW
    assert "--command fdai-operational-instance-certification" in _WORKFLOW
    resolve = _WORKFLOW.index("- name: Resolve exact certification jobs")
    verify = _WORKFLOW.index("- name: Verify exact runtime image provenance")
    bind = _WORKFLOW.index("- name: Bind exact runtime image to ACR")
    assert resolve < verify < bind < refresh
    assert _WORKFLOW.index('deployed_image="$(') < verify
    assert "Resolved exact certification job bindings." in _WORKFLOW
    assert '--args protected "$CERTIFICATION_REQUEST_ID" "$TARGET_COMMIT_SHA"' in _WORKFLOW
    assert "--request-id" not in _WORKFLOW
    assert "authoritative inventory refresh exceeded its 1200-second deadline" in _WORKFLOW


def test_oi12_workflow_recovers_legacy_jobs_from_reviewed_arm_contracts() -> None:
    root_output = "terraform -chdir=infra output -raw inventory_job_name"
    arm_fallback = "az resource list"
    assert _WORKFLOW.index(root_output) < _WORKFLOW.index(arm_fallback)
    assert "--resource-type Microsoft.App/jobs" in _WORKFLOW
    assert "certification_job_ids" in _WORKFLOW
    assert "${#certification_job_ids[@]} <= 64" in _WORKFLOW
    assert "job_scope=()" in _WORKFLOW
    assert 'job_scope=(--resource-group "$resource_group")' in _WORKFLOW
    assert "timeout 30s az resource show" in _WORKFLOW
    assert "--api-version 2024-03-01" in _WORKFLOW
    assert "inventory_job_candidates" in _WORKFLOW
    assert "inventory_job_id_candidates" in _WORKFLOW
    assert "${#inventory_job_candidates[@]} -eq 1" in _WORKFLOW
    assert "${#inventory_job_id_candidates[@]} -eq 1" in _WORKFLOW
    assert "history_job_candidates" in _WORKFLOW
    assert "history_container_candidates" in _WORKFLOW
    assert "inventory_resource_group_candidates" in _WORKFLOW
    assert "history_resource_group_candidates" in _WORKFLOW
    assert "${#history_job_candidates[@]} -eq 1" in _WORKFLOW
    assert "${#history_container_candidates[@]} -eq 1" in _WORKFLOW
    assert "az containerapp job list" not in _WORKFLOW
    assert "az containerapp job show" not in _WORKFLOW
    assert '.name == "inventory"' in _WORKFLOW
    assert '"fdai.delivery.inventory_sync_cli"' in _WORKFLOW
    assert "(.args // []) == []" in _WORKFLOW
    assert '.name == "operational-history-lifecycle"' in _WORKFLOW
    assert '"fdai.delivery.operational_history_lifecycle_runner"' in _WORKFLOW
    assert '(.args // []) == ["--mode", "shadow"]' in _WORKFLOW
    assert '"FDAI_OPERATIONAL_HISTORY_CONTAINER_URL"' in _WORKFLOW
    assert '"FDAI_MI_CLIENT_ID"' in _WORKFLOW
    assert "(.properties.template.containers | length) == 1" in _WORKFLOW
    assert "expected exactly one inventory job matching the reviewed runtime contract" in _WORKFLOW
    assert "expected exactly one history job matching the reviewed runtime contract" in _WORKFLOW
    assert "inventory job output does not match the reviewed ARM runtime" in _WORKFLOW
    assert "history job output does not match the reviewed ARM runtime" in _WORKFLOW
    assert "history container output does not match the reviewed ARM runtime" in _WORKFLOW
    assert (
        '[[ "${inventory_resource_group_candidates[0]}" != '
        '"${history_resource_group_candidates[0]}" ]]'
    ) in _WORKFLOW
    assert "certification jobs do not share one resource group" in _WORKFLOW
    assert "resource group output does not match the reviewed ARM runtimes" in _WORKFLOW
    assert (
        '[[ "$mi_client_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
        "[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]"
    ) in _WORKFLOW
    assert "providers/Microsoft.App/jobs?api-version" not in _WORKFLOW
    assert "state pull" not in _WORKFLOW
    assert "startswith" not in _WORKFLOW
    assert 'job_json="$RUNNER_TEMP/operational-history-job.json"' in _WORKFLOW
    assert "umask 077" in _WORKFLOW
    assert 'rm -f -- "$job_json"' in _WORKFLOW


def test_oi12_inventory_refresh_changes_only_the_reviewed_container_image() -> None:
    refresh = _WORKFLOW.index("- name: Refresh authoritative inventory with exact runtime")
    certify = _WORKFLOW.index("- name: Run protected seven-axis certification")
    block = _WORKFLOW[refresh:certify]

    assert "az containerapp job start" not in block
    assert 'inventory_job_json="$RUNNER_TEMP/inventory-job.json"' in block
    assert 'execution_body="$RUNNER_TEMP/inventory-execution.json"' in block
    assert '--ids "$INVENTORY_JOB_ID"' in block
    assert "--api-version 2024-03-01" in block
    assert "materialize_inventory_execution.py" in block
    assert '--job-json "$inventory_job_json"' in block
    assert '--image "$TF_VAR_core_image"' in block
    assert '--output "$execution_body"' in block
    assert "https://management.azure.com${INVENTORY_JOB_ID}/start?api-version=2024-03-01" in block
    assert '--body "@$execution_body"' in block
    assert 'rm -f -- "$inventory_job_json" "$execution_body"' in block


def test_oi12_workflow_retains_only_sanitized_no_authority_evidence() -> None:
    assert _WORKFLOW.count("observation_authority") >= 3
    assert _WORKFLOW.count("mutation_authority") >= 3
    assert _WORKFLOW.count("execution_authority") >= 3
    assert "operational-instance-certification-${{ inputs.request_id }}" in _WORKFLOW
    assert "retention-days: 90" in _WORKFLOW
    assert "SERVICE_DEPLOY_TFVARS_JSON" not in _WORKFLOW

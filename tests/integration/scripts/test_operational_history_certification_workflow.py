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
        "Verify required CI for exact revision",
        "Verify exact attested runtime image",
        "Verify OI-15 apply receipt artifact",
    ):
        assert value in _WORKFLOW


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


def test_campaign_job_arguments_are_one_azure_cli_value() -> None:
    assert "--args -m" not in _WORKFLOW
    assert _WORKFLOW.count('--args="$campaign_args"') == 2
    assert (
        _WORKFLOW.count(
            'campaign_args="-m fdai.delivery.operational_history_certification_campaign'
        )
        == 2
    )


def test_campaign_resolves_the_exact_acr_revision_instead_of_trusting_job_configuration() -> None:
    assert "contains(tags, 'sha-${TARGET_COMMIT_SHA}')" in _WORKFLOW
    assert 'runtime_image="${registry}/fdai@${runtime_image_digest}"' in _WORKFLOW
    assert 'source_repository="${GITHUB_REPOSITORY,,}/fdai-core-control-plane"' in _WORKFLOW
    assert '[[ "$runtime_image_digest" == "$source_digest" ]]' in _WORKFLOW
    assert 'runtime_image_digest="${runtime_image##*@}"' not in _WORKFLOW

from __future__ import annotations

from pathlib import Path

from scripts.deployment.azure.model_lifecycle_reconciler import reconcile_model_lifecycle

_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")


def test_protected_deploy_resolves_and_seals_model_manifest_before_plan() -> None:
    resolver = _DEPLOY.index("Resolve and seal model capabilities")
    plan = _DEPLOY.index("Terraform plan")

    assert resolver < plan
    assert "fdai.rule_catalog.schema.llm_resolver_cli" in _DEPLOY
    assert "--use-azure-cli" in _DEPLOY
    assert '--assess-fail-on "$MODEL_COMPLETENESS_FAIL_ON"' in _DEPLOY
    assert "MODEL_RESOLVER_DEPLOYER_OBJECT_ID" in _DEPLOY
    assert "resolved-models.sha256" in _DEPLOY
    assert 'echo "TF_VAR_resolved_capabilities=' in _DEPLOY
    assert "RESOLVED_CAPABILITIES_JSON" not in _DEPLOY


def test_gateway_targeted_plan_resolves_models_without_blocking_on_completeness() -> None:
    resolver_step = _DEPLOY.split("- name: Resolve and seal model capabilities", maxsplit=1)[
        1
    ].split("- name: Ensure protected storage containers", maxsplit=1)[0]

    assert "!inputs.deploy_dev_operations_gateway" not in resolver_step
    assert (
        "MODEL_COMPLETENESS_FAIL_ON: "
        "${{ inputs.deploy_dev_operations_gateway && 'none' || 'critical' }}"
    ) in resolver_step
    assert '--assess-fail-on "$MODEL_COMPLETENESS_FAIL_ON"' in resolver_step
    target_expression = _DEPLOY.split("TF_CLI_ARGS_plan:", maxsplit=1)[1].splitlines()[0]
    assert "module.llm_azure_openai[0].azurerm_cognitive_account.primary" in target_expression
    assert "azurerm_cognitive_deployment.capability" not in target_expression


def test_exact_apply_restores_the_plan_sealed_model_manifest() -> None:
    assert 'metadata["model_resolution"]' in _DEPLOY
    assert '"resolved_models_digest"' in _DEPLOY
    assert '"deployment_models_digest"' in _DEPLOY
    assert '"${blob_prefix}/resolved-models.json"' in _DEPLOY
    assert '"${blob_prefix}/deployment-models.json"' in _DEPLOY
    assert '"${blob_prefix}/resolved-models.sha256"' in _DEPLOY
    assert '"${blob_prefix}/deployment-models.sha256"' in _DEPLOY
    assert "protected plan model-resolution evidence is incomplete" in _DEPLOY
    assert 'echo "$resolved_models_digest  resolved-models.json" | sha256sum --check' in _DEPLOY
    assert 'echo "$deployment_models_digest  deployment-models.json" | sha256sum --check' in _DEPLOY
    assert 'echo "TF_VAR_resolved_capabilities=$capabilities_json"' in _DEPLOY


def _resolved(family: str = "gpt-4o", *, status: str = "resolved") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "capabilities": [
            {
                "name": "t2.reasoner.primary",
                "family": family,
                "publisher": "OpenAI",
                "status": status,
            }
        ],
    }


def test_lifecycle_reconciler_is_idempotent_when_mapping_is_current() -> None:
    first = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(),
        deprecations=(),
    )
    second = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(),
        deprecations=(),
    )

    assert first == second
    assert first["status"] == "no-change"
    assert first["changes"] == []
    assert first["activation_authority"] is False


def test_lifecycle_reconciler_proposes_sanitized_family_change() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved("gpt-5"),
        deprecations=(),
    )

    assert result["status"] == "proposal"
    assert result["changes"] == [
        {
            "capability": "t2.reasoner.primary",
            "current_family": "gpt-4o",
            "current_publisher": "OpenAI",
            "proposed_family": "gpt-5",
            "proposed_publisher": "OpenAI",
            "proposed_status": "resolved",
        }
    ]
    assert result["compatibility_impact"] == ["model_family_change"]
    assert result["activation_authority"] is False
    assert len(str(result["proposal_digest"])) == 64


def test_lifecycle_reconciler_proposes_review_for_current_family_deprecation() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(),
        deprecations=({"family": "gpt-4o", "retirement_date": "2027-01-01"},),
    )

    assert result["status"] == "proposal"
    assert result["deprecations"] == [{"family": "gpt-4o", "retirement_date": "2027-01-01"}]
    assert "current_family_deprecated" in result["compatibility_impact"]


def test_lifecycle_reconciler_abstains_on_provider_failure() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=None,
        deprecations=(),
        provider_error="rate_limited",
    )

    assert result == {
        "schema_version": "fdai.model-lifecycle-proposal.v1",
        "status": "abstained",
        "reason": "rate_limited",
        "activation_authority": False,
        "changes": [],
        "deprecations": [],
        "compatibility_impact": [],
        "proposal_digest": None,
    }


def test_scheduled_reconciler_opens_only_idempotent_draft_proposals() -> None:
    workflow_path = _ROOT / ".github" / "workflows" / "model-lifecycle-reconcile.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "runs-on: [self-hosted, fdai-deploy]" in workflow
    assert "model_lifecycle_reconciler" in workflow
    assert "--provider-error" in workflow
    assert "gh pr create --draft" in workflow
    assert "gh pr list --head" in workflow
    assert "proposal_digest" in workflow
    assert "activation_authority" in workflow
    assert "terraform apply" not in workflow
    assert "az cognitiveservices account deployment create" not in workflow
    assert "az cognitiveservices account deployment update" not in workflow


def test_terraform_binds_the_exact_resolved_manifest_to_both_runtimes() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
    operator = (
        _ROOT / "infra" / "modules" / "operator-api" / "container-app" / "main.tf"
    ).read_text(encoding="utf-8")

    assert 'variable "resolved_models_json"' in variables
    assert 'variable "resolved_models_sha256"' in variables
    assert "LLM_RESOLVED_MODELS_PATH   = var.resolved_models_json" in root
    assert "LLM_RESOLVED_MODELS_SHA256 = var.resolved_models_sha256" in root
    assert "resolved_models_path              = var.resolved_models_json" in root
    assert "resolved_models_sha256            = var.resolved_models_sha256" in root
    assert 'name  = "LLM_RESOLVED_MODELS_SHA256"' in operator
    assert "TF_VAR_resolved_models_json" in _DEPLOY
    assert "TF_VAR_resolved_models_sha256" in _DEPLOY

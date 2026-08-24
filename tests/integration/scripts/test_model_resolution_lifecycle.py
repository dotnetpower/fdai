from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.deployment.azure.model_lifecycle_reconciler import reconcile_model_lifecycle

_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")


def _workflow_step(name: str) -> dict[str, object]:
    workflow = yaml.safe_load(_DEPLOY)
    return next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == name
    )


def _embedded_python(step_name: str) -> str:
    step = _workflow_step(step_name)
    run = step.get("run")
    assert isinstance(run, str)
    match = re.search(
        r"python3 - <<'PY'\n(?P<source>.*?)\n\s*PY(?:\n|$)",
        run,
        re.DOTALL,
    )
    assert match is not None
    return match.group("source")


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
    assert 'policy_args=(--binding-policy "$policy")' in _DEPLOY
    assert '--environment "${{ inputs.environment }}"' in _DEPLOY
    assert "MODEL_BINDING_POLICY_DEV_JSON" in _DEPLOY
    assert "MODEL_BINDING_POLICY_STAGING_JSON" in _DEPLOY
    assert "MODEL_BINDING_POLICY_PROD_JSON" in _DEPLOY
    assert "Verify model binding policy active digest" in _DEPLOY
    assert "terraform output -raw resolved_models_sha256" in _DEPLOY
    assert "Model binding policy active digest is stale" in _DEPLOY
    assert "Current active resolved-models digest" in _DEPLOY
    assert "Model binding policy exceeds the 16000-byte plan input bound" in _DEPLOY
    assert "MODEL_BINDING_POLICY_JSON: ${{ !inputs.apply" in _DEPLOY
    assert "RESOLVED_CAPABILITIES_JSON" not in _DEPLOY


def test_gateway_targeted_plan_resolves_models_without_blocking_on_completeness() -> None:
    resolver_step = _DEPLOY.split("- name: Resolve and seal model capabilities", maxsplit=1)[
        1
    ].split("- name: Ensure protected storage containers", maxsplit=1)[0]

    assert "!inputs.deploy_dev_operations_gateway" not in resolver_step
    assert (
        "MODEL_COMPLETENESS_FAIL_ON: "
        "${{ (inputs.deploy_dev_operations_gateway || env.MODEL_BINDING_ONLY == 'true') "
        "&& 'none' || 'critical' }}"
    ) in resolver_step
    assert '--assess-fail-on "$MODEL_COMPLETENESS_FAIL_ON"' in resolver_step
    assert 'if item.get("status") != "hil-only"' in resolver_step
    target_expression = _DEPLOY.split("TF_CLI_ARGS_plan:", maxsplit=1)[1].splitlines()[0]
    assert "module.llm_azure_openai[0].azurerm_cognitive_account.primary" in target_expression
    assert "azurerm_cognitive_deployment.capability" not in target_expression


def test_model_binding_plan_is_exactly_scoped_and_allows_held_quorum() -> None:
    resolver_step = _DEPLOY.split("- name: Resolve and seal model capabilities", maxsplit=1)[
        1
    ].split("- name: Ensure protected storage containers", maxsplit=1)[0]

    assert "deploy_model_binding:" not in _DEPLOY
    assert "startsWith(inputs.request_id, 'plan-model-')" in _DEPLOY
    assert "model-[0-9a-f]{18}" in _DEPLOY
    assert "Validate model-binding-only request" in _DEPLOY
    assert "model-binding plan requires an environment policy" in _DEPLOY
    assert "Bind model-binding Terraform target" in _DEPLOY
    assert "-target=module.llm_azure_openai[0]" in _DEPLOY
    assert "Enforce model-binding-only Terraform plan" in _DEPLOY
    assert "changes outside sealed deployments" in _DEPLOY
    assert "MODEL_BINDING_ONLY: ${{ env.MODEL_BINDING_ONLY }}" in _DEPLOY
    assert 'after_model.get("version") == expected["version"]' in _DEPLOY
    assert (
        "MODEL_COMPLETENESS_FAIL_ON: "
        "${{ (inputs.deploy_dev_operations_gateway || env.MODEL_BINDING_ONLY == 'true') "
        "&& 'none' || 'critical' }}"
    ) in resolver_step


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
    assert '"request_kind"' in _DEPLOY
    assert '"binding_policy_environment"' in _DEPLOY
    assert '"binding_policy_revision"' in _DEPLOY
    assert '--request-kind "$apply_request_kind"' in _DEPLOY
    assert '--environment "$APPLY_ENVIRONMENT"' in _DEPLOY
    assert "Verify model deployment readback" in _DEPLOY
    assert "verify_model_deployments.py" in _DEPLOY
    assert "model-binding-readback.json" in _DEPLOY
    assert '"readback_receipt_digest"' in _DEPLOY


@pytest.mark.parametrize(
    "step_name",
    [
        "Enforce model-binding-only Terraform plan",
        "Store protected plan artifact",
        "Record exact plan apply receipt",
    ],
)
def test_protected_model_evidence_python_compiles(step_name: str) -> None:
    compile(_embedded_python(step_name), step_name, "exec")


def test_model_replacement_allows_only_the_exact_sealed_cross_family_target(
    tmp_path: Path,
) -> None:
    capability = "t2.reasoner.primary"
    address = f'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["{capability}"]'
    resolved = {
        "capabilities": [
            {
                "name": capability,
                "status": "resolved",
                "family": "gpt-5.4",
                "version": "2026-03-05",
                "sku": "GlobalProvisionedManaged",
                "capacity_unit": "ptu",
                "capacity_tpm": 0,
                "capacity_value": 15,
            }
        ]
    }
    (tmp_path / "resolved-models.json").write_text(json.dumps(resolved), encoding="utf-8")

    def run_guard(target_family: str) -> subprocess.CompletedProcess[str]:
        plan = {
            "resource_changes": [
                {
                    "address": address,
                    "change": {
                        "actions": ["delete", "create"],
                        "before": {
                            "name": capability,
                            "cognitive_account_id": "/example/account",
                            "model": [
                                {
                                    "format": "OpenAI",
                                    "name": "gpt-4o",
                                    "version": "2024-11-20",
                                }
                            ],
                            "sku": [{"name": "GlobalStandard", "capacity": 1}],
                        },
                        "after": {
                            "name": capability,
                            "cognitive_account_id": "/example/account",
                            "model": [
                                {
                                    "format": "OpenAI",
                                    "name": target_family,
                                    "version": "2026-03-05",
                                }
                            ],
                            "sku": [
                                {
                                    "name": "GlobalProvisionedManaged",
                                    "capacity": 15,
                                }
                            ],
                        },
                    },
                }
            ]
        }
        (tmp_path / "dev.plan.review.json").write_text(json.dumps(plan), encoding="utf-8")
        return subprocess.run(  # noqa: S603 - fixed interpreter executes local test source
            [sys.executable, "-c", _embedded_python("Reject destructive protected plan")],
            cwd=tmp_path,
            env={
                **os.environ,
                "FDAI_RESOLVED_MODELS_PATH": str(tmp_path / "resolved-models.json"),
                "MODEL_BINDING_ONLY": "true",
                "MIGRATE_EVENT_BUS_TOPICS": "false",
                "MIGRATE_EVENT_BUS_JOBS": "false",
            },
            check=False,
            capture_output=True,
            text=True,
        )

    accepted = run_guard("gpt-5.4")
    assert accepted.returncode == 0, accepted.stderr
    assert "permits exact Azure OpenAI replacement" in accepted.stdout

    rejected = run_guard("gpt-5.4-mini")
    assert rejected.returncode == 1
    assert "reject delete or replacement" in rejected.stdout


def _resolved(
    family: str = "gpt-4o",
    *,
    status: str = "resolved",
    sku: str = "GlobalStandard",
    capacity_tpm: int = 1_000,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "capabilities": [
            {
                "name": "t2.reasoner.primary",
                "family": family,
                "publisher": "OpenAI",
                "sku": sku,
                "capacity_tpm": capacity_tpm,
                "status": status,
            }
        ],
    }


def _digest(value: dict[str, object]) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
    assert first["affected_capabilities"] == []
    assert first["source_models_digest"] == _digest(_resolved())
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
            "current_sku": "GlobalStandard",
            "current_capacity_unit": "tpm",
            "current_capacity_value": 1_000,
            "proposed_family": "gpt-5",
            "proposed_publisher": "OpenAI",
            "proposed_sku": "GlobalStandard",
            "proposed_capacity_unit": "tpm",
            "proposed_capacity_value": 1_000,
            "proposed_status": "resolved",
        }
    ]
    assert result["compatibility_impact"] == ["model_family_change"]
    assert result["affected_capabilities"] == ["t2.reasoner.primary"]
    assert result["source_models_digest"] == _digest(_resolved())
    assert result["activation_authority"] is False
    assert len(str(result["proposal_digest"])) == 64


def test_lifecycle_reconciler_proposes_sku_and_capacity_change() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(sku="Standard", capacity_tpm=200_000),
        deprecations=(),
    )

    assert result["status"] == "proposal"
    assert result["changes"] == [
        {
            "capability": "t2.reasoner.primary",
            "current_family": "gpt-4o",
            "current_publisher": "OpenAI",
            "current_sku": "GlobalStandard",
            "current_capacity_unit": "tpm",
            "current_capacity_value": 1_000,
            "proposed_family": "gpt-4o",
            "proposed_publisher": "OpenAI",
            "proposed_sku": "Standard",
            "proposed_capacity_unit": "tpm",
            "proposed_capacity_value": 200_000,
            "proposed_status": "resolved",
        }
    ]
    assert result["compatibility_impact"] == ["capacity_change", "sku_change"]
    assert result["affected_capabilities"] == ["t2.reasoner.primary"]
    assert result["activation_authority"] is False


def test_lifecycle_reconciler_proposes_review_for_current_family_deprecation() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(),
        deprecations=({"family": "gpt-4o", "retirement_date": "2027-01-01"},),
    )

    assert result["status"] == "proposal"
    assert result["deprecations"] == [{"family": "gpt-4o", "retirement_date": "2027-01-01"}]
    assert "current_family_deprecated" in result["compatibility_impact"]
    assert result["affected_capabilities"] == ["t2.reasoner.primary"]


def test_lifecycle_reconciler_rejects_malformed_retirement_date() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        reconcile_model_lifecycle(
            current=_resolved(),
            candidate=_resolved(),
            deprecations=({"family": "gpt-4o", "retirement_date": "soon"},),
        )


def test_lifecycle_reconciler_ignores_unrelated_deprecation() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=_resolved(),
        deprecations=({"family": "other-family", "retirement_date": "2027-01-01"},),
    )

    assert result["status"] == "no-change"
    assert result["deprecations"] == []
    assert result["affected_capabilities"] == []


def test_lifecycle_reconciler_rejects_boolean_capacity() -> None:
    candidate = _resolved()
    capability = candidate["capabilities"][0]  # type: ignore[index]
    capability["capacity_tpm"] = True  # type: ignore[index]

    with pytest.raises(ValueError, match="non-negative integer"):
        reconcile_model_lifecycle(
            current=_resolved(),
            candidate=candidate,
            deprecations=(),
        )


@pytest.mark.parametrize("name", ["invalid", "t3.reasoner", "t2." + "x" * 65])
def test_lifecycle_reconciler_rejects_invalid_capability_name(name: str) -> None:
    candidate = _resolved()
    capability = candidate["capabilities"][0]  # type: ignore[index]
    capability["name"] = name  # type: ignore[index]

    with pytest.raises(ValueError, match="bounded T1/T2"):
        reconcile_model_lifecycle(
            current=_resolved(),
            candidate=candidate,
            deprecations=(),
        )


def test_lifecycle_reconciler_accounts_for_capability_addition_and_removal() -> None:
    current = _resolved()
    candidate = _resolved()
    current["capabilities"] = [
        *current["capabilities"],  # type: ignore[list-item]
        {
            "name": "t1.judge",
            "family": "gpt-4o-mini",
            "publisher": "OpenAI",
            "sku": "Standard",
            "capacity_tpm": 10_000,
            "status": "resolved",
        },
    ]
    candidate["capabilities"] = [
        *candidate["capabilities"],  # type: ignore[list-item]
        {
            "name": "t2.rca",
            "family": "gpt-5",
            "publisher": "OpenAI",
            "sku": "Standard",
            "capacity_tpm": 10_000,
            "status": "resolved",
        },
    ]

    result = reconcile_model_lifecycle(
        current=current,
        candidate=candidate,
        deprecations=(),
    )

    changes = {str(item["capability"]): item for item in result["changes"]}  # type: ignore[union-attr]
    assert changes["t1.judge"]["proposed_status"] == "unavailable"
    assert changes["t2.rca"]["current_family"] is None
    assert result["affected_capabilities"] == ["t1.judge", "t2.rca"]
    assert "capability_degradation" in result["compatibility_impact"]


def test_lifecycle_reconciler_abstains_on_provider_failure() -> None:
    result = reconcile_model_lifecycle(
        current=_resolved(),
        candidate=None,
        deprecations=(),
        provider_error="rate_limited",
    )

    assert result == {
        "schema_version": "fdai.model-lifecycle-proposal.v3",
        "status": "abstained",
        "reason": "rate_limited",
        "activation_authority": False,
        "source_models_digest": _digest(_resolved()),
        "affected_capabilities": [],
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

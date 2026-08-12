from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]
_WORKFLOW = (_REPO_ROOT / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")


def test_design_mocks_uses_the_protected_terraform_apply_path() -> None:
    assert "deploy_design_mocks:" in _WORKFLOW
    assert "TF_VAR_enable_design_mocks: ${{ inputs.deploy_design_mocks }}" in _WORKFLOW
    assert "inputs.deploy_design_mocks && '-target=module.design_mocks'" in _WORKFLOW
    assert "terraform output -raw design_mocks_static_web_app_id" in _WORKFLOW


def test_design_mocks_rejects_every_other_deployment_target() -> None:
    assert "deploy_design_mocks cannot be combined with another deployment target" in _WORKFLOW
    assert "DEPLOY_OHL_SCALE_OUT_EVIDENCE_TARGET" in _WORKFLOW
    assert "Design-mocks-only plan contains changes outside the Static Web App" in _WORKFLOW
    assert '"module.design_mocks[0].azurerm_static_web_app.design_mocks"' in _WORKFLOW
    assert "if: ${{ !inputs.deploy_design_mocks }}" in _WORKFLOW
    assert "if: ${{ inputs.apply && !inputs.deploy_design_mocks }}" in _WORKFLOW
    health_step = _WORKFLOW[_WORKFLOW.index("- name: Verify deployed health endpoints") :]
    health_step = health_step[: health_step.index("- name: Run canary publisher smoke")]
    assert "if: ${{ inputs.apply && !inputs.deploy_design_mocks }}" in health_step


def test_ohl_evidence_target_uses_the_protected_gateway_plan() -> None:
    assert "deploy_ohl_scale_out_evidence_target:" in _WORKFLOW
    assert (
        "TF_VAR_enable_ohl_scale_out_evidence_target: "
        "${{ inputs.environment == 'dev' && inputs.deploy_ohl_scale_out_evidence_target }}"
        in _WORKFLOW
    )
    assert "-target=azurerm_linux_virtual_machine_scale_set.ohl_evidence" in _WORKFLOW
    assert "-target=module.network[0].azurerm_subnet.evidence_target" in _WORKFLOW
    assert (
        "the OHL scale-out evidence target requires dev and "
        "deploy_dev_operations_gateway." in _WORKFLOW
    )
    assert "OHL_SCALE_OUT_EVIDENCE_IMAGE_VERSION" in _WORKFLOW
    assert "OHL_SCALE_OUT_EVIDENCE_SSH_PUBLIC_KEY" in _WORKFLOW


def test_design_mocks_publishes_only_the_allowlisted_artifact() -> None:
    assert "build_design_mocks_artifact.py tmp/design-mocks-dist" in _WORKFLOW
    assert "Azure/static-web-apps-deploy@" not in _WORKFLOW
    assert "SWA_CLI_DEPLOYMENT_TOKEN: ${{ steps.design_mocks_token.outputs.token }}" in _WORKFLOW
    assert "npx --yes @azure/static-web-apps-cli@2.0.10 deploy" in _WORKFLOW
    assert "tmp/design-mocks-dist --env production" in _WORKFLOW


def test_design_mocks_verifies_the_authentication_redirect() -> None:
    assert "terraform output -raw design_mocks_default_hostname" in _WORKFLOW
    assert "design-mocks site did not enforce the Entra authentication redirect" in _WORKFLOW

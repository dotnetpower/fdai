from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-channel-edge-secrets.yml"


def test_channel_edge_secret_workflow_is_exact_revision_and_value_blind() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "inputs.commit_sha == github.sha" in workflow
    assert "environment: dev" in workflow
    assert "runs-on: [self-hosted, fdai-deploy, fdai-deploy-candidate]" in workflow
    assert "Checkout protected workflow verifier" in workflow
    assert "workflow-path: .github/workflows/deploy-channel-edge-secrets.yml" in workflow
    assert "the exact commit does not have a successful required CI check" in workflow
    assert "https://api.github.com/repos/" in workflow
    assert '"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]' in workflow
    assert "install-pinned-github-cli.sh" not in workflow
    assert "login-deploy-identity.sh" in workflow
    assert "exactly one deployment-owned development Key Vault" in workflow
    assert 'vault_uri="https://${vault_name}.vault.azure.net"' in workflow
    assert "az keyvault show" not in workflow
    assert "az resource show" not in workflow
    assert "az rest --method GET" not in workflow
    assert "materialize_channel_edge_secrets.py" in workflow
    assert "uv run --frozen --package fdai-operator-service python" in workflow
    assert "shred --force --remove" in workflow
    assert "actions: write" not in workflow
    assert "contents: write" not in workflow
    assert "az keyvault secret set" not in workflow
    assert 'echo "$CHANNEL_EDGE_' not in workflow
    assert 'cat "$CHANNEL_EDGE_' not in workflow

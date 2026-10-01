"""Product-profile boundaries for standalone identity/application completion."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fdai_deployment_cli import standalone_application_completion
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


def test_observation_first_completion_skips_entra_and_human_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def deploy(**kwargs):
        captured.update(kwargs)
        return {
            "receipt_digest": "a" * 64,
            "catalog_review_receipt_digest": "b" * 64,
            "catalog_review_state": "skipped",
            "inventory_ready": True,
            "license_mode": "observation-only",
        }

    monkeypatch.setattr(
        standalone_application_completion,
        "deploy_standalone_application",
        deploy,
    )
    monkeypatch.setattr(
        standalone_application_completion.importlib,
        "import_module",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("default profile imported Entra tooling")
        ),
    )
    runtime = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
    )
    kit = SimpleNamespace(
        source_commit="c" * 40,
        verification=SimpleNamespace(manifest_digest="d" * 64),
        runtime=SimpleNamespace(digest="e" * 64),
    )

    result = standalone_application_completion.complete_application(
        kit=kit,
        prepared=SimpleNamespace(run_binding="binding"),
        status={},
        scripts=tmp_path,
        deadline=SimpleNamespace(remaining=lambda: 60),
        selected_runtime=runtime,
        trial_token=None,
        application_state_adoption=None,
        foundation_state_receipt_digest="f" * 64,
        current_operator_object_id=lambda: (_ for _ in ()).throw(
            AssertionError("default profile read human identity")
        ),
    )

    assert captured["entra_bindings"] is None
    assert result["product_profile"]["add_ons"] == []
    assert result["deployment_ready"] is True


def test_explicit_enterprise_add_on_preserves_entra_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    modules = {
        "genesis_supervisor": SimpleNamespace(
            _configure_entra=lambda **_kwargs: {
                "OPERATOR_API_AUDIENCE": "audience",
            }
        ),
        "genesis_entra": SimpleNamespace(plan_entra=lambda: "plan"),
        "genesis_approval_prompt": SimpleNamespace(current_actor_digest=lambda _binding: "actor"),
    }
    monkeypatch.setattr(
        standalone_application_completion.importlib,
        "import_module",
        modules.__getitem__,
    )
    monkeypatch.setattr(
        standalone_application_completion,
        "deploy_standalone_application",
        lambda **kwargs: (
            captured.update(kwargs)
            or {
                "receipt_digest": "a" * 64,
                "catalog_review_receipt_digest": "b" * 64,
                "catalog_review_state": "skipped",
                "inventory_ready": True,
                "license_mode": "trial",
            }
        ),
    )
    runtime = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        product_add_ons=(
            "enterprise-identity-governance",
            "read-only-console",
        ),
    )

    standalone_application_completion.complete_application(
        kit=SimpleNamespace(
            source_commit="c" * 40,
            verification=SimpleNamespace(manifest_digest="d" * 64),
            runtime=SimpleNamespace(digest="e" * 64),
        ),
        prepared=SimpleNamespace(run_binding="binding"),
        status={},
        scripts=tmp_path,
        deadline=SimpleNamespace(remaining=lambda: 60),
        selected_runtime=runtime,
        trial_token=None,
        application_state_adoption=None,
        foundation_state_receipt_digest="f" * 64,
        current_operator_object_id=lambda: "operator-id",
    )

    assert captured["entra_bindings"] == {
        "OPERATOR_API_AUDIENCE": "audience",
        "CURRENT_OPERATOR_OBJECT_ID": "operator-id",
    }

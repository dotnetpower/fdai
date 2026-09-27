"""Select and complete recovered Foundation adoption for standalone deployment."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.catalog_review_profile import CatalogReviewDeploymentProfile
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.deployment_kit import DeploymentKit
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail
from fdai_deployment_cli.foundation_adoption import stage_recovered_foundation
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_application_completion import complete_application


def deploy_with_adopted_foundation(
    *,
    foundation_directory: Path | None,
    recovery_directory: Path | None,
    adopt_runner_image_receipt: Path | None,
    work_dir: Path,
    kit: DeploymentKit,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
    deadline: DeploymentDeadline,
    selected_runtime: RuntimeDeploymentProfile,
    license_signing_key: Path | None,
    trial_token: Path | None,
    application_state_adoption: ApplicationStateAdoption | None,
    catalog_review_profile: CatalogReviewDeploymentProfile | None,
    current_operator_object_id: Callable[[], str],
) -> dict[str, object] | None:
    """Return a completed adopted deployment, or None when adoption isn't selected."""

    inputs = (foundation_directory, recovery_directory)
    if any(value is not None for value in inputs) and not all(
        value is not None for value in inputs
    ):
        raise ValueError("Foundation adoption requires both retained directories")
    if not all(value is not None for value in inputs):
        return None
    if adopt_runner_image_receipt is not None:
        raise ValueError("Foundation adoption cannot combine with runner-image adoption")
    assert foundation_directory is not None
    assert recovery_directory is not None
    scripts = kit.bundle_root / "scripts/deployment/azure"
    if not scripts.is_dir() or scripts.is_symlink():
        raise ValueError("verified deployment bundle is missing Azure orchestration")
    begin_stage("foundation")
    progress_detail("Adopting the verified existing Foundation without repeating effects")
    adoption = stage_recovered_foundation(
        foundation_directory=foundation_directory,
        recovery_directory=recovery_directory,
        destination=work_dir / "run",
        application_source_commit=kit.source_commit,
        kit_manifest_digest=kit.verification.manifest_digest,
        runtime_release_digest=kit.runtime.digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    return complete_application(
        kit=kit,
        prepared=adoption.prepared,
        status=adoption.status,
        scripts=scripts,
        deadline=deadline,
        selected_runtime=selected_runtime,
        license_signing_key=license_signing_key,
        trial_token=trial_token,
        application_state_adoption=application_state_adoption,
        foundation_state_receipt_digest=str(adoption.receipt["foundation_state_receipt_digest"]),
        foundation_adoption_receipt_digest=str(adoption.receipt["receipt_digest"]),
        catalog_review_profile=catalog_review_profile,
        current_operator_object_id=current_operator_object_id,
    )

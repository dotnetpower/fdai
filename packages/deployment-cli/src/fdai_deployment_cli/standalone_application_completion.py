"""Complete standalone identity and application deployment from verified Foundation context."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from fdai_service_contracts.product_profile import ProductAddOn

from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.catalog_review_profile import CatalogReviewDeploymentProfile
from fdai_deployment_cli.control_package import ControlPackage
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.deployment_kit import DeploymentKit
from fdai_deployment_cli.deployment_progress import begin_stage, terminal_output
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_application import deploy_standalone_application


def complete_application(
    *,
    kit: DeploymentKit,
    prepared: Any,
    status: dict[str, Any],
    scripts: Path,
    deadline: DeploymentDeadline,
    selected_runtime: RuntimeDeploymentProfile,
    trial_token: Path | None,
    application_state_adoption: ApplicationStateAdoption | None,
    foundation_state_receipt_digest: str,
    current_operator_object_id: Callable[[], str],
    foundation_adoption_receipt_digest: str | None = None,
    catalog_review_profile: CatalogReviewDeploymentProfile | None = None,
    control_package: ControlPackage | None = None,
) -> dict[str, object]:
    """Configure identity and complete one exact standalone application deployment."""

    entra_bindings: dict[str, str] | None = None
    if selected_runtime.product_profile.selects(ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE):
        begin_stage("identity")
        sys.path.insert(0, str(scripts))
        try:
            supervisor = importlib.import_module("genesis_supervisor")
            entra = importlib.import_module("genesis_entra")
            approval_prompt = importlib.import_module("genesis_approval_prompt")
            actor_digest = approval_prompt.current_actor_digest(prepared.run_binding)
            with (
                terminal_output("Identity configuration and any required approval"),
                redirect_stdout(sys.stderr),
            ):
                entra_bindings = supervisor._configure_entra(
                    prepared=prepared,
                    status=status,
                    actor_digest=actor_digest,
                    plan=entra.plan_entra(),
                )
            entra_bindings["CURRENT_OPERATOR_OBJECT_ID"] = current_operator_object_id()
        finally:
            sys.path.remove(str(scripts))
    application = deploy_standalone_application(
        kit=kit,
        prepared=prepared,
        foundation_status=status,
        entra_bindings=entra_bindings,
        scripts=scripts,
        trial_token=trial_token,
        timeout_seconds=deadline.remaining(),
        runtime_profile=selected_runtime,
        application_state_adoption=application_state_adoption,
        catalog_review_profile=(
            catalog_review_profile or CatalogReviewDeploymentProfile.unselected()
        ),
        control_package=control_package,
    )
    deadline.remaining()
    result: dict[str, object] = {
        "schema_version": "fdai.standalone-azure-deployment.v2",
        "state": "deployment-ready",
        "source_commit": kit.source_commit,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "foundation_state_receipt_digest": foundation_state_receipt_digest,
        "application_receipt_digest": application["receipt_digest"],
        "catalog_review_receipt_digest": application["catalog_review_receipt_digest"],
        "catalog_review_state": application["catalog_review_state"],
        "runtime_profile_digest": selected_runtime.digest,
        "runtime_platform": selected_runtime.runtime_platform.value,
        "database_placement": selected_runtime.database_placement.value,
        "product_profile": selected_runtime.product_profile.model_dump(mode="json"),
        "application_converged": True,
        "deployment_ready": True,
        "inventory_ready": application.get("inventory_ready") is True,
        "license_mode": application["license_mode"],
        "mutation_performed": True,
        "subscription_ready": False,
    }
    if control_package is not None:
        result["control_package_digest"] = control_package.archive_digest
        result["control_package_version"] = control_package.version
    if foundation_adoption_receipt_digest is not None:
        result["foundation_adoption_receipt_digest"] = foundation_adoption_receipt_digest
    return result

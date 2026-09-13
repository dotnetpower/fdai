"""Supervise signed-kit Azure Foundation without GitHub services or a source checkout."""

from __future__ import annotations

import importlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_kit import DeploymentKit, acquire_deployment_kit
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail, terminal_output
from fdai_deployment_cli.foundation_failure import foundation_failure_summary
from fdai_deployment_cli.foundation_output import foundation_output
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_application import deploy_standalone_application
from fdai_deployment_cli.standalone_status import current_status, prior_attempt

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "AZURE_CONFIG_DIR",
        "CURL_CA_BUNDLE",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
    }
)


@dataclass(frozen=True, slots=True)
class ActiveAzureTarget:
    """Authenticated Azure user target selected by the current CLI profile."""

    subscription_id: str
    tenant_id: str


def deploy_azure_foundation(
    *,
    work_dir: Path,
    online: bool,
    offline_kit: Path | None,
    online_url: str | None,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int,
    license_signing_key: Path | None,
    trial_token: Path | None,
) -> dict[str, object]:
    """Advance one standalone deployment through verified application convergence."""

    begin_stage("azure")
    progress_detail("Checking the active Azure CLI human identity")
    target = active_azure_target()
    _create_or_validate_private_directory(work_dir)
    kit_work = work_dir / "kit-work"
    _create_or_validate_private_directory(kit_work)
    begin_stage("kit")
    kit = acquire_deployment_kit(
        work_dir=kit_work,
        online=online,
        offline_kit=offline_kit,
        online_url=online_url,
    )
    begin_stage("discovery")
    progress_detail("Discovering image, storage name, and non-overlapping networks")
    scripts = kit.bundle_root / "scripts/deployment/azure"
    if not scripts.is_dir() or scripts.is_symlink():
        raise ValueError("verified deployment bundle is missing Azure orchestration")
    sys.path.insert(0, str(scripts))
    try:
        prepare = importlib.import_module("genesis_prepare")
        prepared: Any = prepare.prepare_standalone_genesis(
            deployment_kit=kit,
            tenant_id=target.tenant_id,
            subscription_id=target.subscription_id,
            region=region,
            monthly_cost_ceiling=monthly_cost_ceiling,
            connectivity="online" if online else "offline",
            root=work_dir / "run",
        )
    finally:
        sys.path.remove(str(scripts))
    source_evidence = json.dumps(
        {
            "source_commit": kit.source_commit,
            "kit_manifest_digest": kit.verification.manifest_digest,
            "bundle_manifest_digest": kit.bundle_manifest_digest,
            "runtime_release_digest": kit.runtime.digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    deadline = time.monotonic() + timeout_seconds
    approval = prepared.root / "current-foundation-approval.json"
    status_path = prepared.root / "status.json"
    begin_stage("foundation")
    while True:
        remaining = int(deadline - time.monotonic())
        if remaining < 1800:
            raise TimeoutError("standalone Foundation deadline has insufficient remaining budget")
        previous_attempt = prior_attempt(status_path)
        command = (
            sys.executable,
            str(scripts / "genesis_orchestrator.py"),
            "--environment",
            "dev",
            "--region",
            region,
            "--apply",
            "--allow-probe-resources",
            "--source-commit",
            kit.source_commit,
            "--work-dir",
            str(prepared.root),
            "--foundation-offline-kit",
            str(prepared.offline_kit),
            "--foundation-release-root",
            str(prepared.release_root),
            "--foundation-bundle-public-key",
            str(prepared.bundle_public_key),
            "--foundation-profile",
            str(prepared.profile),
            "--foundation-variables-file",
            str(prepared.variables),
            "--create-runner-image",
            "--runner-image-terraform",
            str(prepared.terraform),
            "--runner-ssh-private-key",
            str(prepared.ssh_private_key),
            *(("--approval-file", str(approval)) if approval.exists() else ()),
            "--execution-timeout-seconds",
            str(min(14_400, remaining)),
            "--output",
            "json",
        )
        try:
            with foundation_output() as stderr:
                completed = subprocess.run(
                    command,
                    cwd=kit.bundle_root,
                    env=_standalone_subprocess_environment(
                        PYTHONPATH=os.pathsep.join(
                            (str(scripts), str(Path(__file__).parent.parent))
                        ),
                        AZURE_SUBSCRIPTION_ID=target.subscription_id,
                        AZURE_TENANT_ID=target.tenant_id,
                        FDAI_SIGNED_SOURCE_EVIDENCE=source_evidence,
                    ),
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    check=False,
                    timeout=min(14_400, remaining),
                )
                if completed.returncode not in {0, 2}:
                    raise ValueError(
                        foundation_failure_summary(
                            status_path,
                            previous=previous_attempt,
                            source_commit=kit.source_commit,
                            run_binding=prepared.run_binding,
                        )
                    )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                "standalone Foundation orchestration timed out; inspect retained status before recovery"
            ) from exc
        status = current_status(
            status_path,
            previous=previous_attempt,
            source_commit=kit.source_commit,
            run_binding=prepared.run_binding,
        )
        completed_stages = status.get("completed_stages")
        if (
            status.get("current_stage") == "application-plan"
            and status.get("route") == "private-runner"
            and isinstance(completed_stages, list)
            and "foundation-state" in completed_stages
        ):
            foundation = _foundation_result(kit, prepared, status)
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
                entra_bindings["CURRENT_OPERATOR_OBJECT_ID"] = _current_operator_object_id()
            finally:
                sys.path.remove(str(scripts))
            application = deploy_standalone_application(
                kit=kit,
                prepared=prepared,
                foundation_status=status,
                entra_bindings=entra_bindings,
                scripts=scripts,
                license_signing_key=license_signing_key,
                trial_token=trial_token,
                timeout_seconds=remaining,
            )
            return {
                "schema_version": "fdai.standalone-azure-deployment.v2",
                "state": "deployment-ready",
                "source_commit": kit.source_commit,
                "kit_manifest_digest": kit.verification.manifest_digest,
                "runtime_release_digest": kit.runtime.digest,
                "foundation_state_receipt_digest": foundation["foundation_state_receipt_digest"],
                "application_receipt_digest": application["receipt_digest"],
                "application_converged": True,
                "deployment_ready": True,
                "license_mode": application["license_mode"],
                "mutation_performed": True,
                "subscription_ready": False,
            }
        if completed.returncode != 2:
            raise ValueError("standalone Foundation orchestration failed")
        approval.unlink(missing_ok=True)
        try:
            with terminal_output("Review the exact Foundation plan", approval=True):
                prompt = subprocess.run(
                    (
                        sys.executable,
                        str(scripts / "genesis_approval_prompt.py"),
                        "--status",
                        str(status_path),
                        "--output",
                        str(approval),
                    ),
                    cwd=kit.bundle_root,
                    env=_standalone_subprocess_environment(
                        PYTHONPATH=os.pathsep.join(
                            (str(scripts), str(Path(__file__).parent.parent))
                        ),
                        FDAI_SIGNED_SOURCE_EVIDENCE=source_evidence,
                    ),
                    stdout=sys.stderr,
                    check=False,
                    timeout=600,
                )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("standalone Foundation approval prompt timed out") from exc
        if prompt.returncode != 0:
            raise ValueError("standalone Foundation approval was not granted")


def active_azure_target() -> ActiveAzureTarget:
    """Read the active Azure CLI user target without changing account selection."""

    completed = subprocess.run(
        (
            "az",
            "account",
            "show",
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("Azure authentication is unavailable; run az login first")
    value = json.loads(completed.stdout)
    subscription = value.get("subscription_id") if isinstance(value, dict) else None
    tenant = value.get("tenant_id") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("user_type") != "user"
        or not isinstance(subscription, str)
        or _GUID.fullmatch(subscription) is None
        or not isinstance(tenant, str)
        or _GUID.fullmatch(tenant) is None
    ):
        raise ValueError("standalone deployment requires an authenticated Azure human")
    return ActiveAzureTarget(subscription_id=subscription, tenant_id=tenant)


def _standalone_subprocess_environment(
    source: Mapping[str, str] | None = None,
    **overrides: str,
) -> dict[str, str]:
    """Return the minimal non-secret environment used by standalone child processes."""

    inherited = os.environ if source is None else source
    result = {key: inherited[key] for key in _SAFE_ENVIRONMENT_KEYS if key in inherited}
    result.update(overrides)
    return result


def _current_operator_object_id() -> str:
    completed = subprocess.run(
        (
            "az",
            "ad",
            "signed-in-user",
            "show",
            "--query",
            "id",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or _GUID.fullmatch(value) is None:
        raise ValueError("authenticated Azure operator object ID is unavailable")
    return value


def _foundation_result(
    kit: DeploymentKit, prepared: Any, status: dict[str, Any]
) -> dict[str, object]:
    report = status.get("foundation_report")
    handoff = report.get("state_handoff") if isinstance(report, dict) else None
    receipt = handoff.get("receipt_digest") if isinstance(handoff, dict) else None
    if not isinstance(receipt, str) or _DIGEST.fullmatch(receipt) is None:
        raise ValueError("Foundation state handoff receipt is unavailable")
    return {
        "schema_version": "fdai.standalone-azure-deployment.v1",
        "state": "foundation-ready",
        "source_commit": kit.source_commit,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "foundation_state_receipt_digest": receipt,
        "work_dir": str(prepared.root),
        "next_action": "plan-standalone-application",
        "mutation_performed": True,
        "subscription_ready": False,
    }


def _private_json(path: Path) -> dict[str, Any]:
    value = json.loads(read_private_bytes(path, max_bytes=1_048_576))
    if not isinstance(value, dict):
        raise ValueError("standalone deployment status is invalid")  # noqa: TRY004 - JSON contract.
    return {str(key): item for key, item in value.items()}


def _create_or_validate_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("standalone deployment directory must be current-UID mode 0700")

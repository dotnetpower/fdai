"""Control standalone managed-host application deployment through Azure Bastion."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_kit import DeploymentKit, archive_verified_kit
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.license_issue import (
    discover_license_signing_key,
    issue_deployment_license,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.trust_roots import license_public_key_pem

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


def deploy_standalone_application(
    *,
    kit: DeploymentKit,
    prepared: Any,
    foundation_status: dict[str, Any],
    entra_bindings: dict[str, str],
    scripts: Path,
    license_signing_key: Path | None,
    trial_token: Path | None,
    timeout_seconds: int,
) -> dict[str, object]:
    """Deploy and independently replan the application without a workflow host."""

    report = _mapping(foundation_status.get("foundation_report"), "Foundation report")
    plan = _mapping(report.get("foundation_plan"), "Foundation plan")
    plan_directory = prepared.root / str(plan["plan_ref"])
    handoff_path = plan_directory / "foundation-private-handoff.json"
    handoff = _private_json(handoff_path, "Foundation handoff")
    runner = _mapping(handoff.get("runner"), "Foundation runner")
    access = _mapping(handoff.get("access"), "Foundation access")
    ops = _mapping(handoff.get("ops"), "Foundation operations")
    known_hosts = plan_directory / "runner-known-hosts"
    module = _import_bastion(scripts)
    module.validate_known_hosts(known_hosts)
    private_key = prepared.ssh_private_key
    if module.validate_ssh_private_key(private_key) != runner.get("ssh_key_digest"):
        raise ValueError("standalone host SSH key differs from Foundation evidence")
    transport_archive = prepared.root / "standalone-kit.tar.gz"
    archive_digest = archive_verified_kit(kit, transport_archive)
    entra_path = prepared.root / "entra-bindings.json"
    _replace_private_json(entra_path, entra_bindings)
    work_ref = canonical_digest(
        {
            "target_binding": prepared.target_binding,
            "source_commit": prepared.source_commit,
            "kit_manifest_digest": prepared.kit_manifest_digest,
        }
    )[:24]
    username = str(runner["admin_username"])
    if _SSH_USER.fullmatch(username) is None:
        raise ValueError("Foundation runner SSH username is invalid")
    remote_root = f"/home/{username}/.fdai-transfer-{work_ref}"
    remote_archive = f"{remote_root}/kit.tar.gz"
    remote_handoff = f"{remote_root}/foundation-handoff.json"
    remote_entra = f"{remote_root}/entra-bindings.json"
    remote_approval = f"{remote_root}/approval.json"
    app_work = f"{remote_root}/application"
    host_alias = (
        "fdai-standalone-"
        + hashlib.sha256(str(runner["vm_id"]).casefold().encode()).hexdigest()[:16]
    )
    with module.BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=str(ops["resource_group_name"]),
        bastion_name=str(access["bastion_name"]),
        vm_id=str(runner["vm_id"]),
        username=username,
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=plan_directory,
        timeout=timeout_seconds,
        trust_new_host_key=False,
    ) as tunnel:
        _prepare_remote(
            tunnel,
            remote_root=remote_root,
            remote_archive=remote_archive,
            archive=transport_archive,
            archive_digest=archive_digest,
            handoff_path=handoff_path,
            remote_handoff=remote_handoff,
            entra_path=entra_path,
            remote_entra=remote_entra,
            app_work=app_work,
            timeout_seconds=timeout_seconds,
        )
        substrate_plan = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("plan", "--stage", "substrate"),
            timeout=3600,
        )
        substrate_approval = _approve_plan(prepared.root, substrate_plan)
        tunnel.copy_to(substrate_approval, remote_approval, timeout=120)
        substrate_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("apply", "--stage", "substrate", "--approval", remote_approval),
            timeout=7200,
        )
        _require_receipt(substrate_receipt, "substrate")
        image_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("import-images",),
            timeout=5400,
        )
        image_digests = _mapping(image_receipt.get("image_digests"), "image import receipt")
        core_digest = str(image_digests["core-control-plane"]).removeprefix("sha256:")
        app_name = f"ca-fdai-dev-{str(handoff['region'])[:3]}-core"
        deployment_binding = hashlib.sha256(
            (f"{handoff['tenant_id']}\0{handoff['subscription_id']}\0{app_name}").encode()
        ).hexdigest()
        token = _license_token(
            key=license_signing_key,
            trial_token=trial_token,
            image_digest=core_digest,
            deployment_binding=deployment_binding,
            work_ref=work_ref,
        )
        license_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            (
                "install-license",
                "--image-digest",
                core_digest,
                "--deployment-binding",
                deployment_binding,
            ),
            timeout=300,
            input_text=token,
        )
        token = ""
        if license_receipt.get("secret_metadata_verified") is not True:
            raise ValueError("standalone license installation was not verified")
        migration_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("migrate",),
            timeout=5400,
        )
        if (
            migration_receipt.get("state") != "migrated"
            or migration_receipt.get("catalogs_materialized") is not True
        ):
            raise ValueError("standalone database and catalog bootstrap is incomplete")
        application_plan = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("plan", "--stage", "application"),
            timeout=3600,
        )
        application_approval = _approve_plan(prepared.root, application_plan)
        tunnel.ssh(("rm", "-f", remote_approval), timeout=60)
        tunnel.copy_to(application_approval, remote_approval, timeout=120)
        application_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("apply", "--stage", "application", "--approval", remote_approval),
            timeout=7200,
        )
        _require_receipt(application_receipt, "application")
        verification = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("verify",),
            timeout=3600,
        )
        if (
            verification.get("terraform_zero_change_verified") is not True
            or verification.get("runtime_health_verified") is not True
        ):
            raise ValueError("standalone application convergence is incomplete")
        cleanup = tunnel.ssh(("rm", "-f", "--", remote_archive, remote_approval), timeout=300)
        archive_absent = tunnel.ssh(("test", "!", "-e", remote_archive), timeout=60)
        approval_absent = tunnel.ssh(("test", "!", "-e", remote_approval), timeout=60)
        if any(result.returncode != 0 for result in (cleanup, archive_absent, approval_absent)):
            raise ValueError("standalone remote transient cleanup is incomplete")
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-terminal-receipt.v1",
        "state": "application-converged",
        "source_commit": prepared.source_commit,
        "target_binding": prepared.target_binding,
        "substrate_receipt_digest": substrate_receipt["receipt_digest"],
        "image_import_receipt_digest": image_receipt["receipt_digest"],
        "migration_receipt_digest": migration_receipt["receipt_digest"],
        "application_receipt_digest": application_receipt["receipt_digest"],
        "verification_receipt_digest": verification["receipt_digest"],
        "remote_transient_cleanup_verified": True,
        "application_converged": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(prepared.root / "standalone-application-receipt.json", receipt)
    return receipt


def _prepare_remote(
    tunnel: Any,
    *,
    remote_root: str,
    remote_archive: str,
    archive: Path,
    archive_digest: str,
    handoff_path: Path,
    remote_handoff: str,
    entra_path: Path,
    remote_entra: str,
    app_work: str,
    timeout_seconds: int,
) -> None:
    created = tunnel.ssh(("install", "-d", "-m", "0700", remote_root), timeout=60)
    if created.returncode != 0:
        raise ValueError("standalone remote work directory is unavailable")
    removed = tunnel.ssh(("rm", "-f", "--", remote_archive), timeout=60)
    if removed.returncode != 0:
        raise ValueError("standalone remote archive reset failed")
    tunnel.copy_to(archive, remote_archive, timeout=min(1800, timeout_seconds))
    tunnel.copy_to(handoff_path, remote_handoff, timeout=120)
    tunnel.copy_to(entra_path, remote_entra, timeout=120)
    digest = tunnel.ssh(("sha256sum", remote_archive), timeout=300)
    if digest.returncode != 0 or digest.stdout.split(maxsplit=1)[0] != archive_digest:
        raise ValueError("standalone transport archive digest differs")
    commands = (
        (("rm", "-rf", "--", f"{remote_root}/kit"), 300),
        (("tar", "-xzf", remote_archive, "-C", remote_root), 1800),
        (("python3", "-m", "venv", f"{remote_root}/venv"), 300),
        (
            (
                f"{remote_root}/venv/bin/pip",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--find-links",
                f"{remote_root}/kit/python",
                "fdai-deployment-cli",
            ),
            900,
        ),
        (("install", "-d", "-m", "0700", app_work), 60),
        (
            (
                f"{remote_root}/venv/bin/python",
                "-m",
                "fdai_deployment_cli.standalone_host",
                "--work-dir",
                app_work,
                "prepare",
                "--kit",
                f"{remote_root}/kit",
                "--handoff",
                remote_handoff,
                "--entra",
                remote_entra,
            ),
            1800,
        ),
    )
    for command, limit in commands:
        setup = tunnel.ssh(command, timeout=min(limit, timeout_seconds))
        if setup.returncode != 0:
            raise ValueError("standalone managed-host preparation failed")


def _remote_json(
    tunnel: Any,
    remote_root: str,
    app_work: str,
    arguments: tuple[str, ...],
    *,
    timeout: int,
    input_text: str | None = None,
) -> dict[str, Any]:
    result = tunnel.ssh(
        (
            f"{remote_root}/venv/bin/python",
            "-m",
            "fdai_deployment_cli.standalone_host",
            "--work-dir",
            app_work,
            *arguments,
        ),
        timeout=timeout,
        input_text=input_text,
    )
    if result.returncode != 0:
        raise ValueError("standalone managed-host checkpoint failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("standalone managed-host checkpoint returned invalid output") from exc
    return _mapping(value, "standalone managed-host result")


def _approve_plan(root: Path, review: dict[str, Any]) -> Path:
    stage = str(review.get("stage", ""))
    expected = f"{stage}-apply"
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    supplied = input(f"Type the exact stage name to approve ({expected}): ").strip()
    if supplied != expected:
        raise ValueError("standalone application plan approval was denied")
    actor = _azure_actor_digest(str(review["target_binding"]))
    now = datetime.now(UTC).replace(microsecond=0)
    expires = min(_parse_moment(str(review["expires_at"])), now + timedelta(hours=1))
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": stage,
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": actor,
        "approved_at": _moment(now),
        "expires_at": _moment(expires),
    }
    path = root / f"{stage}-approval.json"
    path.unlink(missing_ok=True)
    write_private_output(path, json.dumps(approval, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def _license_token(
    *,
    key: Path | None,
    trial_token: Path | None,
    image_digest: str,
    deployment_binding: str,
    work_ref: str,
) -> str:
    issuer = discover_license_signing_key(key)
    if issuer is not None:
        return issue_deployment_license(
            private_key=issuer,
            image_digest=image_digest,
            deployment_binding=deployment_binding,
            license_id=f"lic-{work_ref}",
        )
    token_path = trial_token
    if token_path is None:
        supplied = input("Path to a pre-issued mode-0600 Trial token: ").strip()
        if not supplied:
            raise ValueError("a license issuer key or Trial token is required")
        token_path = Path(supplied)
    path = token_path if token_path.is_absolute() else Path.cwd() / token_path
    token = read_private_bytes(path, max_bytes=8192).decode("ascii")
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=image_digest,
        expected_tenant_binding=deployment_binding,
    )
    return token


def _require_receipt(value: dict[str, Any], stage: str) -> None:
    if (
        value.get("state") != "applied"
        or value.get("stage") != stage
        or value.get("control_plane_readback_verified") is not True
        or not isinstance(value.get("receipt_digest"), str)
        or _DIGEST.fullmatch(str(value["receipt_digest"])) is None
    ):
        raise ValueError(f"standalone {stage} apply receipt is invalid")


def _import_bastion(scripts: Path) -> Any:
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("genesis_bastion")
    finally:
        sys.path.remove(str(scripts))


def _azure_actor_digest(target_binding: str) -> str:
    result = subprocess.run(
        (
            "az",
            "account",
            "show",
            "--query",
            "user.name",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    login = result.stdout.strip()
    if result.returncode != 0 or not login:
        raise ValueError("authenticated Azure approval actor is unavailable")
    return hashlib.sha256(f"{target_binding}:{login.casefold()}".encode()).hexdigest()


def _private_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=4 * 1024 * 1024))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid") from exc
    return _mapping(value, label)


def _replace_private_json(path: Path, value: dict[str, object] | dict[str, str]) -> None:
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    write_private_output(
        temporary,
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_moment(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("plan expiry is invalid")
    return result.astimezone(UTC)

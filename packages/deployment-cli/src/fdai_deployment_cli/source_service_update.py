"""Build and deploy one source-selected service through retained AKS state."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli.aks_service_update import SERVICES
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_snapshot import materialize_source, verify_source_snapshot
from fdai_deployment_cli.standalone_application import (
    _approval_input,
    _approve_plan,
    _azure_actor_digest,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")


def deploy_source_service_update(
    *,
    source_root: Path,
    application_work_dir: Path,
    work_dir: Path,
    service: str,
    timeout_seconds: int,
    adopt_historical_binding: Path | None = None,
    adopt_historical_state: Path | None = None,
    adopt_historical_variables: Path | None = None,
    adopt_historical_live: Path | None = None,
    adopt_historical_plan: Path | None = None,
    approve_import: Callable[[Path, dict[str, Any], DeploymentDeadline], Path] | None = None,
    approve_plan: Callable[[Path, dict[str, Any]], Path] | None = None,
) -> dict[str, object]:
    """Build, import, plan, approve, apply, and verify one dev AKS service update."""

    if service not in SERVICES:
        raise ValueError("source service update names an unsupported service")
    deadline = DeploymentDeadline(timeout_seconds)
    source = inspect_source(source_root)
    application = application_work_dir.absolute()
    _require_private_directory(application, create=False)
    work = work_dir.absolute()
    if work.resolve().is_relative_to(source.root) or application == work:
        raise ValueError("source service update work directories are invalid")
    _require_private_directory(work, create=True)
    lock = _lock(work)
    try:
        adoption_inputs = (
            adopt_historical_binding,
            adopt_historical_state,
            adopt_historical_variables,
            adopt_historical_live,
            adopt_historical_plan,
        )
        if any(value is not None for value in adoption_inputs) and not all(
            isinstance(value, Path) for value in adoption_inputs
        ):
            raise ValueError("historical AKS adoption requires all five evidence inputs")
        if all(isinstance(value, Path) for value in adoption_inputs):
            binding, state, variables, live, plan = adoption_inputs
            assert isinstance(binding, Path)
            assert isinstance(state, Path)
            assert isinstance(variables, Path)
            assert isinstance(live, Path)
            assert isinstance(plan, Path)
            adoption_arguments = (
                "adopt-historical-aks-application",
                "--binding",
                str(binding.absolute()),
                "--state",
                str(state.absolute()),
                "--variables",
                str(variables.absolute()),
                "--live",
                str(live.absolute()),
                "--plan",
                str(plan.absolute()),
            )
            adopted = _host_json(
                application,
                adoption_arguments,
                timeout=deadline.remaining(2400),
            )
            if adopted.get("state") == "reconciliation-required":
                review = adopted.get("reconciliation_review")
                if (
                    not isinstance(review, dict)
                    or review.get("schema_version") != "fdai.standalone-application-plan.v1"
                    or review.get("stage") != "application"
                ):
                    raise ValueError("historical AKS reconciliation review is invalid")
                recovered = _host_json(
                    application,
                    ("recover-historical-aks-reconciliation",),
                    timeout=deadline.remaining(2100),
                )
                if recovered.get("state") == "applied":
                    if (
                        recovered.get("effect_verified") is not True
                        or recovered.get("terraform_zero_change_verified") is not True
                    ):
                        raise ValueError("historical AKS reconciliation recovery is incomplete")
                else:
                    reconciliation_approval = (
                        approve_plan(work, review)
                        if approve_plan is not None
                        else _approve_plan(work, review, deadline=deadline)
                    )
                    reconciled = _host_json(
                        application,
                        (
                            "apply-historical-aks-reconciliation",
                            "--approval",
                            str(reconciliation_approval),
                        ),
                        timeout=deadline.remaining(7500),
                    )
                    if (
                        reconciled.get("state") != "applied"
                        or reconciled.get("effect_verified") is not True
                        or reconciled.get("terraform_zero_change_verified") is not True
                    ):
                        raise ValueError("historical AKS reconciliation is incomplete")
                adopted = _host_json(
                    application,
                    adoption_arguments,
                    timeout=deadline.remaining(2400),
                )
            if (
                adopted.get("schema_version") != "fdai.historical-aks-application-adoption.v1"
                or adopted.get("state") != "adopted"
                or adopted.get("managed_identity_verified") is not True
                or adopted.get("remote_state_verified") is not True
                or adopted.get("live_baseline_verified") is not True
                or adopted.get("terraform_zero_change_verified") is not True
                or adopted.get("azure_resource_mutation_performed") is not False
            ):
                raise ValueError("historical AKS application adoption is incomplete")
        context = _host_json(
            application,
            ("service-update-context", "--service", service),
            timeout=deadline.remaining(120),
        )
        if (
            context.get("schema_version") != "fdai.source-service-update-context.v1"
            or context.get("state") != "verified"
            or context.get("service") != service
            or not isinstance(context.get("target_binding"), str)
            or _DIGEST.fullmatch(str(context["target_binding"])) is None
        ):
            raise ValueError("retained AKS service update context is invalid")
        intent = {
            "schema_version": "fdai.source-service-update-intent.v1",
            "source": source.to_mapping(),
            "service": service,
            "target_binding": context["target_binding"],
            "application_work_binding": canonical_digest(
                {"path": str(application), "target_binding": context["target_binding"]}
            ),
        }
        intent_path = work / "source-service-update-intent.json"
        snapshot = work / "source-snapshot"
        if intent_path.exists() or intent_path.is_symlink():
            if _read(intent_path) != intent:
                raise ValueError("retained source service update intent differs")
            snapshot_digest = str(_read(work / "source-snapshot-receipt.json")["snapshot_digest"])
            verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
        else:
            if any(path.name != "source-service-update.lock" for path in work.iterdir()):
                raise ValueError("source service update cannot adopt existing work state")
            write_private_bytes(intent_path, canonical_bytes(intent))
            snapshot_digest = materialize_source(source, snapshot)
            write_private_bytes(
                work / "source-snapshot-receipt.json",
                canonical_bytes({"snapshot_digest": snapshot_digest}),
            )
        source.reverify()
        image = _build_image(
            snapshot=snapshot,
            snapshot_digest=snapshot_digest,
            work_dir=work / "source-images",
            service=service,
            timeout_seconds=deadline.remaining(3600),
        )
        if (
            image.get("state") != "built"
            or image.get("source_commit") != source.commit
            or image.get("service") != service
        ):
            raise ValueError("source service image build did not produce exact evidence")
        import_review = {
            "schema_version": "fdai.source-service-image-import-review.v1",
            "service": service,
            "source_commit": source.commit,
            "archive_sha256": image["archive_sha256"],
            "image_digest": image["image_digest"],
            "target_binding": context["target_binding"],
            "expires_at": _moment(datetime.now(UTC) + timedelta(hours=1)),
            "mutation_performed": False,
        }
        import_review["review_digest"] = canonical_digest(import_review)
        import_approval = work / "source-image-import-approval.json"
        if import_approval.is_symlink():
            raise ValueError("source service image import approval must not be a symlink")
        if not import_approval.is_file():
            import_approval = (approve_import or _approve_import)(work, import_review, deadline)
        archive = work / "source-images" / str(image["archive_ref"])
        imported = _host_json(
            application,
            (
                "import-source-image",
                "--service",
                service,
                "--archive",
                str(archive),
                "--archive-sha256",
                str(image["archive_sha256"]),
                "--image-digest",
                str(image["image_digest"]),
                "--source-commit",
                source.commit,
                "--approval",
                str(import_approval),
            ),
            timeout=deadline.remaining(2400),
        )
        expected_update = {
            "service": service,
            "image": imported.get("image"),
            "source_commit": source.commit,
        }
        active = context.get("active_service_update")
        if active is None:
            prepared = _host_json(
                application,
                (
                    "prepare-service-update",
                    "--service",
                    service,
                    "--image",
                    str(imported["image"]),
                    "--source-commit",
                    source.commit,
                ),
                timeout=deadline.remaining(300),
            )
            if any(prepared.get(key) != value for key, value in expected_update.items()):
                raise ValueError("prepared source service update differs from imported image")
        elif not isinstance(active, dict) or any(
            active.get(key) != value for key, value in expected_update.items()
        ):
            raise ValueError("another AKS service update is active")
        recovered = _host_json(
            application,
            ("recover-apply", "--stage", "application", "--service", service),
            timeout=deadline.remaining(2100),
        )
        if recovered.get("state") == "applied":
            applied = recovered
        else:
            review = _host_json(
                application,
                ("plan", "--stage", "application", "--service", service),
                timeout=deadline.remaining(3900),
            )
            plan_approval = (
                approve_plan(work, review)
                if approve_plan is not None
                else _approve_plan(work, review, deadline=deadline)
            )
            applied = _host_json(
                application,
                (
                    "apply",
                    "--stage",
                    "application",
                    "--service",
                    service,
                    "--approval",
                    str(plan_approval),
                ),
                timeout=deadline.remaining(7500),
            )
        result: dict[str, object] = {
            "schema_version": "fdai.source-service-update.v1",
            "state": "applied",
            "service": service,
            "source_commit": source.commit,
            "image_digest": image["image_digest"],
            "target_binding": context["target_binding"],
            "image_import_receipt_digest": imported["receipt_digest"],
            "application_receipt_digest": applied["receipt_digest"],
            "effect_verified": applied.get("control_plane_readback_verified") is True,
            "peer_state_unchanged_verified": applied.get("peer_state_unchanged_verified") is True,
            "terraform_zero_change_verified": applied.get("terraform_zero_change_verified") is True,
            "mutation_performed": True,
            "subscription_ready": False,
        }
        if not all(
            result[key] is True
            for key in (
                "effect_verified",
                "peer_state_unchanged_verified",
                "terraform_zero_change_verified",
            )
        ):
            raise ValueError("source service update effect verification is incomplete")
        result["receipt_digest"] = canonical_digest(result)
        receipt_path = work / "source-service-update-receipt.json"
        if receipt_path.exists() or receipt_path.is_symlink():
            if _read(receipt_path) != result:
                raise ValueError("retained source service update receipt differs")
        else:
            write_private_bytes(receipt_path, canonical_bytes(result))
        return result
    finally:
        os.close(lock)


def _approve_import(root: Path, review: dict[str, Any], deadline: DeploymentDeadline) -> Path:
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    expected = f"import-{review['service']}"
    print(f"Type {expected} to approve the exact source image import: ", end="", file=sys.stderr)
    supplied = _approval_input(timeout_seconds=deadline.remaining(600))
    if supplied != expected:
        raise ValueError("source service image import approval was denied")
    actor = _azure_actor_digest(str(review["target_binding"]), timeout_seconds=60)
    now = datetime.now(UTC).replace(microsecond=0)
    approval = {
        "schema_version": "fdai.source-service-image-import-approval.v1",
        "service": review["service"],
        "source_commit": review["source_commit"],
        "archive_sha256": review["archive_sha256"],
        "image_digest": review["image_digest"],
        "target_binding": review["target_binding"],
        "actor_digest": actor,
        "approved_at": _moment(now),
        "expires_at": _moment(min(now + timedelta(hours=1), _parse(review["expires_at"]))),
    }
    approval["approval_digest"] = canonical_digest(approval)
    path = root / "source-image-import-approval.json"
    path.unlink(missing_ok=True)
    write_private_bytes(path, canonical_bytes(approval))
    return path


def _build_image(**kwargs: Any) -> dict[str, object]:
    snapshot = Path(kwargs["snapshot"])
    scripts = snapshot / "tree/scripts/deployment/azure/source_image_build.py"
    if not scripts.is_file():
        raise ValueError("source service image builder is unavailable in the selected snapshot")
    command = (
        sys.executable,
        str(scripts),
        "--snapshot",
        str(snapshot),
        "--snapshot-digest",
        str(kwargs["snapshot_digest"]),
        "--work-dir",
        str(kwargs["work_dir"]),
        "--service",
        str(kwargs["service"]),
        "--timeout-seconds",
        str(kwargs["timeout_seconds"]),
    )
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        timeout=kwargs["timeout_seconds"],
    )
    if completed.returncode != 0:
        raise ValueError("source service image build failed; preserve retained evidence")
    return load_json_object(completed.stdout, label="source service image build")


def _host_json(work_dir: Path, arguments: tuple[str, ...], *, timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "fdai_deployment_cli.standalone_host",
            "--work-dir",
            str(work_dir),
            *arguments,
        ),
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ValueError("managed-host source service update checkpoint failed")
    return load_json_object(completed.stdout, label="managed-host source service update")


def _require_private_directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ValueError("source service update requires private owned work directories")


def _lock(work: Path) -> int:
    path = work / "source-service-update.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise ValueError("source service update is already active") from None
    return descriptor


def _read(path: Path) -> dict[str, object]:
    return load_json_object(read_private_bytes(path, max_bytes=65536), label="source update state")


def _parse(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("source image import review expiry is invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

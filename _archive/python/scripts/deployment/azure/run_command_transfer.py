"""Orchestrate one claim-bound private-relay Run Command transfer."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes
from run_command_authority import (
    require_approval_current,
    validate_delegated_transport_authority,
    validate_transport_authority,
)
from run_command_bootstrap import (
    DIGEST,
    MAX_BUNDLE_BYTES,
    OPERATION,
    build_run_command,
    validate_parameters,
    validate_target,
)
from run_command_private_relay import PrivateRelay


class Capture(Protocol):
    def __call__(self, command: tuple[str, ...], *, timeout: int) -> str: ...


class Relay(Protocol):
    certificate_digest: str

    def start(self) -> None: ...

    def result(self) -> bytes: ...

    def close(self) -> None: ...


class RelayFactory(Protocol):
    def __call__(
        self,
        *,
        relay_host: str,
        relay_port: int,
        allowed_source: str,
        operation_id: str,
        bundle: Path,
        bundle_digest: str,
        receiver: Path,
        receiver_digest: str,
        require_bundle: bool,
    ) -> Relay: ...


def validate_host_result(
    content: bytes,
    *,
    operation_id: str,
    bundle_digest: str,
    claim_digest: str,
    file_count: int,
    inventory_digest: str,
) -> dict[str, object]:
    """Validate the WSL receiver result against the exact operation and bundle."""

    result = load_json_object(content, label="run command host result", max_bytes=16_384)
    digest = result.get("receipt_digest")
    document = {key: value for key, value in result.items() if key != "receipt_digest"}
    if (
        set(result)
        != {
            "schema_version",
            "state",
            "operation_id",
            "bundle_digest",
            "claim_digest",
            "file_count",
            "inventory_digest",
            "mutation_performed",
            "receipt_digest",
        }
        or result.get("schema_version") != "fdai.run-command-bundle-host-result.v1"
        or result.get("state") != "verified"
        or result.get("operation_id") != operation_id
        or result.get("bundle_digest") != bundle_digest
        or result.get("claim_digest") != claim_digest
        or type(result.get("file_count")) is not int
        or result.get("file_count") != file_count
        or result.get("inventory_digest") != inventory_digest
        or result.get("mutation_performed") is not False
        or digest != canonical_digest(document)
    ):
        raise ValueError("run command host result is invalid")
    return result


def transfer_parameters(
    *,
    operation_id: str,
    bundle_digest: str,
    bundle_size: int,
    receiver_digest: str,
    file_count: int,
    inventory_digest: str,
    target: dict[str, object],
) -> dict[str, object]:
    """Bind one transfer to stable non-secret relay and host coordinates."""

    validate_target(target)
    parameters: dict[str, object] = {
        "bundle_digest": bundle_digest,
        "bundle_size": bundle_size,
        "claim_digest": "0" * 64,
        "file_count": file_count,
        "inventory_digest": inventory_digest,
        "operation_id": operation_id,
        "recovery_mode": "fresh",
        "receiver_digest": receiver_digest,
        "relay_certificate_digest": "0" * 64,
        "relay_host": target["relay_private_ip"],
        "relay_port": target["relay_port"],
    }
    validate_parameters(parameters)
    return parameters


def transfer_claim(
    *,
    parameters: dict[str, object],
    target: dict[str, object],
    bundle_receipt_digest: str,
    approval_digest: str,
    profile_digest: str,
    authority_receipt_digest: str | None = None,
) -> dict[str, object]:
    """Create the immutable pre-effect transfer claim."""

    validate_parameters(parameters)
    validate_target(target)
    target_binding = str(target["target_binding"])
    binding_digests = [
        target_binding,
        bundle_receipt_digest,
        approval_digest,
        profile_digest,
    ]
    if authority_receipt_digest is not None:
        binding_digests.append(authority_receipt_digest)
    if any(DIGEST.fullmatch(value) is None for value in binding_digests):
        raise ValueError("run command transfer binding is invalid")
    stable_parameters = {
        key: value
        for key, value in parameters.items()
        if key not in {"claim_digest", "recovery_mode", "relay_certificate_digest"}
    }
    claim: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-transfer-claim.v1",
        "target_binding": target_binding,
        "target_digest": canonical_digest(target),
        "bundle_receipt_digest": bundle_receipt_digest,
        "approval_digest": approval_digest,
        "profile_digest": profile_digest,
        "parameters_digest": canonical_digest(stable_parameters),
        "operation_id": parameters["operation_id"],
        "bundle_digest": parameters["bundle_digest"],
        "receiver_digest": parameters["receiver_digest"],
        "mutation_performed": False,
    }
    if authority_receipt_digest is not None:
        claim["schema_version"] = "fdai.run-command-private-relay-transfer-claim.v2"
        claim["authority_receipt_digest"] = authority_receipt_digest
    return claim


def invocation_claim_record(
    claim_digest: str,
    parameters: dict[str, object],
    target: dict[str, object],
) -> dict[str, object]:
    """Bind one fresh or verification-only invocation before the relay listens."""

    validate_parameters(parameters)
    document: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-invocation-claim.v1",
        "claim_digest": claim_digest,
        "mode": parameters["recovery_mode"],
        "relay_certificate_digest": parameters["relay_certificate_digest"],
        "parameters_digest": canonical_digest(parameters),
        "target_digest": canonical_digest(target),
        "mutation_performed": False,
    }
    document["record_digest"] = canonical_digest(document)
    return document


def transfer_execution_bundle(
    *,
    work_dir: Path,
    bundle: Path,
    bundle_receipt: dict[str, object],
    receiver: Path,
    receiver_digest: str,
    target: dict[str, object],
    profile: dict[str, object],
    approval: dict[str, object],
    authority_receipt: dict[str, object] | None = None,
    timeout_seconds: int,
    capture: Capture,
    relay_factory: RelayFactory = PrivateRelay,
) -> dict[str, object]:
    """Stage one bundle through a source-bound ephemeral private TLS relay."""

    work_descriptor = _private_directory(work_dir)
    try:
        _acquire_work_lock(work_descriptor)
        _require_work_directory_identity(work_dir, work_descriptor)
        return _transfer_execution_bundle_locked(
            work_dir=work_dir,
            bundle=bundle,
            bundle_receipt=bundle_receipt,
            receiver=receiver,
            receiver_digest=receiver_digest,
            target=target,
            profile=profile,
            approval=approval,
            authority_receipt=authority_receipt,
            timeout_seconds=timeout_seconds,
            capture=capture,
            relay_factory=relay_factory,
            work_descriptor=work_descriptor,
        )
    finally:
        fcntl.flock(work_descriptor, fcntl.LOCK_UN)
        os.close(work_descriptor)


def _transfer_execution_bundle_locked(
    *,
    work_dir: Path,
    bundle: Path,
    bundle_receipt: dict[str, object],
    receiver: Path,
    receiver_digest: str,
    target: dict[str, object],
    profile: dict[str, object],
    approval: dict[str, object],
    authority_receipt: dict[str, object] | None,
    timeout_seconds: int,
    capture: Capture,
    relay_factory: RelayFactory,
    work_descriptor: int,
) -> dict[str, object]:
    deadline = DeploymentDeadline(timeout_seconds)
    validate_target(target)
    _validate_bundle_receipt(bundle_receipt)
    file_count = _required_int(bundle_receipt, "file_count")
    bundle_digest = _private_digest(bundle, maximum=MAX_BUNDLE_BYTES)
    if (
        bundle_digest != bundle_receipt["bundle_digest"]
        or bundle.stat().st_size != bundle_receipt["bundle_size"]
    ):
        raise ValueError("run command bundle differs from its receipt")
    if _private_digest(receiver, maximum=4 * 1024 * 1024) != receiver_digest:
        raise ValueError("run command receiver digest differs")
    operation_id = str(bundle_receipt["operation_id"])
    approval_digest = (
        validate_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            operation_id=operation_id,
            bundle_receipt_digest=str(bundle_receipt["receipt_digest"]),
            receiver_digest=receiver_digest,
            capture=capture,
            deadline=deadline,
        )
        if authority_receipt is None
        else validate_delegated_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            authority_receipt=authority_receipt,
            operation_id=operation_id,
            bundle_receipt_digest=str(bundle_receipt["receipt_digest"]),
            receiver_digest=receiver_digest,
            capture=capture,
            deadline=deadline,
        )
    )
    parameters = transfer_parameters(
        operation_id=operation_id,
        bundle_digest=bundle_digest,
        bundle_size=bundle.stat().st_size,
        receiver_digest=receiver_digest,
        file_count=file_count,
        inventory_digest=str(bundle_receipt["inventory_digest"]),
        target=target,
    )
    claim = transfer_claim(
        parameters=parameters,
        target=target,
        bundle_receipt_digest=str(bundle_receipt["receipt_digest"]),
        approval_digest=approval_digest,
        profile_digest=canonical_digest(profile),
        authority_receipt_digest=(
            str(authority_receipt.get("receipt_digest")) if authority_receipt is not None else None
        ),
    )
    claim_digest = canonical_digest(claim)
    parameters["claim_digest"] = claim_digest
    validate_parameters(parameters)
    claim_path = work_dir / "run-command-bundle-transfer-claim.json"
    invocation_path = work_dir / "run-command-bundle-invocation-claim.json"
    recovery_path = work_dir / "run-command-bundle-recovery-claim.json"
    fresh_status_path = work_dir / "run-command-bundle-invocation-status.json"
    recovery_status_path = work_dir / "run-command-bundle-recovery-status.json"
    receipt_path = work_dir / "run-command-bundle-transfer-receipt.json"
    host_result_path = work_dir / "run-command-host-result.json"

    if claim_path.exists() or claim_path.is_symlink():
        if _read(claim_path, "run command transfer claim") != claim:
            raise ValueError("run command transfer claim differs")
    else:
        if any(
            path.exists() or path.is_symlink()
            for path in (
                invocation_path,
                recovery_path,
                fresh_status_path,
                recovery_status_path,
                receipt_path,
                host_result_path,
            )
        ):
            raise ValueError("run command transfer evidence exists without its claim")
        require_approval_current(approval)
        _write_durable_private(
            work_descriptor,
            claim_path.name,
            canonical_bytes(claim),
        )
        _require_work_directory_identity(work_dir, work_descriptor)
        _perform_invocation(
            mode="fresh",
            claim_path=invocation_path,
            status_path=fresh_status_path,
            host_result_path=host_result_path,
            parameters=parameters,
            target=target,
            approval=approval,
            work_dir=work_dir,
            work_descriptor=work_descriptor,
            bundle=bundle,
            receiver=receiver,
            deadline=deadline,
            capture=capture,
            relay_factory=relay_factory,
        )

    if not invocation_path.exists() and not invocation_path.is_symlink():
        raise ValueError("run command transfer stopped before invocation")
    _validate_invocation_claim(
        invocation_path,
        claim_digest=claim_digest,
        parameters=parameters,
        target=target,
        expected_mode="fresh",
    )
    if recovery_path.exists() or recovery_path.is_symlink():
        _validate_invocation_claim(
            recovery_path,
            claim_digest=claim_digest,
            parameters=parameters,
            target=target,
            expected_mode="verify",
        )

    host_result = _valid_host_result(
        host_result_path,
        operation_id=operation_id,
        bundle_digest=bundle_digest,
        claim_digest=claim_digest,
        file_count=file_count,
        inventory_digest=str(bundle_receipt["inventory_digest"]),
    )
    completed_status = _completed_status(
        fresh_status_path,
        recovery_status_path,
        invocation_path,
        recovery_path,
        claim_digest=claim_digest,
    )
    if host_result is None or completed_status is None:
        if recovery_path.exists() or recovery_path.is_symlink():
            _validate_invocation_claim(
                recovery_path,
                claim_digest=claim_digest,
                parameters=parameters,
                target=target,
                expected_mode="verify",
            )
            raise ValueError("run command verification recovery is already claimed")
        require_approval_current(approval)
        _require_work_directory_identity(work_dir, work_descriptor)
        _perform_invocation(
            mode="verify",
            claim_path=recovery_path,
            status_path=recovery_status_path,
            host_result_path=host_result_path,
            parameters=parameters,
            target=target,
            approval=approval,
            work_dir=work_dir,
            work_descriptor=work_descriptor,
            bundle=bundle,
            receiver=receiver,
            deadline=deadline,
            capture=capture,
            relay_factory=relay_factory,
        )
        host_result = _valid_host_result(
            host_result_path,
            operation_id=operation_id,
            bundle_digest=bundle_digest,
            claim_digest=claim_digest,
            file_count=file_count,
            inventory_digest=str(bundle_receipt["inventory_digest"]),
        )
        completed_status = _completed_status(
            fresh_status_path,
            recovery_status_path,
            invocation_path,
            recovery_path,
            claim_digest=claim_digest,
        )
    if host_result is None or completed_status is None:
        raise ValueError("run command transfer evidence is incomplete")

    result: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-transfer-receipt.v1",
        "state": "verified",
        "operation_id": operation_id,
        "target_binding": target["target_binding"],
        "approval_digest": approval_digest,
        "claim_digest": claim_digest,
        "bundle_digest": bundle_digest,
        "receiver_digest": receiver_digest,
        "host_result_digest": canonical_digest(host_result),
        "completion_status_digest": canonical_digest(completed_status),
        "host_transfer_verified": True,
        "host_download_cleanup_verified": True,
        "host_execution_retained": True,
        "relay_tls_pinned": True,
        "relay_source_address_verified": True,
        "relay_transient_material_cleanup_verified": True,
        "cloud_artifact_residue_created": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": True,
    }
    result["receipt_digest"] = canonical_digest(result)
    _require_work_directory_identity(work_dir, work_descriptor)
    if receipt_path.exists() or receipt_path.is_symlink():
        if _read(receipt_path, "run command transfer receipt") != result:
            raise ValueError("run command transfer receipt differs")
    else:
        _write_durable_private(
            work_descriptor,
            receipt_path.name,
            canonical_bytes(result),
        )
    return result


def _perform_invocation(
    *,
    mode: str,
    claim_path: Path,
    status_path: Path,
    host_result_path: Path,
    parameters: dict[str, object],
    target: dict[str, object],
    approval: dict[str, object],
    work_dir: Path,
    work_descriptor: int,
    bundle: Path,
    receiver: Path,
    deadline: DeploymentDeadline,
    capture: Capture,
    relay_factory: RelayFactory,
) -> None:
    relay = relay_factory(
        relay_host=str(target["relay_private_ip"]),
        relay_port=_required_int(target, "relay_port"),
        allowed_source=str(target["host_private_ip"]),
        operation_id=str(parameters["operation_id"]),
        bundle=bundle,
        bundle_digest=str(parameters["bundle_digest"]),
        receiver=receiver,
        receiver_digest=str(parameters["receiver_digest"]),
        require_bundle=mode == "fresh",
    )
    invocation_parameters = dict(parameters)
    invocation_parameters["recovery_mode"] = mode
    invocation_parameters["relay_certificate_digest"] = relay.certificate_digest
    validate_parameters(invocation_parameters)
    invocation_claim = invocation_claim_record(
        str(parameters["claim_digest"]), invocation_parameters, target
    )
    require_approval_current(approval)
    _write_durable_private(
        work_descriptor,
        claim_path.name,
        canonical_bytes(invocation_claim),
    )
    _require_work_directory_identity(work_dir, work_descriptor)
    try:
        relay.start()
        status = _invoke_host(
            invocation_parameters,
            target=target,
            deadline=deadline,
            capture=capture,
        )
        host_result_content = relay.result()
    finally:
        relay.close()
    _store_host_result(
        host_result_path,
        host_result_content,
        work_descriptor=work_descriptor,
    )
    _write_durable_private(
        work_descriptor,
        status_path.name,
        canonical_bytes(status),
    )


def _invoke_host(
    parameters: dict[str, object],
    *,
    target: dict[str, object],
    deadline: DeploymentDeadline,
    capture: Capture,
) -> dict[str, object]:
    invocation = load_json_object(
        capture(
            build_run_command(
                vm_resource_id=str(target["vm_resource_id"]),
                parameters=parameters,
            ),
            timeout=deadline.remaining(1800),
        ).encode(),
        label="run command response",
        max_bytes=1024 * 1024,
    )
    values = invocation.get("value")
    expected_codes = {
        "ComponentStatus/StdOut/succeeded",
        "ComponentStatus/StdErr/succeeded",
    }
    if (
        not isinstance(values, list)
        or len(values) != 2
        or {value.get("code") for value in values if isinstance(value, dict)} != expected_codes
        or any(not isinstance(value, dict) or value.get("level") != "Info" for value in values)
    ):
        raise ValueError("fixed Run Command status is invalid")
    messages: list[str] = []
    for value in values:
        if isinstance(value, dict):
            message = value.get("message")
            if isinstance(message, str):
                messages.append(message)
    if sum(message.count("FDAI_RUN_COMMAND_COMPLETED=true") for message in messages) != 1:
        raise ValueError("fixed Run Command did not report completed host cleanup")
    result: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-status.v1",
        "claim_digest": parameters["claim_digest"],
        "mode": parameters["recovery_mode"],
        "parameters_digest": canonical_digest(parameters),
        "host_cleanup_verified": True,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result


def _validate_invocation_claim(
    path: Path,
    *,
    claim_digest: str,
    parameters: dict[str, object],
    target: dict[str, object],
    expected_mode: str,
) -> None:
    retained = _read(path, "run command invocation claim")
    certificate_digest = retained.get("relay_certificate_digest")
    if not isinstance(certificate_digest, str) or DIGEST.fullmatch(certificate_digest) is None:
        raise ValueError("run command invocation claim is invalid")
    expected_parameters = dict(parameters)
    expected_parameters["recovery_mode"] = expected_mode
    expected_parameters["relay_certificate_digest"] = certificate_digest
    expected = invocation_claim_record(claim_digest, expected_parameters, target)
    if retained != expected:
        raise ValueError("run command invocation claim differs")


def _completed_status(
    fresh_path: Path,
    recovery_path: Path,
    fresh_claim_path: Path,
    recovery_claim_path: Path,
    *,
    claim_digest: str,
) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []
    for path, claim_path, mode in (
        (fresh_path, fresh_claim_path, "fresh"),
        (recovery_path, recovery_claim_path, "verify"),
    ):
        if not path.exists() and not path.is_symlink():
            continue
        value = _read(path, "run command completion status")
        invocation_claim = _read(claim_path, "run command invocation claim")
        digest = value.get("receipt_digest")
        document = {key: item for key, item in value.items() if key != "receipt_digest"}
        if (
            set(value)
            != {
                "schema_version",
                "claim_digest",
                "mode",
                "parameters_digest",
                "host_cleanup_verified",
                "mutation_performed",
                "receipt_digest",
            }
            or value.get("schema_version") != "fdai.run-command-private-relay-status.v1"
            or value.get("claim_digest") != claim_digest
            or value.get("mode") != mode
            or not isinstance(value.get("parameters_digest"), str)
            or DIGEST.fullmatch(str(value["parameters_digest"])) is None
            or value.get("parameters_digest") != invocation_claim.get("parameters_digest")
            or value.get("host_cleanup_verified") is not True
            or value.get("mutation_performed") is not False
            or digest != canonical_digest(document)
        ):
            raise ValueError("run command completion status is invalid")
        candidates.append(value)
    return candidates[-1] if candidates else None


def _valid_host_result(
    path: Path,
    **expected: object,
) -> dict[str, object] | None:
    if not path.exists() and not path.is_symlink():
        return None
    content = read_private_bytes(path, max_bytes=16_384)
    try:
        return validate_host_result(content, **expected)  # type: ignore[arg-type]
    except ValueError:
        quarantine = path.with_name(
            f"run-command-host-result.invalid-{hashlib.sha256(content).hexdigest()}.json"
        )
        if quarantine.exists() or quarantine.is_symlink():
            raise ValueError("run command invalid host result quarantine exists") from None
        os.rename(path, quarantine)
        return None


def _store_host_result(path: Path, content: bytes, *, work_descriptor: int) -> None:
    if path.exists() or path.is_symlink():
        retained = read_private_bytes(path, max_bytes=16_384)
        if retained != content:
            raise ValueError("run command host result differs")
        return
    _write_durable_private(work_descriptor, path.name, content)


def _validate_bundle_receipt(receipt: dict[str, object]) -> None:
    digest = receipt.get("receipt_digest")
    document = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    bundle_size = _optional_int(receipt.get("bundle_size"))
    file_count = _optional_int(receipt.get("file_count"))
    if (
        set(receipt)
        != {
            "schema_version",
            "state",
            "operation_id",
            "bundle_digest",
            "bundle_size",
            "file_count",
            "inventory_digest",
            "apply_authorized",
            "deployment_ready",
            "mutation_performed",
            "receipt_digest",
        }
        or receipt.get("schema_version") != "fdai.execution-bundle-receipt.v1"
        or receipt.get("state") != "prepared"
        or not isinstance(receipt.get("operation_id"), str)
        or OPERATION.fullmatch(str(receipt["operation_id"])) is None
        or not isinstance(receipt.get("bundle_digest"), str)
        or DIGEST.fullmatch(str(receipt["bundle_digest"])) is None
        or bundle_size is None
        or not 0 < bundle_size <= MAX_BUNDLE_BYTES
        or file_count is None
        or not 0 < file_count <= 20_000
        or not isinstance(receipt.get("inventory_digest"), str)
        or DIGEST.fullmatch(str(receipt["inventory_digest"])) is None
        or receipt.get("apply_authorized") is not False
        or receipt.get("deployment_ready") is not False
        or receipt.get("mutation_performed") is not False
        or digest != canonical_digest(document)
    ):
        raise ValueError("run command bundle receipt is invalid")


def _private_directory(path: Path) -> int:
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("run command transport work directory must be current-UID mode 0700")
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino):
        os.close(descriptor)
        raise PermissionError("run command transport work directory changed")
    return descriptor


def _acquire_work_lock(descriptor: int) -> None:
    details = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("run command transport lock is invalid")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise ValueError("run command transport is already active") from exc


def _require_work_directory_identity(path: Path, descriptor: int) -> None:
    retained = os.fstat(descriptor)
    current = path.lstat()
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
        retained.st_dev,
        retained.st_ino,
    ):
        raise ValueError("run command transport work directory identity changed")


def _private_digest(path: Path, *, maximum: int) -> str:
    return hashlib.sha256(read_private_bytes(path, max_bytes=maximum)).hexdigest()


def _write_durable_private(directory_descriptor: int, name: str, content: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_descriptor,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_descriptor)
    finally:
        os.close(descriptor)


def _required_int(values: dict[str, object], key: str) -> int:
    value = _optional_int(values.get(key))
    if value is None:
        raise ValueError(f"run command {key} must be an integer")
    return value


def _optional_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _read(path: Path, label: str) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=1024 * 1024),
        label=label,
        max_bytes=1024 * 1024,
    )


def capture(command: tuple[str, ...], *, timeout: int) -> str:
    """Run one bounded Azure CLI checkpoint with sanitized failure output."""

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("run command transport checkpoint failed") from exc
    if len(completed.stdout) > 1024 * 1024:
        raise ValueError("run command transport response exceeds its limit")
    return completed.stdout

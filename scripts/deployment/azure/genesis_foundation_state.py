#!/usr/bin/env python3
"""Migrate exact Foundation state to its private backend through Bastion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import genesis_foundation_apply as foundation_apply
import genesis_foundation_state_contract as state_contract
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.state_handoff import compare_foundation_state
from genesis_bastion import BastionTunnel, validate_known_hosts, validate_ssh_private_key
from genesis_checks import CheckError, GenesisChecks
from genesis_foundation_state_archive import create_foundation_state_archive

ENROLLMENT_RECEIPT_NAME = "runner-enrollment-receipt.json"
KNOWN_HOSTS_NAME = "runner-known-hosts"
CLAIM_NAME = "foundation-state-handoff-claim.json"
AUTHORITY_NAME = "foundation-state-authority.json"
RECEIPT_NAME = "foundation-state-handoff-receipt.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class RetrievedEvidence:
    """Private remote-state bytes plus their parsed comparison objects."""

    remote_state: dict[str, object]
    remote_plan: dict[str, object]
    observation: dict[str, object]
    remote_state_bytes: bytes
    remote_plan_bytes: bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-plan-directory", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--variables-file", type=Path, required=True)
    parser.add_argument("--offline-kit", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--bundle-public-key", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ssh-private-key", type=Path, required=True)
    parser.add_argument("--expected-foundation-receipt-digest", required=True)
    parser.add_argument("--expected-enrollment-receipt-digest", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--resume-verification", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def _execute(args: argparse.Namespace) -> dict[str, object]:
    _validate_arguments(args)
    root = _repository_root()
    directory = _absolute(args.foundation_plan_directory)
    profile_path = _absolute(args.profile)
    profile = load_profile(profile_path)
    if profile.access_method != "bastion":
        raise ValueError("Foundation state handoff requires the reviewed Bastion profile")
    foundation = state_contract.load_receipt(
        directory / foundation_apply.RECEIPT_NAME,
        schema="fdai.genesis-foundation-apply-receipt.v1",
        expected_digest=args.expected_foundation_receipt_digest,
    )
    enrollment = state_contract.load_receipt(
        directory / ENROLLMENT_RECEIPT_NAME,
        schema="fdai.genesis-runner-enrollment-receipt.v1",
        expected_digest=args.expected_enrollment_receipt_digest,
    )
    handoff = _private_json(
        directory / foundation_apply.HANDOFF_NAME, label="Foundation private handoff"
    )
    state_contract.validate_context(profile.target_binding, foundation, enrollment, handoff)
    state = _object(handoff["state"], "Foundation state handoff")
    runner = _object(handoff["runner"], "Foundation runner handoff")
    access = _object(handoff["access"], "Foundation access handoff")
    ops = _object(handoff["ops"], "Foundation operations handoff")
    connection = _connection(runner, access, ops)
    private_key = _absolute(args.ssh_private_key)
    if validate_ssh_private_key(private_key) != runner.get("ssh_key_digest"):
        raise ValueError("runner SSH private key does not match the Foundation handoff")
    known_hosts = directory / KNOWN_HOSTS_NAME
    validate_known_hosts(known_hosts)

    checks = GenesisChecks(root)
    checks.verify_target(
        subscription_id=str(handoff["subscription_id"]),
        tenant_id=str(handoff["tenant_id"]),
        region=str(handoff["region"]),
    )
    checks.verify_source(
        source_commit=str(handoff["source_commit"]), repository=args.repository, apply=True
    )

    backend_key = _required_text(state, "foundation_key")
    work_id = canonical_digest(
        {
            "foundation_receipt_digest": foundation["receipt_digest"],
            "enrollment_receipt_digest": enrollment["receipt_digest"],
            "backend_key_digest": hashlib.sha256(backend_key.encode()).hexdigest(),
        }
    )
    local_state = state_contract.local_state_path(directory, foundation)
    archive = directory / f"foundation-state-handoff-{work_id[:12]}.tar.gz"
    claim_path = directory / CLAIM_NAME
    authority_path = directory / AUTHORITY_NAME
    receipt_path = directory / RECEIPT_NAME
    claim = state_contract.load_claim(claim_path)
    if receipt_path.exists():
        if claim is None:
            raise ValueError("Foundation state handoff receipt is missing its immutable claim")
        state_contract.validate_claim(claim, foundation, enrollment, work_id)
        receipt = state_contract.load_receipt(
            receipt_path,
            schema="fdai.genesis-foundation-state-handoff-receipt.v1",
            expected_digest=None,
        )
        authority = state_contract.load_authority(authority_path)
        if authority is None:
            raise ValueError("Foundation state handoff receipt is missing backend authority")
        state_contract.validate_final_receipt(
            receipt,
            foundation,
            enrollment,
            authority,
            claim,
            work_id,
        )
        state_contract.validate_authority(
            authority,
            foundation,
            enrollment,
            claim,
            work_id,
        )
        _reobserve_remote_authority(
            directory=directory,
            handoff=handoff,
            runner=runner,
            state=state,
            ops=ops,
            connection=connection,
            private_key=private_key,
            known_hosts=known_hosts,
            work_id=work_id,
            archive_digest=_required_text(receipt, "archive_digest"),
            expected_state_digest=_required_text(authority, "state_digest"),
            timeout=args.timeout_seconds,
        )
        return receipt

    authority = state_contract.load_authority(authority_path)
    if args.resume_verification:
        if claim is None:
            raise ValueError("Foundation state verification resume requires an existing claim")
        state_contract.validate_claim(claim, foundation, enrollment, work_id)
    elif claim is not None:
        raise ValueError("Foundation state handoff claim exists; only verification may resume")
    elif authority is not None:
        raise ValueError("Foundation state authority exists without its immutable claim")

    if authority is None:
        if claim is None:
            _unlink_private_if_present(archive, max_bytes=1024 * 1024 * 1024)
            archive_result = _prepare_archive(
                args=args,
                directory=directory,
                profile_path=profile_path,
                foundation=foundation,
                handoff=handoff,
                archive=archive,
                local_state=local_state,
            )
            archive_digest = str(archive_result["archive_digest"])
        else:
            archive_digest = _required_text(claim, "archive_digest")
    else:
        if claim is None:
            raise ValueError("Foundation state authority is missing its immutable claim")
        state_contract.validate_authority(authority, foundation, enrollment, claim, work_id)
        archive_digest = _required_text(authority, "archive_digest")

    remote_archive = f"/home/{connection['username']}/.fdai-transfer-{work_id[:24]}.tar.gz"
    remote_work = f"/home/{connection['username']}/.fdai-state-handoff/{work_id[:24]}"
    remote_arguments = _remote_arguments(
        archive=remote_archive,
        work_id=work_id,
        archive_digest=archive_digest,
        handoff=handoff,
        state=state,
        runner=runner,
        ops=ops,
        expected_state_digest=_required_text(foundation, "state_digest"),
    )
    host_alias = (
        "fdai-genesis-" + hashlib.sha256(connection["vm_id"].casefold().encode()).hexdigest()[:16]
    )
    with BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=connection["resource_group"],
        bastion_name=connection["bastion_name"],
        vm_id=connection["vm_id"],
        username=connection["username"],
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=directory,
        timeout=args.timeout_seconds,
        trust_new_host_key=False,
    ) as tunnel:
        if authority is None:
            if claim is None:
                preflight = tunnel.ssh(
                    (
                        "/usr/bin/test",
                        "-x",
                        "/usr/local/sbin/fdai-migrate-foundation-state",
                    ),
                    timeout=60,
                )
                archive_absent = tunnel.ssh(
                    ("/usr/bin/test", "!", "-e", remote_archive), timeout=60
                )
                work_absent = tunnel.ssh(("/usr/bin/test", "!", "-e", remote_work), timeout=60)
                if any(
                    result.returncode != 0 for result in (preflight, archive_absent, work_absent)
                ):
                    raise ValueError("Foundation remote state preflight is not clean")
                claim = state_contract.create_claim(
                    foundation=foundation,
                    enrollment=enrollment,
                    work_id=work_id,
                    archive_digest=archive_digest,
                    state_digest=_required_text(foundation, "state_digest"),
                    backend_key=backend_key,
                    actor_digest=_operator_digest(checks, profile.target_binding),
                )
                write_private_output(
                    claim_path,
                    json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
                )
                tunnel.copy_to(archive, remote_archive, timeout=min(600, args.timeout_seconds))
                mode = "migrate"
            else:
                mode = "verify"
            result = tunnel.ssh(
                (
                    "/usr/local/sbin/fdai-migrate-foundation-state",
                    mode,
                    *remote_arguments,
                ),
                timeout=args.timeout_seconds,
            )
            marker = f"state_handoff_complete work_ref={work_id[:24]}"
            if result.returncode != 0 or marker not in result.stdout.splitlines():
                raise ValueError("Foundation remote state handoff did not complete")
            evidence = _retrieve_evidence(tunnel, directory, remote_work, work_id)
            comparison = compare_foundation_state(
                _read_json_object(local_state, label="Foundation local state"),
                evidence.remote_state,
                evidence.remote_plan,
            )
            _validate_remote_observation(
                evidence.observation,
                work_id=work_id,
                archive_digest=archive_digest,
                remote_state=evidence.remote_state_bytes,
                remote_plan=evidence.remote_plan_bytes,
            )
            if claim is None:
                raise ValueError("Foundation state claim was not persisted before migration")
            authority = state_contract.create_authority(
                foundation=foundation,
                enrollment=enrollment,
                claim=claim,
                work_id=work_id,
                archive_digest=archive_digest,
                comparison=comparison,
                observation=evidence.observation,
                backend_key=backend_key,
            )
            write_private_output(
                authority_path,
                json.dumps(authority, sort_keys=True, separators=(",", ":")) + "\n",
            )
            _remove_evidence_files(directory, work_id)
        else:
            if claim is None:
                raise ValueError("Foundation state authority is missing its immutable claim")
            state_contract.validate_authority(authority, foundation, enrollment, claim, work_id)

        _delete_local_state_if_present(
            local_state, expected_digest=_required_text(foundation, "state_digest")
        )
        cleanup = tunnel.ssh(
            (
                "/usr/local/sbin/fdai-migrate-foundation-state",
                "cleanup",
                *remote_arguments,
            ),
            timeout=300,
        )
        cleanup_marker = f"state_handoff_cleanup_complete work_ref={work_id[:24]}"
        if cleanup.returncode != 0 or cleanup_marker not in cleanup.stdout.splitlines():
            raise ValueError("Foundation remote state transient cleanup failed")

    _unlink_private_if_present(archive, max_bytes=1024 * 1024 * 1024)
    if authority is None:
        raise ValueError("Foundation backend authority was not recorded")
    completed_at = _utc_now().replace(microsecond=0).isoformat()
    final_receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-state-handoff-receipt.v1",
        "state": "verified",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "enrollment_receipt_digest": enrollment["receipt_digest"],
        "target_binding": foundation["target_binding"],
        "source_commit": foundation["source_commit"],
        "work_id": work_id,
        "archive_digest": archive_digest,
        "authority_digest": authority["authority_digest"],
        "claim_digest": authority["claim_digest"],
        "actor_digest": authority["actor_digest"],
        "state_digest": authority["state_digest"],
        "managed_resource_count": authority["managed_resource_count"],
        "remote_backend_authority_verified": True,
        "zero_change_verified": True,
        "local_state_deletion_authorized": True,
        "local_state_deleted": True,
        "remote_transient_deleted": True,
        "runner_attested": True,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": completed_at,
    }
    final_receipt["receipt_digest"] = canonical_digest(final_receipt)
    write_private_output(
        receipt_path,
        json.dumps(final_receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return final_receipt


def _prepare_archive(
    *,
    args: argparse.Namespace,
    directory: Path,
    profile_path: Path,
    foundation: Mapping[str, object],
    handoff: Mapping[str, object],
    archive: Path,
    local_state: Path,
) -> dict[str, object]:
    if not local_state.is_file():
        raise ValueError("Foundation local recovery state is unavailable before migration")
    review = foundation_apply._foundation_review(directory)
    context = _object(review.get("context"), "Foundation review context")
    normalized = directory / ".foundation-state-input.json"
    normalized.unlink(missing_ok=True)
    foundation_apply._foundation_target(
        variables_path=_absolute(args.variables_file),
        profile_path=profile_path,
        destination=normalized,
        expected_context=context,
    )
    snapshot = foundation_apply._prepare_verified_snapshot(
        plan_directory=directory,
        offline_kit=_absolute(args.offline_kit),
        release_root=_absolute(args.release_root),
        bundle_public_key=_absolute(args.bundle_public_key),
        context=context,
    )
    try:
        if snapshot.infra_root / "terraform.tfstate" != local_state:
            raise ValueError("Foundation local state reference does not match the verified root")
        return create_foundation_state_archive(
            terraform_root=snapshot.infra_root,
            provider_mirror=snapshot.mirror,
            variables_file=normalized,
            destination=archive,
            source_commit=str(handoff["source_commit"]),
            expected_state_digest=str(foundation["state_digest"]),
        )
    finally:
        snapshot.cleanup()
        normalized.unlink(missing_ok=True)


def _remote_arguments(
    *,
    archive: str,
    work_id: str,
    archive_digest: str,
    handoff: Mapping[str, object],
    state: Mapping[str, object],
    runner: Mapping[str, object],
    ops: Mapping[str, object],
    expected_state_digest: str,
) -> tuple[str, ...]:
    return (
        "--archive",
        archive,
        "--archive-digest",
        archive_digest,
        "--work-id",
        work_id,
        "--subscription-id",
        _required_text(handoff, "subscription_id"),
        "--tenant-id",
        _required_text(handoff, "tenant_id"),
        "--client-id",
        _required_text(runner, "client_id"),
        "--principal-id",
        _required_text(runner, "principal_id"),
        "--state-account-id",
        _required_text(state, "account_id"),
        "--resource-group",
        _required_text(ops, "resource_group_name"),
        "--account-name",
        _required_text(state, "account_name"),
        "--container-name",
        _required_text(state, "container_name"),
        "--backend-key",
        _required_text(state, "foundation_key"),
        "--expected-state-digest",
        expected_state_digest,
    )


def _reobserve_remote_authority(
    *,
    directory: Path,
    handoff: Mapping[str, object],
    runner: Mapping[str, object],
    state: Mapping[str, object],
    ops: Mapping[str, object],
    connection: Mapping[str, str],
    private_key: Path,
    known_hosts: Path,
    work_id: str,
    archive_digest: str,
    expected_state_digest: str,
    timeout: int,
) -> None:
    remote_archive = f"/home/{connection['username']}/.fdai-transfer-{work_id[:24]}.tar.gz"
    remote_arguments = _remote_arguments(
        archive=remote_archive,
        work_id=work_id,
        archive_digest=archive_digest,
        handoff=handoff,
        state=state,
        runner=runner,
        ops=ops,
        expected_state_digest=expected_state_digest,
    )
    host_alias = (
        "fdai-genesis-" + hashlib.sha256(connection["vm_id"].casefold().encode()).hexdigest()[:16]
    )
    with BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=connection["resource_group"],
        bastion_name=connection["bastion_name"],
        vm_id=connection["vm_id"],
        username=connection["username"],
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=directory,
        timeout=timeout,
        trust_new_host_key=False,
    ) as tunnel:
        result = tunnel.ssh(
            (
                "/usr/local/sbin/fdai-migrate-foundation-state",
                "observe",
                *remote_arguments,
            ),
            timeout=timeout,
        )
        marker = f"state_handoff_observation_complete work_ref={work_id[:24]}"
        if result.returncode != 0 or marker not in result.stdout.splitlines():
            raise ValueError("Foundation remote state authority re-observation failed")


def _validate_arguments(args: argparse.Namespace) -> None:
    if args.approve == args.resume_verification:
        raise ValueError("Foundation state handoff requires exactly one approval or resume mode")
    if _REPOSITORY.fullmatch(args.repository) is None:
        raise ValueError("Foundation state repository is invalid")
    if any(
        _DIGEST.fullmatch(value) is None
        for value in (
            args.expected_foundation_receipt_digest,
            args.expected_enrollment_receipt_digest,
        )
    ):
        raise ValueError("Foundation state expected receipt digest is invalid")
    if not 900 <= args.timeout_seconds <= 7200:
        raise ValueError("Foundation state timeout must be from 900 through 7200 seconds")


def _connection(
    runner: Mapping[str, object], access: Mapping[str, object], ops: Mapping[str, object]
) -> dict[str, str]:
    values = {
        "resource_group": ops.get("resource_group_name"),
        "bastion_name": access.get("bastion_name"),
        "vm_id": runner.get("vm_id"),
        "username": runner.get("admin_username"),
    }
    if access.get("method") != "bastion" or any(
        not isinstance(value, str) or not value for value in values.values()
    ):
        raise ValueError("Foundation state handoff requires exact Bastion access")
    return {key: str(value) for key, value in values.items()}


def _retrieve_evidence(
    tunnel: BastionTunnel, directory: Path, remote_work: str, work_id: str
) -> RetrievedEvidence:
    paths = {
        "remote_state": directory / f"remote-state-{work_id[:12]}.json",
        "remote_plan": directory / f"remote-plan-{work_id[:12]}.json",
        "observation": directory / f"remote-observation-{work_id[:12]}.json",
    }
    for path in paths.values():
        _unlink_private_if_present(path, max_bytes=64 * 1024 * 1024)
    tunnel.copy_from(f"{remote_work}/remote-state.json", paths["remote_state"], timeout=300)
    tunnel.copy_from(f"{remote_work}/remote-plan.json", paths["remote_plan"], timeout=300)
    tunnel.copy_from(f"{remote_work}/observation.json", paths["observation"], timeout=120)
    state_bytes = read_private_bytes(paths["remote_state"], max_bytes=64 * 1024 * 1024)
    plan_bytes = read_private_bytes(paths["remote_plan"], max_bytes=64 * 1024 * 1024)
    return RetrievedEvidence(
        remote_state=_json_object(state_bytes, label="Foundation remote state"),
        remote_plan=_json_object(plan_bytes, label="Foundation remote plan"),
        observation=_private_json(paths["observation"], label="remote state observation"),
        remote_state_bytes=state_bytes,
        remote_plan_bytes=plan_bytes,
    )


def _validate_remote_observation(
    observation: Mapping[str, object],
    *,
    work_id: str,
    archive_digest: str,
    remote_state: bytes,
    remote_plan: bytes,
) -> None:
    if (
        observation.get("schema_version") != "fdai.genesis-foundation-remote-state-observation.v1"
        or observation.get("state") != "verified"
        or observation.get("work_id") != work_id
        or observation.get("archive_digest") != archive_digest
        or observation.get("remote_state_digest") != hashlib.sha256(remote_state).hexdigest()
        or observation.get("remote_plan_digest") != hashlib.sha256(remote_plan).hexdigest()
        or observation.get("managed_identity_verified") is not True
        or observation.get("backend_protection_verified") is not True
        or observation.get("backend_blob_verified") is not True
        or observation.get("zero_change_verified") is not True
    ):
        raise ValueError("Foundation remote state observation is invalid")


def _delete_local_state_if_present(path: Path, *, expected_digest: str) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("Foundation local recovery state is not a regular file")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (
            opened.st_dev != current.st_dev
            or opened.st_ino != current.st_ino
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or digest.hexdigest() != expected_digest
        ):
            raise ValueError("Foundation local recovery state changed before deletion")
        os.unlink(path.name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def _remove_evidence_files(directory: Path, work_id: str) -> None:
    for name in ("remote-state", "remote-plan"):
        _unlink_private_if_present(
            directory / f"{name}-{work_id[:12]}.json", max_bytes=64 * 1024 * 1024
        )


def _unlink_private_if_present(path: Path, *, max_bytes: int) -> None:
    try:
        read_private_bytes(path, max_bytes=max_bytes)
    except FileNotFoundError:
        return
    path.unlink()


def _private_json(path: Path, *, label: str) -> dict[str, object]:
    return _json_object(read_private_bytes(path, max_bytes=16 * 1024 * 1024), label=label)


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    return _json_object(read_private_bytes(path, max_bytes=64 * 1024 * 1024), label=label)


def _json_object(value: bytes, *, label: str) -> dict[str, object]:
    result = json.loads(value)
    if not isinstance(result, dict) or any(not isinstance(key, str) for key in result):
        raise ValueError(f"{label} is invalid")
    return {key: item for key, item in result.items()}


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {key: item for key, item in value.items()}


def _required_text(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Foundation state handoff {name} is invalid")
    return item


def _operator_digest(checks: GenesisChecks, target_binding: str) -> str:
    raw = checks.capture(
        (
            "az",
            "account",
            "show",
            "--query",
            "{type:user.type,name:user.name}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        "foundation_state_operator_unavailable",
        timeout=30,
    )
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("type") != "user"
        or not isinstance(value.get("name"), str)
        or not value["name"]
    ):
        raise ValueError("Foundation state handoff requires a human Azure operator")
    return hashlib.sha256(f"{target_binding}:{value['name'].casefold()}".encode()).hexdigest()


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint


def _print(result: Mapping[str, object], output: str) -> None:
    safe = {
        key: result[key]
        for key in (
            "schema_version",
            "state",
            "managed_resource_count",
            "remote_backend_authority_verified",
            "zero_change_verified",
            "local_state_deleted",
            "remote_transient_deleted",
            "effect_verified",
            "subscription_ready",
            "receipt_digest",
        )
    }
    if output == "json":
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    else:
        print("Foundation state migrated, compared, and cleaned after backend authority")


def main(argv: Sequence[str] | None = None) -> int:
    """Run a one-time state migration or verification-only continuation."""

    args = _parser().parse_args(argv)
    try:
        result = _execute(args)
        _print(result, args.output)
        return 0
    except (
        CheckError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        reason = exc.reason_code if isinstance(exc, CheckError) else str(exc)
        print(f"genesis-foundation-state: {reason}", file=sys.stderr)
        return exc.exit_code if isinstance(exc, CheckError) else 3


if __name__ == "__main__":
    raise SystemExit(main())

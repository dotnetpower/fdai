"""Transfer verified source to the enrolled host under the caller's Foundation execution lock."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

import genesis_foundation_state_contract as state_contract
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.deadline_transport import DeadlineTransport
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_receiver import prepare_source_receiver
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.source_transport import prepare_source_transport
from genesis_bastion import BastionTunnel, validate_known_hosts, validate_ssh_private_key
from genesis_runner_enrollment import _attest_runner

if TYPE_CHECKING:
    from genesis_foundation_recovery_state import RecoveryMigration


def transfer_application_source(
    *,
    foundation_root: Path,
    snapshot: Path,
    snapshot_digest: str,
    source_commit: str,
    target_binding: str,
    report: dict[str, object] | None,
    timeout_seconds: int,
    recovery: RecoveryMigration | None = None,
) -> dict[str, object]:
    """Verify the complete handoff and current host before a claimed source-only transfer.

    The caller must hold the exact source run's execution lock and have verified current
    human target, source CI and Foundation state authority. This command does not apply
    infrastructure, install dependencies, build images, or activate the application.
    Interrupted transfers permit verification only, never automatic replacement or retry.
    A recovered Foundation supplies its verified migration context under the same original
    lock after independent backend observation; no ordinary apply receipt is substituted.
    """
    deadline = DeploymentDeadline(timeout_seconds)
    report = _object(report)
    if recovery is None:
        plan_ref = _object(report.get("foundation_plan")).get("plan_ref")
        if (
            not isinstance(plan_ref, str)
            or re.fullmatch(r"foundation-plan-attempt-[1-9][0-9]*", plan_ref) is None
        ):
            raise ValueError("source transfer requires an exact Foundation plan reference")
        directory = foundation_root / plan_ref
    else:
        recovery.verify_configuration()
        if (
            recovery.original_directory.parent != foundation_root
            or recovery.recovered.receipt.get("source_commit") != source_commit
            or recovery.recovered.target_binding != target_binding
        ):
            raise ValueError("source transfer recovery context differs from the original run")
        directory = recovery.directory
    state = state_contract.load_receipt(
        directory / "foundation-state-handoff-receipt.json",
        schema="fdai.genesis-foundation-state-handoff-receipt.v1",
        expected_digest=_digest(_object(report.get("state_handoff")).get("receipt_digest")),
    )
    if (
        state.get("state") != "verified"
        or state.get("source_commit") != source_commit
        or state.get("target_binding") != target_binding
        or any(
            state.get(key) is not True
            for key in (
                "effect_verified",
                "runner_attested",
                "remote_backend_authority_verified",
                "zero_change_verified",
                "remote_transient_deleted",
                "local_state_deleted",
            )
        )
    ):
        raise ValueError("source transfer Foundation state is not verified")
    if recovery is None:
        foundation = state_contract.load_receipt(
            directory / "foundation-apply-receipt.json",
            schema="fdai.genesis-foundation-apply-receipt.v1",
            expected_digest=_digest(state.get("foundation_receipt_digest")),
        )
        handoff = _read(directory / "foundation-private-handoff.json")
        if foundation.get("effect_verified") is not True:
            raise ValueError("source transfer Foundation source or effect differs")
    else:
        recovery.validate_record(state)
        foundation, handoff = recovery.foundation, recovery.recovered.handoff
        if foundation["receipt_digest"] != state.get("foundation_receipt_digest"):
            raise ValueError("source transfer recovery receipt differs from state handoff")
    enrollment = state_contract.load_receipt(
        directory / "runner-enrollment-receipt.json",
        schema="fdai.genesis-runner-enrollment-receipt.v1",
        expected_digest=_digest(state.get("enrollment_receipt_digest")),
    )
    state_contract.validate_context(target_binding, foundation, enrollment, handoff)
    if foundation.get("source_commit") != source_commit:
        raise ValueError("source transfer Foundation source or effect differs")
    runner, access, ops = (_object(handoff.get(key)) for key in ("runner", "access", "ops"))
    username = runner.get("admin_username")
    if (
        access.get("method") != "bastion"
        or runner.get("execution_transport") != "manual"
        or not isinstance(username, str)
        or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) is None
    ):
        raise ValueError("source transfer requires the exact enrolled manual Bastion host")
    known_hosts = directory / "runner-known-hosts"
    private_key = foundation_root / "runner_ed25519"
    validate_known_hosts(known_hosts)
    if hashlib.sha256(
        read_private_bytes(known_hosts, max_bytes=65536)
    ).hexdigest() != enrollment.get("host_key_digest") or validate_ssh_private_key(
        private_key
    ) != runner.get("ssh_key_digest"):
        raise ValueError("source transfer SSH identity differs from enrollment")
    source = verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
    if source.get("source_commit") != source_commit:
        raise ValueError("source transfer snapshot differs from the approved source")
    work = foundation_root.parent
    transfer = prepare_source_transport(snapshot, work, snapshot_digest=snapshot_digest)
    receiver_digest = prepare_source_receiver(snapshot, work, snapshot_digest=snapshot_digest)
    deadline.remaining()
    context = {
        "source_commit": source_commit,
        "target_binding": target_binding,
        "snapshot_digest": snapshot_digest,
        "archive_digest": transfer["archive_digest"],
        "receiver_digest": receiver_digest,
        "state_handoff_digest": state["receipt_digest"],
    }
    claim = {"schema_version": "fdai.source-host-transfer-claim.v1", **context}
    claim_path = work / "source-host-transfer-claim.json"
    verification_only = claim_path.exists() or claim_path.is_symlink()
    if verification_only and _read(claim_path) != claim:
        raise ValueError("source transfer claim differs; preserve retained evidence")
    remote_root = f"/home/{username}/.fdai-transfer-{canonical_digest(claim)[:24]}"
    remote_receiver = f"{remote_root}/source-receiver.pyz"
    remote_archive = f"{remote_root}/source-transfer.tar"
    vm_id = _text(runner, "vm_id")
    with BastionTunnel(
        subscription_id=_text(handoff, "subscription_id"),
        resource_group=_text(ops, "resource_group_name"),
        bastion_name=_text(access, "bastion_name"),
        vm_id=vm_id,
        username=username,
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias="fdai-genesis-" + hashlib.sha256(vm_id.casefold().encode()).hexdigest()[:16],
        cwd=directory,
        timeout=deadline.remaining(),
        trust_new_host_key=False,
    ) as underlying:
        tunnel = DeadlineTransport(underlying, deadline)
        _attest_runner(
            underlying,
            handoff=handoff,
            runner=runner,
            timeout=deadline.remaining(),
            transport="manual",
        )
        deadline.remaining()
        if not verification_only:
            write_private_bytes(claim_path, canonical_bytes(claim))
            created = tunnel.ssh(("mkdir", "-m", "0700", "--", remote_root), timeout=60)
            if created.returncode != 0:
                raise ValueError("source transfer destination is not fresh; preserve the claim")
            tunnel.copy_to(work / "source-receiver.pyz", remote_receiver, timeout=120)
            tunnel.copy_to(work / "source-transfer.tar", remote_archive, timeout=1800)
        observed = tunnel.ssh(("sha256sum", "--", remote_receiver), timeout=60)
        if (
            observed.returncode != 0
            or observed.stdout.strip() != f"{receiver_digest}  {remote_receiver}"
        ):
            raise ValueError("source receiver bootstrap hash differs; no source was executed")
        received = tunnel.ssh(
            (
                "python3",
                "-I",
                remote_receiver,
                "--archive",
                remote_archive,
                "--destination",
                f"{remote_root}/source-snapshot",
                "--archive-digest",
                str(transfer["archive_digest"]),
                "--snapshot-digest",
                snapshot_digest,
                *(("--verify-existing",) if verification_only else ()),
            ),
            timeout=1800,
        )
        if received.returncode != 0:
            raise ValueError(
                "source receiver failed; retain the claim and verify without retransmission"
            )
        receipt = load_json_object(
            received.stdout.encode("utf-8"), label="remote source receiver", max_bytes=16384
        )
        expected = {
            key: value
            for key, value in transfer.items()
            if key
            not in (
                "archive_ref",
                "state",
                "remote_transfer_verified",
                "receipt_digest",
            )
        }
        if receipt != expected:
            raise ValueError(
                "remote source receipt differs from independently verified local evidence"
            )
    deadline.remaining()
    result = {
        "schema_version": "fdai.source-host-transfer-receipt.v1",
        "state": "verified",
        **context,
        "receiver_receipt_digest": canonical_digest(receipt),
        "remote_transfer_verified": True,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    receipt_path = work / "source-host-transfer-receipt.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        if _read(receipt_path) != result:
            raise ValueError("source host transfer receipt changed; preserve the run")
    else:
        write_private_bytes(receipt_path, canonical_bytes(result))
    return result


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("source transfer requires complete Foundation objects")
    return value


def _read(path: Path) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=1024 * 1024),
        label="source transfer evidence",
        max_bytes=1024 * 1024,
    )


def _digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("source transfer requires exact evidence digests")
    return value


def _text(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if (
        not isinstance(result, str)
        or not result
        or any(character.isspace() for character in result)
    ):
        raise ValueError("source transfer connection evidence is invalid")
    return result

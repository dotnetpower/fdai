"""Adopt one verified recovered Foundation without repeating its effects."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import (
    ProvisionProfile,
    canonical_bytes,
    canonical_digest,
    load_json_object,
)
from fdai_deployment_cli.foundation_adoption_evidence import (
    validate_foundation_adoption_receipt,
    verify_foundation_chain,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.target import compute_target_binding

_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_PLAN_REF = "foundation-adoption"


@dataclass(frozen=True, slots=True)
class AdoptedGenesisContext:
    """Prepared fields consumed by the existing standalone application coordinator."""

    root: Path
    profile: Path
    ssh_private_key: Path
    source_commit: str
    target_binding: str
    run_binding: str
    kit_manifest_digest: str


@dataclass(frozen=True, slots=True)
class FoundationAdoption:
    """Staged no-effect Foundation context and its immutable evidence."""

    prepared: AdoptedGenesisContext
    status: dict[str, object]
    receipt: dict[str, object]


def stage_recovered_foundation(
    *,
    foundation_directory: Path,
    recovery_directory: Path,
    destination: Path,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> FoundationAdoption:
    """Verify and stage a recovered Foundation for a separately approved application.

    The source Foundation remains the only owner of its backend and resources. This
    boundary copies only immutable handoff and access evidence into a new private
    application context. It never plans, applies, migrates, enrolls, or reclaims state.
    """

    _validate_inputs(
        foundation_directory=foundation_directory,
        recovery_directory=recovery_directory,
        destination=destination,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    _require_private_directory(foundation_directory)
    _require_private_directory(recovery_directory)
    _create_or_validate_private_directory(destination)
    plan_directory = destination / _PLAN_REF
    _create_or_validate_private_directory(plan_directory)
    evidence_directory = plan_directory / "evidence"
    _create_or_validate_private_directory(evidence_directory)

    profile_bytes = read_private_bytes(foundation_directory / "profile.json", max_bytes=65_536)
    profile = ProvisionProfile.from_mapping(
        load_json_object(profile_bytes, label="adopted Foundation profile")
    )
    private_key = read_private_bytes(foundation_directory / "runner_ed25519", max_bytes=65_536)
    handoff_bytes, handoff = _read_record(
        recovery_directory / "recovery-private-handoff.json",
        label="recovered Foundation handoff",
    )
    recovery_bytes, recovery = _read_receipt(
        recovery_directory / "recovery-apply-receipt.json",
        label="Foundation recovery receipt",
        digest_field="receipt_digest",
    )
    enrollment_bytes, enrollment = _read_receipt(
        recovery_directory / "runner-enrollment-receipt.json",
        label="Foundation enrollment receipt",
        digest_field="receipt_digest",
    )
    state_bytes, state_receipt = _read_receipt(
        recovery_directory / "foundation-state-handoff-receipt.json",
        label="Foundation state handoff receipt",
        digest_field="receipt_digest",
    )
    authority_bytes, authority = _read_receipt(
        recovery_directory / "foundation-state-authority.json",
        label="Foundation state authority",
        digest_field="authority_digest",
    )
    known_hosts = read_private_bytes(recovery_directory / "runner-known-hosts", max_bytes=262_144)

    receipt = build_foundation_adoption_receipt(
        profile=profile,
        handoff=handoff,
        recovery=recovery,
        enrollment=enrollment,
        state_receipt=state_receipt,
        authority=authority,
        known_hosts=known_hosts,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    target_binding = str(receipt["target_binding"])
    adopted_run_binding = str(receipt["adopted_run_binding"])

    staged = {
        destination / "profile.json": profile_bytes,
        destination / "runner_ed25519": private_key,
        plan_directory / "foundation-private-handoff.json": handoff_bytes,
        plan_directory / "runner-known-hosts": known_hosts,
        evidence_directory / "recovery-apply-receipt.json": recovery_bytes,
        evidence_directory / "runner-enrollment-receipt.json": enrollment_bytes,
        evidence_directory / "foundation-state-handoff-receipt.json": state_bytes,
        evidence_directory / "foundation-state-authority.json": authority_bytes,
        destination / "foundation-adoption-receipt.json": canonical_bytes(receipt),
    }
    for path, content in staged.items():
        _write_or_verify(path, content)

    prepared = AdoptedGenesisContext(
        root=destination,
        profile=destination / "profile.json",
        ssh_private_key=destination / "runner_ed25519",
        source_commit=application_source_commit,
        target_binding=target_binding,
        run_binding=adopted_run_binding,
        kit_manifest_digest=kit_manifest_digest,
    )
    status: dict[str, object] = {
        "schema_version": "fdai.foundation-adoption-status.v1",
        "state": "adopted",
        "source_commit": application_source_commit,
        "run_binding": adopted_run_binding,
        "target_binding": target_binding,
        "foundation_report": {
            "foundation_plan": {"plan_ref": _PLAN_REF},
            "state_handoff": {"receipt_digest": state_receipt["receipt_digest"]},
        },
        "mutation_performed": False,
        "deployment_ready": False,
        "subscription_ready": False,
    }
    return FoundationAdoption(prepared=prepared, status=status, receipt=receipt)


def build_foundation_adoption_receipt(
    *,
    profile: ProvisionProfile,
    handoff: dict[str, Any],
    recovery: dict[str, Any],
    enrollment: dict[str, Any],
    state_receipt: dict[str, Any],
    authority: dict[str, Any],
    known_hosts: bytes,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> dict[str, object]:
    """Verify one terminal Foundation chain and bind it to an application kit revision."""

    target_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    foundation_source_commit, foundation_run_binding = verify_foundation_chain(
        profile=profile,
        handoff=handoff,
        recovery=recovery,
        enrollment=enrollment,
        state_receipt=state_receipt,
        authority=authority,
        known_hosts=known_hosts,
        target_binding=target_binding,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    adopted_run_binding = canonical_digest(
        {
            "foundation_run_binding": foundation_run_binding,
            "application_source_commit": application_source_commit,
            "kit_manifest_digest": kit_manifest_digest,
            "runtime_release_digest": runtime_release_digest,
        }
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.foundation-adoption.v1",
        "state": "adopted",
        "foundation_source_commit": foundation_source_commit,
        "application_source_commit": application_source_commit,
        "foundation_run_binding": foundation_run_binding,
        "adopted_run_binding": adopted_run_binding,
        "target_binding": target_binding,
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
        "profile_digest": canonical_digest(profile.to_mapping()),
        "foundation_handoff_digest": canonical_digest(handoff),
        "foundation_recovery_receipt_digest": recovery["receipt_digest"],
        "foundation_enrollment_receipt_digest": enrollment["receipt_digest"],
        "foundation_state_receipt_digest": state_receipt["receipt_digest"],
        "foundation_state_authority_digest": authority["authority_digest"],
        "known_hosts_digest": hashlib.sha256(known_hosts).hexdigest(),
        "managed_resource_count": state_receipt["managed_resource_count"],
        "remote_backend_authority_verified": True,
        "zero_change_verified": True,
        "local_state_deleted": True,
        "no_effect_adoption": True,
        "mutation_performed": False,
        "deployment_ready": False,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    validate_foundation_adoption_receipt(
        receipt,
        handoff=handoff,
        target_binding=target_binding,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
    )
    return receipt


def write_lineage_adoption_receipt(
    *,
    run_root: Path,
    plan_directory: Path,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> dict[str, object]:
    """Bind a retained offline Foundation to a newer kit through no-effect adoption evidence.

    An offline kit upgrade continues the Foundation in its original work directory. The
    managed host accepts a kit from another revision only through this receipt, rebuilt
    from the retained, independently verified Foundation chain. A receipt for another kit
    is derived evidence and is superseded atomically.
    """

    _require_private_directory(run_root)
    _require_private_directory(plan_directory)
    profile = ProvisionProfile.from_mapping(
        load_json_object(
            read_private_bytes(run_root / "profile.json", max_bytes=65_536),
            label="retained Foundation profile",
        )
    )
    _handoff_bytes, handoff = _read_record(
        plan_directory / "foundation-private-handoff.json",
        label="retained Foundation handoff",
    )
    _apply_bytes, applied = _read_receipt(
        plan_directory / "foundation-apply-receipt.json",
        label="retained Foundation apply receipt",
        digest_field="receipt_digest",
    )
    _enrollment_bytes, enrollment = _read_receipt(
        plan_directory / "runner-enrollment-receipt.json",
        label="retained Foundation enrollment receipt",
        digest_field="receipt_digest",
    )
    _state_bytes, state_receipt = _read_receipt(
        plan_directory / "foundation-state-handoff-receipt.json",
        label="retained Foundation state handoff receipt",
        digest_field="receipt_digest",
    )
    _authority_bytes, authority = _read_receipt(
        plan_directory / "foundation-state-authority.json",
        label="retained Foundation state authority",
        digest_field="authority_digest",
    )
    known_hosts = read_private_bytes(plan_directory / "runner-known-hosts", max_bytes=262_144)
    receipt = build_foundation_adoption_receipt(
        profile=profile,
        handoff=handoff,
        recovery=applied,
        enrollment=enrollment,
        state_receipt=state_receipt,
        authority=authority,
        known_hosts=known_hosts,
        application_source_commit=application_source_commit,
        kit_manifest_digest=kit_manifest_digest,
        runtime_release_digest=runtime_release_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
    )
    if receipt["foundation_source_commit"] == application_source_commit:
        raise ValueError("a same-revision Foundation needs no lineage adoption")
    path = run_root / "foundation-adoption-receipt.json"
    content = canonical_bytes(receipt)
    if path.exists() or path.is_symlink():
        if read_private_bytes(path, max_bytes=1_048_576) == content:
            return receipt
        path.unlink()
    write_private_bytes(path, content)
    return receipt


def _validate_inputs(
    *,
    foundation_directory: Path,
    recovery_directory: Path,
    destination: Path,
    application_source_commit: str,
    kit_manifest_digest: str,
    runtime_release_digest: str,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> None:
    if not all(
        path.is_absolute() for path in (foundation_directory, recovery_directory, destination)
    ):
        raise ValueError("Foundation adoption paths must be absolute")
    foundation_resolved = foundation_directory.resolve()
    recovery_resolved = recovery_directory.resolve()
    destination_resolved = destination.resolve()
    if (
        foundation_resolved == recovery_resolved
        or destination_resolved.is_relative_to(foundation_resolved)
        or destination_resolved.is_relative_to(recovery_resolved)
        or foundation_resolved.is_relative_to(destination_resolved)
        or recovery_resolved.is_relative_to(destination_resolved)
    ):
        raise ValueError("Foundation adoption destination must be separate")
    if (
        _COMMIT.fullmatch(application_source_commit) is None
        or _DIGEST.fullmatch(kit_manifest_digest) is None
        or _DIGEST.fullmatch(runtime_release_digest) is None
        or _GUID.fullmatch(tenant_id) is None
        or _GUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"[a-z][a-z0-9]+", region) is None
        or type(monthly_cost_ceiling) is not int
        or monthly_cost_ceiling <= 0
    ):
        raise ValueError("Foundation adoption context is invalid")


def _read_record(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = read_private_bytes(path, max_bytes=1_048_576)
    return raw, load_json_object(raw, label=label)


def _read_receipt(path: Path, *, label: str, digest_field: str) -> tuple[bytes, dict[str, Any]]:
    raw, value = _read_record(path, label=label)
    digest = value.get(digest_field)
    unsigned = {key: item for key, item in value.items() if key != digest_field}
    if not isinstance(digest, str) or canonical_digest(unsigned) != digest:
        raise ValueError(f"{label} digest differs")
    return raw, value


def _create_or_validate_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    _require_private_directory(path)


def _require_private_directory(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("Foundation adoption directory must be absolute")
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("Foundation adoption directory must be current-UID mode 0700")


def _write_or_verify(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        if read_private_bytes(path, max_bytes=max(1, len(content))) != content:
            raise ValueError("retained Foundation adoption artifact differs")
        return
    write_private_bytes(path, content)

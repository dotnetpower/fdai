#!/usr/bin/env python3
"""Validate immutable claims and receipts for Foundation state handoff."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.target import compute_target_binding

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _private_json(path: Path, *, label: str) -> dict[str, object]:
    value = json.loads(read_private_bytes(path, max_bytes=16 * 1024 * 1024))
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {key: item for key, item in value.items()}


def load_receipt(path: Path, *, schema: str, expected_digest: str | None) -> dict[str, object]:
    """Load one canonical receipt and require its exact schema and optional digest."""

    receipt = _private_json(path, label="Genesis receipt")
    digest = receipt.pop("receipt_digest", None)
    if (
        not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or (expected_digest is not None and digest != expected_digest)
        or canonical_digest(receipt) != digest
        or receipt.get("schema_version") != schema
    ):
        raise ValueError("Genesis receipt integrity or schema is invalid")
    receipt["receipt_digest"] = digest
    return receipt


def validate_context(
    target_binding: str,
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    handoff: Mapping[str, object],
) -> None:
    """Require one target, source, Foundation, enrollment, and handoff binding."""

    tenant = handoff.get("tenant_id")
    subscription = handoff.get("subscription_id")
    if (
        not isinstance(tenant, str)
        or _GUID.fullmatch(tenant) is None
        or not isinstance(subscription, str)
        or _GUID.fullmatch(subscription) is None
        or compute_target_binding(tenant_id=tenant, subscription_id=subscription) != target_binding
        or canonical_digest(dict(handoff)) != foundation.get("handoff_digest")
        or foundation.get("target_binding") != target_binding
        or enrollment.get("target_binding") != target_binding
        or enrollment.get("foundation_receipt_digest") != foundation.get("receipt_digest")
        or enrollment.get("handoff_digest") != foundation.get("handoff_digest")
        or enrollment.get("source_commit") != foundation.get("source_commit")
        or handoff.get("source_commit") != foundation.get("source_commit")
        or enrollment.get("effect_verified") is not True
        or enrollment.get("identity_attested") is not True
    ):
        raise ValueError("Foundation state handoff context is invalid")


def local_state_path(directory: Path, foundation: Mapping[str, object]) -> Path:
    """Resolve only the verified Foundation bundle's exact local state path."""

    value = foundation.get("state_ref")
    if not isinstance(value, str):
        raise ValueError("Foundation local state reference is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Foundation local state reference is unsafe")
    if (
        len(relative.parts) != 5
        or relative.parts[0] != "foundation-apply-bundle"
        or relative.parts[2:] != ("infra", "genesis-foundation", "terraform.tfstate")
    ):
        raise ValueError("Foundation local state reference is outside the verified bundle")
    return directory.joinpath(*relative.parts)


def create_claim(
    *,
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    work_id: str,
    archive_digest: str,
    state_digest: str,
    backend_key: str,
    actor_digest: str,
) -> dict[str, object]:
    """Create the no-retry claim that must precede transfer and backend mutation."""

    return {
        "schema_version": "fdai.genesis-foundation-state-handoff-claim.v1",
        "state": "migrating",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "enrollment_receipt_digest": enrollment["receipt_digest"],
        "target_binding": foundation["target_binding"],
        "source_commit": foundation["source_commit"],
        "work_id": work_id,
        "archive_digest": archive_digest,
        "state_digest": state_digest,
        "backend_key_digest": hashlib.sha256(backend_key.encode()).hexdigest(),
        "idempotency_key": work_id,
        "actor_digest": actor_digest,
        "claimed_at": _utc_now().replace(microsecond=0).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def load_claim(path: Path) -> dict[str, object] | None:
    """Load an optional immutable local state-migration claim."""

    if not path.exists():
        return None
    claim = _private_json(path, label="Foundation state handoff claim")
    if claim.get("schema_version") != "fdai.genesis-foundation-state-handoff-claim.v1":
        raise ValueError("Foundation state handoff claim is invalid")
    return claim


def validate_claim(
    claim: Mapping[str, object],
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    work_id: str,
) -> None:
    """Require a claim bound to the exact prior receipts and recovery state."""

    if (
        claim.get("state") != "migrating"
        or claim.get("foundation_receipt_digest") != foundation["receipt_digest"]
        or claim.get("enrollment_receipt_digest") != enrollment["receipt_digest"]
        or claim.get("target_binding") != foundation["target_binding"]
        or claim.get("source_commit") != foundation["source_commit"]
        or claim.get("work_id") != work_id
        or claim.get("state_digest") != foundation["state_digest"]
        or not isinstance(claim.get("actor_digest"), str)
        or _DIGEST.fullmatch(str(claim["actor_digest"])) is None
        or claim.get("mutation_performed") is not False
    ):
        raise ValueError("Foundation state handoff claim context is invalid")


def create_authority(
    *,
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    claim: Mapping[str, object],
    work_id: str,
    archive_digest: str,
    comparison: Mapping[str, object],
    observation: Mapping[str, object],
    backend_key: str,
) -> dict[str, object]:
    """Seal comparison and independent backend observations before raw cleanup."""

    authority: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-state-authority.v1",
        "state": "verified",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "enrollment_receipt_digest": enrollment["receipt_digest"],
        "target_binding": foundation["target_binding"],
        "source_commit": foundation["source_commit"],
        "work_id": work_id,
        "claim_digest": canonical_digest(dict(claim)),
        "actor_digest": claim["actor_digest"],
        "archive_digest": archive_digest,
        "backend_key_digest": hashlib.sha256(backend_key.encode()).hexdigest(),
        "comparison_digest": canonical_digest(dict(comparison)),
        "observation_digest": canonical_digest(dict(observation)),
        "state_digest": comparison["state_digest"],
        "plan_digest": comparison["plan_digest"],
        "managed_resource_count": comparison["managed_resource_count"],
        "remote_backend_authority_verified": True,
        "zero_change_verified": True,
        "local_state_deletion_authorized": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    authority["authority_digest"] = canonical_digest(authority)
    return authority


def load_authority(path: Path) -> dict[str, object] | None:
    """Load an optional content-addressed backend-authority record."""

    if not path.exists():
        return None
    authority = _private_json(path, label="Foundation state authority")
    digest = authority.pop("authority_digest", None)
    if not isinstance(digest, str) or canonical_digest(authority) != digest:
        raise ValueError("Foundation state authority digest is invalid")
    authority["authority_digest"] = digest
    return authority


def validate_authority(
    authority: Mapping[str, object],
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    claim: Mapping[str, object],
    work_id: str,
) -> None:
    """Require authority from the exact claimed handoff before deleting raw state."""

    if (
        authority.get("schema_version") != "fdai.genesis-foundation-state-authority.v1"
        or authority.get("state") != "verified"
        or authority.get("foundation_receipt_digest") != foundation["receipt_digest"]
        or authority.get("enrollment_receipt_digest") != enrollment["receipt_digest"]
        or authority.get("target_binding") != foundation["target_binding"]
        or authority.get("source_commit") != foundation["source_commit"]
        or authority.get("work_id") != work_id
        or authority.get("claim_digest") != canonical_digest(dict(claim))
        or authority.get("actor_digest") != claim.get("actor_digest")
        or authority.get("remote_backend_authority_verified") is not True
        or authority.get("local_state_deletion_authorized") is not True
    ):
        raise ValueError("Foundation state authority context is invalid")


def validate_final_receipt(
    receipt: Mapping[str, object],
    foundation: Mapping[str, object],
    enrollment: Mapping[str, object],
    authority: Mapping[str, object],
    claim: Mapping[str, object],
    work_id: str,
) -> None:
    """Require a final receipt that closes backend authority and both raw-state cleanups."""

    if (
        receipt.get("state") != "verified"
        or receipt.get("foundation_receipt_digest") != foundation["receipt_digest"]
        or receipt.get("enrollment_receipt_digest") != enrollment["receipt_digest"]
        or receipt.get("work_id") != work_id
        or receipt.get("authority_digest") != authority.get("authority_digest")
        or receipt.get("claim_digest") != canonical_digest(dict(claim))
        or receipt.get("actor_digest") != claim.get("actor_digest")
        or receipt.get("state_digest") != authority.get("state_digest")
        or receipt.get("remote_backend_authority_verified") is not True
        or receipt.get("local_state_deleted") is not True
        or receipt.get("remote_transient_deleted") is not True
        or receipt.get("effect_verified") is not True
    ):
        raise ValueError("Foundation state handoff receipt context is invalid")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint

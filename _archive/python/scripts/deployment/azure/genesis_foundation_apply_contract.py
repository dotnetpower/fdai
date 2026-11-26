#!/usr/bin/env python3
"""Validate immutable claim and receipt records for local Foundation apply."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input


def load_apply_claim(
    path: Path, *, review: Mapping[str, object], profile: ProvisionProfile
) -> dict[str, object] | None:
    """Load an exact apply claim, or return ``None`` when no effect started."""

    if not path.exists():
        return None
    claim = read_plan_input(path)
    expected_idempotency = canonical_digest(
        {
            "target_binding": profile.target_binding,
            "plan_digest": review["plan_digest"],
        }
    )
    if (
        claim.get("schema_version") != "fdai.genesis-foundation-apply-claim.v1"
        or claim.get("state") != "applying"
        or claim.get("review_digest") != review["review_digest"]
        or claim.get("plan_digest") != review["plan_digest"]
        or claim.get("target_binding") != profile.target_binding
        or claim.get("idempotency_key") != expected_idempotency
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
    ):
        raise ValueError("Foundation apply claim does not match the reviewed plan")
    return claim


def load_apply_receipt(
    path: Path, *, review: Mapping[str, object], profile: ProvisionProfile
) -> dict[str, object]:
    """Load a content-addressed Foundation receipt bound to its review and profile."""

    receipt = read_plan_input(path)
    digest = receipt.pop("receipt_digest", None)
    if (
        not isinstance(digest, str)
        or canonical_digest(receipt) != digest
        or receipt.get("schema_version") != "fdai.genesis-foundation-apply-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("review_digest") != review["review_digest"]
        or receipt.get("plan_digest") != review["plan_digest"]
        or receipt.get("target_binding") != profile.target_binding
        or receipt.get("control_plane_readback_verified") is not True
        or receipt.get("zero_change_verified") is not True
        or receipt.get("remote_backend_authority_verified") is not False
        or receipt.get("runner_attested") is not False
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
    ):
        raise ValueError("Foundation apply receipt does not match the reviewed plan")
    receipt["receipt_digest"] = digest
    return receipt


def require_same_effect(receipt: Mapping[str, object], observed: Mapping[str, object]) -> None:
    """Require a fresh readback to match every stable field in its retained receipt."""

    ignored = {"completed_at", "receipt_digest"}
    if {key: value for key, value in receipt.items() if key not in ignored} != {
        key: value for key, value in observed.items() if key not in ignored
    }:
        raise ValueError("Foundation current readback differs from its exact receipt")

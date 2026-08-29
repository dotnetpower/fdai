"""Compile the fixed subscription-genesis dependency graph."""

from __future__ import annotations

from fdai_deployment_cli.contracts import (
    ApprovalClass,
    ManifestEntry,
    ProvisionProfile,
    SubscriptionProvisioningManifest,
    canonical_digest,
)

_STAGES: tuple[tuple[str, ApprovalClass, int, int], ...] = (
    ("inspect-context", ApprovalClass.STANDARD, 300, 60),
    ("reconcile-current-state", ApprovalClass.STANDARD, 600, 120),
    ("foundation", ApprovalClass.HIGH_IMPACT, 3600, 300),
    ("attest-runner", ApprovalClass.STANDARD, 900, 120),
    ("data-substrate", ApprovalClass.HIGH_IMPACT, 7200, 600),
    ("database", ApprovalClass.HIGH_IMPACT, 1800, 300),
    ("semantic-defaults", ApprovalClass.STANDARD, 900, 120),
    ("models", ApprovalClass.HIGH_IMPACT, 3600, 300),
    ("runtime-services", ApprovalClass.HIGH_IMPACT, 3600, 300),
    ("initial-inventory", ApprovalClass.STANDARD, 1800, 300),
    ("system-readiness", ApprovalClass.STANDARD, 900, 120),
)


def compile_manifest(
    profile: ProvisionProfile,
    *,
    source_commit: str,
) -> SubscriptionProvisioningManifest:
    """Compile the finite stage chain and bind every idempotency key to the profile."""

    profile_digest = canonical_digest(profile.to_mapping())
    entries: list[ManifestEntry] = []
    previous: str | None = None
    for stage, approval, timeout, no_progress in _STAGES:
        entries.append(
            ManifestEntry(
                entry_id=stage,
                owner="deployment",
                desired_state="ready",
                prerequisites=() if previous is None else (previous,),
                approval_class=approval,
                idempotency_key=f"genesis.{profile_digest[:24]}.{stage}",
                timeout_seconds=timeout,
                no_progress_seconds=no_progress,
                rollback_ref=f"rollback.{stage}",
                observer=f"observer.{stage}",
            )
        )
        previous = stage
    return SubscriptionProvisioningManifest(
        source_commit=source_commit,
        profile_digest=profile_digest,
        entries=tuple(entries),
    )

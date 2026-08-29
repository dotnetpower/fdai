"""Compile the fixed subscription-genesis dependency graph."""

from __future__ import annotations

from fdai_deployment_cli.contracts import (
    ApprovalClass,
    ManifestEntry,
    ProvisionProfile,
    SubscriptionProvisioningManifest,
    canonical_digest,
)

_ENTRIES: tuple[tuple[str, ApprovalClass], ...] = (
    ("inspect-context", ApprovalClass.STANDARD),
    ("reconcile-current-state", ApprovalClass.STANDARD),
    ("provider-registrations", ApprovalClass.HIGH_IMPACT),
    ("ops-resource-group", ApprovalClass.HIGH_IMPACT),
    ("application-resource-group", ApprovalClass.HIGH_IMPACT),
    ("state-storage", ApprovalClass.HIGH_IMPACT),
    ("ops-network", ApprovalClass.HIGH_IMPACT),
    ("deploy-identity", ApprovalClass.HIGH_IMPACT),
    ("foundation", ApprovalClass.HIGH_IMPACT),
    ("runner", ApprovalClass.HIGH_IMPACT),
    ("attest-runner", ApprovalClass.STANDARD),
    ("application-network", ApprovalClass.HIGH_IMPACT),
    ("key-vault", ApprovalClass.HIGH_IMPACT),
    ("postgres", ApprovalClass.HIGH_IMPACT),
    ("event-hubs-primary", ApprovalClass.HIGH_IMPACT),
    ("event-hubs-operational", ApprovalClass.HIGH_IMPACT),
    ("container-registry", ApprovalClass.HIGH_IMPACT),
    ("log-analytics", ApprovalClass.HIGH_IMPACT),
    ("application-insights", ApprovalClass.HIGH_IMPACT),
    ("container-apps-environment", ApprovalClass.HIGH_IMPACT),
    ("database", ApprovalClass.HIGH_IMPACT),
    ("semantic-defaults", ApprovalClass.STANDARD),
    ("model-account-openai", ApprovalClass.HIGH_IMPACT),
    ("model-account-foundry", ApprovalClass.HIGH_IMPACT),
    ("model-deployments", ApprovalClass.HIGH_IMPACT),
    ("runtime-identities", ApprovalClass.HIGH_IMPACT),
    ("core-control-plane", ApprovalClass.HIGH_IMPACT),
    ("operator-service", ApprovalClass.HIGH_IMPACT),
    ("document-ingestion-api", ApprovalClass.HIGH_IMPACT),
    ("document-processing-worker", ApprovalClass.HIGH_IMPACT),
    ("isolated-executor", ApprovalClass.HIGH_IMPACT),
    ("inventory-job", ApprovalClass.STANDARD),
    ("canary-job", ApprovalClass.STANDARD),
    ("initial-inventory", ApprovalClass.STANDARD),
    ("console", ApprovalClass.STANDARD),
    ("monitoring", ApprovalClass.STANDARD),
    ("system-readiness", ApprovalClass.STANDARD),
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
    for stage, approval in _ENTRIES:
        timeout = 3_600 if approval is ApprovalClass.HIGH_IMPACT else 900
        no_progress = 300 if approval is ApprovalClass.HIGH_IMPACT else 120
        entries.append(
            ManifestEntry(
                entry_id=stage,
                owner="deployment",
                desired_state="ready",
                prerequisites=() if previous is None else (previous,),
                approval_class=approval,
                idempotency_key=(f"genesis.{profile_digest[:16]}.{source_commit}.{stage}"),
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

"""Choose the next Release for an installation and sign the Plan for it.

The target is the newest Release on the subscribed channel that passes every Release-specific
constraint. A closed maintenance window or an active suppression doesn't move the target to an
older Release; the installation waits for the target instead.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import cast

from fdai_deployment_cli.lifecycle_plan import (
    CapabilityMode,
    DataResidencyRequirement,
    LifecycleConstraintContext,
    LifecycleEffectEnvelope,
    LifecyclePlan,
    MaintenanceWindow,
    canonical_plan_payload,
    evaluate_lifecycle_constraints,
)
from fdai_deployment_cli.runtime_release import RuntimeRelease

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.domain import (
    CandidateCheck,
    Installation,
    Issued,
    NoEligibleRelease,
    PlanOutcome,
    Unchanged,
    UpToDate,
    Waiting,
)
from fdai_lifecycle_hub.signing import HubSigningKey

TIMING_REASONS = frozenset(
    {
        "maintenance_window_unavailable",
        "maintenance_window_invalid",
        "suppression_window_active",
        "suppression_window_invalid",
        "suppression_scope_invalid",
    }
)


def plan_next(
    installation: Installation,
    now: datetime,
    *,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
) -> PlanOutcome:
    """Return the next Plan for `installation`, or why there is none."""

    if now.tzinfo is None:
        raise ValueError("planning time must be timezone-aware")
    windows = installation.maintenance_windows(now)
    checks: list[CandidateCheck] = []
    candidates = catalog.newer_than(installation.settings.channel, installation.current_release)
    for release_id, release in candidates:
        draft = _draft(installation, release_id, release, key=key, windows=windows, now=now)
        context = _constraint_context(
            installation, draft, release, catalog=catalog, windows=windows, now=now
        )
        blocks = evaluate_lifecycle_constraints(context, admitted_plan=draft)
        checks.append(CandidateCheck(release_id, blocks))
        if any(block.reason_code not in TIMING_REASONS for block in blocks):
            continue
        if blocks:
            return Waiting(release_id, tuple(checks))
        if (open_plan := installation.open_plan) and open_plan.still_valid_for(draft, now):
            return Unchanged(open_plan, tuple(checks))
        return Issued(_sign(draft, key), tuple(checks))
    return NoEligibleRelease(tuple(checks)) if checks else UpToDate()


def plan_id_for(installation_id: str, sequence: int) -> str:
    return f"{installation_id}-{sequence:08d}"


def _draft(
    installation: Installation,
    release_id: str,
    release: RuntimeRelease,
    *,
    key: HubSigningKey,
    windows: tuple[MaintenanceWindow, ...],
    now: datetime,
) -> LifecyclePlan:
    settings = installation.settings
    sequence = installation.last_sequence + 1
    entity_ids = installation.managed_entity_ids
    regions = frozenset({settings.region})
    # The manifest parser already restricted every maximum to a CapabilityMode value.
    modes = cast(dict[str, CapabilityMode], dict(sorted(release.capability_maximums.items())))
    open_window_ends = [w.ends_at for w in windows if w.starts_at <= now < w.ends_at]
    return LifecyclePlan(
        plan_id=plan_id_for(installation.installation_id, sequence),
        audience=installation.installation_id,
        hub_key_epoch=key.epoch,
        hub_key_id=key.key_id,
        source_state_digest=installation.reported.digest,
        sequence=sequence,
        fencing_generation=settings.fencing_generation,
        plan_type="upgrade",
        target_release_id=release_id,
        target_release_digest=release.digest,
        configuration_revision_digest=installation.configuration.digest,
        entity_ids=entity_ids,
        capability_ids=tuple(modes),
        release_regions=regions,
        rollback_target_plan_id=None,
        declared_duration_minutes=settings.plan_duration_minutes,
        envelope=LifecycleEffectEnvelope(
            entity_ids=entity_ids,
            regions=regions,
            capability_modes=modes,
            destructive_allowed=False,
            max_duration_minutes=settings.plan_duration_minutes,
        ),
        expires_at=max(open_window_ends, default=now + settings.plan_duration),
        signed_payload=b"",
        signature=b"",
    )


def _constraint_context(
    installation: Installation,
    draft: LifecyclePlan,
    release: RuntimeRelease,
    *,
    catalog: ReleaseCatalog,
    windows: tuple[MaintenanceWindow, ...],
    now: datetime,
) -> LifecycleConstraintContext:
    settings, configuration = installation.settings, installation.configuration
    return LifecycleConstraintContext(
        now=now,
        plan_id=draft.plan_id,
        plan_type=draft.plan_type,
        rollback_target_plan_id=draft.rollback_target_plan_id,
        declared_duration_minutes=draft.declared_duration_minutes,
        requires_downtime=False,
        target_release_version=draft.target_release_id,
        candidate_release=release,
        configuration_revision_digest=draft.configuration_revision_digest,
        current_schema_revision=installation.reported.schema_revision,
        version_range=settings.version_range,
        configuration_schema=configuration.schema,
        environment_config=configuration.environment,
        entity_overrides=configuration.entity_overrides,
        available_artifact_digests=installation.reported.artifact_digests(),
        data_residency=DataResidencyRequirement(
            allowed_regions=settings.allowed_regions, release_regions=draft.release_regions
        ),
        maintenance_windows=windows,
        suppression_windows=installation.suppressions,
        entity_ids=draft.entity_ids,
        capability_ids=draft.capability_ids,
        recall_records=catalog.recalls,
    )


def _sign(draft: LifecyclePlan, key: HubSigningKey) -> LifecyclePlan:
    payload = canonical_plan_payload(draft)
    return replace(draft, signed_payload=payload, signature=key.sign(payload))

"""Choose the next Release for an installation and sign the Plan for it.

The target is the newest Release on the subscribed channel that passes every Release-specific
constraint. A closed maintenance window or an active suppression doesn't move the target to an
older Release; the installation waits for the target instead.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_plan import (
    CapabilityMode,
    ConstraintBlock,
    DataResidencyRequirement,
    LifecycleConstraintContext,
    LifecycleEffectEnvelope,
    LifecyclePlan,
    MaintenanceWindow,
    PlanType,
    SuppressionWindow,
    canonical_plan_payload,
    evaluate_lifecycle_constraints,
    overrides_adopted,
    required_artifact_digests,
)
from fdai_deployment_cli.lifecycle_release import LifecycleRelease
from fdai_deployment_cli.runtime_release import compare_release_ids, evaluate_recall_candidate

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.domain import (
    CandidateCheck,
    EntityState,
    Health,
    Installation,
    Issued,
    NoEligibleRelease,
    NoManagedEntity,
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
    configuration_revision: ConfigurationRevisionCandidate | None = None,
) -> PlanOutcome:
    """Return the next Plan, optionally verifying one transient full configuration revision.

    The optional candidate never enrolls keys or persists configuration. Its selection is the
    installation's already-managed Entity set, not a package-supplied permission.
    """

    if now.tzinfo is None:
        raise ValueError("planning time must be timezone-aware")
    if not installation.managed_entity_ids:
        return NoManagedEntity()
    windows = installation.maintenance_windows(now)
    checks: list[CandidateCheck] = []
    managed_states = [
        state
        for entity_id, state in installation.reported.entities.items()
        if entity_id in installation.managed_entity_ids
    ]
    active_break_glass = tuple(
        cmd for cmd in installation.commands if cmd.kind == "break-glass" and cmd.is_active(now)
    )
    bypass_scopes: frozenset[str] = frozenset().union(
        *(cmd.bypass_scopes for cmd in active_break_glass)
    )
    active_emergency_overrides = tuple(
        block for cmd in active_break_glass for block in cmd.emergency_overrides
    )
    expired_unadopted_break_glass = any(
        cmd.kind == "break-glass"
        and cmd.is_expired(now)
        and not overrides_adopted(
            cmd.emergency_overrides, installation.configuration.entity_overrides
        )
        for cmd in installation.commands
    )
    effective_installation = (
        replace(
            installation,
            configuration=replace(
                installation.configuration,
                entity_overrides=_merge_emergency_overrides(
                    installation.configuration.entity_overrides,
                    active_emergency_overrides,
                ),
            ),
        )
        if active_emergency_overrides
        else installation
    )
    rolloff_required = any(
        state.release_id is not None
        and not evaluate_recall_candidate(
            release_id=state.release_id,
            capability_ids=(
                tuple(sorted(catalog.releases[state.release_id].capability_maximums))
                if state.release_id in catalog.releases
                else ()
            ),
            recall_records=catalog.recalls,
        ).allowed
        for state in managed_states
    )
    drift_detected = not rolloff_required and (
        any(_entity_has_drift(state, catalog) for state in managed_states)
        or expired_unadopted_break_glass
    )
    current_release = installation.current_release
    if rolloff_required:
        candidates = list(catalog.newer_than(installation.settings.channel, None))
    elif (drift_detected or bool(active_emergency_overrides)) and current_release is not None:
        candidates = [
            (release_id, release)
            for release_id, release in catalog.newer_than(installation.settings.channel, None)
            if compare_release_ids(release_id, current_release) >= 0
        ]
    else:
        candidates = list(catalog.newer_than(installation.settings.channel, current_release))
    for release_id, release in candidates:
        if rolloff_required:
            plan_type: PlanType = "recall-rolloff"
        elif drift_detected and release_id == current_release:
            plan_type = "drift-reconciliation"
        elif active_emergency_overrides and release_id == current_release:
            plan_type = "configuration-change"
        else:
            plan_type = "upgrade"
        if catalog.plan_types is not None and plan_type not in catalog.plan_types:
            checks.append(
                CandidateCheck(release_id, (ConstraintBlock("catalog_timestamp_expired"),))
            )
            continue
        if not rolloff_required and any(
            state.release_id is not None and compare_release_ids(release_id, state.release_id) < 0
            for state in managed_states
        ):
            checks.append(
                CandidateCheck(release_id, (ConstraintBlock("release_would_downgrade_entity"),))
            )
            continue
        if release.product != installation.settings.product:
            checks.append(
                CandidateCheck(release_id, (ConstraintBlock("release_product_mismatch"),))
            )
            continue
        schema = release.configuration_schema
        if (
            configuration_revision is None
            and schema is not None
            and (
                schema.release_version != release_id
                or schema.digest != canonical_digest(installation.configuration.schema)
            )
        ):
            checks.append(
                CandidateCheck(
                    release_id, (ConstraintBlock("release_configuration_schema_mismatch"),)
                )
            )
            continue
        resolved = None
        if configuration_revision is not None:
            try:
                resolved = configuration_revision.resolve(
                    release_id,
                    release,
                    installation.managed_entity_ids,
                    installation_id=installation.installation_id,
                )
            except ValueError:
                checks.append(
                    CandidateCheck(release_id, (ConstraintBlock("configuration_revision_invalid"),))
                )
                continue
        draft = _draft(
            effective_installation,
            release_id,
            release,
            key=key,
            windows=windows,
            now=now,
            plan_type=plan_type,
        )
        if configuration_revision is not None:
            draft = replace(
                draft, configuration_revision_digest=configuration_revision.package.digest
            )
        context = _constraint_context(
            effective_installation,
            draft,
            release,
            catalog=catalog,
            windows=windows,
            now=now,
            bypass_scopes=bypass_scopes,
        )
        contexts = [
            context,
            *(
                replace(
                    context,
                    entity_overrides=_merge_emergency_overrides(
                        entity.settings.overrides,
                        active_emergency_overrides,
                    ),
                )
                for entity in sorted(installation.entities, key=lambda item: item.entity_id)
                if entity.settings is not None
            ),
        ]
        if resolved is not None:
            # Every Entity was independently verified against the same catalog schema.
            if schema is None:
                raise ValueError("verified configuration requires a catalog schema")
            contexts = [
                replace(
                    context,
                    configuration_schema=schema.to_mapping(),
                    environment_config={},
                    entity_overrides=({"versions": release_id, "values": resolution.values},),
                )
                for resolution in resolved.entities.values()
            ]
        blocks = tuple(
            dict.fromkeys(
                block
                for entity_context in contexts
                for block in evaluate_lifecycle_constraints(entity_context, admitted_plan=draft)
            )
        )
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
    release: LifecycleRelease,
    *,
    key: HubSigningKey,
    windows: tuple[MaintenanceWindow, ...],
    now: datetime,
    plan_type: PlanType = "upgrade",
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
        plan_type=plan_type,
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


def _entity_has_drift(state: EntityState, catalog: ReleaseCatalog) -> bool:
    if state.release_id is None:
        return False
    if state.health is not Health.HEALTHY:
        return True
    release = catalog.releases.get(state.release_id)
    if release is not None and state.artifact_digests:
        if not state.artifact_digests <= required_artifact_digests(release):
            return True
    return False


def _merge_emergency_overrides(
    base_overrides: tuple[dict[str, object] | object, ...],
    emergency_overrides: tuple[dict[str, object] | object, ...],
) -> tuple[Any, ...]:
    if not emergency_overrides:
        return base_overrides
    emergency_versions = {
        block.get("versions")
        for block in emergency_overrides
        if isinstance(block, dict) and "versions" in block
    }
    retained = [
        block
        for block in base_overrides
        if not (isinstance(block, dict) and block.get("versions") in emergency_versions)
    ]
    return (*retained, *emergency_overrides)


def _constraint_context(
    installation: Installation,
    draft: LifecyclePlan,
    release: LifecycleRelease,
    *,
    catalog: ReleaseCatalog,
    windows: tuple[MaintenanceWindow, ...],
    now: datetime,
    bypass_scopes: frozenset[str] = frozenset(),
) -> LifecycleConstraintContext:
    settings, configuration = installation.settings, installation.configuration
    available_artifacts = installation.reported.artifact_digests()
    if installation.reported.available_artifact_digests is None and draft.plan_type in {
        "drift-reconciliation",
        "configuration-change",
    }:
        available_artifacts = available_artifacts | required_artifact_digests(release)
    effective_windows = (
        (*windows, MaintenanceWindow(now, now + settings.plan_duration, allows_downtime=True))
        if "maintenance-window" in bypass_scopes
        else windows
    )
    command_suppressions = tuple(
        SuppressionWindow(scope=cmd.scope, starts_at=cmd.starts_at, ends_at=cmd.expires_at)
        for cmd in installation.commands
        if cmd.kind == "suppression-window" and cmd.expires_at is not None and cmd.is_active(now)
    )
    effective_suppressions = (
        ()
        if "suppression-window" in bypass_scopes
        else (*installation.suppressions, *command_suppressions)
    )
    effective_version_range = (
        ">=0.0.0" if "version-range" in bypass_scopes else settings.version_range
    )
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
        version_range=effective_version_range,
        configuration_schema=configuration.schema,
        environment_config=configuration.environment,
        entity_overrides=configuration.entity_overrides,
        available_artifact_digests=available_artifacts,
        data_residency=DataResidencyRequirement(
            allowed_regions=settings.allowed_regions, release_regions=draft.release_regions
        ),
        maintenance_windows=effective_windows,
        suppression_windows=effective_suppressions,
        entity_ids=draft.entity_ids,
        capability_ids=draft.capability_ids,
        recall_records=catalog.recalls,
    )


def _sign(draft: LifecyclePlan, key: HubSigningKey) -> LifecyclePlan:
    payload = canonical_plan_payload(draft)
    return replace(draft, signed_payload=payload, signature=key.sign(payload))

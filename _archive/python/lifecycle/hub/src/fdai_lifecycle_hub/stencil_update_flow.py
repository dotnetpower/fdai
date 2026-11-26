"""Customer Lifecycle Hub automatic Stencil update, transition guardrails, and readiness view.

Implements #2533 and #2535 on top of the #2528 / #2529 / #2530 / #2531 contracts:
- Zero inter-party pin/digest/key/file handoffs and zero additional customer apply clicks for
  routine online updates inside an approved channel and maintenance window.
- Explicit Stencil switch/downgrade guardrails requiring an entitled distribution grant,
  customer-approved configuration, matching RuntimeBundle, and forward/compatible schema checks
  without silent data purge or fabricated schema rollback.
- Restart/replay idempotency preserving installation keys, PVC/journal sequence, and the original
  30-day Trial anchor / runtime entitlement.
- Unified customer update readiness and recovery read-model distinguishing catalog acceptance from
  executable readiness and mapping UXH-01..UXH-18.
"""

from __future__ import annotations

import hashlib
from base64 import b64decode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.lifecycle_promotion import BoundaryRegistryMirror
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    LifecycleRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.lifecycle_stencil_grant import (
    StencilBindingError,
    extract_stencil_variant_binding,
    verify_release_plan_bundle_stencil_binding,
    verify_stencil_distribution_grant,
)
from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    compare_release_ids,
    evaluate_recall_candidate,
)

from fdai_lifecycle_hub.catalog_import import verify_export_signature

ReadinessClassification = Literal[
    "verified-ready",
    "scheduled-waiting-window",
    "blocked-prerequisite",
    "recovery-rolloff-required",
    "grant-expired-or-revoked",
    "agent-inactive",
    "catalog-untrusted",
    "up-to-date",
]


@dataclass(frozen=True, slots=True)
class StencilInstallationState:
    """Durable installation state for automatic Stencil updates and recovery (#2533/#2535)."""

    installation_id: str
    customer_principal: str
    subscribed_channel: str
    current_release_id: str
    current_stencil_id: str
    current_stencil_digest: str
    current_schema_revision: int
    selected_stencil_id: str
    configuration_stencil_id: str | None
    configuration_revision_digest: str
    runtime_bundle_stencil_id: str | None
    runtime_bundle_workloads: tuple[str, ...]
    runtime_bundle_component_images: Mapping[str, str]
    trial_anchor_created_at: str
    runtime_entitlement_digest: str
    installation_key_id: str
    pvc_journal_sequence: int
    catalog_minimum_revision: int = 0
    last_accepted_export_digest: str | None = None
    last_applied_plan_digest: str | None = None
    maintenance_window_open: bool = True
    next_window_starts_at: str = "2026-11-05T02:00:00+00:00"
    check_interval_seconds: int = 300
    jitter_seconds: int = 15
    agent_active: bool = True
    inputs_staged: bool = True
    db_and_model_ready: bool = True
    pinned_grant_id: str = ""
    pinned_grant_revision: int = 0
    pinned_grant_scope_digest: str = ""
    last_agent_report: Mapping[str, Any] | None = None
    last_failure: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StencilUpdateReconciliationResult:
    """Result of one pull-only Stencil catalog poll, preparation, and readiness evaluation."""

    installation_id: str
    classification: ReadinessClassification
    executable_readiness: bool
    plan_issued: bool
    plan_type: str | None
    plan_digest: str | None
    applied_in_window: bool
    current_release_id: str
    current_stencil_id: str
    proposed_release_id: str | None
    proposed_stencil_id: str | None
    blocker_code: str | None
    blocker_detail: str | None
    decision_owner: str
    inter_party_handoff_count: int
    additional_customer_apply_clicks: int
    outside_window_mutations: int
    changed_features: Mapping[str, list[str]]
    mirrored_digests: tuple[str, ...]
    updated_state: StencilInstallationState
    readiness_view: Mapping[str, Any]


def _extract_stencil_sets(release: LifecycleRelease | None) -> tuple[set[str], set[str], set[str]]:
    if not isinstance(release, ApplicationRelease) or release.stencil is None:
        return set(), set(), set()
    st = release.stencil
    raw_panels = st.get("enabled_panel_ids")
    raw_workloads = st.get("enabled_workloads")
    raw_loops = st.get("enabled_loops")
    panels = {
        str(p) for p in (raw_panels if isinstance(raw_panels, list) else ()) if isinstance(p, str)
    }
    workloads = {
        str(w)
        for w in (raw_workloads if isinstance(raw_workloads, list) else ())
        if isinstance(w, str)
    }
    loops = {
        str(lp) for lp in (raw_loops if isinstance(raw_loops, list) else ()) if isinstance(lp, str)
    }
    return panels, workloads, loops


def _compute_feature_diff(
    current_release: LifecycleRelease | None,
    proposed_release: LifecycleRelease | None,
) -> dict[str, list[str]]:
    cur_p, cur_w, cur_l = _extract_stencil_sets(current_release)
    prop_p, prop_w, prop_l = _extract_stencil_sets(proposed_release)
    if proposed_release is None:
        return {
            "added_panels": [],
            "removed_panels": [],
            "added_workloads": [],
            "removed_workloads": [],
            "added_loops": [],
            "removed_loops": [],
        }
    return {
        "added_panels": sorted(prop_p - cur_p),
        "removed_panels": sorted(cur_p - prop_p),
        "added_workloads": sorted(prop_w - cur_w),
        "removed_workloads": sorted(cur_w - prop_w),
        "added_loops": sorted(prop_l - cur_l),
        "removed_loops": sorted(cur_l - prop_l),
    }


def reconcile_stencil_update(
    state: StencilInstallationState,
    *,
    scoped_export_raw: bytes,
    export_signature: str,
    export_scope_signature: str,
    export_public_key: Ed25519PublicKey,
    grant_envelope: Mapping[str, Any],
    grant_issuer_public_keys: Sequence[Ed25519PublicKey],
    mirror: BoundaryRegistryMirror,
    expected_grant_scope_digest: str | None = None,
    now: datetime | None = None,
) -> StencilUpdateReconciliationResult:
    """Detect, verify, stage, and plan/apply a Stencil update inside approved policies (#2533)."""
    check_now = now or datetime.now(UTC)
    if not verify_export_signature(scoped_export_raw, export_signature, export_public_key):
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="export_signature_invalid",
            blocker_detail="Customer catalog export signature failed verification.",
            decision_owner="vendor-release-operator",
        )

    export_digest = hashlib.sha256(scoped_export_raw).hexdigest()
    doc = load_json_object(scoped_export_raw, label="scoped customer export", strict=True)
    raw_expires = doc.get("expires_at")
    if not isinstance(raw_expires, str) or not raw_expires.strip():
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="catalog_export_expired",
            blocker_detail="Scoped customer catalog export is missing a valid expires_at string.",
            decision_owner="vendor-release-operator",
        )
    try:
        exp_dt = datetime.fromisoformat(raw_expires)
    except ValueError:
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="catalog_export_expired",
            blocker_detail="Scoped customer catalog export expires_at is not valid ISO-8601.",
            decision_owner="vendor-release-operator",
        )
    if exp_dt.tzinfo is None or check_now >= exp_dt:
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="catalog_export_expired",
            blocker_detail="Scoped customer catalog export has expired or lacks timezone.",
            decision_owner="vendor-release-operator",
        )
    revision = int(doc.get("revision", 0))
    if revision < state.catalog_minimum_revision or (
        revision == state.catalog_minimum_revision
        and state.last_accepted_export_digest not in (None, export_digest)
    ):
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="catalog_revision_rollback",
            blocker_detail=(
                "Scoped catalog export revision regressed or mutated without a new revision."
            ),
            decision_owner="vendor-release-operator",
        )

    recovery_only = False
    min_grant_rev = max(1, state.pinned_grant_revision)
    try:
        verified_grant = verify_stencil_distribution_grant(
            grant_envelope,
            trusted_public_keys=grant_issuer_public_keys,
            expected_installation_id=state.installation_id,
            expected_customer_principal=state.customer_principal,
            minimum_revision=min_grant_rev,
            now=check_now,
            allow_expired_or_revoked_for_recovery=False,
        )
    except StencilBindingError as exc:
        if exc.reason_code in {"grant_expired", "grant_revoked"}:
            try:
                verified_grant = verify_stencil_distribution_grant(
                    grant_envelope,
                    trusted_public_keys=grant_issuer_public_keys,
                    expected_installation_id=state.installation_id,
                    expected_customer_principal=state.customer_principal,
                    minimum_revision=min_grant_rev,
                    now=check_now,
                    allow_expired_or_revoked_for_recovery=True,
                )
                recovery_only = True
            except StencilBindingError as inner_exc:
                return _build_blocked_result(
                    state,
                    classification="grant-expired-or-revoked",
                    blocker_code=inner_exc.reason_code,
                    blocker_detail=str(inner_exc),
                    decision_owner="customer-installation-admin",
                )
        else:
            return _build_blocked_result(
                state,
                classification="grant-expired-or-revoked",
                blocker_code=exc.reason_code,
                blocker_detail=str(exc),
                decision_owner="customer-installation-admin",
            )

    if state.pinned_grant_id and verified_grant.grant.grant_id != state.pinned_grant_id:
        return _build_blocked_result(
            state,
            classification="grant-expired-or-revoked",
            blocker_code="grant_id_mismatch",
            blocker_detail="Presented grant_id does not match the installation's pinned grant_id.",
            decision_owner="customer-installation-admin",
        )
    if (
        state.pinned_grant_scope_digest
        and verified_grant.grant.revision == state.pinned_grant_revision
        and verified_grant.grant.scope_digest != state.pinned_grant_scope_digest
    ):
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="cache_scope_mismatch",
            blocker_detail=("Grant scope digest mutated without advancing the grant revision."),
            decision_owner="customer-installation-admin",
        )
    if (
        expected_grant_scope_digest is not None
        and verified_grant.grant.scope_digest != expected_grant_scope_digest
    ):
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="cache_scope_mismatch",
            blocker_detail=(
                "Catalog response scope digest does not match this installation's grant."
            ),
            decision_owner="customer-installation-admin",
        )
    if not isinstance(export_scope_signature, str) or not export_scope_signature.strip():
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="export_scope_signature_invalid",
            blocker_detail="Export scope binding signature is required.",
            decision_owner="customer-installation-admin",
        )
    mode = "recovery" if recovery_only else "active"
    scope_msg = b"fdai.export-grant-scope.v1\n" + (
        f"{export_digest}:{revision}:{state.installation_id}:"
        f"{verified_grant.grant.grant_id}:{verified_grant.grant.revision}:"
        f"{verified_grant.grant.scope_digest}:{mode}"
    ).encode("ascii")
    try:
        export_public_key.verify(b64decode(export_scope_signature, validate=True), scope_msg)
    except (InvalidSignature, ValueError):
        return _build_blocked_result(
            state,
            classification="catalog-untrusted",
            blocker_code="export_scope_signature_invalid",
            blocker_detail=(
                "Export scope binding signature failed verification against the Release Hub "
                "key; stale or cross-grant export replay rejected."
            ),
            decision_owner="customer-installation-admin",
        )
    state = replace(
        state,
        pinned_grant_id=verified_grant.grant.grant_id,
        pinned_grant_revision=verified_grant.grant.revision,
        pinned_grant_scope_digest=verified_grant.grant.scope_digest,
    )

    raw_releases = doc.get("releases") or {}
    raw_channels = doc.get("channels") or {}
    raw_recalls = doc.get("recalls") or []
    recalls = tuple(RecallRecord(**r) for r in raw_recalls if isinstance(r, dict))

    parsed_releases: dict[str, LifecycleRelease] = {}
    for rel_id, art in raw_releases.items():
        if isinstance(art, dict) and isinstance(art.get("manifest"), str):
            parsed_releases[str(rel_id)] = parse_lifecycle_release_manifest(
                art["manifest"].encode("utf-8")
            )

    current_rel = parsed_releases.get(state.current_release_id)
    current_recalled = False
    if current_rel is not None:
        eval_cur = evaluate_recall_candidate(
            release_id=state.current_release_id,
            capability_ids=tuple(sorted(current_rel.capability_maximums)),
            recall_records=recalls,
        )
        current_recalled = not eval_cur.allowed
    elif not evaluate_recall_candidate(
        release_id=state.current_release_id,
        capability_ids=(),
        recall_records=recalls,
    ).allowed:
        current_recalled = True

    if recovery_only and not current_recalled:
        return _build_blocked_result(
            state,
            classification="grant-expired-or-revoked",
            blocker_code="grant_expired" if not verified_grant.grant.revoked else "grant_revoked",
            blocker_detail=(
                "Distribution grant is expired or revoked; routine upgrades are held while "
                "installed workload continues."
            ),
            decision_owner="customer-installation-admin",
        )

    target_stencil_id = state.current_stencil_id if current_recalled else state.selected_stencil_id
    stencil_switching = target_stencil_id != state.current_stencil_id

    if stencil_switching:
        if target_stencil_id not in verified_grant.grant.allowed_stencil_ids:
            return _build_blocked_result(
                state,
                classification="grant-expired-or-revoked",
                blocker_code="stencil_transition_grant_missing",
                blocker_detail=(
                    f"Distribution grant does not permit switching to Stencil "
                    f"{target_stencil_id!r}."
                ),
                decision_owner="customer-installation-admin",
            )
        if state.configuration_stencil_id != target_stencil_id:
            return _build_blocked_result(
                state,
                classification="blocked-prerequisite",
                blocker_code="stencil_transition_config_unreviewed",
                blocker_detail=(
                    "Stencil switch requires a customer-reviewed configuration revision for the "
                    "target Stencil."
                ),
                decision_owner="customer-configuration-owner",
            )
        if state.runtime_bundle_stencil_id != target_stencil_id:
            return _build_blocked_result(
                state,
                classification="blocked-prerequisite",
                blocker_code="stencil_transition_bundle_mismatch",
                blocker_detail=(
                    "Stencil switch requires a RuntimeBundle bound to the target Stencil."
                ),
                decision_owner="customer-installation-admin",
            )

    channel_members = [
        str(rid)
        for rid in (raw_channels.get(state.subscribed_channel) or [])
        if str(rid) in parsed_releases
    ]
    matching_candidates: list[tuple[str, LifecycleRelease]] = []
    for rid in channel_members:
        rel = parsed_releases[rid]
        binding = extract_stencil_variant_binding(rid, rel)
        if binding is None or binding.stencil_id != target_stencil_id:
            continue
        rec_eval = evaluate_recall_candidate(
            release_id=rid,
            capability_ids=tuple(sorted(rel.capability_maximums)),
            recall_records=recalls,
        )
        if not rec_eval.allowed:
            continue
        if current_recalled:
            matching_candidates.append((rid, rel))
        elif stencil_switching or compare_release_ids(rid, state.current_release_id) > 0:
            matching_candidates.append((rid, rel))

    matching_candidates.sort(key=lambda item: item[0], reverse=True)
    if not matching_candidates:
        if current_recalled:
            return _build_blocked_result(
                state,
                classification="recovery-rolloff-required",
                blocker_code="no_safe_rolloff_candidate",
                blocker_detail=(
                    "Current release is recalled and no non-recalled roll-off candidate is "
                    "available."
                ),
                decision_owner="vendor-release-operator",
            )
        next_state = replace(
            state,
            catalog_minimum_revision=revision,
            last_accepted_export_digest=export_digest,
        )
        return _build_up_to_date_result(next_state)

    proposed_id, proposed_rel = matching_candidates[0]
    diff = _compute_feature_diff(current_rel, proposed_rel)

    # Check schema compatibility: never fabricate schema rollback or silently purge data (#2533).
    if isinstance(proposed_rel, ApplicationRelease) and proposed_rel.schema_target > 0:
        if proposed_rel.schema_target < state.current_schema_revision and not (
            proposed_rel.schema_range.minimum
            <= state.current_schema_revision
            <= proposed_rel.schema_range.maximum
        ):
            return _build_blocked_result(
                state,
                classification="blocked-prerequisite",
                blocker_code="stencil_transition_schema_rollback_forbidden",
                blocker_detail=(
                    "Target Stencil/Release requires an incompatible lower database schema "
                    "revision; silent data purge or fabricated schema rollback is forbidden."
                ),
                decision_owner="customer-database-owner",
                proposed_release_id=proposed_id,
                proposed_stencil_id=target_stencil_id,
                changed_features=diff,
            )

    try:
        variant_binding = verify_release_plan_bundle_stencil_binding(
            release_id=proposed_id,
            release=proposed_rel,
            expected_stencil_id=target_stencil_id,
            runtime_bundle_workloads=state.runtime_bundle_workloads,
            runtime_bundle_component_images=state.runtime_bundle_component_images,
            runtime_bundle_stencil_id=state.runtime_bundle_stencil_id,
            configuration_stencil_id=state.configuration_stencil_id,
            grant=None if recovery_only else verified_grant.grant,
            channel=None if recovery_only else state.subscribed_channel,
        )
    except StencilBindingError as exc:
        return _build_blocked_result(
            state,
            classification="blocked-prerequisite",
            blocker_code=exc.reason_code,
            blocker_detail=str(exc),
            decision_owner="customer-installation-admin",
            proposed_release_id=proposed_id,
            proposed_stencil_id=target_stencil_id,
            changed_features=diff,
        )

    if variant_binding is None:
        raise RuntimeError("Expected StencilVariantBinding for verified Stencil candidate.")
    updated_mirror = mirror.mirror_release(
        proposed_rel,
        available_upstream_digests=tuple(variant_binding.component_digests.values()),
    )
    mirrored = tuple(sorted(updated_mirror.mirrored_digests))

    if not state.inputs_staged or not state.db_and_model_ready:
        return _build_blocked_result(
            state,
            classification="blocked-prerequisite",
            blocker_code="prerequisites_unprepared",
            blocker_detail=(
                "Catalog candidate is accepted, but staged inputs or DB/model prerequisites "
                "are not ready."
            ),
            decision_owner="customer-lifecycle-operator",
            proposed_release_id=proposed_id,
            proposed_stencil_id=target_stencil_id,
            changed_features=diff,
            mirrored_digests=mirrored,
        )

    if not state.agent_active:
        return _build_blocked_result(
            state,
            classification="agent-inactive",
            blocker_code="lifecycle_agent_inactive",
            blocker_detail=(
                "Catalog candidate is staged, but the cluster Lifecycle Agent is inactive; "
                "executable readiness is false."
            ),
            decision_owner="customer-platform-operator",
            proposed_release_id=proposed_id,
            proposed_stencil_id=target_stencil_id,
            changed_features=diff,
            mirrored_digests=mirrored,
        )

    plan_type = (
        "recall-rolloff"
        if current_recalled
        else ("configuration-change" if stencil_switching else "upgrade")
    )
    plan_digest = "sha256:" + canonical_digest(
        {
            "installation_id": state.installation_id,
            "plan_type": plan_type,
            "target_release_id": proposed_id,
            "target_release_digest": variant_binding.release_digest,
            "stencil_id": variant_binding.stencil_id,
            "stencil_digest": variant_binding.stencil_digest,
            "configuration_revision_digest": state.configuration_revision_digest,
        }
    )

    if not state.maintenance_window_open and not current_recalled:
        next_state = replace(
            state,
            catalog_minimum_revision=revision,
            last_accepted_export_digest=export_digest,
        )
        view = build_customer_stencil_readiness_view(
            next_state,
            classification="scheduled-waiting-window",
            executable_readiness=True,
            proposed_release_id=proposed_id,
            proposed_stencil_id=target_stencil_id,
            changed_features=diff,
            blocker_code=None,
            blocker_detail=None,
            decision_owner="automatic-maintenance-window",
        )
        return StencilUpdateReconciliationResult(
            installation_id=state.installation_id,
            classification="scheduled-waiting-window",
            executable_readiness=True,
            plan_issued=True,
            plan_type=plan_type,
            plan_digest=plan_digest,
            applied_in_window=False,
            current_release_id=state.current_release_id,
            current_stencil_id=state.current_stencil_id,
            proposed_release_id=proposed_id,
            proposed_stencil_id=target_stencil_id,
            blocker_code=None,
            blocker_detail=None,
            decision_owner="automatic-maintenance-window",
            inter_party_handoff_count=0,
            additional_customer_apply_clicks=0,
            outside_window_mutations=0,
            changed_features=diff,
            mirrored_digests=mirrored,
            updated_state=next_state,
            readiness_view=view,
        )

    # Readback-before-replay: if this exact plan_digest was already applied, do not re-mutate.
    already_applied = state.last_applied_plan_digest == plan_digest
    next_journal_seq = (
        state.pvc_journal_sequence if already_applied else state.pvc_journal_sequence + 1
    )
    proposed_schema_target = proposed_rel.schema_target or 0
    applied_state = replace(
        state,
        current_release_id=proposed_id,
        current_stencil_id=variant_binding.stencil_id,
        current_stencil_digest=variant_binding.stencil_digest,
        current_schema_revision=max(state.current_schema_revision, proposed_schema_target),
        pvc_journal_sequence=next_journal_seq,
        catalog_minimum_revision=revision,
        last_accepted_export_digest=export_digest,
        last_applied_plan_digest=plan_digest,
        last_agent_report={
            "reported_release_id": proposed_id,
            "reported_stencil_id": variant_binding.stencil_id,
            "plan_digest": plan_digest,
            "status": "healthy",
            "idempotent_replay_skipped": already_applied,
        },
        last_failure=None,
    )
    view = build_customer_stencil_readiness_view(
        applied_state,
        classification="verified-ready",
        executable_readiness=True,
        proposed_release_id=proposed_id,
        proposed_stencil_id=variant_binding.stencil_id,
        changed_features=diff,
        blocker_code=None,
        blocker_detail=None,
        decision_owner="none-automatic",
    )
    return StencilUpdateReconciliationResult(
        installation_id=state.installation_id,
        classification="verified-ready",
        executable_readiness=True,
        plan_issued=True,
        plan_type=plan_type,
        plan_digest=plan_digest,
        applied_in_window=True,
        current_release_id=applied_state.current_release_id,
        current_stencil_id=applied_state.current_stencil_id,
        proposed_release_id=proposed_id,
        proposed_stencil_id=variant_binding.stencil_id,
        blocker_code=None,
        blocker_detail=None,
        decision_owner="none-automatic",
        inter_party_handoff_count=0,
        additional_customer_apply_clicks=0,
        outside_window_mutations=0,
        changed_features=diff,
        mirrored_digests=mirrored,
        updated_state=applied_state,
        readiness_view=view,
    )


def _build_up_to_date_result(state: StencilInstallationState) -> StencilUpdateReconciliationResult:
    empty_diff = _compute_feature_diff(None, None)
    view = build_customer_stencil_readiness_view(
        state,
        classification="up-to-date",
        executable_readiness=state.agent_active and state.inputs_staged,
        proposed_release_id=None,
        proposed_stencil_id=None,
        changed_features=empty_diff,
        blocker_code=None,
        blocker_detail=None,
        decision_owner="none-automatic",
    )
    return StencilUpdateReconciliationResult(
        installation_id=state.installation_id,
        classification="up-to-date",
        executable_readiness=state.agent_active and state.inputs_staged,
        plan_issued=False,
        plan_type=None,
        plan_digest=None,
        applied_in_window=False,
        current_release_id=state.current_release_id,
        current_stencil_id=state.current_stencil_id,
        proposed_release_id=None,
        proposed_stencil_id=None,
        blocker_code=None,
        blocker_detail=None,
        decision_owner="none-automatic",
        inter_party_handoff_count=0,
        additional_customer_apply_clicks=0,
        outside_window_mutations=0,
        changed_features=empty_diff,
        mirrored_digests=(),
        updated_state=state,
        readiness_view=view,
    )


def _build_blocked_result(
    state: StencilInstallationState,
    *,
    classification: ReadinessClassification,
    blocker_code: str,
    blocker_detail: str,
    decision_owner: str,
    proposed_release_id: str | None = None,
    proposed_stencil_id: str | None = None,
    changed_features: Mapping[str, list[str]] | None = None,
    mirrored_digests: tuple[str, ...] = (),
) -> StencilUpdateReconciliationResult:
    diff = (
        dict(changed_features)
        if changed_features is not None
        else _compute_feature_diff(None, None)
    )
    failed_state = replace(
        state,
        last_failure={
            "blocker_code": blocker_code,
            "blocker_detail": blocker_detail,
            "decision_owner": decision_owner,
        },
    )
    view = build_customer_stencil_readiness_view(
        failed_state,
        classification=classification,
        executable_readiness=False,
        proposed_release_id=proposed_release_id,
        proposed_stencil_id=proposed_stencil_id,
        changed_features=diff,
        blocker_code=blocker_code,
        blocker_detail=blocker_detail,
        decision_owner=decision_owner,
    )
    return StencilUpdateReconciliationResult(
        installation_id=state.installation_id,
        classification=classification,
        executable_readiness=False,
        plan_issued=False,
        plan_type=None,
        plan_digest=None,
        applied_in_window=False,
        current_release_id=state.current_release_id,
        current_stencil_id=state.current_stencil_id,
        proposed_release_id=proposed_release_id,
        proposed_stencil_id=proposed_stencil_id,
        blocker_code=blocker_code,
        blocker_detail=blocker_detail,
        decision_owner=decision_owner,
        inter_party_handoff_count=0,
        additional_customer_apply_clicks=0,
        outside_window_mutations=0,
        changed_features=diff,
        mirrored_digests=mirrored_digests,
        updated_state=failed_state,
        readiness_view=view,
    )


def build_customer_stencil_readiness_view(
    state: StencilInstallationState,
    *,
    classification: ReadinessClassification,
    executable_readiness: bool,
    proposed_release_id: str | None,
    proposed_stencil_id: str | None,
    changed_features: Mapping[str, list[str]],
    blocker_code: str | None,
    blocker_detail: str | None,
    decision_owner: str,
) -> dict[str, Any]:
    """Build the unified customer Lifecycle Hub readiness and recovery view (#2535)."""
    if classification == "scheduled-waiting-window":
        next_action = {
            "action_id": "wait-for-maintenance-window",
            "label": (
                f"Scheduled automatic update at {state.next_window_starts_at} (no click required)"
            ),
            "label_ko": (
                f"다음 유지보수 윈도우({state.next_window_starts_at})에 자동 적용 예정 "
                "(추가 승인 클릭 불필요)"
            ),
            "decision_owner": decision_owner,
            "requires_extra_apply_click": False,
            "requires_machine_value_transcription": False,
        }
    elif classification in {"verified-ready", "up-to-date"}:
        next_action = {
            "action_id": "no-action-required",
            "label": "Installation is aligned with the entitled Stencil channel",
            "label_ko": "설치 환경이 승인된 Stencil 채널과 최신 상태로 동기화되어 있습니다",
            "decision_owner": "none-automatic",
            "requires_extra_apply_click": False,
            "requires_machine_value_transcription": False,
        }
    else:
        next_action = {
            "action_id": f"resolve-{blocker_code or 'blocker'}",
            "label": f"Resolve {blocker_code}: {blocker_detail}",
            "label_ko": f"차단 사유({blocker_code}) 해결 필요: {blocker_detail}",
            "decision_owner": decision_owner,
            "requires_extra_apply_click": False,
            "requires_machine_value_transcription": False,
        }

    return {
        "installation_id": state.installation_id,
        "current_stencil_id": state.current_stencil_id,
        "current_version": state.current_release_id,
        "proposed_stencil_id": proposed_stencil_id,
        "proposed_version": proposed_release_id,
        "changed_features": dict(changed_features),
        "classification": classification,
        "executable_readiness": executable_readiness,
        "catalog_accepted": state.last_accepted_export_digest is not None,
        "inputs_staged": state.inputs_staged,
        "agent_active": state.agent_active,
        "next_execution_window": state.next_window_starts_at,
        "check_interval_seconds": state.check_interval_seconds,
        "jitter_seconds": state.jitter_seconds,
        "last_agent_report": dict(state.last_agent_report) if state.last_agent_report else None,
        "primary_next_action": next_action,
        "preservation_guarantees": {
            "trial_anchor_created_at": state.trial_anchor_created_at,
            "runtime_entitlement_digest": state.runtime_entitlement_digest,
            "installation_key_id": state.installation_key_id,
            "pvc_journal_sequence": state.pvc_journal_sequence,
        },
        "recovery_context": {
            "original_failure": dict(state.last_failure) if state.last_failure else None,
            "current_workload_release": state.current_release_id,
            "current_workload_stencil": state.current_stencil_id,
            "retained_evidence_digest": state.last_applied_plan_digest,
            "owner": decision_owner,
            "safe_resume_action": next_action["action_id"],
        },
    }


__all__ = [
    "ReadinessClassification",
    "StencilInstallationState",
    "StencilUpdateReconciliationResult",
    "build_customer_stencil_readiness_view",
    "reconcile_stencil_update",
]

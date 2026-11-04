"""Comprehensive tests for Stencil Epic #2524 (#2525-#2536) across SQLite and PostgreSQL."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_plan import LifecycleEffectEnvelope, LifecyclePlan
from fdai_deployment_cli.lifecycle_promotion import BoundaryRegistryMirror
from fdai_deployment_cli.lifecycle_release import (
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.lifecycle_stencil_grant import (
    StencilBindingError,
    format_variant_release_id,
    issue_stencil_distribution_grant,
    split_variant_release_id,
    verify_release_plan_bundle_stencil_binding,
    verify_stencil_distribution_grant,
)
from scripts.deployment.local.rehearse_stencil_epic_2524 import (
    run_stencil_epic_2524_qualification,
)
from sqlalchemy import create_engine, text
from starlette.testclient import TestClient

from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.stencil_update_flow import (
    StencilInstallationState,
    reconcile_stencil_update,
)
from fdai_release_hub.api import create_app
from fdai_release_hub.stencil_product_decisions import (
    F01_TO_F15_FEATURE_MAPPING,
    REVIEWED_STENCIL_DRAFTS,
    STENCIL_PRODUCT_DECISION_REGISTER,
    build_reviewed_stencil_candidate_set,
    verify_physical_stencil_exclusion,
)
from fdai_release_hub.stencils import CONSOLE_PANEL_CATALOG, STENCIL_PRESETS
from fdai_release_hub.store import Change, ReleaseStore

NOW = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC)
SOURCE_SHA = "a648e8fb0313dce62378422ffd663fe30ba1d83b"


def test_reviewed_stencil_drafts_feature_mapping_and_physical_exclusion() -> None:
    basic = REVIEWED_STENCIL_DRAFTS["basic"]
    premium = REVIEWED_STENCIL_DRAFTS["premium"]
    regulated = REVIEWED_STENCIL_DRAFTS["regulated"]
    full = REVIEWED_STENCIL_DRAFTS["full"]

    assert basic.stencil_id == "lite-observe-alert"
    assert premium.stencil_id == "standard-sre"
    assert regulated.stencil_id == "regulated-governance"
    assert full.stencil_id == "full-enterprise"

    # Premium and Regulated are independent: neither is a subset of the other (#2525)
    assert not set(premium.enabled_panel_ids).issubset(set(regulated.enabled_panel_ids))
    assert not set(regulated.enabled_panel_ids).issubset(set(premium.enabled_panel_ids))
    assert "hil-queue" in premium.enabled_panel_ids
    assert "hil-queue" not in regulated.enabled_panel_ids
    assert "code-security" in regulated.enabled_panel_ids
    assert "code-security" not in premium.enabled_panel_ids
    assert "assurance-twin" in regulated.enabled_panel_ids
    assert "github" not in regulated.enabled_panel_ids

    # Every feature ID referenced by CONSOLE_PANEL_CATALOG is mapped in F01_TO_F15_FEATURE_MAPPING
    referenced_fids = {fid for panel in CONSOLE_PANEL_CATALOG for fid in panel.feature_ids}
    assert referenced_fids.issubset(set(F01_TO_F15_FEATURE_MAPPING))
    assert len(STENCIL_PRODUCT_DECISION_REGISTER) >= 5

    # Physical exclusion checks (#2526)
    proof_cost = verify_physical_stencil_exclusion(full, basic, feature_panel_id="cost-governance")
    assert proof_cost["included_gate_allowed"] is True
    assert proof_cost["excluded_gate_allowed"] is False
    assert proof_cost["console_chunk_pruned_in_excluded"] is True
    assert "cost-governance" in proof_cost["physically_omitted_loops"]

    proof_hil = verify_physical_stencil_exclusion(premium, regulated, feature_panel_id="hil-queue")
    assert "isolated-executor" in proof_hil["physically_omitted_workloads"]
    assert "remediation-execution" in proof_hil["physically_omitted_loops"]


def test_variant_identity_plan_bundle_binding_and_grant_verification() -> None:
    assert format_variant_release_id("0.5.0", "lite-observe-alert") == "0.5.0-lite-observe-alert"
    assert split_variant_release_id("0.5.0-lite-observe-alert", "lite-observe-alert") == "0.5.0"

    with pytest.raises(StencilBindingError) as exc_info:
        split_variant_release_id("0.5.0+build1", "lite-observe-alert")
    assert exc_info.value.reason_code == "invalid_release_id"

    candidates = build_reviewed_stencil_candidate_set(
        source_commit=SOURCE_SHA, base_release_version="0.5.0"
    )
    lite_cand = candidates["lite-observe-alert"]
    lite_rel = parse_lifecycle_release_manifest(
        lite_cand["canonical_manifest_bytes"].encode("utf-8")
    )

    grant_priv = Ed25519PrivateKey.generate()
    grant_pub = grant_priv.public_key()
    other_priv = Ed25519PrivateKey.generate()

    # Reject DEV channel in customer distribution grant (#2529)
    with pytest.raises(StencilBindingError) as dev_exc:
        issue_stencil_distribution_grant(
            private_key=grant_priv,
            grant_id="grant-bad-dev",
            installation_id="inst-01",
            customer_principal="entra:op-01",
            allowed_stencil_ids=("lite-observe-alert",),
            allowed_channels=("DEV", "RELEASE"),
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )
    assert dev_exc.value.reason_code == "dev_channel_forbidden_in_customer_grant"

    signed_grant = issue_stencil_distribution_grant(
        private_key=grant_priv,
        grant_id="grant-01",
        installation_id="inst-01",
        customer_principal="entra:op-01",
        allowed_stencil_ids=("lite-observe-alert",),
        allowed_channels=("RELEASE_CANDIDATE", "RELEASE"),
        revision=2,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )

    verified = verify_stencil_distribution_grant(
        signed_grant.to_envelope(),
        trusted_public_keys=(grant_pub,),
        expected_installation_id="inst-01",
        expected_customer_principal="entra:op-01",
        minimum_revision=2,
        now=NOW + timedelta(hours=1),
    )
    assert verified.grant.grant_id == "grant-01"
    assert verified.grant.runtime_license_granted is False
    assert verified.grant.execution_authority_granted is False

    # Wrong principal, wrong installation, lower revision, wrong key, expired grant all fail closed
    with pytest.raises(StencilBindingError) as wrong_key_exc:
        verify_stencil_distribution_grant(
            signed_grant.to_envelope(),
            trusted_public_keys=(other_priv.public_key(),),
            now=NOW,
        )
    assert wrong_key_exc.value.reason_code == "untrusted_grant_issuer"

    with pytest.raises(StencilBindingError) as wrong_inst_exc:
        verify_stencil_distribution_grant(
            signed_grant.to_envelope(),
            trusted_public_keys=(grant_pub,),
            expected_installation_id="inst-other",
            now=NOW,
        )
    assert wrong_inst_exc.value.reason_code == "grant_installation_mismatch"

    with pytest.raises(StencilBindingError) as rollback_exc:
        verify_stencil_distribution_grant(
            signed_grant.to_envelope(),
            trusted_public_keys=(grant_pub,),
            minimum_revision=3,
            now=NOW,
        )
    assert rollback_exc.value.reason_code == "grant_revision_rollback"

    with pytest.raises(StencilBindingError) as exp_exc:
        verify_stencil_distribution_grant(
            signed_grant.to_envelope(),
            trusted_public_keys=(grant_pub,),
            now=NOW + timedelta(days=8),
        )
    assert exp_exc.value.reason_code == "grant_expired"

    # Cross-layer Release / Plan / Bundle verification (#2528)
    plan = LifecyclePlan(
        plan_id="plan-01",
        audience="inst-01",
        hub_key_epoch=1,
        hub_key_id="hub-01",
        source_state_digest="sha256:" + "1" * 64,
        sequence=1,
        fencing_generation=1,
        plan_type="upgrade",
        target_release_id="0.5.0-lite-observe-alert",
        target_release_digest=lite_rel.digest,
        configuration_revision_digest="sha256:" + "2" * 64,
        entity_ids=frozenset({"fdai-workloads"}),
        capability_ids=("stencil:lite-observe-alert", "core-control-plane", "operator-service"),
        release_regions=frozenset({"koreacentral"}),
        rollback_target_plan_id=None,
        declared_duration_minutes=15,
        envelope=LifecycleEffectEnvelope(
            entity_ids=frozenset({"fdai-workloads"}),
            regions=frozenset({"koreacentral"}),
            capability_modes={"stencil:lite-observe-alert": "shadow"},
            destructive_allowed=False,
            max_duration_minutes=30,
        ),
        expires_at=NOW + timedelta(hours=1),
        signed_payload=b"{}",
        signature=b"sig",
    )
    binding = verify_release_plan_bundle_stencil_binding(
        release_id="0.5.0-lite-observe-alert",
        release=lite_rel,
        expected_stencil_id="lite-observe-alert",
        plan=plan,
        runtime_bundle_workloads=("core-control-plane", "operator-service"),
        runtime_bundle_component_images=lite_cand["provenance"]["component_digests"],
        runtime_bundle_stencil_id="lite-observe-alert",
        configuration_stencil_id="lite-observe-alert",
        grant=verified.grant,
        channel="RELEASE",
    )
    assert binding is not None
    assert binding.variant_key == "0.5.0@lite-observe-alert"

    # Reject excluded workload present in RuntimeBundle
    with pytest.raises(StencilBindingError) as leak_exc:
        verify_release_plan_bundle_stencil_binding(
            release_id="0.5.0-lite-observe-alert",
            release=lite_rel,
            runtime_bundle_workloads=(
                "core-control-plane",
                "operator-service",
                "isolated-executor",
            ),
        )
    assert leak_exc.value.reason_code == "bundle_excluded_workload_present"


def test_stencil_update_transition_guardrails_and_recall_recovery(tmp_path: Path) -> None:
    from fdai_release_hub.catalog_serialization import CatalogError

    hub_key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    grant_priv = Ed25519PrivateKey.generate()
    grant_pub = grant_priv.public_key()

    candidates_050 = build_reviewed_stencil_candidate_set(
        source_commit=SOURCE_SHA, base_release_version="0.5.0"
    )
    candidates_051 = build_reviewed_stencil_candidate_set(
        source_commit=SOURCE_SHA, base_release_version="0.5.1"
    )
    lite_050_bytes = candidates_050["lite-observe-alert"]["canonical_manifest_bytes"]
    lite_051_bytes = candidates_051["lite-observe-alert"]["canonical_manifest_bytes"]
    std_051_bytes = candidates_051["standard-sre"]["canonical_manifest_bytes"]

    clock_box = [NOW]
    store = ReleaseStore(
        tmp_path / "test-stencil-flow.sqlite",
        hub_key,
        clock=lambda: clock_box[0],
    )
    for rel_id, raw_str in (
        ("0.5.0-lite-observe-alert", lite_050_bytes),
        ("0.5.1-lite-observe-alert", lite_051_bytes),
        ("0.5.1-standard-sre", std_051_bytes),
    ):
        clock_box[0] += timedelta(seconds=5)
        snap = store.change(
            "register",
            rel_id,
            Change(
                revision=store.snapshot()["revision"],
                confirmation=rel_id,
                reason="reg",
                manifest=raw_str,
            ),
        )
        clock_box[0] += timedelta(seconds=5)
        snap = store.change(
            "publish",
            rel_id,
            Change(revision=snap["revision"], confirmation=rel_id, reason="pub"),
        )
        clock_box[0] += timedelta(seconds=5)
        store.change(
            "contribute",
            rel_id,
            Change(
                revision=snap["revision"],
                confirmation=rel_id,
                reason="rel",
                channel="RELEASE",
            ),
        )

    grant = issue_stencil_distribution_grant(
        private_key=grant_priv,
        grant_id="grant-flow-01",
        installation_id="inst-flow-01",
        customer_principal="entra:flow-admin",
        allowed_stencil_ids=("lite-observe-alert", "standard-sre"),
        allowed_channels=("RELEASE",),
        revision=1,
        issued_at=clock_box[0],
        expires_at=clock_box[0] + timedelta(days=10),
    )

    from fdai_release_hub.stencil_grants import (
        build_scoped_customer_export,
        register_or_renew_grant,
    )

    register_or_renew_grant(
        store,
        grant.to_envelope(),
        trusted_public_keys=(grant_pub,),
        now=clock_box[0],
    )
    # Customer without presented envelope is rejected (401)
    with pytest.raises(CatalogError):
        build_scoped_customer_export(
            store,
            installation_id="inst-flow-01",
            customer_principal="entra:flow-admin",
            trusted_public_keys=(grant_pub,),
            presented_envelope=None,
            now=clock_box[0],
        )
    scoped = build_scoped_customer_export(
        store,
        installation_id="inst-flow-01",
        customer_principal="entra:flow-admin",
        trusted_public_keys=(grant_pub,),
        presented_envelope=grant.to_envelope(),
        now=clock_box[0],
    )

    base_state = StencilInstallationState(
        installation_id="inst-flow-01",
        customer_principal="entra:flow-admin",
        subscribed_channel="RELEASE",
        current_release_id="0.5.0-lite-observe-alert",
        current_stencil_id="lite-observe-alert",
        current_stencil_digest=STENCIL_PRESETS["lite-observe-alert"].digest,
        current_schema_revision=0,
        selected_stencil_id="standard-sre",
        configuration_stencil_id="lite-observe-alert",
        configuration_revision_digest="sha256:" + "1" * 64,
        runtime_bundle_stencil_id="lite-observe-alert",
        runtime_bundle_workloads=("core-control-plane", "operator-service"),
        runtime_bundle_component_images=candidates_051["lite-observe-alert"]["provenance"][
            "component_digests"
        ],
        trial_anchor_created_at="2026-10-01T00:00:00+00:00",
        runtime_entitlement_digest="sha256:" + "9" * 64,
        installation_key_id="key-flow-01",
        pvc_journal_sequence=5,
    )

    # Unreviewed configuration blocks Stencil switch (#2533)
    blocked_switch = reconcile_stencil_update(
        base_state,
        scoped_export_raw=scoped.raw,
        export_signature=scoped.signature,
        export_scope_signature=scoped.scope_binding_signature,
        export_public_key=hub_key.public_key,
        grant_envelope=grant.to_envelope(),
        grant_issuer_public_keys=(grant_pub,),
        mirror=BoundaryRegistryMirror(),
        expected_grant_scope_digest=scoped.grant_scope_digest,
        now=clock_box[0],
    )
    assert blocked_switch.classification == "blocked-prerequisite"
    assert blocked_switch.blocker_code == "stencil_transition_config_unreviewed"
    assert blocked_switch.executable_readiness is False

    # Inactive Agent prevents executable readiness (#2535)
    inactive_agent_state = replace(
        base_state,
        selected_stencil_id="lite-observe-alert",
        agent_active=False,
    )
    inactive_res = reconcile_stencil_update(
        inactive_agent_state,
        scoped_export_raw=scoped.raw,
        export_signature=scoped.signature,
        export_scope_signature=scoped.scope_binding_signature,
        export_public_key=hub_key.public_key,
        grant_envelope=grant.to_envelope(),
        grant_issuer_public_keys=(grant_pub,),
        mirror=BoundaryRegistryMirror(),
        expected_grant_scope_digest=scoped.grant_scope_digest,
        now=clock_box[0],
    )
    assert inactive_res.classification == "agent-inactive"
    assert inactive_res.executable_readiness is False

    # Closed window schedules without extra apply click or outside-window mutation (#2533/#2535)
    closed_win_state = replace(
        base_state,
        selected_stencil_id="lite-observe-alert",
        maintenance_window_open=False,
    )
    scheduled_res = reconcile_stencil_update(
        closed_win_state,
        scoped_export_raw=scoped.raw,
        export_signature=scoped.signature,
        export_scope_signature=scoped.scope_binding_signature,
        export_public_key=hub_key.public_key,
        grant_envelope=grant.to_envelope(),
        grant_issuer_public_keys=(grant_pub,),
        mirror=BoundaryRegistryMirror(),
        expected_grant_scope_digest=scoped.grant_scope_digest,
        now=clock_box[0],
    )
    assert scheduled_res.classification == "scheduled-waiting-window"
    assert scheduled_res.plan_issued is True
    assert scheduled_res.applied_in_window is False
    assert scheduled_res.outside_window_mutations == 0
    assert (
        scheduled_res.readiness_view["primary_next_action"]["requires_extra_apply_click"] is False
    )


def test_end_to_end_rehearsal_and_postgres_persistence_parity() -> None:
    result = run_stencil_epic_2524_qualification(source_commit=SOURCE_SHA)
    assert result["schema_version"] == "fdai.stencil-epic-2524-qualification.v1"
    assert result["customer_isolation_and_delivery"]["dev_or_unentitled_leaks"] == 0
    assert result["customer_isolation_and_delivery"]["inter_party_handoff_count"] == 0
    assert result["customer_isolation_and_delivery"]["additional_customer_apply_clicks"] == 0
    assert result["customer_isolation_and_delivery"]["trial_anchor_preserved"] is True

    db_url = os.environ.get("FDAI_DATABASE_URL", "")
    if not db_url:
        pytest.fail("FDAI_DATABASE_URL must be bound via with-local-test-database.py")
    sa_url = (
        db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if db_url.startswith("postgresql://")
        else db_url
    )
    schema_name = f"test_stencil_2524_{os.urandom(4).hex()}"
    admin_engine = create_engine(sa_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    try:
        scoped_engine = create_engine(
            sa_url,
            connect_args={"options": f"-c search_path={schema_name}"},
        )
        hub_key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
        grant_priv = Ed25519PrivateKey.generate()
        grant_pub = grant_priv.public_key()
        clock_box = [NOW]
        pg_store = ReleaseStore(scoped_engine, hub_key, clock=lambda: clock_box[0])
        app = create_app(pg_store, grant_issuer_public_keys=(grant_pub,))
        candidates = build_reviewed_stencil_candidate_set(
            source_commit=SOURCE_SHA, base_release_version="0.5.0"
        )
        with TestClient(
            app,
            base_url="http://127.0.0.1:8091",
            client=("127.0.0.1", 50001),
        ) as client:
            lite_cand = candidates["lite-observe-alert"]
            resp = client.post(
                "/v1/releases/0.5.0-lite-observe-alert/workflow-jobs",
                json={
                    "job_id": "pg-job-1",
                    "idempotency_key": "pg-idem-1",
                    "release_id": "0.5.0-lite-observe-alert",
                    "stencil_id": "lite-observe-alert",
                    "source_commit": SOURCE_SHA,
                    "manifest": lite_cand["release_manifest"],
                },
            )
            assert resp.status_code == 200
            # Duplicate same-version variant registration under another ID fails 409 (#2528)
            dup_manifest = dict(lite_cand["release_manifest"])
            dup_manifest["release_version"] = "0.5.0-lite-observe-alert-dup"
            dup_resp = client.post(
                "/v1/releases/0.5.0-lite-observe-alert-dup/register",
                json={
                    "revision": pg_store.snapshot()["revision"],
                    "confirmation": "0.5.0-lite-observe-alert-dup",
                    "reason": "attempt duplicate variant",
                    "manifest": __import__("json").dumps(dup_manifest),
                },
            )
            assert dup_resp.status_code == 409

            # Simulate mid-flight workflow job crash (job row stuck in 'running')
            from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest

            from fdai_release_hub.database import release_workflow_jobs

            std_cand = candidates["standard-sre"]
            std_raw = canonical_bytes(std_cand["release_manifest"]).decode("utf-8")
            pg_store.change(
                "register",
                "0.5.0-standard-sre",
                Change(
                    revision=pg_store.snapshot()["revision"],
                    confirmation="0.5.0-standard-sre",
                    reason="register before simulated crash",
                    manifest=std_raw,
                ),
            )
            std_input_digest = "sha256:" + canonical_digest(
                {
                    "release_id": "0.5.0-standard-sre",
                    "stencil_id": "standard-sre",
                    "source_commit": SOURCE_SHA,
                    "manifest": std_raw,
                }
            )
            with pg_store.connect() as db:
                db.execute(
                    release_workflow_jobs.insert().values(
                        job_id="pg-job-crash",
                        idempotency_key="pg-idem-crash",
                        release_id="0.5.0-standard-sre",
                        stencil_id="standard-sre",
                        source_commit=SOURCE_SHA,
                        stage="reserved",
                        status="running",
                        input_digest=std_input_digest,
                        manifest_digest="sha256:" + "0" * 64,
                        actor="vendor-operator",
                        error_code=None,
                        result_json="{}",
                        created_at=NOW.isoformat(),
                        updated_at=NOW.isoformat(),
                    )
                )
            recovered_resp = client.post(
                "/v1/releases/0.5.0-standard-sre/workflow-jobs",
                json={
                    "job_id": "pg-job-crash-retry",
                    "idempotency_key": "pg-idem-crash",
                    "release_id": "0.5.0-standard-sre",
                    "stencil_id": "standard-sre",
                    "source_commit": SOURCE_SHA,
                    "manifest": std_cand["release_manifest"],
                },
            )
            assert recovered_resp.status_code == 200
            assert recovered_resp.json()["status"] == "resumed"
            assert recovered_resp.json()["resumed_from_durable_state"] is True
            assert recovered_resp.json()["result"]["state"] == "published"
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


def test_lifecycle_hub_stencil_routes_integration(tmp_path: Path) -> None:

    from fdai_lifecycle_hub.api import create_app as create_hub_app
    from fdai_lifecycle_hub.store import HubStore
    from fdai_release_hub.stencil_grants import (
        build_scoped_customer_export,
        register_or_renew_grant,
    )

    hub_key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    grant_priv = Ed25519PrivateKey.generate()
    grant_pub = grant_priv.public_key()

    candidates_050 = build_reviewed_stencil_candidate_set(
        source_commit=SOURCE_SHA, base_release_version="0.5.0"
    )
    candidates_051 = build_reviewed_stencil_candidate_set(
        source_commit=SOURCE_SHA, base_release_version="0.5.1"
    )
    clock_box = [NOW]
    rel_store = ReleaseStore(tmp_path / "rel-hub.sqlite", hub_key, clock=lambda: clock_box[0])
    for rel_id, raw_str in (
        (
            "0.5.0-lite-observe-alert",
            candidates_050["lite-observe-alert"]["canonical_manifest_bytes"],
        ),
        (
            "0.5.1-lite-observe-alert",
            candidates_051["lite-observe-alert"]["canonical_manifest_bytes"],
        ),
    ):
        clock_box[0] += timedelta(seconds=5)
        snap = rel_store.change(
            "register",
            rel_id,
            Change(
                revision=rel_store.snapshot()["revision"],
                confirmation=rel_id,
                reason="reg",
                manifest=raw_str,
            ),
        )
        clock_box[0] += timedelta(seconds=5)
        snap = rel_store.change(
            "publish",
            rel_id,
            Change(revision=snap["revision"], confirmation=rel_id, reason="pub"),
        )
        clock_box[0] += timedelta(seconds=5)
        rel_store.change(
            "contribute",
            rel_id,
            Change(revision=snap["revision"], confirmation=rel_id, reason="rel", channel="RELEASE"),
        )

    grant = issue_stencil_distribution_grant(
        private_key=grant_priv,
        grant_id="grant-lhub-01",
        installation_id="inst-lhub-01",
        customer_principal="entra:lhub-admin@contoso.com",
        allowed_stencil_ids=("lite-observe-alert",),
        allowed_channels=("RELEASE",),
        revision=1,
        issued_at=clock_box[0],
        expires_at=clock_box[0] + timedelta(days=10),
    )
    register_or_renew_grant(
        rel_store, grant.to_envelope(), trusted_public_keys=(grant_pub,), now=clock_box[0]
    )
    scoped = build_scoped_customer_export(
        rel_store,
        installation_id="inst-lhub-01",
        customer_principal="entra:lhub-admin@contoso.com",
        trusted_public_keys=(grant_pub,),
        presented_envelope=grant.to_envelope(),
        now=clock_box[0],
    )

    hub_store = HubStore(create_engine(f"sqlite:///{tmp_path / 'lifecycle-hub.sqlite'}"))
    hub_app = create_hub_app(
        hub_store,
        clock=lambda: clock_box[0],
        stencil_export_public_key=hub_key.public_key,
        stencil_grant_issuer_public_keys=(grant_pub,),
    )
    cust_headers = {"X-FDAI-Customer-Principal": "entra:lhub-admin@contoso.com"}

    with TestClient(
        hub_app,
        base_url="http://127.0.0.1:8090",
        client=("127.0.0.1", 50002),
    ) as hub_client:
        # Unauthenticated header-only request is rejected with 401
        unauth_put = hub_client.put(
            "/v1/installations/inst-lhub-01/stencil-state",
            headers=cust_headers,
            json={
                "customer_principal": "entra:lhub-admin@contoso.com",
                "subscribed_channel": "RELEASE",
                "current_release_id": "0.5.0-lite-observe-alert",
                "current_stencil_id": "lite-observe-alert",
                "current_stencil_digest": STENCIL_PRESETS["lite-observe-alert"].digest,
                "current_schema_revision": 0,
                "selected_stencil_id": "lite-observe-alert",
                "configuration_stencil_id": "lite-observe-alert",
                "configuration_revision_digest": "sha256:" + "c" * 64,
                "runtime_bundle_stencil_id": "lite-observe-alert",
                "runtime_bundle_workloads": ["core-control-plane", "operator-service"],
                "runtime_bundle_component_images": candidates_051["lite-observe-alert"][
                    "provenance"
                ]["component_digests"],
                "trial_anchor_created_at": "2026-10-15T00:00:00+00:00",
                "runtime_entitlement_digest": "sha256:" + "e" * 64,
                "installation_key_id": "key-lhub-01",
                "pvc_journal_sequence": 1,
            },
        )
        assert unauth_put.status_code == 401

        login_resp = hub_client.post(
            "/v1/auth/entra/login",
            json={
                "mode": "msal_account",
                "principal": "lhub-admin@contoso.com",
                "display_name": "Lifecycle Hub Admin",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "client_id": "00000000-0000-0000-0000-000000000002",
            },
        )
        assert login_resp.status_code == 200

        # Caller attempt to write server-pinned grant fields in PUT /stencil-state is rejected (422)
        forged_pin_put = hub_client.put(
            "/v1/installations/inst-lhub-01/stencil-state",
            headers=cust_headers,
            json={
                "customer_principal": "entra:lhub-admin@contoso.com",
                "subscribed_channel": "RELEASE",
                "current_release_id": "0.5.0-lite-observe-alert",
                "current_stencil_id": "lite-observe-alert",
                "current_stencil_digest": STENCIL_PRESETS["lite-observe-alert"].digest,
                "current_schema_revision": 0,
                "selected_stencil_id": "lite-observe-alert",
                "configuration_stencil_id": "lite-observe-alert",
                "configuration_revision_digest": "sha256:" + "c" * 64,
                "runtime_bundle_stencil_id": "lite-observe-alert",
                "runtime_bundle_workloads": ["core-control-plane", "operator-service"],
                "runtime_bundle_component_images": candidates_051["lite-observe-alert"][
                    "provenance"
                ]["component_digests"],
                "trial_anchor_created_at": "2026-10-15T00:00:00+00:00",
                "runtime_entitlement_digest": "sha256:" + "e" * 64,
                "installation_key_id": "key-lhub-01",
                "pvc_journal_sequence": 1,
                "pinned_grant_scope_digest": scoped.grant_scope_digest,
            },
        )
        assert forged_pin_put.status_code == 422

        put_resp = hub_client.put(
            "/v1/installations/inst-lhub-01/stencil-state",
            headers=cust_headers,
            json={
                "customer_principal": "entra:lhub-admin@contoso.com",
                "subscribed_channel": "RELEASE",
                "current_release_id": "0.5.0-lite-observe-alert",
                "current_stencil_id": "lite-observe-alert",
                "current_stencil_digest": STENCIL_PRESETS["lite-observe-alert"].digest,
                "current_schema_revision": 0,
                "selected_stencil_id": "lite-observe-alert",
                "configuration_stencil_id": "lite-observe-alert",
                "configuration_revision_digest": "sha256:" + "c" * 64,
                "runtime_bundle_stencil_id": "lite-observe-alert",
                "runtime_bundle_workloads": ["core-control-plane", "operator-service"],
                "runtime_bundle_component_images": candidates_051["lite-observe-alert"][
                    "provenance"
                ]["component_digests"],
                "trial_anchor_created_at": "2026-10-15T00:00:00+00:00",
                "runtime_entitlement_digest": "sha256:" + "e" * 64,
                "installation_key_id": "key-lhub-01",
                "pvc_journal_sequence": 1,
                "grant_envelope": grant.to_envelope(),
            },
        )
        assert put_resp.status_code == 200

        # Another authenticated principal attempting to overwrite inst-lhub-01 is rejected (403)
        hub_client.post(
            "/v1/auth/entra/login",
            json={
                "mode": "msal_account",
                "principal": "other-user@contoso.com",
                "display_name": "Other User",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "client_id": "00000000-0000-0000-0000-000000000002",
            },
        )
        hijack_put = hub_client.put(
            "/v1/installations/inst-lhub-01/stencil-state",
            headers={"X-FDAI-Customer-Principal": "entra:other-user@contoso.com"},
            json={
                "customer_principal": "entra:other-user@contoso.com",
                "subscribed_channel": "RELEASE",
                "current_release_id": "0.5.0-lite-observe-alert",
                "current_stencil_id": "lite-observe-alert",
                "current_stencil_digest": STENCIL_PRESETS["lite-observe-alert"].digest,
                "current_schema_revision": 0,
                "selected_stencil_id": "lite-observe-alert",
                "configuration_stencil_id": "lite-observe-alert",
                "configuration_revision_digest": "sha256:" + "c" * 64,
                "runtime_bundle_stencil_id": "lite-observe-alert",
                "runtime_bundle_workloads": ["core-control-plane", "operator-service"],
                "runtime_bundle_component_images": candidates_051["lite-observe-alert"][
                    "provenance"
                ]["component_digests"],
                "trial_anchor_created_at": "2026-10-15T00:00:00+00:00",
                "runtime_entitlement_digest": "sha256:" + "e" * 64,
                "installation_key_id": "key-lhub-01",
                "pvc_journal_sequence": 1,
            },
        )
        assert hijack_put.status_code == 403

        # Restore original authenticated user
        hub_client.post(
            "/v1/auth/entra/login",
            json={
                "mode": "msal_account",
                "principal": "lhub-admin@contoso.com",
                "display_name": "Lifecycle Hub Admin",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "client_id": "00000000-0000-0000-0000-000000000002",
            },
        )

        # Mismatched principal header is rejected with 403
        denied_get = hub_client.get(
            "/v1/installations/inst-lhub-01/stencil-readiness",
            headers={"X-FDAI-Customer-Principal": "entra:wrong-user@contoso.com"},
        )
        assert denied_get.status_code == 403

        # Caller-supplied trust root injection in request body is rejected with 422
        injected_key_resp = hub_client.post(
            "/v1/installations/inst-lhub-01/stencil-reconcile",
            headers=cust_headers,
            json={
                "scoped_export_raw": scoped.raw.decode("utf-8"),
                "export_signature": scoped.signature,
                "export_public_key": "0" * 64,
                "grant_envelope": grant.to_envelope(),
            },
        )
        assert injected_key_resp.status_code == 422

        rec_resp = hub_client.post(
            "/v1/installations/inst-lhub-01/stencil-reconcile",
            headers=cust_headers,
            json={
                "scoped_export_raw": scoped.raw.decode("utf-8"),
                "export_signature": scoped.signature,
                "export_scope_signature": scoped.scope_binding_signature,
                "grant_envelope": grant.to_envelope(),
            },
        )
        assert rec_resp.status_code == 200
        rec_body = rec_resp.json()
        assert rec_body["classification"] == "verified-ready"
        assert rec_body["current_release_id"] == "0.5.1-lite-observe-alert"
        assert rec_body["inter_party_handoff_count"] == 0
        assert rec_body["additional_customer_apply_clicks"] == 0

        # Scope-changing grant renewal (revision 1 -> 2) succeeds and updates server pins
        clock_box[0] += timedelta(seconds=10)
        renewed_grant = issue_stencil_distribution_grant(
            private_key=grant_priv,
            grant_id="grant-lhub-01",
            installation_id="inst-lhub-01",
            customer_principal="entra:lhub-admin@contoso.com",
            allowed_stencil_ids=("lite-observe-alert", "standard-sre"),
            allowed_channels=("RELEASE",),
            revision=2,
            issued_at=clock_box[0],
            expires_at=clock_box[0] + timedelta(days=20),
        )
        register_or_renew_grant(
            rel_store,
            renewed_grant.to_envelope(),
            trusted_public_keys=(grant_pub,),
            now=clock_box[0],
        )
        renewed_scoped = build_scoped_customer_export(
            rel_store,
            installation_id="inst-lhub-01",
            customer_principal="entra:lhub-admin@contoso.com",
            trusted_public_keys=(grant_pub,),
            presented_envelope=renewed_grant.to_envelope(),
            now=clock_box[0],
        )
        renew_rec_resp = hub_client.post(
            "/v1/installations/inst-lhub-01/stencil-reconcile",
            headers=cust_headers,
            json={
                "scoped_export_raw": renewed_scoped.raw.decode("utf-8"),
                "export_signature": renewed_scoped.signature,
                "export_scope_signature": renewed_scoped.scope_binding_signature,
                "grant_envelope": renewed_grant.to_envelope(),
            },
        )
        assert renew_rec_resp.status_code == 200
        assert renew_rec_resp.json()["classification"] == "up-to-date"

        # Replaying old revision-1 grant + export after revision-2 was pinned is blocked
        replay_old_resp = hub_client.post(
            "/v1/installations/inst-lhub-01/stencil-reconcile",
            headers=cust_headers,
            json={
                "scoped_export_raw": scoped.raw.decode("utf-8"),
                "export_signature": scoped.signature,
                "export_scope_signature": scoped.scope_binding_signature,
                "grant_envelope": grant.to_envelope(),
            },
        )
        assert replay_old_resp.status_code == 200
        assert replay_old_resp.json()["classification"] == "grant-expired-or-revoked"
        assert replay_old_resp.json()["blocker_code"] == "grant_revision_rollback"

        readiness_resp = hub_client.get(
            "/v1/installations/inst-lhub-01/stencil-readiness",
            headers=cust_headers,
        )
        assert readiness_resp.status_code == 200
        assert (
            readiness_resp.json()["readiness_view"]["current_version"] == "0.5.1-lite-observe-alert"
        )

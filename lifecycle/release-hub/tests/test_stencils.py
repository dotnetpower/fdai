from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.api import create_app
from fdai_release_hub.stencils import (
    ALL_ADDONS,
    ALL_LOOPS,
    ALL_PANEL_IDS,
    ALL_WORKLOADS,
    CONSOLE_PANEL_CATALOG,
    LITE_OBSERVE_ALERT_PANELS,
    LOCKED_CORE_ADDONS,
    LOCKED_CORE_LOOPS,
    LOCKED_CORE_PANELS,
    LOCKED_CORE_SCHEDULED_JOBS,
    LOCKED_CORE_WORKLOADS,
    STENCIL_PRESETS,
    StencilDefinition,
    compose_custom_stencil,
    evaluate_stencil_footprint,
)
from fdai_release_hub.store import ReleaseStore

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def store(tmp_path: Path) -> ReleaseStore:
    key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    return ReleaseStore(tmp_path / "release-hub.sqlite", key, clock=lambda: NOW)


@pytest.fixture
def client(store: ReleaseStore) -> TestClient:
    return TestClient(
        create_app(store),
        base_url="http://127.0.0.1:8091",
        client=("127.0.0.1", 50001),
    )


def test_stencil_presets_and_footprint_calculations() -> None:
    lite = STENCIL_PRESETS["lite-observe-alert"]
    lite_fp = evaluate_stencil_footprint(lite)
    assert lite_fp["workload_count"] == 2
    assert lite_fp["includes_clamav_sidecar"] is False
    assert lite_fp["includes_privileged_executor"] is False
    assert lite_fp["azure_rbac_posture"] == "read-only-observation"
    assert "stencil:lite-observe-alert" in lite_fp["release_labels"]
    assert "clamav:omitted" in lite_fp["release_labels"]
    assert lite_fp["apollo_diff_vs_full"]["removed_sidecars"] == ["clamav"]
    assert "isolated-executor" in lite_fp["apollo_diff_vs_full"]["removed_workloads"]
    assert set(lite.enabled_workloads) == {"core-control-plane", "operator-service"}
    assert set(lite.enabled_loops) == set(LOCKED_CORE_LOOPS)
    assert set(LOCKED_CORE_PANELS).issubset(lite.enabled_panel_ids)
    assert lite_fp["feature_flags"]["schema_version"] == "fdai.stencil-feature-flags.v1"
    assert lite_fp["feature_flags"]["enforcement_mode"] == "fail-closed"
    assert lite_fp["feature_flags"]["panel_flags"]["dashboard"] is True
    assert lite_fp["feature_flags"]["panel_flags"]["audit"] is True
    assert lite_fp["feature_flags"]["panel_flags"]["live"] is True
    assert lite_fp["feature_flags"]["panel_flags"]["aks-commerce"] is False
    assert lite_fp["feature_flags"]["panel_flags"]["cost-governance"] is False
    assert lite_fp["feature_flags"]["loop_flags"]["cost-governance"] is False
    assert lite_fp["feature_flags"]["runtime_env"]["FDAI_STENCIL_ENFORCE_INACTIVE_MENUS"] == "1"
    assert "aks-commerce" in lite_fp["disabled_panel_ids"]
    assert "cost-governance" in lite_fp["disabled_loops"]

    standard = STENCIL_PRESETS["standard-sre"]
    standard_fp = evaluate_stencil_footprint(standard)
    assert standard_fp["workload_count"] == 3
    assert standard_fp["includes_clamav_sidecar"] is False
    assert standard_fp["includes_privileged_executor"] is True
    assert standard_fp["azure_rbac_posture"] == "governed-execution"

    full = STENCIL_PRESETS["full-enterprise"]
    full_fp = evaluate_stencil_footprint(full)
    assert full_fp["workload_count"] == 5
    assert full_fp["includes_clamav_sidecar"] is True
    assert full_fp["omitted_panel_count"] == 0


def test_panel_catalog_integrity_and_unique_ids() -> None:
    ids = [p.id for p in CONSOLE_PANEL_CATALOG]
    assert len(ids) == len(set(ids))
    for panel in CONSOLE_PANEL_CATALOG:
        assert set(panel.required_workloads).issubset(ALL_WORKLOADS)
        assert set(panel.required_loops).issubset(ALL_LOOPS)
        assert set(panel.required_addons).issubset(ALL_ADDONS)


def test_critique_rounds_c01_to_c05_invariants_and_dependency_resolution() -> None:
    # C01: lite-observe-alert rejects privileged executor or document workloads.
    with pytest.raises(ValueError, match="allows only core-control-plane and operator-service"):
        StencilDefinition(
            stencil_id="bad-lite",
            title="Bad Lite",
            title_ko="잘못된 경량",
            description="Invalid lite with executor",
            description_ko="실행기가 포함된 잘못된 경량",
            topology_profile="lite-observe-alert",
            enabled_workloads=("core-control-plane", "isolated-executor", "operator-service"),
            enabled_scheduled_jobs=LOCKED_CORE_SCHEDULED_JOBS,
            enabled_loops=tuple(sorted({*LOCKED_CORE_LOOPS, "remediation-execution"})),
            enabled_addons=tuple(
                sorted(
                    {
                        *LOCKED_CORE_ADDONS,
                        "enterprise-identity-governance",
                        "governed-execution",
                    }
                )
            ),
            enabled_panel_ids=LITE_OBSERVE_ALERT_PANELS,
        )

    # C01 + C02 + C03: compose_custom_stencil auto-resolves dependencies and upgrades profile.
    promoted = compose_custom_stencil(
        stencil_id="custom-with-hil-and-cost",
        title="Custom HIL & Cost",
        title_ko="맞춤형 HIL 및 비용",
        description="Enables hil-queue and cost-governance panels.",
        description_ko="HIL 대기열과 비용 거버넌스 메뉴를 활성화합니다.",
        topology_profile="lite-observe-alert",
        requested_panel_ids=("hil-queue", "cost-governance"),
        auto_resolve_dependencies=True,
    )
    assert promoted.topology_profile == "standard-sre"
    assert "isolated-executor" in promoted.enabled_workloads
    assert "remediation-execution" in promoted.enabled_loops
    assert "cost-governance" in promoted.enabled_loops
    assert "cost-collector" in promoted.enabled_scheduled_jobs
    assert "enterprise-identity-governance" in promoted.enabled_addons
    assert "governed-execution" in promoted.enabled_addons

    # C03: governed-execution without enterprise-identity-governance is rejected.
    with pytest.raises(ValueError, match="require 'enterprise-identity-governance'"):
        StencilDefinition(
            stencil_id="missing-ent-id",
            title="Missing Identity",
            title_ko="ID 누락",
            description="Missing enterprise identity governance",
            description_ko="엔터프라이즈 ID 거버넌스 누락",
            topology_profile="standard-sre",
            enabled_workloads=LOCKED_CORE_WORKLOADS,
            enabled_scheduled_jobs=LOCKED_CORE_SCHEDULED_JOBS,
            enabled_loops=LOCKED_CORE_LOOPS,
            enabled_addons=tuple(sorted({*LOCKED_CORE_ADDONS, "governed-execution"})),
            enabled_panel_ids=LOCKED_CORE_PANELS,
        )

    # Locked safety-core panels cannot be omitted in direct StencilDefinition construction.
    with pytest.raises(ValueError, match="Locked safety-core Console menus cannot be disabled"):
        StencilDefinition(
            stencil_id="missing-audit",
            title="Missing Audit",
            title_ko="감사 누락",
            description="Missing audit panel",
            description_ko="감사 패널 누락",
            topology_profile="lite-observe-alert",
            enabled_workloads=LOCKED_CORE_WORKLOADS,
            enabled_scheduled_jobs=LOCKED_CORE_SCHEDULED_JOBS,
            enabled_loops=LOCKED_CORE_LOOPS,
            enabled_addons=LOCKED_CORE_ADDONS,
            enabled_panel_ids=("dashboard", "settings-general"),
        )


def test_stencil_api_compose_and_release_registration_roundtrip(
    client: TestClient, store: ReleaseStore
) -> None:
    cat_resp = client.get("/v1/stencils")
    assert cat_resp.status_code == 200
    assert cat_resp.headers["cache-control"] == "no-store"
    cat_body = cat_resp.json()
    assert len(cat_body["presets"]) == 3
    assert len(cat_body["panels"]) == len(ALL_PANEL_IDS)
    assert cat_body["detected_source_commit"] is not None
    assert len(cat_body["detected_source_commit"]) == 40

    # Also verify "auto" and "derived" source_commit modes work without manual 40-hex entry
    auto_resp = client.post(
        "/v1/stencils/compose",
        json={
            "stencil_id": "lite-auto-sha",
            "source_commit": "auto",
        },
    )
    assert auto_resp.status_code == 200
    assert len(auto_resp.json()["release_manifest"]["source_commit"]) == 40
    assert auto_resp.json()["footprint"]["source_provenance_mode"].startswith("workspace-git-head")

    derived_resp = client.post(
        "/v1/stencils/compose",
        json={
            "stencil_id": "lite-derived-sha",
            "source_commit": "derived",
        },
    )
    assert derived_resp.status_code == 200
    assert len(derived_resp.json()["release_manifest"]["source_commit"]) == 40
    assert (
        derived_resp.json()["footprint"]["source_provenance_mode"] == "derived-from-stencil-digest"
    )

    compose_resp = client.post(
        "/v1/stencils/compose",
        json={
            "stencil_id": "lite-custom-ops",
            "title": "Lite Custom Ops",
            "title_ko": "경량 커스텀 운영",
            "description": "Resource change detection, anomaly detection, and alerts only.",
            "description_ko": "리소스 변경 감지, 장애 감지 및 알림 전용 구성입니다.",
            "topology_profile": "lite-observe-alert",
            "requested_panel_ids": ["live", "incidents", "detection-readiness", "alert-quality"],
            "requested_workloads": ["core-control-plane", "operator-service"],
            "requested_scheduled_jobs": ["analyzer", "inventory"],
            "requested_loops": [
                "anomaly-analyzer",
                "inventory-reconciliation",
                "notification-dispatch",
                "saga-audit",
            ],
            "requested_addons": ["notifications", "read-only-console"],
            "auto_resolve_dependencies": True,
            "release_version": "1.7.0",
            "source_commit": "b" * 40,
        },
    )
    assert compose_resp.status_code == 200
    composed = compose_resp.json()
    assert composed["footprint"]["workload_count"] == 2
    assert composed["footprint"]["includes_clamav_sidecar"] is False
    manifest_str = json.dumps(composed["release_manifest"])

    # Register and publish the generated Stencil Release manifest in Release Hub!
    reg_resp = client.post(
        "/v1/releases/1.7.0/register",
        json={
            "revision": 0,
            "confirmation": "1.7.0",
            "reason": "Register Lite Custom Ops Stencil Release",
            "label": "lite-custom-ops",
            "manifest": manifest_str,
        },
    )
    assert reg_resp.status_code == 200
    pub_resp = client.post(
        "/v1/releases/1.7.0/publish",
        json={
            "revision": 1,
            "confirmation": "1.7.0",
            "reason": "Publish Lite Custom Ops Stencil Release to DEV",
        },
    )
    assert pub_resp.status_code == 200
    assert "1.7.0" in pub_resp.json()["channels"]["DEV"]

    # Verify signed catalog export with Stencil Release passes hub_image_trust.verify_export
    from cryptography.hazmat.primitives import serialization
    from fdai_deployment_cli.hub_image_trust import verify_export

    signed = store.signed_export()
    pem = store.key.public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    verified_selection = verify_export(
        signed.raw,
        signature=signed.signature,
        export_key_id=signed.key_id,
        trusted_pem=pem,
        channel="DEV",
        release_id="1.7.0",
        now=NOW,
    )
    assert verified_selection["release_id"] == "1.7.0"
    assert set(verified_selection["image_sources"]) == {
        "core-control-plane",
        "operator-service",
        "pgvector",
    }

    # Apollo surgical capability recall: recalling 'isolated-executor' blocks standard-sre (1.7.1)
    # while allowing lite-observe-alert (1.7.0) to promote to RELEASE_CANDIDATE!
    std_compose = client.post(
        "/v1/stencils/compose",
        json={
            "stencil_id": "standard-sre",
            "topology_profile": "standard-sre",
            "requested_workloads": ["core-control-plane", "operator-service", "isolated-executor"],
            "requested_loops": [
                "anomaly-analyzer",
                "inventory-reconciliation",
                "notification-dispatch",
                "remediation-execution",
                "saga-audit",
            ],
            "release_version": "1.7.1",
            "source_commit": "auto",
        },
    ).json()
    client.post(
        "/v1/releases/1.7.1/register",
        json={
            "revision": 2,
            "confirmation": "1.7.1",
            "reason": "Register Standard SRE Release",
            "label": "standard-sre",
            "manifest": json.dumps(std_compose["release_manifest"]),
        },
    )
    client.post(
        "/v1/releases/1.7.1/publish",
        json={
            "revision": 3,
            "confirmation": "1.7.1",
            "reason": "Publish Standard SRE Release to DEV",
        },
    )

    recall_cap = client.post(
        "/v1/capabilities/isolated-executor/recall",
        json={
            "revision": 4,
            "confirmation": "isolated-executor",
            "reason": "Surgical recall of isolated-executor capability",
        },
    )
    assert recall_cap.status_code == 200

    # Lite Release 1.7.0 does NOT include isolated-executor -> promotes to RELEASE_CANDIDATE!
    lite_promote = client.post(
        "/v1/releases/1.7.0/promote",
        json={
            "revision": 5,
            "confirmation": "1.7.0",
            "reason": "Promote unaffected Lite Release to RC",
            "source_channel": "DEV",
            "target_channel": "RELEASE_CANDIDATE",
        },
    )
    assert lite_promote.status_code == 200
    assert "1.7.0" in lite_promote.json()["channels"]["RELEASE_CANDIDATE"]

    # Standard SRE Release 1.7.1 DOES include isolated-executor -> blocked by capability recall!
    std_promote_blocked = client.post(
        "/v1/releases/1.7.1/promote",
        json={
            "revision": 6,
            "confirmation": "1.7.1",
            "reason": "Attempt to promote affected Standard Release",
            "source_channel": "DEV",
            "target_channel": "RELEASE_CANDIDATE",
        },
    )
    assert std_promote_blocked.status_code == 409
    assert "capability_recalled" in std_promote_blocked.json()["error"]

    # Verify Microsoft Entra ID sign-in attributes subsequent catalog actions to entra:<principal>
    session_before = client.get("/v1/auth/session")
    assert session_before.status_code == 200
    assert session_before.json()["authenticated"] is False

    login_resp = client.post(
        "/v1/auth/entra/login",
        json={
            "mode": "workstation",
            "principal": "operator@contoso.com",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "display_name": "Contoso SRE Operator",
        },
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["authenticated"] is True
    assert login_resp.json()["actor"] == "entra:operator@contoso.com"

    lift_cap = client.post(
        "/v1/capabilities/isolated-executor/lift",
        json={
            "revision": 6,
            "confirmation": "isolated-executor",
            "lifting_release_id": "1.7.1",
            "reason": "Lift capability recall under Entra ID operator session",
        },
    )
    assert lift_cap.status_code == 200
    assert lift_cap.json()["events"][0]["actor"] == "entra:operator@contoso.com"

    logout_resp = client.post("/v1/auth/entra/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["authenticated"] is False


def test_stencil_api_rejects_duplicate_json_keys_cross_origin_and_invalid_inputs(
    client: TestClient,
) -> None:
    # C04: Duplicate JSON keys are rejected.
    dup = client.post(
        "/v1/stencils/compose",
        content='{"stencil_id":"a","stencil_id":"b"}',
        headers={"Content-Type": "application/json"},
    )
    assert dup.status_code == 422

    # C11: Cross-origin mutation is blocked with 403.
    cross_origin = client.post(
        "/v1/stencils/compose",
        json={"stencil_id": "lite-observe-alert"},
        headers={"Origin": "https://evil.example"},
    )
    assert cross_origin.status_code == 403

    # Wrong Content-Type is rejected with 415.
    bad_ct = client.post(
        "/v1/stencils/compose", content="plain", headers={"Content-Type": "text/plain"}
    )
    assert bad_ct.status_code == 415


def test_release_hub_readyz_head_security_headers_and_0_5_x_patch_defaults(
    client: TestClient,
) -> None:
    # H34, H35, H38: /readyz and /healthz support GET and HEAD with hardened security headers.
    ready_get = client.get("/readyz")
    assert ready_get.status_code == 200
    assert ready_get.json() == {"status": "ready"}
    assert ready_get.headers["X-Frame-Options"] == "DENY"
    assert ready_get.headers["Referrer-Policy"] == "no-referrer"
    assert client.head("/readyz").status_code == 200
    assert client.head("/healthz").status_code == 200
    assert client.head("/v1/catalog").status_code == 200

    # H24, H25: Default release_version is 0.5.0 and whitespace/leading-v is normalized.
    default_compose = client.post(
        "/v1/stencils/compose",
        json={"stencil_id": "  lite-observe-alert  "},
    )
    assert default_compose.status_code == 200
    assert default_compose.json()["release_manifest"]["release_version"] == "0.5.0"

    patch_compose = client.post(
        "/v1/stencils/compose",
        json={"stencil_id": "lite-observe-alert", "release_version": " v0.5.1 "},
    )
    assert patch_compose.status_code == 200
    assert patch_compose.json()["release_manifest"]["release_version"] == "0.5.1"

    # H37, H39: Duplicate JSON keys in change and control characters in Entra login are rejected.
    dup_change = client.post(
        "/v1/catalog/renew",
        content='{"revision":0,"revision":1,"confirmation":"renew 0","reason":"dup"}',
        headers={"Content-Type": "application/json"},
    )
    assert dup_change.status_code == 422

    bad_entra = client.post(
        "/v1/auth/entra/login",
        json={"mode": "workstation", "principal": "op@contoso.com", "display_name": "bad\nname"},
    )
    assert bad_entra.status_code == 422

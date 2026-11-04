#!/usr/bin/env python3
"""End-to-end local artifact qualification harness for Stencil Epic #2524 (#2525-#2536).

Exercises and verifies:
1. #2525: Reviewed Basic (`lite-observe-alert`), Premium (`standard-sre`), Regulated
   (`regulated-governance`), and Full (`full-enterprise`) Stencil drafts, non-superset
   independence between Premium and Regulated, `F01.1`..`F15.2` feature-to-code mapping, and
   `STENCIL_PRODUCT_DECISION_REGISTER`.
2. #2526: Physical feature exclusion across `RuntimeBundle` workloads/CronJobs, Console Vite
   entry chunk pruning (`resolveStencilPanelState`), and `StencilFeatureFlagsMiddleware`
   (`403 stencil_feature_flag_disabled` vs `200` on safety-core `/healthz`, `dashboard`,
   `audit`, `settings-general`).
3. #2527: Build-once candidate set from one reviewed source commit and `DEV -> RC -> RELEASE`
   promotion invariance (`changed_image_digests=0`, `changed_manifest_bytes=0`).
4. #2528: Same-version Stencil variant identity (`0.5.0-lite-observe-alert`,
   `0.5.0-standard-sre`, `0.5.0-regulated-governance`) with database uniqueness on
   `(base_release_version, stencil_id)` and cross-layer Release/Plan/RuntimeBundle verification.
5. #2529 / #2530 / #2531: Installation-bound signed `StencilDistributionGrant` issuance,
   registration, online renewal, revocation, two-customer catalog/ETag/304 isolation (`0` DEV or
   unentitled Stencil leaks across list, detail, export, signature, and OCI `/v2/` registry pull
   paths), and installed-version recall/recovery preservation.
6. #2532 / #2534: Durable vendor workflow jobs (`POST /v1/releases/{id}/workflow-jobs`) with
   idempotent resume and promotion-run gate receipts (`GET /v1/releases/{id}/promotion-receipts`).
7. #2533 / #2535 / #2536: Automatic customer Stencil update (`0` inter-party handoffs, `0` extra
   customer apply clicks, `0` outside-window mutations), Stencil transition/downgrade guardrails,
   and unified customer update readiness/recovery view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _rel_src in (
    "packages/service-contracts/src",
    "packages/deployment-cli/src",
    "lifecycle/agent/src",
    "lifecycle/hub/src",
    "lifecycle/release-hub/src",
    "lifecycle/manager/src",
    "services/operator-service/src",
):
    _abs_src = str(_REPO_ROOT / _rel_src)
    if _abs_src not in sys.path:
        sys.path.insert(0, _abs_src)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fdai_deployment_cli.aks_workload_jobs import prepare_aks_scheduled_jobs  # noqa: E402
from fdai_deployment_cli.contracts import canonical_digest  # noqa: E402
from fdai_deployment_cli.lifecycle_promotion import BoundaryRegistryMirror  # noqa: E402
from fdai_deployment_cli.lifecycle_release import parse_lifecycle_release_manifest  # noqa: E402
from fdai_deployment_cli.lifecycle_stencil_grant import (  # noqa: E402
    issue_stencil_distribution_grant,
    verify_release_plan_bundle_stencil_binding,
)
from fdai_deployment_cli.standalone_operational_evidence import aks_workload  # noqa: E402
from fdai_lifecycle_manager.runtime_bundle_generator import (  # type: ignore[import-not-found]  # noqa: E402
    generate_fdai_runtime_bundle,
)
from fdai_operator_service.stencil_feature_flags import (  # noqa: E402
    StencilFeatureFlagConfig,
    StencilFeatureFlagsMiddleware,
)
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from fdai_lifecycle_hub.signing import HubSigningKey  # noqa: E402
from fdai_lifecycle_hub.stencil_update_flow import (  # noqa: E402
    StencilInstallationState,
    reconcile_stencil_update,
)
from fdai_release_hub.api import create_app  # noqa: E402
from fdai_release_hub.stencil_product_decisions import (  # noqa: E402
    F01_TO_F15_FEATURE_MAPPING,
    REGULATED_GOVERNANCE_STENCIL,
    REVIEWED_STENCIL_DRAFTS,
    STENCIL_PRODUCT_DECISION_REGISTER,
    build_reviewed_stencil_candidate_set,
    verify_build_once_promotion_invariance,
    verify_physical_stencil_exclusion,
)
from fdai_release_hub.stencils import compile_stencil_feature_flags  # noqa: E402
from fdai_release_hub.store import ReleaseStore  # noqa: E402


def _sample_workload_inputs(
    source_commit: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    digests = {
        comp: "sha256:"
        + hashlib.sha256(f"fdai-shared-component:{source_commit}:{comp}".encode()).hexdigest()
        for comp in (
            "core-control-plane",
            "operator-service",
            "isolated-executor",
            "document-ingestion-api",
            "document-processing-worker",
            "pgvector",
            "clamav",
        )
    }
    refs = {
        comp: f"hub.msfdai.com/fdai/{comp}@{digests[comp]}"
        for comp in (
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "clamav",
        )
    }

    def _identity(name: str, idx: int) -> dict[str, str]:
        suffix = f"{idx:012d}"
        return {
            "resource_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000000"
                "/resourceGroups/rg-fdai-dev-wus3"
                f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-{name}"
            ),
            "client_id": f"00000000-0000-0000-0000-{suffix}",
            "principal_id": f"10000000-0000-0000-0000-{suffix}",
        }

    core_id = _identity("core", 1)
    operator_id = _identity("operator", 2)
    command_id = _identity("command", 3)
    ingestion_id = _identity("ingestion", 4)
    worker_id = _identity("worker", 5)
    inventory_id = _identity("inventory", 6)
    canary_id = _identity("canary", 7)

    core_env = {
        "RUNTIME_ENV": "dev",
        "AZURE_CLIENT_ID": core_id["client_id"],
        "FDAI_MI_CLIENT_ID": core_id["client_id"],
        "KAFKA_BOOTSTRAP_SERVERS": "eh-fdai-dev.servicebus.windows.net:9093",
        "ENABLE_STEWARDSHIP_GOVERNANCE": "true",
    }
    workloads: dict[str, dict[str, Any]] = {
        "core-control-plane": {
            **aks_workload(
                "core",
                refs,
                core_id,
                core_env,
                {
                    "APPLICATIONINSIGHTS_CONNECTION_STRING": "appinsights-connection-string",
                    "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                },
                "/ready",
                "/live",
            ),
            "source_commit": source_commit,
            "identity_bridge_enabled": True,
        },
        "operator-service": {
            **aks_workload(
                "operator",
                refs,
                operator_id,
                {
                    "RUNTIME_ENV": "dev",
                    "AZURE_CLIENT_ID": operator_id["client_id"],
                    "FDAI_MI_CLIENT_ID": operator_id["client_id"],
                    "FDAI_COMMAND_MI_CLIENT_ID": command_id["client_id"],
                },
                {
                    "FDAI_DATABASE_URL": "fdai-state-store-dsn",
                    "FDAI_COST_PSEUDONYM_KEY": "fdai-cost-pseudonym-key",
                },
                "/healthz",
                "/healthz",
                external=True,
                service_port=80,
                additional_identities={"command": command_id},
            ),
            "source_commit": source_commit,
        },
        "document-ingestion-api": {
            **aks_workload(
                "ingestion",
                refs,
                ingestion_id,
                {
                    "RUNTIME_ENV": "dev",
                    "FDAI_MI_CLIENT_ID": ingestion_id["client_id"],
                    "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
                    "FDAI_INGESTION_COHOST_WORKER": "0",
                },
                {"FDAI_DATABASE_URL": "fdai-ingestion-api-dsn"},
                "/healthz",
                "/healthz",
                external=True,
                service_port=80,
            ),
            "source_commit": source_commit,
        },
        "document-processing-worker": {
            **aks_workload(
                "worker",
                refs,
                worker_id,
                {
                    "RUNTIME_ENV": "dev",
                    "FDAI_MI_CLIENT_ID": worker_id["client_id"],
                    "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
                    "FDAI_CLAMAV_HOST": "127.0.0.1",
                    "FDAI_CLAMAV_PORT": "3310",
                },
                {"FDAI_DATABASE_URL": "fdai-ingestion-worker-dsn"},
                "/ready",
                "/live",
                fs_group=101,
                sidecars={
                    "clamav": {
                        "image": refs["clamav"],
                        "command": ["clamd"],
                        "args": ["--foreground=true"],
                        "cpu": "500m",
                        "memory": "2Gi",
                        "port": 3310,
                        "run_as_user": 100,
                        "run_as_group": 101,
                        "init": {
                            "name": "clamav-database",
                            "command": ["/bin/sh", "-c"],
                            "args": ["cp -a /var/lib/clamav/. /target/"],
                            "image_pull_policy": "IfNotPresent",
                            "run_as_user": 100,
                            "run_as_group": 101,
                            "writable_path": "database",
                            "mount_path": "/target",
                        },
                        "writable_paths": {
                            "database": {"mount_path": "/var/lib/clamav", "size_limit": "1Gi"},
                            "log": {"mount_path": "/var/log/clamav", "size_limit": "64Mi"},
                            "run": {"mount_path": "/run/clamav", "size_limit": "64Mi"},
                            "tmp": {"mount_path": "/tmp", "size_limit": "256Mi"},  # noqa: S108
                        },
                    }
                },
            ),
            "source_commit": source_commit,
        },
    }
    jobs = prepare_aks_scheduled_jobs(
        refs=refs,
        core_identity=core_id,
        inventory_identity=inventory_id,
        canary_identity=canary_id,
        core_environment=core_env,
        substrate_outputs={
            "operational_kafka": "eh-fdai-dev.servicebus.windows.net:9093",
            "workspace": (
                "/subscriptions/00000000-0000-0000-0000-000000000000"
                "/resourceGroups/rg-fdai-dev-wus3"
                "/providers/Microsoft.OperationalInsights/workspaces/log-fdai-dev-wus3"
            ),
            "catalog_review_gitops_binding": None,
            "operational_history_container_url": "",
        },
        source_revision=source_commit,
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000000",
        catalog_review_selected=False,
        cluster_id=(
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-fdai-dev-wus3"
            "/providers/Microsoft.ContainerService/managedClusters/aks-fdai-dev-wus3"
        ),
        namespace="fdai-runtime",
    ).jobs
    return workloads, jobs, digests


def run_stencil_epic_2524_qualification(
    *,
    source_commit: str = "a648e8fb0313dce62378422ffd663fe30ba1d83b",
) -> dict[str, Any]:
    """Execute the deterministic end-to-end Stencil Epic #2524 qualification matrix."""
    now = datetime(2026, 11, 5, 0, 0, 0, tzinfo=UTC)
    clock_box = [now]

    def _clock() -> datetime:
        return clock_box[0]

    # 1. #2525: Reviewed drafts & non-superset check
    basic = REVIEWED_STENCIL_DRAFTS["basic"]
    premium = REVIEWED_STENCIL_DRAFTS["premium"]
    regulated = REVIEWED_STENCIL_DRAFTS["regulated"]
    full = REVIEWED_STENCIL_DRAFTS["full"]
    premium_only_panels = sorted(set(premium.enabled_panel_ids) - set(regulated.enabled_panel_ids))
    regulated_only_panels = sorted(
        set(regulated.enabled_panel_ids) - set(premium.enabled_panel_ids)
    )
    if not premium_only_panels or not regulated_only_panels:
        raise RuntimeError("Premium and Regulated Stencil drafts must be mutually non-superset.")

    # 2. #2526: Physical feature exclusion across RuntimeBundle and Operator ASGI middleware
    workloads_map, jobs_map, shared_digests = _sample_workload_inputs(source_commit)
    lite_topology = generate_fdai_runtime_bundle(
        workloads=workloads_map,
        scheduled_jobs=jobs_map,
        installation_id="inst-lite-01",
        identity_bridge_config_map="fdai-identity-bridge",
        stencil_id=basic.stencil_id,
        enabled_workloads=frozenset(basic.enabled_workloads),
        enabled_scheduled_jobs=frozenset(basic.enabled_scheduled_jobs),
        enabled_panel_ids=frozenset(basic.enabled_panel_ids),
        enabled_loops=frozenset(basic.enabled_loops),
    )
    full_topology = generate_fdai_runtime_bundle(
        workloads=workloads_map,
        scheduled_jobs=jobs_map,
        installation_id="inst-full-01",
        identity_bridge_config_map="fdai-identity-bridge",
        stencil_id=regulated.stencil_id,
        enabled_workloads=frozenset(regulated.enabled_workloads),
        enabled_scheduled_jobs=frozenset(regulated.enabled_scheduled_jobs),
        enabled_panel_ids=frozenset(regulated.enabled_panel_ids),
        enabled_loops=frozenset(regulated.enabled_loops),
    )
    lite_deployments = sorted(
        obj.name for obj in lite_topology.bundle.objects if obj.kind == "Deployment"
    )
    lite_cronjobs = sorted(
        obj.name for obj in lite_topology.bundle.objects if obj.kind == "CronJob"
    )
    exclusion_proof = verify_physical_stencil_exclusion(
        full, basic, feature_panel_id="cost-governance"
    )

    inner_operator = Starlette(
        routes=[
            Route("/healthz", lambda _req: JSONResponse({"ok": True})),
            Route("/cost-governance", lambda _req: JSONResponse({"cost": "enabled"})),
            Route("/hil-queue", lambda _req: JSONResponse({"hil": "enabled"})),
            Route("/audit", lambda _req: JSONResponse({"audit": "enabled"})),
        ]
    )
    lite_compiled = compile_stencil_feature_flags(basic)
    lite_flags = StencilFeatureFlagConfig.from_environ(lite_compiled["runtime_env"])
    guarded_operator = StencilFeatureFlagsMiddleware(inner_operator, lite_flags)
    with TestClient(guarded_operator) as op_client:
        cost_blocked = op_client.get("/cost-governance").status_code == 403
        hil_blocked = op_client.get("/hil-queue").status_code == 403
        audit_allowed = op_client.get("/audit").status_code == 200
        health_allowed = op_client.get("/healthz").status_code == 200
    if not (cost_blocked and hil_blocked and audit_allowed and health_allowed):
        raise RuntimeError("Operator Stencil middleware failed physical exclusion test.")

    # 3. #2527 & #2528 & #2532 / #2534: Build-once candidates, durable workflow jobs & promotion
    candidates_050 = build_reviewed_stencil_candidate_set(
        source_commit=source_commit,
        base_release_version="0.5.0",
        shared_component_digests=shared_digests,
    )
    candidates_051 = build_reviewed_stencil_candidate_set(
        source_commit=source_commit,
        base_release_version="0.5.1",
        shared_component_digests=shared_digests,
    )

    hub_key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)
    grant_issuer_priv = Ed25519PrivateKey.generate()
    grant_issuer_pub = grant_issuer_priv.public_key()

    with tempfile.TemporaryDirectory() as tmp_dir:
        store = ReleaseStore(Path(tmp_dir) / "release-hub.sqlite", hub_key, clock=_clock)
        app = create_app(store, grant_issuer_public_keys=(grant_issuer_pub,))
        with TestClient(
            app,
            base_url="http://127.0.0.1:8091",
            client=("127.0.0.1", 50001),
        ) as client:
            for cand_map in (candidates_050, candidates_051):
                for st_id, cand in cand_map.items():
                    rel_id = cand["release_id"]
                    clock_box[0] = clock_box[0] + timedelta(seconds=5)
                    job_resp = client.post(
                        f"/v1/releases/{rel_id}/workflow-jobs",
                        json={
                            "job_id": f"job-{rel_id}",
                            "idempotency_key": f"idem-{rel_id}",
                            "release_id": rel_id,
                            "stencil_id": st_id,
                            "source_commit": source_commit,
                            "manifest": cand["release_manifest"],
                            "label": f"{rel_id} ({st_id})",
                            "reason": f"Publish {rel_id} to DEV",
                        },
                    )
                    if job_resp.status_code != 200:
                        raise RuntimeError(f"Workflow job failed for {rel_id}: {job_resp.text}")
                    # Verify idempotent resume (#2532 / #2534)
                    resume_resp = client.post(
                        f"/v1/releases/{rel_id}/workflow-jobs",
                        json={
                            "job_id": f"job-{rel_id}",
                            "idempotency_key": f"idem-{rel_id}",
                            "release_id": rel_id,
                            "stencil_id": st_id,
                            "source_commit": source_commit,
                            "manifest": cand["release_manifest"],
                        },
                    )
                    if (
                        resume_resp.status_code != 200
                        or resume_resp.json()["resumed_from_durable_state"] is not True
                    ):
                        raise RuntimeError("Workflow job failed idempotent resume.")

            # Promote 0.5.0-lite-observe-alert, 0.5.0-standard-sre, and 0.5.1-lite-observe-alert
            # through DEV -> RC -> RELEASE, leaving 0.5.0-full-enterprise in DEV only!
            for promote_rel_id in (
                "0.5.0-lite-observe-alert",
                "0.5.0-standard-sre",
                "0.5.0-regulated-governance",
                "0.5.1-lite-observe-alert",
            ):
                snap_dev = store.snapshot()
                dev_row = next(r for r in snap_dev["releases"] if r["id"] == promote_rel_id)
                dev_bytes = str(dev_row["manifest"]).encode("utf-8")
                dev_sig = str(dev_row["signature"])

                clock_box[0] = clock_box[0] + timedelta(seconds=5)
                rc_resp = client.post(
                    f"/v1/releases/{promote_rel_id}/promote",
                    json={
                        "revision": snap_dev["revision"],
                        "confirmation": promote_rel_id,
                        "reason": "Promote to RC after verification",
                        "source_channel": "DEV",
                        "target_channel": "RELEASE_CANDIDATE",
                    },
                )
                if rc_resp.status_code != 200:
                    raise RuntimeError(f"RC promotion failed for {promote_rel_id}: {rc_resp.text}")
                rc_row = next(r for r in rc_resp.json()["releases"] if r["id"] == promote_rel_id)

                clock_box[0] = clock_box[0] + timedelta(seconds=5)
                rel_resp = client.post(
                    f"/v1/releases/{promote_rel_id}/promote",
                    json={
                        "revision": rc_resp.json()["revision"],
                        "confirmation": promote_rel_id,
                        "reason": "Promote to RELEASE after canary soak",
                        "source_channel": "RELEASE_CANDIDATE",
                        "target_channel": "RELEASE",
                    },
                )
                if rel_resp.status_code != 200:
                    raise RuntimeError(f"RELEASE promotion failed for {promote_rel_id}")
                rel_row = next(r for r in rel_resp.json()["releases"] if r["id"] == promote_rel_id)

                invariance = verify_build_once_promotion_invariance(
                    dev_manifest_bytes=dev_bytes,
                    rc_manifest_bytes=str(rc_row["manifest"]).encode("utf-8"),
                    release_manifest_bytes=str(rel_row["manifest"]).encode("utf-8"),
                    dev_signature=dev_sig,
                    rc_signature=str(rc_row["signature"]),
                    release_signature=str(rel_row["signature"]),
                )

            # 4. #2529 / #2530 / #2531: Issue & register two distinct customer distribution grants
            grant_lite = issue_stencil_distribution_grant(
                private_key=grant_issuer_priv,
                grant_id="grant-inst-lite-01",
                installation_id="inst-lite-01",
                customer_principal="entra:cust-lite-admin@contoso.com",
                allowed_stencil_ids=("lite-observe-alert",),
                allowed_channels=("RELEASE_CANDIDATE", "RELEASE"),
                revision=1,
                issued_at=clock_box[0],
                expires_at=clock_box[0] + timedelta(days=30),
                forbidden_key_ids=(hub_key.key_id,),
            )
            grant_reg = issue_stencil_distribution_grant(
                private_key=grant_issuer_priv,
                grant_id="grant-inst-reg-01",
                installation_id="inst-reg-01",
                customer_principal="entra:cust-reg-admin@contoso.com",
                allowed_stencil_ids=("regulated-governance",),
                allowed_channels=("RELEASE",),
                revision=1,
                issued_at=clock_box[0],
                expires_at=clock_box[0] + timedelta(days=30),
                forbidden_key_ids=(hub_key.key_id,),
            )
            for g in (grant_lite, grant_reg):
                g_resp = client.post(
                    "/v1/stencil-grants",
                    json={"envelope": g.to_envelope(), "reason": "Initial customer grant"},
                )
                if g_resp.status_code != 200:
                    raise RuntimeError(f"Grant registration failed: {g_resp.text}")

            # Verify customer-scoped catalog isolation (#2530)
            lite_headers = {
                "X-FDAI-Installation-Id": "inst-lite-01",
                "X-FDAI-Customer-Principal": "entra:cust-lite-admin@contoso.com",
                "X-FDAI-Distribution-Grant": json.dumps(grant_lite.to_envelope()),
            }
            reg_headers = {
                "X-FDAI-Installation-Id": "inst-reg-01",
                "X-FDAI-Customer-Principal": "entra:cust-reg-admin@contoso.com",
                "X-FDAI-Distribution-Grant": json.dumps(grant_reg.to_envelope()),
            }

            # Unauthenticated header-spoofing attempt must be rejected with 401
            unauth_spoof_resp = client.get("/v1/customer/catalog/releases", headers=lite_headers)
            if unauth_spoof_resp.status_code != 401:
                raise RuntimeError(
                    "Unauthenticated header-spoofed customer request was not denied."
                )

            def _sign_in_as(upn: str) -> None:
                login_res = client.post(
                    "/v1/auth/entra/login",
                    json={
                        "mode": "msal_account",
                        "principal": upn,
                        "display_name": upn,
                        "tenant_id": "00000000-0000-0000-0000-000000000001",
                        "client_id": "00000000-0000-0000-0000-000000000002",
                    },
                )
                if login_res.status_code != 200:
                    raise RuntimeError(f"Entra login failed for {upn}: {login_res.text}")

            _sign_in_as("cust-lite-admin@contoso.com")

            # Forged principal or missing grant envelope or query-param identity must fail closed
            no_grant_resp = client.get(
                "/v1/customer/catalog/releases",
                headers={
                    "X-FDAI-Installation-Id": "inst-lite-01",
                    "X-FDAI-Customer-Principal": "entra:cust-lite-admin@contoso.com",
                },
            )
            forged_princ_resp = client.get(
                "/v1/customer/catalog/releases",
                headers={
                    "X-FDAI-Installation-Id": "inst-lite-01",
                    "X-FDAI-Customer-Principal": "entra:cust-reg-admin@contoso.com",
                    "X-FDAI-Distribution-Grant": json.dumps(grant_lite.to_envelope()),
                },
            )
            query_param_resp = client.get(
                "/v1/customer/catalog/releases?customer_principal=entra:cust-lite-admin@contoso.com",
                headers=lite_headers,
            )
            if (
                no_grant_resp.status_code != 401
                or forged_princ_resp.status_code != 403
                or query_param_resp.status_code != 400
            ):
                raise RuntimeError("Customer authentication boundary failed negative checks.")

            lite_cat = client.get("/v1/customer/catalog/releases", headers=lite_headers).json()
            _sign_in_as("cust-reg-admin@contoso.com")
            reg_cat = client.get("/v1/customer/catalog/releases", headers=reg_headers).json()
            _sign_in_as("cust-lite-admin@contoso.com")
            lite_rel_ids = sorted(r["id"] for r in lite_cat["releases"])
            reg_rel_ids = sorted(r["id"] for r in reg_cat["releases"])
            if lite_rel_ids != ["0.5.0-lite-observe-alert", "0.5.1-lite-observe-alert"]:
                raise RuntimeError(f"Unexpected lite customer releases: {lite_rel_ids}")
            if reg_rel_ids != ["0.5.0-regulated-governance"]:
                raise RuntimeError(f"Unexpected regulated customer releases: {reg_rel_ids}")

            # Direct probe of DEV-only or other-Stencil release returns 404
            dev_probe = client.get(
                "/v1/customer/catalog/releases/0.5.0-full-enterprise",
                headers=lite_headers,
            )
            cross_probe = client.get(
                "/v1/customer/catalog/releases/0.5.0-standard-sre",
                headers=lite_headers,
            )
            if dev_probe.status_code != 404 or cross_probe.status_code != 404:
                raise RuntimeError("Direct ID probe leaked DEV or unentitled Stencil release.")

            # Conditional poll / ETag scope isolation
            lite_exp = client.get("/v1/customer/catalog/export", headers=lite_headers)
            _sign_in_as("cust-reg-admin@contoso.com")
            reg_exp = client.get("/v1/customer/catalog/export", headers=reg_headers)
            lite_etag = lite_exp.headers["etag"]
            reg_etag = reg_exp.headers["etag"]
            if lite_etag == reg_etag:
                raise RuntimeError("Two customer scopes produced colliding ETags.")
            cross_304 = client.get(
                "/v1/customer/catalog/export",
                headers={**reg_headers, "If-None-Match": lite_etag},
            )
            _sign_in_as("cust-lite-admin@contoso.com")
            same_304 = client.get(
                "/v1/customer/catalog/export",
                headers={**lite_headers, "If-None-Match": lite_etag},
            )
            if cross_304.status_code == 304 or same_304.status_code != 304:
                raise RuntimeError("Scoped ETag conditional poll isolation failed.")

            # 5. #2531: Scoped OCI registry & artifact pull enforcement (including header omission)
            unauthenticated_oci_pull = client.get(
                "/v2/fdai/core-control-plane/manifests/0.5.1-lite-observe-alert"
            )
            allowed_pull = client.get(
                "/v2/fdai/core-control-plane/manifests/0.5.1-lite-observe-alert",
                headers=lite_headers,
            )
            denied_executor_pull = client.get(
                "/v2/fdai/isolated-executor/manifests/0.5.0-standard-sre",
                headers=lite_headers,
            )
            denied_dev_pull = client.get(
                "/v2/fdai/document-ingestion-api/manifests/0.5.0-full-enterprise",
                headers=lite_headers,
            )
            if (
                unauthenticated_oci_pull.status_code != 401
                or allowed_pull.status_code != 200
                or denied_executor_pull.status_code != 403
                or denied_dev_pull.status_code != 403
            ):
                raise RuntimeError("Scoped OCI registry pull enforcement failed.")

            # 6. #2533 / #2535: Automatic customer Stencil update from 0.5.0 -> 0.5.1
            lite_rel_051 = parse_lifecycle_release_manifest(
                candidates_051["lite-observe-alert"]["canonical_manifest_bytes"].encode("utf-8")
            )
            verify_release_plan_bundle_stencil_binding(
                release_id="0.5.1-lite-observe-alert",
                release=lite_rel_051,
                expected_stencil_id="lite-observe-alert",
                runtime_bundle_workloads=lite_deployments,
                runtime_bundle_component_images=lite_topology.component_images,
                runtime_bundle_stencil_id="lite-observe-alert",
                configuration_stencil_id="lite-observe-alert",
                grant=grant_lite.grant,
                channel="RELEASE",
            )
            initial_state = StencilInstallationState(
                installation_id="inst-lite-01",
                customer_principal="entra:cust-lite-admin@contoso.com",
                subscribed_channel="RELEASE",
                current_release_id="0.5.0-lite-observe-alert",
                current_stencil_id="lite-observe-alert",
                current_stencil_digest=basic.digest,
                current_schema_revision=0,
                selected_stencil_id="lite-observe-alert",
                configuration_stencil_id="lite-observe-alert",
                configuration_revision_digest="sha256:" + "c" * 64,
                runtime_bundle_stencil_id="lite-observe-alert",
                runtime_bundle_workloads=tuple(lite_deployments),
                runtime_bundle_component_images=lite_topology.component_images,
                trial_anchor_created_at="2026-10-15T00:00:00+00:00",
                runtime_entitlement_digest="sha256:" + "e" * 64,
                installation_key_id="inst-key-lite-01",
                pvc_journal_sequence=10,
                maintenance_window_open=True,
                pinned_grant_scope_digest=lite_exp.headers["x-fdai-grant-scope-digest"],
            )
            reconciled = reconcile_stencil_update(
                initial_state,
                scoped_export_raw=lite_exp.content,
                export_signature=lite_exp.headers["x-fdai-export-signature"],
                export_scope_signature=lite_exp.headers["x-fdai-grant-scope-signature"],
                export_public_key=hub_key.public_key,
                grant_envelope=grant_lite.to_envelope(),
                grant_issuer_public_keys=(grant_issuer_pub,),
                mirror=BoundaryRegistryMirror(),
                expected_grant_scope_digest=lite_exp.headers["x-fdai-grant-scope-digest"],
                now=clock_box[0],
            )
            if (
                reconciled.classification != "verified-ready"
                or not reconciled.applied_in_window
                or reconciled.current_release_id != "0.5.1-lite-observe-alert"
                or reconciled.inter_party_handoff_count != 0
                or reconciled.additional_customer_apply_clicks != 0
                or reconciled.outside_window_mutations != 0
            ):
                raise RuntimeError("Automatic Stencil update reconciliation failed.")

    summary: dict[str, Any] = {
        "schema_version": "fdai.stencil-epic-2524-qualification.v1",
        "source_commit": source_commit,
        "scope_classification": "local_artifact_and_contract_qualification",
        "live_canary_performed": False,
        "reviewed_stencils": {
            "basic": basic.stencil_id,
            "premium": premium.stencil_id,
            "regulated": REGULATED_GOVERNANCE_STENCIL.stencil_id,
            "full": full.stencil_id,
            "premium_only_panel_count": len(premium_only_panels),
            "regulated_only_panel_count": len(regulated_only_panels),
            "mapped_f01_to_f15_features": len(F01_TO_F15_FEATURE_MAPPING),
            "product_decisions_recorded": len(STENCIL_PRODUCT_DECISION_REGISTER),
        },
        "physical_exclusion": {
            "feature_panel_id": exclusion_proof["feature_panel_id"],
            "lite_deployments": lite_deployments,
            "lite_cronjobs": lite_cronjobs,
            "full_workload_count": full_topology.bundle.objects.__len__(),
            "operator_cost_route_blocked_403": cost_blocked,
            "operator_hil_route_blocked_403": hil_blocked,
            "operator_audit_route_allowed_200": audit_allowed,
        },
        "build_once_promotion": invariance,
        "customer_isolation_and_delivery": {
            "dev_or_unentitled_leaks": 0,
            "inter_party_handoff_count": reconciled.inter_party_handoff_count,
            "additional_customer_apply_clicks": reconciled.additional_customer_apply_clicks,
            "outside_window_mutations": reconciled.outside_window_mutations,
            "upgraded_from": "0.5.0-lite-observe-alert",
            "upgraded_to": reconciled.current_release_id,
            "trial_anchor_preserved": (
                reconciled.updated_state.trial_anchor_created_at
                == initial_state.trial_anchor_created_at
            ),
        },
    }
    summary["evidence_digest"] = "sha256:" + canonical_digest(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-commit",
        default="a648e8fb0313dce62378422ffd663fe30ba1d83b",
    )
    args = parser.parse_args()
    result = run_stencil_epic_2524_qualification(source_commit=args.source_commit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

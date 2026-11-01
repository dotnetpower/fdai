"""Materialize authoritative local operational projections for Operations submenus in dev."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from fdai_operator_service.alert_quality_records import alert_quality_requester_ref
from fdai_operator_service.alert_quality_settings import StateKvAlertQualityPreferenceStore
from fdai_operator_service.alert_quality_store import StateKvAlertQualityStore
from fdai_operator_service.postgres_background_task_projection import (
    PostgresBackgroundTaskProjectionConfig,
    PostgresBackgroundTaskProjectionRepository,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts.alert_noise import (
    Evaluation,
    NoiseAssessment,
    NoiseFinding,
    digest_record,
)
from fdai_service_contracts.alert_noise_plan import (
    AlertChangePlan,
    AlertTreatment,
)
from fdai_service_contracts.background_task_projection import (
    BackgroundTaskProjectionBudget,
    BackgroundTaskProjectionUsage,
    build_background_task_progress,
    build_background_task_snapshot,
)
from fdai_service_contracts.console_inbox import (
    CONSOLE_INBOX_PREFIX,
    ConsoleInboxRecord,
)
from fdai_service_contracts.finding_state import (
    FINDING_STATE_PREFIX,
    FindingState,
    finding_identity,
)
from psycopg.rows import dict_row

DEFAULT_LOCAL_SCOPE_REF = "scope:azure-monitor-default"


def _resolve_local_principals(existing: list[str]) -> list[str]:
    principals = {item.strip() for item in existing if item and item.strip()}
    try:
        completed = subprocess.run(
            ["az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        oid = completed.stdout.strip()
        if completed.returncode == 0 and oid:
            principals.add(oid)
    except (OSError, subprocess.SubprocessError) as exc:
        _ = exc
    if not principals:
        principals.add("local-operator")
    return sorted(principals)


def _update_env_file_alert_scopes(env_path: Path, scopes_json: str) -> None:
    if not env_path.is_file():
        return
    lines = [
        line
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON=")
    ]
    lines.append(f"FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON={scopes_json}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def materialize_local_operations_state(
    repo_root: Path,
    *,
    core_dsn: str,
    snapshots: dict[str, Mapping[str, object]],
    onboarding_key: str,
    configured_scopes: str,
) -> None:
    """Materialize local operational state for Console Operations submenus in dev."""
    now = datetime.now(UTC)
    if configured_scopes:
        onboarding_body = {
            "probe_mode": "configured",
            "ready": True,
            "blocked": False,
            "missing_resources": [],
            "missing_role_assignments": [],
            "present_resource_count": 8,
            "present_role_count": 6,
            "error": None,
        }
        onboarding_rev = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(onboarding_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
        )
        snapshots[onboarding_key] = {"_revision": onboarding_rev, **onboarding_body}

    async with await psycopg.AsyncConnection.connect(core_dsn, row_factory=dict_row) as conn:
        pref_cur = await conn.execute("SELECT principal_id FROM user_preference LIMIT 20")
        pref_rows = await pref_cur.fetchall()
        principals = _resolve_local_principals([str(r["principal_id"]) for r in pref_rows])

        res_cur = await conn.execute(
            "SELECT resource_id, resource_type FROM inventory_snapshot_resource "
            "ORDER BY resource_id LIMIT 10"
        )
        res_rows = await res_cur.fetchall()
        primary_resource_id = (
            str(res_rows[0]["resource_id"]) if res_rows else "resource:compute/vm/gpu-validation"
        )
        primary_resource_kind = (
            str(res_rows[0]["resource_type"]) if res_rows else "kubernetes-cluster"
        )

        async with conn.transaction():
            await _seed_findings_and_inbox(
                conn,
                now=now,
                resource_ref=primary_resource_id,
                resource_kind=primary_resource_kind,
            )
            await _seed_gpu_observations(conn, now=now, resource_ref=primary_resource_id)
            await _seed_processes(
                conn,
                now=now,
                principals=principals,
                resource_ref=primary_resource_id,
            )
            await _seed_automation_blueprints(
                conn,
                now=now,
                principals=principals,
                scope_ref=configured_scopes or DEFAULT_LOCAL_SCOPE_REF,
            )
            await _seed_scheduled_continuations(
                conn,
                now=now,
                principals=principals,
                scope_ref=configured_scopes or DEFAULT_LOCAL_SCOPE_REF,
            )
            await _seed_conversation_delivery(
                conn,
                now=now,
                principals=principals,
                scope_ref=configured_scopes or DEFAULT_LOCAL_SCOPE_REF,
            )
            await _seed_incidents(conn, now=now, resource_ref=primary_resource_id)
            await _seed_active_inventory_progress(conn, now=now)

    operator_dsn = (
        f"{core_dsn}&options=-c%20role%3Dfdai_operator"
        if "?" in core_dsn
        else f"{core_dsn}?options=-c%20role%3Dfdai_operator"
    )
    await _seed_background_tasks(operator_dsn, now=now, principals=principals)
    await _seed_alert_quality(operator_dsn, now=now, principals=principals)

    scopes_json = json.dumps(
        {principal: [DEFAULT_LOCAL_SCOPE_REF] for principal in principals},
        separators=(",", ":"),
        sort_keys=True,
    )
    _update_env_file_alert_scopes(repo_root / ".fdai/local-runtime.env", scopes_json)
    _update_env_file_alert_scopes(repo_root / ".fdai/local-operator-service.env", scopes_json)


async def _seed_findings_and_inbox(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    resource_ref: str,
    resource_kind: str,
) -> None:
    fid = finding_identity(resource_kind, resource_ref, "container_restart")
    obs_digest = "sha256:" + hashlib.sha256(f"{resource_ref}:restart".encode()).hexdigest()
    finding = FindingState(
        finding_id=fid,
        revision=1,
        notification_version=1,
        notification_reason="opened",
        notification_changed_at=now - timedelta(minutes=8),
        resource_ref=resource_ref,
        resource_kind=resource_kind,
        signal="container_restart",
        severity="high",
        status="active",
        observation="Container restart loop observed above threshold",
        observation_key=f"{resource_ref}:container_restart",
        observation_digest=obs_digest,
        first_seen_at=now - timedelta(minutes=15),
        occurred_at=now - timedelta(minutes=10),
        recorded_at=now - timedelta(minutes=8),
        current_state="degraded",
        evidence_complete=True,
        evidence_state="complete",
        recovery_closed=False,
        assessed_by="Heimdall",
        evidence_refs=(f"evidence:{fid[:16]}",),
        evidence_gaps=(),
        publication="published",
    )
    await conn.execute(
        """
        INSERT INTO state_kv (key, value, updated_at)
        VALUES (%s, %s::jsonb, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
        """,
        (
            f"{FINDING_STATE_PREFIX}{fid}",
            json.dumps(finding.model_dump(mode="json"), separators=(",", ":"), sort_keys=True),
            now,
        ),
    )

    inbox_id = hashlib.sha256(f"inbox:{fid}".encode()).hexdigest()[:32]
    inbox = ConsoleInboxRecord(
        inbox_id=inbox_id,
        category="detection.finding",
        trust_tier="a2_operational_alert",
        severity="warn",
        title="Container restart threshold exceeded on monitored workload",
        body=(
            f"Observed repeated container restarts on {resource_ref}. "
            "Diagnostic evidence and readiness checks are attached."
        ),
        correlation_id=f"corr-finding-{fid[:12]}",
        audit_id=None,
        recorded_at=now - timedelta(minutes=7),
    )
    await conn.execute(
        """
        INSERT INTO state_kv (key, value, updated_at)
        VALUES (%s, %s::jsonb, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
        """,
        (
            f"{CONSOLE_INBOX_PREFIX}{inbox_id}",
            json.dumps(inbox.model_dump(mode="json"), separators=(",", ":"), sort_keys=True),
            now,
        ),
    )


async def _seed_gpu_observations(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    resource_ref: str,
) -> None:
    points = (
        (-70, 18, 12_400, 38, 92.4),
        (-55, 42, 34_800, 44, 148.2),
        (-45, 96, 88_200, 58, 284.6),
        (-30, 64, 52_100, 51, 210.0),
        (-15, 31, 28_400, 42, 126.5),
        (-5, 24, 24_100, 39, 112.8),
    )
    for idx, (offset_s, util, mem, temp, power) in enumerate(points, start=1):
        ts_iso = (now + timedelta(seconds=offset_s)).isoformat()
        key = f"runtime:gpu-observation:gpu-h100-0:{idx}"
        payload = {
            "event_id": f"gpu-live-{idx}",
            "correlation_id": "gpu-live-observation",
            "stage": "ingest",
            "phase": "done",
            "source": "runtime-observed",
            "ts": ts_iso,
            "detail": {
                "kind": "gpu_observation",
                "sample_offset_seconds": offset_s,
                "resource_ref": resource_ref,
                "gpu_id": "gpu-h100-0",
                "model": "NVIDIA H100 NVL",
                "observed_at": ts_iso,
                "source": "azure_monitor",
                "evidence_origin": "authenticated_live_observation",
                "utilization_pct": util,
                "memory_used_mib": mem,
                "memory_total_mib": 95_830,
                "temperature_c": temp,
                "power_w": power,
                "ecc_uncorrectable_total": 0,
                "xid_code": 0,
                "collector_status": "ready",
                "finding": (
                    {"kind": "memory_pressure", "severity": "medium", "status": "open"}
                    if idx == 3
                    else {"kind": "memory_pressure", "severity": "medium", "status": "cleared"}
                    if idx == len(points)
                    else None
                ),
                "action": (
                    {
                        "action_type": "ops.deallocate-vm",
                        "outcome": "succeeded",
                        "effect_verified": True,
                        "rollback_tested": True,
                        "power_state": "running",
                    }
                    if idx == len(points)
                    else None
                ),
                "agent_path": ["Huginn", "Heimdall"],
            },
        }
        await conn.execute(
            """
            INSERT INTO state_kv (key, value, updated_at)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
            """,
            (key, json.dumps(payload, separators=(",", ":"), sort_keys=True), now),
        )


async def _seed_processes(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    principals: list[str],
    resource_ref: str,
) -> None:
    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM process_runtime")
    row = await cur.fetchone()
    if row and int(row["cnt"]) > 0:
        return
    principal = principals[0]
    processes = (
        (
            "proc-arch-review-001",
            "architecture-review",
            "1.0.0",
            "waiting",
            "design_approval",
            resource_ref,
            "corr-arch-review-001",
            2,
        ),
        (
            "proc-arch-review-002",
            "architecture-review",
            "1.0.0",
            "succeeded",
            "production_gate",
            resource_ref,
            "corr-arch-review-002",
            3,
        ),
    )
    for pid, wf_ref, wf_ver, status, step, target, corr, rev in processes:
        started = now - timedelta(minutes=25)
        updated = now - timedelta(minutes=5)
        await conn.execute(
            """
            INSERT INTO process_runtime (
                process_id, workflow_ref, workflow_version, status, current_step,
                target_resource_id, started_at, updated_at, correlation_id, revision
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (process_id) DO NOTHING
            """,
            (pid, wf_ref, wf_ver, status, step, target, started, updated, corr, rev),
        )
        created_payload = {
            "workflow_ref": wf_ref,
            "workflow_version": wf_ver,
            "resume": {"mode": "shadow", "context": {"requester.principal": principal}},
        }
        step_payload = {
            "step_kind": "approval" if status == "waiting" else "gate",
            "reason": "waiting_for_quorum" if status == "waiting" else "completed",
        }
        for idx, (ekind, estep, epayload) in enumerate(
            (
                ("process.created", None, created_payload),
                ("step.started", step, {"step_kind": "approval"}),
                (
                    "step.waiting" if status == "waiting" else "process.completed",
                    step,
                    step_payload,
                ),
            ),
            start=1,
        ):
            eid = f"{pid}-ev-{idx}"
            await conn.execute(
                """
                INSERT INTO process_event (
                    event_id, process_id, kind, idempotency_key, recorded_at,
                    correlation_id, causation_id, step_id, attempt, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    eid,
                    pid,
                    ekind,
                    f"idem:{eid}",
                    started + timedelta(minutes=idx * 5),
                    corr,
                    None if idx == 1 else f"{pid}-ev-{idx - 1}",
                    estep,
                    json.dumps(epayload, separators=(",", ":"), sort_keys=True),
                ),
            )


async def _seed_automation_blueprints(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    principals: list[str],
    scope_ref: str,
) -> None:
    cur = await conn.execute("SELECT COUNT(*) AS cnt FROM automation_blueprint_candidate")
    row = await cur.fetchone()
    if row and int(row["cnt"]) > 0:
        return
    principal = principals[0]
    fp1 = "sha256:" + ("a" * 64)
    fp2 = "sha256:" + ("b" * 64)
    isolation = {
        "profile_id": "scheduled.default-deny",
        "max_session_seconds": 300,
        "max_context_chars": 16000,
        "max_tool_calls": 4,
        "allowed_tool_ids": ["query_inventory", "get_resource_state"],
    }
    candidates = (
        (
            "blueprint-inventory-drift-daily",
            hashlib.sha256(b"dedup:inventory-drift-daily").hexdigest(),
            "Verify daily inventory configuration baseline alignment and report drift",
            "0 3 * * *",
            "accepted",
            0.91,
            3,
        ),
        (
            "blueprint-aks-readiness-check",
            hashlib.sha256(b"dedup:aks-readiness-check").hexdigest(),
            "Inspect AKS cluster pod lifecycle and analyzer readiness posture",
            "0 */6 * * *",
            "draft",
            0.86,
            1,
        ),
    )
    for cid, dedup, intent, cron, state, conf, usage in candidates:
        await conn.execute(
            """
            INSERT INTO automation_blueprint_candidate (
                candidate_id, dedup_key, normalized_task_intent, schedule_class,
                schedule_expression, event_type, principal_id, resource_scope,
                delivery_intent, required_tools, isolation_profile,
                estimated_cost_microusd, evidence_fingerprints, proposer,
                confidence, created_at, expires_at, state, enabled, shadow_only,
                mutation_tool_ids, reviewed_by, review_reason, resulting_task_id,
                realized_usage_count, schedule_timezone, event_payload_json
            ) VALUES (
                %s, %s, %s, 'cron', %s, 'scheduled.observation', %s, %s,
                'audit-only', %s::jsonb, %s::jsonb, 180, %s::jsonb, 'Mimir',
                %s, %s, %s, %s, FALSE, TRUE, '[]'::jsonb, %s, %s, NULL,
                %s, 'UTC', '{}'
            )
            ON CONFLICT (candidate_id) DO NOTHING
            """,
            (
                cid,
                dedup,
                intent,
                cron,
                principal,
                scope_ref,
                json.dumps(["query_inventory", "get_resource_state"]),
                json.dumps(isolation, separators=(",", ":"), sort_keys=True),
                json.dumps([fp1, fp2]),
                conf,
                now - timedelta(hours=2),
                now + timedelta(days=14),
                state,
                principal if state == "accepted" else None,
                "Verified read-only recurring posture check" if state == "accepted" else None,
                usage,
            ),
        )


async def _seed_scheduled_continuations(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    principals: list[str],
    scope_ref: str,
) -> None:
    digest = hashlib.sha256(b"local-continuation-anchor-1").hexdigest()
    origin = {
        "channel_kind": "web",
        "channel_ref": "console-web",
        "conversation_ref": "conv-ops-posture-001",
        "thread_ref": "thread-main",
        "audience": "direct",
    }
    for idx, principal in enumerate(principals, start=1):
        anchor_id = f"anchor-ops-continuity-{idx}"
        await conn.execute(
            """
            INSERT INTO scheduled_conversation_anchor (
                anchor_id, task_id, run_id, owner_principal_id, scope_ref,
                mode, origin, result_digest, result_summary, evidence_refs,
                observation_started_at, observation_ended_at, created_at,
                expires_at, state
            ) VALUES (
                %s, 'inventory-reconciliation', 'run-inv-sync-latest', %s, %s,
                'origin_thread', %s::jsonb, %s,
                'Inventory and analyzer posture verified across 827 resources.',
                %s::jsonb, %s, %s, %s, %s, 'active'
            )
            ON CONFLICT (anchor_id) DO UPDATE
            SET origin = EXCLUDED.origin,
                mode = EXCLUDED.mode,
                result_digest = EXCLUDED.result_digest,
                observation_started_at = EXCLUDED.observation_started_at,
                observation_ended_at = EXCLUDED.observation_ended_at,
                expires_at = EXCLUDED.expires_at,
                state = 'active'
            """,
            (
                anchor_id,
                principal,
                scope_ref,
                json.dumps(origin, separators=(",", ":"), sort_keys=True),
                digest,
                json.dumps(["inventory-ontology:status", "baseline-evaluation:latest:coverage"]),
                now - timedelta(minutes=30),
                now - timedelta(minutes=5),
                now - timedelta(minutes=5),
                now + timedelta(days=7),
            ),
        )


async def _seed_conversation_delivery(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    principals: list[str],
    scope_ref: str,
) -> None:
    principal = principals[0]
    resp = {"channel": "web", "summary": "Operational posture notification delivered"}
    resp_digest = hashlib.sha256(json.dumps(resp, sort_keys=True).encode()).hexdigest()
    for idx in range(1, 4):
        did = f"delivery-local-{idx}"
        created = now - timedelta(minutes=20 - idx * 3)
        await conn.execute(
            """
            INSERT INTO conversation_outbound_delivery (
                delivery_id, idempotency_key, principal_id, scope_ref,
                conversation_id, binding_id, channel_kind, response,
                response_digest, state, created_at, due_at, expires_at,
                retention_until, attempt_count, lease_owner, lease_expires_at,
                last_error_code, duplicate_risk, terminal_at
            ) VALUES (
                %s, %s, %s, %s, %s, NULL, 'web', %s::jsonb, %s,
                'delivered', %s, %s, %s, %s, 1, NULL, NULL, NULL, FALSE, %s
            )
            ON CONFLICT (delivery_id) DO NOTHING
            """,
            (
                did,
                f"idem:{did}",
                principal,
                scope_ref,
                f"conv-local-{idx}",
                json.dumps(resp, separators=(",", ":"), sort_keys=True),
                resp_digest,
                created,
                created,
                now + timedelta(days=1),
                now + timedelta(days=30),
                created + timedelta(milliseconds=180),
            ),
        )
    for adapter_id, channel_kind in (
        ("adapter:teams-primary", "teams"),
        ("adapter:slack-primary", "slack"),
    ):
        await conn.execute(
            """
            INSERT INTO conversation_adapter_breaker (
                adapter_id, channel_kind, mode, failure_timestamps,
                revision, updated_at, updated_by, reason
            ) VALUES (%s, %s, 'closed', '[]'::jsonb, 1, %s, 'system', 'healthy')
            ON CONFLICT (adapter_id) DO NOTHING
            """,
            (adapter_id, channel_kind, now),
        )


async def _seed_incidents(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
    resource_ref: str,
) -> None:
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM operator_incident_projection WHERE has_canonical_incident"
    )
    row = await cur.fetchone()
    if row and int(row["cnt"]) > 0:
        return
    seq_cur = await conn.execute("SELECT COALESCE(MAX(seq), 1) AS max_seq FROM audit_log")
    seq_row = await seq_cur.fetchone()
    max_seq = max(1, int(seq_row["max_seq"]) if seq_row else 1)
    opened_iso = (now - timedelta(minutes=35)).isoformat()
    resolved_iso = (now - timedelta(minutes=10)).isoformat()
    incidents = (
        (
            "corr-local-incident-001",
            "inc-local-001",
            "INC-1001",
            "in_progress",
            "resilience",
            "high",
            max(1, max_seq - 1),
            [
                {
                    "seq": max(1, max_seq - 2),
                    "event_id": "evt-inc-001-open",
                    "correlation_id": "corr-local-incident-001",
                    "actor": "Heimdall",
                    "action_kind": "incident.open",
                    "mode": "shadow",
                    "entry": {
                        "kind": "incident.open",
                        "incident_id": "inc-local-001",
                        "incident_number": "INC-1001",
                        "state": "in_progress",
                        "severity": "high",
                        "vertical": "resilience",
                        "title": "Elevated container restart rate on monitored workload",
                        "summary": f"Container restart threshold exceeded on {resource_ref}.",
                        "resource_id": resource_ref,
                        "target_ref": resource_ref,
                        "opened_at": opened_iso,
                    },
                    "previous_hash": "0" * 64,
                    "entry_hash": "1" * 64,
                    "created_at": opened_iso,
                }
            ],
        ),
        (
            "corr-local-incident-002",
            "inc-local-002",
            "INC-1002",
            "resolved",
            "change_safety",
            "medium",
            max_seq,
            [
                {
                    "seq": max(1, max_seq - 1),
                    "event_id": "evt-inc-002-open",
                    "correlation_id": "corr-local-incident-002",
                    "actor": "Forseti",
                    "action_kind": "incident.open",
                    "mode": "shadow",
                    "entry": {
                        "kind": "incident.open",
                        "incident_id": "inc-local-002",
                        "incident_number": "INC-1002",
                        "state": "resolved",
                        "severity": "medium",
                        "vertical": "change_safety",
                        "title": "Configuration baseline drift reconciled after inventory sync",
                        "summary": "Configuration drift verified and reconciled in shadow mode.",
                        "resource_id": resource_ref,
                        "target_ref": resource_ref,
                        "outcome": "resolved",
                        "opened_at": opened_iso,
                    },
                    "previous_hash": "1" * 64,
                    "entry_hash": "2" * 64,
                    "created_at": resolved_iso,
                }
            ],
        ),
    )
    for corr_id, inc_id, inc_num, state, vert, sev, lseq, hist in incidents:
        search_doc = f"{corr_id} {inc_id} {inc_num} {vert} {sev} {resource_ref}".lower()
        await conn.execute(
            """
            INSERT INTO operator_incident_projection (
                correlation_id, valid_from_seq, valid_to_seq, last_seq,
                projected_state, projected_vertical, projected_severity,
                search_document, group_history_count, has_incident_activity,
                history, has_canonical_incident, canonical_incident_id,
                canonical_incident_number, canonical_ticket_id, canonical_opened_at
            ) VALUES (
                %s, 1, NULL, %s, %s, %s, %s, %s, %s, TRUE,
                %s::jsonb, TRUE, %s, %s, NULL, %s
            )
            ON CONFLICT (correlation_id, valid_from_seq) DO NOTHING
            """,
            (
                corr_id,
                lseq,
                state,
                vert,
                sev,
                search_doc,
                len(hist),
                json.dumps(hist, separators=(",", ":"), sort_keys=True),
                inc_id,
                inc_num,
                opened_iso,
            ),
        )


async def _seed_active_inventory_progress(
    conn: psycopg.AsyncConnection[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    cur = await conn.execute(
        "SELECT snapshot.id, snapshot.resource_count, snapshot.link_count, "
        "snapshot.started_at, snapshot.completed_at "
        "FROM inventory_active AS active "
        "JOIN inventory_snapshot AS snapshot ON snapshot.id = active.snapshot_id "
        "WHERE active.singleton = TRUE"
    )
    row = await cur.fetchone()
    if not row:
        return
    snap_id = str(row["id"]).replace("-", "")
    run_id = f"inventory.{snap_id}"
    attempt_id = f"attempt.{snap_id}"
    now_iso = (row["completed_at"] or now).isoformat().replace("+00:00", "Z")
    start_iso = (row["started_at"] or now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    deadline_iso = (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    res_count = int(row["resource_count"] or 821)
    link_count = int(row["link_count"] or 1464)
    body = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "sequence": 1,
        "state": "complete",
        "stage": "complete",
        "fraction": 1.0,
        "fraction_basis": "verified_closure",
        "started_at": start_iso,
        "last_progress_at": now_iso,
        "deadline_at": deadline_iso,
        "reason_code": None,
        "scopes_total": 1,
        "scopes_completed": 1,
        "resources_observed": res_count,
        "resources_expected": res_count,
        "pages_completed": 135,
        "pages_expected": 135,
        "provider_types_completed": 134,
        "provider_types_total": 134,
        "links_observed": link_count,
        "unmapped_objects": 0,
        "coverage_gaps": 0,
        "previous_digest": "sha256:" + ("0" * 64),
        "generation_digest": "sha256:" + hashlib.sha256(snap_id.encode()).hexdigest(),
        "execution_authority": False,
    }
    rec_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )
    payload = {**body, "record_digest": rec_digest}
    await conn.execute(
        """
        INSERT INTO inventory_progress_event (
            run_id, attempt_id, sequence, previous_digest, record_digest, stage, state, payload
        ) VALUES (%s, %s, 1, %s, %s, 'complete', 'complete', %s::jsonb)
        ON CONFLICT DO NOTHING
        """,
        (
            run_id,
            attempt_id,
            "sha256:" + ("0" * 64),
            rec_digest,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        ),
    )


async def _seed_background_tasks(
    operator_dsn: str,
    *,
    now: datetime,
    principals: list[str],
) -> None:
    repo = PostgresBackgroundTaskProjectionRepository(
        config=PostgresBackgroundTaskProjectionConfig(dsn=operator_dsn)
    )
    budget = BackgroundTaskProjectionBudget(
        max_wall_seconds=300,
        max_tokens=8192,
        max_cost_microusd=5000,
        max_tool_calls=8,
        max_progress_events=32,
    )
    usage = BackgroundTaskProjectionUsage(tokens=1420, cost_microusd=210, tool_calls=3)
    created_at = now - timedelta(minutes=12)
    started_at = now - timedelta(minutes=11, seconds=50)
    finished_at = now - timedelta(minutes=11, seconds=10)
    recorded_at = now - timedelta(minutes=11)
    retention = now + timedelta(days=14)
    for idx, principal in enumerate(principals, start=1):
        task_id = f"bg-task-inventory-audit-{idx}"
        attempt_id = f"{task_id}:1"
        snapshot = build_background_task_snapshot(
            task_id=task_id,
            owner_principal_id=principal,
            attempt_id=attempt_id,
            task_kind="read_only_investigation",
            status="succeeded",
            revision=2,
            created_at=created_at,
            updated_at=finished_at,
            retention_until=retention,
            usage=usage,
            budget=budget,
            recorded_at=recorded_at,
            request_summary=(
                "Verify Azure inventory projection completeness and analyzer rule coverage."
            ),
            accountable_agent="Heimdall",
            result_summary=(
                "Completed read-only verification across 827 inventory resources and 944 links."
            ),
            evidence_refs=("inventory-ontology:status", "baseline-evaluation:latest:coverage"),
            terminal_reason="completed",
            started_at=started_at,
            finished_at=finished_at,
            completion_state="delivered",
            completion_attempt_count=1,
            progress_watermark=2,
        )
        prog0 = build_background_task_progress(
            task_id=task_id,
            owner_principal_id=principal,
            attempt_id=attempt_id,
            progress_sequence=0,
            progress_order=1,
            progress_kind="task.started",
            progress_message="Started read-only inventory and analyzer coverage check",
            progress_at=started_at,
            retention_until=retention,
            usage=BackgroundTaskProjectionUsage(tokens=320, cost_microusd=45, tool_calls=1),
            recorded_at=recorded_at,
        )
        prog1 = build_background_task_progress(
            task_id=task_id,
            owner_principal_id=principal,
            attempt_id=attempt_id,
            progress_sequence=1,
            progress_order=2,
            progress_kind="evidence.verified",
            progress_message="Verified 827 projected resources and 732 baseline evaluations",
            progress_at=finished_at,
            retention_until=retention,
            usage=usage,
            recorded_at=recorded_at,
        )
        try:
            await repo.project_background_task_projection(snapshot)
            await repo.project_background_task_projection(prog0)
            await repo.project_background_task_projection(prog1)
        except Exception as exc:
            _ = exc


async def _seed_alert_quality(
    operator_dsn: str,
    *,
    now: datetime,
    principals: list[str],
) -> None:
    store = PostgresFamilyStore(PostgresFamilyStoreConfig(dsn=operator_dsn, role="fdai_operator"))
    aq_store = StateKvAlertQualityStore(store, clock=lambda: now)
    pref_store = StateKvAlertQualityPreferenceStore(store, clock=lambda: now)
    scope_ref = DEFAULT_LOCAL_SCOPE_REF
    tenant_ref = "tenant:azure-local"
    date_tag = f"alert-ev:{now.date().isoformat()}".encode()
    ev_digest = "sha256:" + hashlib.sha256(date_tag).hexdigest()
    pol_digest = "sha256:" + hashlib.sha256(b"alert-noise-policy-v1").hexdigest()
    target_rev = "sha256:" + hashlib.sha256(b"rule:aks-cpu-burst:v1").hexdigest()
    rollback_ref = "sha256:" + hashlib.sha256(b"rollback:aks-cpu-burst:v1").hexdigest()
    observed_at = now - timedelta(minutes=2)
    valid_until = now + timedelta(days=7)
    window_start = now - timedelta(hours=24)
    window_end = now - timedelta(minutes=5)

    assessment = NoiseAssessment(
        evidence_digest=ev_digest,
        policy_digest=pol_digest,
        tenant_ref=tenant_ref,
        scope_ref=scope_ref,
        observed_at=observed_at,
        valid_until=valid_until,
        window_start=window_start,
        window_end=window_end,
        coverage="complete",
        reasons=(),
        source_episodes=42,
        notification_attempts=68,
        confirmed_deliveries=64,
        acknowledgements=19,
        findings=(
            NoiseFinding(
                rule_ref="rule:aks-container-restart-burst",
                service_ref="service:aks-runtime",
                reason="flapping",
                guidance="review-evaluation",
                source_episodes=31,
                observed_deliveries=48,
                potential_recipients_lower=4,
                potential_recipients_upper=4,
                duplicate_paths=2,
                protected=False,
                team_refs=("team:platform-sre",),
                audience_kinds=("channel", "oncall"),
            ),
            NoiseFinding(
                rule_ref="rule:postgres-storage-threshold",
                service_ref="service:state-store",
                reason="protected",
                guidance="retain-protected",
                source_episodes=11,
                observed_deliveries=16,
                potential_recipients_lower=2,
                potential_recipients_upper=2,
                duplicate_paths=0,
                protected=True,
                team_refs=("team:data-platform",),
                audience_kinds=("oncall",),
            ),
        ),
    )

    for principal in principals:
        try:
            await pref_store.set_enabled(
                scope_ref=scope_ref,
                enabled=True,
                expected_revision=0,
                requester_ref=alert_quality_requester_ref(principal, scope_ref),
                before_commit=lambda: None,
            )
        except Exception as exc:
            _ = exc
        try:
            await aq_store.persist_assessment(
                principal_id=principal,
                scope_ref=scope_ref,
                assessment=assessment,
            )
            plan = AlertChangePlan(
                action_type="ops.tune-alert-evaluation",
                tenant_ref=tenant_ref,
                scope_ref=scope_ref,
                requester_ref=alert_quality_requester_ref(principal, scope_ref),
                evidence_digest=ev_digest,
                policy_digest=pol_digest,
                target_revision=target_rev,
                treatment=AlertTreatment(
                    kind="evaluation",
                    target_ref="rule:aks-container-restart-burst",
                    evaluation=Evaluation(
                        metric_ref="metric:container.restart.count",
                        operator="above",
                        threshold=5.0,
                        window_seconds=900,
                        frequency_seconds=300,
                        aggregation="average",
                    ),
                ),
                service_refs=("service:aks-runtime",),
                lock_refs=("lock:rule:aks-container-restart-burst",),
                created_at=observed_at + timedelta(seconds=5),
                expires_at=valid_until,
                max_execution_seconds=300,
                max_observation_seconds=1800,
                max_recovery_seconds=600,
                rollback_ref=rollback_ref,
                evaluation_receipt_digest=digest_record(assessment),
            )
            await aq_store.persist_plan(
                principal_id=principal,
                scope_ref=scope_ref,
                plan=plan,
            )
        except Exception as exc:
            _ = exc

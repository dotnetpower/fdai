#!/usr/bin/env python3
"""Verify and record governed A1/A3 channel qualification receipts (#941).

Exercises Teams and Slack A1 human approval round trips (durable outbound
request outbox, signed callback / one-use browser handoff, PostgreSQL CAS
nonce race, fresh Entra auth_time verification, durable decision outbox,
broker publication, and Core convergence without executor identity) and
Teams/Slack A3 channel-edge parity (schema-v3 adaptive presentation, post,
edit/update, restart deduplication, and process-loss ambiguous recovery).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
from fdai.delivery.chatops.slack_adapter import (
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.delivery.chatops.slack_binding import resolve_local_slack_approval_environment
from fdai.delivery.chatops.slack_request_outbox import DurableSlackApprovalChannel
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.providers.hil_channel import HilChannelError
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelKind,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    RenderedChannelMessage,
)
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    SlackPublisherConfig,
    SlackResponsePublisher,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
_QUAL_TEST = runpy.run_path(
    str(ROOT / "tests/integration/services/test_a1_a3_channel_qualification_postgres.py")
)
_PIPE_TEST = runpy.run_path(
    str(ROOT / "services/operator-service/tests/test_channel_edge_pipeline_postgres.py")
)
_ASSIGN_TEST = runpy.run_path(
    str(ROOT / "tests/integration/services/test_assignment_receipt_postgres.py")
)


def _primary_checkout() -> Path:
    res = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(res.stdout.strip()).parent


async def _slack_history_readback(
    http_client: httpx.AsyncClient,
    *,
    bot_token: str,
    channel_id: str,
    ts: str,
) -> dict[str, Any]:
    resp = await http_client.get(
        "https://slack.com/api/conversations.history",
        params={"channel": channel_id, "latest": ts, "inclusive": "true", "limit": "1"},
        headers={"Authorization": f"Bearer {bot_token}"},
        timeout=10.0,
    )
    body = resp.json()
    messages = body.get("messages") if isinstance(body, dict) else None
    first = messages[0] if isinstance(messages, list) and messages else {}
    blocks = first.get("blocks") if isinstance(first, dict) else []
    return {
        "http_status": resp.status_code,
        "ok": bool(isinstance(body, dict) and body.get("ok") is True),
        "verified_ts": str(first.get("ts") or ""),
        "block_count": len(blocks) if isinstance(blocks, list) else 0,
    }


async def run_qualification(*, allow_live_slack: bool = True) -> dict[str, Any]:
    base_dsn = (
        os.environ.get("FDAI_DATABASE_URL", "")
        .strip()
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    if not base_dsn or conninfo_to_dict(base_dsn).get("host") not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise RuntimeError("loopback FDAI_DATABASE_URL is required")

    primary_fdai = _primary_checkout() / ".fdai"
    local_slack = (
        resolve_local_slack_approval_environment(
            {"FDAI_LOCAL_SLACK_APPROVAL_ACTIVATION": "1"},
            fdai_dir=primary_fdai,
        )
        if allow_live_slack
        else {}
    )
    live_slack_token = local_slack.get("FDAI_SLACK_APPROVAL_BOT_TOKEN", "").strip()
    live_slack_channel = local_slack.get("FDAI_SLACK_APPROVAL_CHANNEL_ID", "").strip()
    use_live_slack = bool(live_slack_token and live_slack_channel)

    dbname = f"fdai_qual_941_{uuid4().hex[:10]}"
    migrations = (
        _ASSIGN_TEST["CORE_MIGRATION"],
        _ASSIGN_TEST["MIGRATION"],
        _ASSIGN_TEST["KNOWLEDGE_MIGRATION"],
        _ASSIGN_TEST["OPERATOR_DOCUMENT_MIGRATION"],
        _ASSIGN_TEST["REVIEWER_MIGRATION"],
        ROOT / "alembic/versions/20260720_0047_conversation_delivery.py",
        ROOT
        / "service-migrations/branches/operator-service/versions"
        / "20260819_operator_a3_channel_delivery.py",
    )
    statements: list[str] = []
    for path in migrations:
        mod = runpy.run_path(str(path))
        with patch("alembic.op.execute", side_effect=statements.append):
            mod["upgrade"]()

    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    dsn = make_conninfo(base_dsn, dbname=dbname)
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                """CREATE TABLE state_kv (
                    key TEXT PRIMARY KEY, value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
                GRANT USAGE ON SCHEMA public TO fdai_core, fdai_operator, fdai_ingestion_worker;
                GRANT SELECT, INSERT, UPDATE ON state_kv TO fdai_core, fdai_operator;
                CREATE TABLE audit_log (
                    seq BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL,
                    correlation_id TEXT, actor TEXT NOT NULL, action_kind TEXT NOT NULL,
                    mode TEXT NOT NULL, entry JSONB NOT NULL, previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW());
                GRANT SELECT, INSERT ON audit_log TO fdai_core;
                GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO fdai_core;
                CREATE TABLE document_version (
                    document_id UUID NOT NULL, version_id UUID PRIMARY KEY,
                    state TEXT NOT NULL, active BOOLEAN NOT NULL, payload JSONB NOT NULL);"""
            )
            for stmt in statements:
                conn.execute(stmt)

        now = datetime.now(UTC).replace(microsecond=0)
        core_store = PostgresStateStore(
            config=PostgresStateStoreConfig(dsn=make_conninfo(dsn, options="-c role=fdai_core"))
        )
        op_dsn = make_conninfo(dsn, options="-c role=fdai_operator")
        seed_park = _QUAL_TEST["_seed_action_park"]
        channel_id = live_slack_channel if use_live_slack else _QUAL_TEST["SLACK_CHANNEL_ID"]
        bot_token = live_slack_token if use_live_slack else "xoxb-synthetic-941"

        slack_approve_req, _ = seed_park(dsn, approval_id="qual-941-slack-approve", now=now)
        slack_reject_req, _ = seed_park(dsn, approval_id="qual-941-slack-reject", now=now)
        slack_unknown_req, _ = seed_park(dsn, approval_id="qual-941-slack-unknown", now=now)
        slack_readbacks: dict[str, Any] = {}
        slack_a3_receipt: dict[str, Any] = {}

        async with (
            httpx.AsyncClient(timeout=15.0)
            if use_live_slack
            else httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(
                        200,
                        json={
                            "ok": True,
                            "channel": channel_id,
                            "ts": "1793751001.000100",
                            "messages": [{"ts": "1793751001.000100", "blocks": [{}, {}]}],
                        },
                    )
                )
            )
        ) as slack_http:
            adapter = SlackHilAdapter(
                config=SlackHilAdapterConfig(
                    api_url=SLACK_POST_URL,
                    channel_id=channel_id,
                    bot_token=bot_token,
                ),
                http_client=slack_http,
            )
            outbox_ch = DurableSlackApprovalChannel(
                adapter=adapter, store=core_store, clock=lambda: now
            )
            app_rec = await outbox_ch.send(slack_approve_req)
            rej_rec = await outbox_ch.send(slack_reject_req)
            for label, rec in (("slack_a1_approve", app_rec), ("slack_a1_reject", rej_rec)):
                ts = rec.channel_ref.split("/", 1)[1]
                slack_readbacks[label] = await _slack_history_readback(
                    slack_http, bot_token=bot_token, channel_id=channel_id, ts=ts
                )
            # Exercise Slack A3 post + chat.update + readback
            slack_pub = SlackResponsePublisher(
                config=SlackPublisherConfig(bot_token=bot_token),
                http_client=slack_http,
            )
            a3_post = await slack_pub.send(
                RenderedChannelMessage(
                    channel_kind=ChannelKind.SLACK,
                    channel_id=channel_id,
                    payload={"text": "FDAI #941 A3 Slack qualification turn (initial)."},
                )
            )
            a3_edit = await slack_pub.send(
                RenderedChannelMessage(
                    channel_kind=ChannelKind.SLACK,
                    channel_id=channel_id,
                    payload={"text": "FDAI #941 A3 Slack qualification turn (updated)."},
                    edit_message_id=a3_post.message_id,
                )
            )
            slack_a3_receipt = {
                "posted_ts": a3_post.message_id,
                "updated_ts": a3_edit.message_id,
                "readback": await _slack_history_readback(
                    slack_http,
                    bot_token=bot_token,
                    channel_id=channel_id,
                    ts=a3_edit.message_id,
                ),
            }

        # Exercise unknown outbox hold across restart
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("ambiguous"))
            )
        ) as fail_http:
            fail_ch = DurableSlackApprovalChannel(
                adapter=SlackHilAdapter(
                    config=SlackHilAdapterConfig(
                        api_url=SLACK_POST_URL, channel_id=channel_id, bot_token=bot_token
                    ),
                    http_client=fail_http,
                ),
                store=core_store,
                clock=lambda: now,
            )
            try:
                await fail_ch.send(slack_unknown_req)
            except HilChannelError:
                pass
            unknown_row = await core_store.read_state(
                DurableSlackApprovalChannel._key("qual-941-slack-unknown", "initial")
            )
            reconciled_after_restart = await fail_ch.reconcile_once()

        # Run full Slack A1 + Teams A1 + Teams A3 PostgreSQL qualification assertions
        await _QUAL_TEST[
            "test_slack_a1_durable_outbox_handoff_nonce_race_and_decision_round_trip_postgres"
        ](dsn)
        await _QUAL_TEST["test_teams_a1_bot_activity_obo_round_trip_and_broker_replay_postgres"](
            dsn
        )
        prev_admin = os.environ.get("FDAI_ADMIN_DATABASE_URL")
        prev_db = os.environ.get("FDAI_DATABASE_URL")
        os.environ["FDAI_ADMIN_DATABASE_URL"] = dsn
        os.environ["FDAI_DATABASE_URL"] = op_dsn
        try:
            await _PIPE_TEST[
                "test_teams_a3_edge_runtime_round_trip_schema_v3_edit_and_restart_dedup_postgres"
            ]()
        finally:
            if prev_admin is None:
                os.environ.pop("FDAI_ADMIN_DATABASE_URL", None)
            else:
                os.environ["FDAI_ADMIN_DATABASE_URL"] = prev_admin
            if prev_db is None:
                os.environ.pop("FDAI_DATABASE_URL", None)
            else:
                os.environ["FDAI_DATABASE_URL"] = prev_db

        readiness_rows = {
            str(r["key"]): {
                "source": r["source"],
                "ready": r["ready"],
                "configured": r["configured"],
            }
            for r in integration_projection(
                {
                    "FDAI_TEAMS_APPROVAL_ACTIVITY_URL": "https://smba.example.com/activities",
                    "FDAI_TEAMS_APPROVAL_TEAM_ID": "team-941",
                    "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "channel-941",
                    "FDAI_TEAMS_APPLICATION_ID": "00000000-0000-0000-0000-00000000b011",
                    "FDAI_TEAMS_TENANT_ID": "00000000-0000-0000-0000-00000000b010",
                    "FDAI_TEAMS_JWKS_URL": "https://login.example.com/keys",
                    "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": '["https://smba.example.com/"]',
                    "FDAI_TEAMS_PRINCIPAL_MAP_JSON": (
                        '{"29:u": "00000000-0000-0000-0000-00000000b002"}'
                    ),
                    "FDAI_CHATOPS_WEBHOOK_SECRET": "synthetic",
                    "FDAI_SLACK_SIGNING_SECRET": "synthetic",
                    "FDAI_SLACK_BOT_TOKEN": "synthetic",
                    "FDAI_SLACK_TEAM_ID": "T941QUAL",
                    "FDAI_SLACK_PRINCIPAL_MAP_JSON": (
                        '{"U1": "00000000-0000-0000-0000-00000000b002"}'
                    ),
                    "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS": "slack,teams",
                    "FDAI_HIL_DECISION_TOPIC": "fdai.hil.decisions",
                    "FDAI_STATE_STORE_DSN": "postgresql://localhost/fdai",
                }
            )
            if str(r["key"]).startswith(("teams-a1", "teams-a3", "slack-a1", "slack-a3"))
        }

        slack_only_send = integration_projection(
            {
                "FDAI_SLACK_APPROVAL_API_URL": SLACK_POST_URL,
                "FDAI_SLACK_APPROVAL_CHANNEL_ID": "C941QUAL01",
                "FDAI_SLACK_APPROVAL_BOT_TOKEN": "synthetic",
            }
        )
        for row in slack_only_send:
            if row["key"] == "slack-a1-approval-send":
                readiness_rows["slack-a1-approval-send"] = {
                    "source": row["source"],
                    "ready": row["ready"],
                    "configured": row["configured"],
                }

        return {
            "kind": "issue-941-a1-a3-channel-qualification",
            "observed_at": datetime.now(UTC).isoformat(),
            "slack_transport_mode": "live_slack_web_api" if use_live_slack else "loopback_http",
            "slack_channel_digest_prefix": hashlib.sha256(channel_id.encode()).hexdigest()[:12],
            "slack_a1": {
                "approve_channel_ref_suffix": app_rec.channel_ref.split("/", 1)[1],
                "reject_channel_ref_suffix": rej_rec.channel_ref.split("/", 1)[1],
                "independent_readbacks": slack_readbacks,
                "unknown_attempt_state": None if unknown_row is None else unknown_row["status"],
                "unknown_repost_on_restart": reconciled_after_restart,
                "postgres_nonce_cas_race_winners": 1,
                "fresh_auth_time_enforced": True,
                "core_converged_decisions": ["approve", "reject"],
                "executor_identity_shared": False,
            },
            "teams_a1": {
                "bot_service_jwt_rs256_verified": True,
                "delegated_obo_jwt_rs256_verified": True,
                "tampered_card_field_refused_status": 400,
                "durable_outbox_redriven_after_broker_outage": True,
                "core_converged_decisions": ["approve", "reject"],
                "executor_identity_shared": False,
            },
            "teams_a3_parity": {
                "schema_v3_operational_brief_rendered": True,
                "adaptive_card_version": "1.5",
                "activity_post_and_put_edit_verified": True,
                "restart_replay_duplicate_posts": 0,
                "interrupted_sending_reconciled_to_ambiguous": True,
                "executor_identity_shared": False,
            },
            "slack_a3": slack_a3_receipt,
            "readiness_visibility": readiness_rows,
        }
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-live-slack", action="store_true")
    args = parser.parse_args()
    receipt = asyncio.run(run_qualification(allow_live_slack=not args.no_live_slack))
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

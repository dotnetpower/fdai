from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from fdai_cost_governance.campaign_export import (
    CostReleaseQualification,
    PostgresCostCampaignObservationSource,
)


def _requires_live_db() -> str:
    dsn = os.environ.get("FDAI_VALIDATION_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL is not configured")
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.asyncio
async def test_postgres_source_joins_complete_authoritative_lineage() -> None:
    base_dsn = _requires_live_db()
    schema = f"cost_export_{uuid4().hex}"
    scoped_dsn = make_conninfo(base_dsn, options=f"-csearch_path={schema}")
    observed_at = datetime.now(tz=UTC).replace(microsecond=0)
    action_id = str(uuid4())
    denied_action_id = str(uuid4())
    event_id = str(uuid4())
    qualification = CostReleaseQualification(
        source_revision="a" * 40,
        revision_pin_digest=f"sha256:{'b' * 64}",
        ontology_competency_passed=True,
        parity_explained=True,
        evidence_refs=(f"sha256:{'c' * 64}", f"sha256:{'d' * 64}"),
        digest=f"sha256:{'e' * 64}",
    )
    connection = psycopg.connect(base_dsn, autocommit=True)
    try:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(
            sql.SQL(
                """
                CREATE TABLE {}.audit_log (
                    seq BIGSERIAL PRIMARY KEY,
                    action_kind TEXT NOT NULL,
                    entry JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE {}.process_runtime (
                    process_id TEXT PRIMARY KEY,
                    workflow_ref TEXT NOT NULL
                );
                CREATE TABLE {}.state_kv (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL
                );
                CREATE TABLE {}.cost_disclosure_audit (
                    decision_id TEXT PRIMARY KEY,
                    authorized BOOLEAN NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE {}.cost_disclosure_audit_retention (
                    decision_id TEXT PRIMARY KEY,
                    purged_at TIMESTAMPTZ NULL
                );
                """
            ).format(*(sql.Identifier(schema) for _ in range(5)))
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.cost_disclosure_audit VALUES (%s, TRUE, %s)"
            ).format(sql.Identifier(schema)),
            ("decision-001", observed_at),
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.cost_disclosure_audit_retention VALUES (%s, NULL)"
            ).format(sql.Identifier(schema)),
            ("decision-001",),
        )
        entries = (
            (
                "risk_gate.unified",
                {
                    "action_id": action_id,
                        "action_type_id": "remediate.right-size",
                        "authority": {
                            "ceiling_inputs": {
                                "kill_switch_engaged": False,
                                "system_degraded": False,
                            }
                        },
                    "correlation_id": "correlation-001",
                    "decision": "shadow",
                    "producer_principal": "Forseti",
                },
            ),
            (
                "remediate.right-size",
                {
                    "action_id": action_id,
                    "audit_phase": "intent",
                    "dry_run_passed": True,
                    "dry_run_receipt": "dry-run:001",
                    "idempotency_key": "action:001",
                },
            ),
            (
                "remediate.right-size",
                {
                    "action_id": action_id,
                    "action_kind": "remediate.right-size",
                    "actor": "fdai.core.executor.shadow",
                    "audit_phase": "terminal",
                    "blast_radius": {"scope": "resource", "count": 1},
                    "dry_run_receipt": "dry-run:001",
                    "idempotency_key": "action:001",
                    "rollback_kind": "pr_revert",
                    "safeguard_bundle_digest": f"sha256:{'f' * 64}",
                    "stop_condition": "provider_api_error_streak",
                    "workflow_action": {
                        "process_id": "process-001",
                        "step_id": "apply_rightsize",
                        "proposal_ref": "proposal-001",
                        "attempt": 1,
                    },
                },
            ),
            (
                "measurement.action_outcome.v1",
                {
                    "action_id": action_id,
                    "action_type_id": "remediate.right-size",
                    "actor": "fdai.measurement",
                    "decision": "auto",
                    "evidence_refs": ["effect:prediction-001"],
                    "event_id": event_id,
                    "execution_mode": "shadow",
                    "execution_outcome": "published",
                    "expected_max": 100,
                    "expected_min": 0,
                    "label": "verified",
                    "metric": "monthly-cost",
                    "observation_deadline": (observed_at + timedelta(hours=1)).isoformat(),
                    "observed_at": observed_at.isoformat(),
                    "predicted_at": (observed_at - timedelta(hours=1)).isoformat(),
                    "prediction_id": "prediction-001",
                    "verification_passed": True,
                    "verification_reason": "value_within_expected_range",
                },
            ),
        )
        for offset, (action_kind, entry) in enumerate(entries):
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.audit_log (action_kind, entry, created_at) "
                    "VALUES (%s, %s, %s)"
                ).format(sql.Identifier(schema)),
                (action_kind, Jsonb(entry), observed_at + timedelta(seconds=offset)),
            )
        connection.execute(
            sql.SQL(
                "INSERT INTO {}.audit_log (action_kind, entry, created_at) "
                "VALUES (%s, %s, %s)"
            ).format(sql.Identifier(schema)),
            (
                "risk_gate.unified",
                Jsonb(
                    {
                        "action_id": denied_action_id,
                        "action_type_id": "remediate.right-size",
                        "authority": {
                            "ceiling_inputs": {
                                "kill_switch_engaged": False,
                                "system_degraded": False,
                            }
                        },
                        "correlation_id": "correlation-001",
                        "decision": "deny",
                        "gate_reasons": ["promotion_required"],
                        "producer_principal": "Forseti",
                        "workflow_action": {
                            "process_id": "process-001",
                            "step_id": "apply_rightsize",
                            "proposal_ref": "proposal-002",
                            "attempt": 1,
                        },
                    }
                ),
                observed_at + timedelta(seconds=len(entries)),
            ),
        )
        connection.execute(
            sql.SQL("INSERT INTO {}.process_runtime VALUES (%s, %s)").format(
                sql.Identifier(schema)
            ),
            ("process-001", "cost-aware-remediation"),
        )
        connection.execute(
            sql.SQL("INSERT INTO {}.state_kv VALUES (%s, %s)").format(
                sql.Identifier(schema)
            ),
            (
                "proposal-001",
                Jsonb(
                    {
                        "kind": "operational_planning.kinetic_proposal",
                        "correlation_id": "correlation-001",
                        "proposal": {"plan": {"plan_id": "prediction-001"}},
                        "operational_plan": {
                            "complete": True,
                            "selection": {"selected_option_id": "option-001"},
                            "decision_case": {
                                "protected_objective_ids": ["service-objective-001"],
                                "options": [
                                    {
                                        "option_id": "option-001",
                                        "action_type": "remediate.right-size",
                                        "effects": [
                                            {
                                                "objective_id": "service-objective-001",
                                                "metric": "monthly-cost",
                                                "expected_min": 0,
                                                "expected_max": 100,
                                            }
                                        ],
                                    }
                                ],
                            },
                        },
                    }
                ),
            ),
        )

        observations = await PostgresCostCampaignObservationSource(
            dsn=scoped_dsn,
            operator_dsn=scoped_dsn,
        ).observations(
            start_at=observed_at - timedelta(minutes=1),
            end_at=observed_at + timedelta(minutes=1),
            action_type_ids=("remediate.right-size",),
            workflow_ids=frozenset({"cost-aware-remediation"}),
            qualification=qualification,
            maximum_episodes=1_000,
        )

        assert len(observations) == 2
        by_id = {item["episode_id"]: item for item in observations}
        executed = by_id[f"action-{action_id}"]
        denied = by_id[f"action-{denied_action_id}"]
        assert executed["protected_objectives_complete"] is True
        assert executed["target_refs"] == [
            "remediate.right-size",
            "cost-aware-remediation",
        ]
        assert denied["outcome"] == "deny"
        assert denied["decision_correct"] is False
        assert denied["settlement_statuses"] == []
        assert denied["effect_path_complete"] is True
        assert denied["target_refs"] == [
            "remediate.right-size",
            "cost-aware-remediation",
        ]
    finally:
        connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        connection.close()
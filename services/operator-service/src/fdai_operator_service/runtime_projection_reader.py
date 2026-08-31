"""Read durable runtime projections that are not stored as state snapshots.

Responsibility: Project Process and automation-blueprint tables into existing Operator DTOs.
Boundary: The reader uses the Operator read-only database role and delegates unknown operations.
Authority and state: Reads only; it cannot create, transition, approve, or execute runtime records.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.families.operations import (
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
)
from fdai_operator_service.investigation_projection import (
    project_adaptive_investigation,
)
from fdai_operator_service.process_transition_projection import (
    ProcessControlUnavailableError,
    project_process_control,
)

_WORKFLOW_CATALOG_KEY = "operator-projection:workflow:workflow.catalog"


@dataclass(frozen=True, slots=True)
class RuntimeProjectionReaderConfig:
    """Configure bounded PostgreSQL reads for runtime-backed Console panels."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


@dataclass(frozen=True, slots=True)
class RuntimeProjectionReader:
    """Serve current runtime records before delegating catalog and legacy reads."""

    config: RuntimeProjectionReaderConfig
    fallback: ProjectionReader

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Return one supported durable projection or delegate unchanged."""
        if query.operation == "process.list":
            return await self._process_list(query)
        if query.operation == "process.events":
            return await self._process_events(query)
        if query.operation == "automation_blueprint.list":
            return await self._automation_blueprints()
        if query.operation == "autonomy":
            return await self._autonomy_measurement()
        if query.operation == "conversation-delivery":
            return await self._conversation_delivery()
        if query.operation == "forecast-learning":
            return await self._forecast_learning()
        if query.operation == "operator-memory":
            return await self._operator_memory(query)
        if query.operation == "skills":
            return await self._skills()
        if query.operation == "detection.readiness":
            return await self._detection_readiness()
        if query.operation == "configuration-baselines":
            return await self._configuration_baselines()
        return await self.fallback.read(query)

    async def _process_list(self, query: ProjectionQuery) -> Mapping[str, object]:
        workflow_ref = _last(query.params.get("workflow_ref"))
        if workflow_ref:
            rows = await self._fetch_all(
                "SELECT runtime.process_id, runtime.workflow_ref, runtime.workflow_version, "
                "runtime.status, runtime.current_step, runtime.target_resource_id, "
                "runtime.updated_at FROM process_runtime AS runtime "
                "JOIN process_event AS created ON created.process_id = runtime.process_id "
                "AND created.kind = 'process.created' "
                "WHERE runtime.workflow_ref = %s "
                "AND LOWER(BTRIM(created.payload #>> "
                "'{resume,context,requester.principal}')) = LOWER(BTRIM(%s)) "
                "ORDER BY runtime.updated_at DESC, runtime.process_id LIMIT 500",
                (workflow_ref, query.principal_id),
            )
        else:
            rows = await self._fetch_all(
                "SELECT runtime.process_id, runtime.workflow_ref, runtime.workflow_version, "
                "runtime.status, runtime.current_step, runtime.target_resource_id, "
                "runtime.updated_at FROM process_runtime AS runtime "
                "JOIN process_event AS created ON created.process_id = runtime.process_id "
                "AND created.kind = 'process.created' "
                "WHERE LOWER(BTRIM(created.payload #>> "
                "'{resume,context,requester.principal}')) = LOWER(BTRIM(%s)) "
                "ORDER BY runtime.updated_at DESC, runtime.process_id LIMIT 500",
                (query.principal_id,),
            )
        return {
            "source": "postgresql:process_runtime",
            "synthetic": False,
            "durable": True,
            "principal_scoped": True,
            "items": [_process_summary(row) for row in rows],
        }

    async def _process_events(self, query: ProjectionQuery) -> Mapping[str, object]:
        process_id = query.path.get("process_id", "")
        process_rows = await self._fetch_all(
            "SELECT runtime.process_id, runtime.workflow_ref, runtime.workflow_version, "
            "runtime.status, runtime.current_step, runtime.target_resource_id, "
            "runtime.started_at, runtime.updated_at, runtime.correlation_id, runtime.revision "
            "FROM process_runtime AS runtime "
            "JOIN process_event AS created ON created.process_id = runtime.process_id "
            "AND created.kind = 'process.created' "
            "WHERE runtime.process_id = %s "
            "AND LOWER(BTRIM(created.payload #>> "
            "'{resume,context,requester.principal}')) = LOWER(BTRIM(%s))",
            (process_id, query.principal_id),
        )
        if not process_rows:
            raise ProjectionNotFoundError(process_id)
        event_rows = await self._fetch_all(
            "SELECT event_id, kind, recorded_at, correlation_id, causation_id, step_id, "
            "attempt, payload FROM process_event WHERE process_id = %s ORDER BY seq",
            (process_id,),
        )
        confirmed_rows = await self._fetch_all(
            "SELECT runtime.process_id, runtime.workflow_ref, runtime.workflow_version, "
            "runtime.status, runtime.current_step, runtime.target_resource_id, "
            "runtime.started_at, runtime.updated_at, runtime.correlation_id, runtime.revision "
            "FROM process_runtime AS runtime "
            "JOIN process_event AS created ON created.process_id = runtime.process_id "
            "AND created.kind = 'process.created' "
            "WHERE runtime.process_id = %s "
            "AND LOWER(BTRIM(created.payload #>> "
            "'{resume,context,requester.principal}')) = LOWER(BTRIM(%s))",
            (process_id, query.principal_id),
        )
        if len(confirmed_rows) != 1 or confirmed_rows[0].get("revision") != process_rows[0].get(
            "revision"
        ):
            raise ProjectionUnavailableError(
                "Process changed while its journal was being projected"
            )
        process = {
            **_process_summary(process_rows[0]),
            "started_at": _timestamp(process_rows[0]["started_at"]),
            "correlation_id": str(process_rows[0]["correlation_id"]),
            "revision": int(process_rows[0]["revision"]),
        }
        events = [
            {
                "event_id": str(row["event_id"]),
                "kind": str(row["kind"]),
                "recorded_at": _timestamp(row["recorded_at"]),
                "correlation_id": str(row["correlation_id"]),
                "causation_id": _optional_text(row["causation_id"]),
                "step_id": _optional_text(row["step_id"]),
                "attempt": int(row["attempt"]),
                "payload": _json_mapping(row["payload"]),
            }
            for row in event_rows
        ]
        catalog_rows = await self._fetch_all(
            "SELECT value FROM state_kv WHERE key = %s",
            (_WORKFLOW_CATALOG_KEY,),
        )
        control: Mapping[str, object]
        if len(catalog_rows) != 1:
            control = _unavailable_process_control(
                process=process,
                reason="Authoritative Workflow catalog projection is unavailable",
            )
        else:
            try:
                approval_state = await self._approval_state(
                    process_id=str(process["id"]),
                    step_id=str(process["current_step"]),
                    events=event_rows,
                )
                control = project_process_control(
                    process=process_rows[0],
                    events=event_rows,
                    workflow_catalog=_json_mapping(catalog_rows[0].get("value")),
                    principal_id=query.principal_id,
                    roles=query.roles,
                    approval_state=approval_state,
                ).payload
            except (ProcessControlUnavailableError, ProjectionUnavailableError) as exc:
                control = _unavailable_process_control(process=process, reason=str(exc))
        return {
            "process": process,
            "events": events,
            "count": len(events),
            "control": control,
            "planning": None,
            "investigation": project_adaptive_investigation(
                process_id=str(process["id"]),
                workflow_ref=str(process["workflow_ref"]),
                workflow_version=str(process["workflow_version"]),
                process_revision=_integer(
                    process["revision"],
                    "process revision",
                ),
                events=events,
            ),
        }

    async def _approval_state(
        self,
        *,
        process_id: str,
        step_id: str,
        events: list[dict[str, Any]],
    ) -> Mapping[str, object] | None:
        latest = next(
            (
                event
                for event in reversed(events)
                if event.get("step_id") == step_id and isinstance(event.get("payload"), Mapping)
            ),
            None,
        )
        if latest is None or _json_mapping(latest["payload"]).get("step_kind") != "approval":
            return None
        attempt = max(_integer(event.get("attempt", 1), "approval attempt") for event in events)
        key = _workflow_approval_key(process_id, step_id, attempt)
        rows = await self._fetch_all("SELECT value FROM state_kv WHERE key = %s", (key,))
        if len(rows) != 1:
            return None
        record = _json_mapping(rows[0].get("value"))
        record["_external_decisions"] = await self._approval_decisions(record)
        return record

    async def _approval_decisions(
        self,
        approval: Mapping[str, object],
    ) -> list[dict[str, object]]:
        slots = approval.get("slots")
        if not isinstance(slots, list) or any(not isinstance(slot, Mapping) for slot in slots):
            raise ProjectionUnavailableError("durable approval slots are malformed")
        keys = [
            f"hil_decision:{slot['idempotency_key']}"
            for slot in slots
            if isinstance(slot.get("idempotency_key"), str)
        ]
        if len(keys) != len(slots) or not keys:
            raise ProjectionUnavailableError("durable approval slots are malformed")
        rows = await self._fetch_all(
            "SELECT key, value FROM state_kv WHERE key = ANY(%s)",
            (keys,),
        )
        decisions: list[dict[str, object]] = []
        for row in rows:
            value = _json_mapping(row.get("value"))
            decisions.append(
                {
                    "principal": str(value.get("approver_oid") or ""),
                    "decision": str(value.get("decision") or ""),
                }
            )
        return decisions

    async def _automation_blueprints(self) -> Mapping[str, object]:
        rows = await self._fetch_all(
            "SELECT candidate_id, normalized_task_intent, schedule_expression, resource_scope, "
            "delivery_intent, required_tools, isolation_profile, estimated_cost_microusd, "
            "evidence_fingerprints, confidence, expires_at, state, enabled, shadow_only, "
            "mutation_tool_ids, realized_usage_count "
            "FROM automation_blueprint_candidate ORDER BY created_at DESC, candidate_id LIMIT 200",
        )
        aggregate_rows = await self._fetch_all(
            "SELECT COUNT(*) AS proposed, "
            "COUNT(*) FILTER (WHERE state = 'accepted') AS accepted, "
            "COUNT(*) FILTER (WHERE state = 'rejected') AS rejected, "
            "COUNT(*) FILTER (WHERE state = 'expired') AS expired, "
            "COUNT(*) FILTER (WHERE state = 'materialized') AS materialized, "
            "COALESCE(SUM(realized_usage_count), 0)::bigint AS realized_usage "
            "FROM automation_blueprint_candidate"
        )
        if len(aggregate_rows) != 1:
            raise ProjectionUnavailableError("automation blueprint aggregate is unavailable")
        aggregate = aggregate_rows[0]
        candidates = [
            {
                "candidate_id": str(row["candidate_id"]),
                "state": str(row["state"]),
                "normalized_task_intent": str(row["normalized_task_intent"]),
                "schedule_expression": str(row["schedule_expression"]),
                "resource_scope": str(row["resource_scope"]),
                "delivery_intent": str(row["delivery_intent"]),
                "required_tools": _string_list(row["required_tools"]),
                "isolation_profile": _json_mapping(row["isolation_profile"]),
                "estimated_cost_microusd": int(row["estimated_cost_microusd"]),
                "evidence_fingerprints": _string_list(row["evidence_fingerprints"]),
                "confidence": float(row["confidence"]),
                "expires_at": _timestamp(row["expires_at"]),
                "enabled": bool(row["enabled"]),
                "shadow_only": bool(row["shadow_only"]),
                "mutation_tool_ids": _string_list(row["mutation_tool_ids"]),
            }
            for row in rows
        ]
        proposed = _integer(aggregate["proposed"], "automation blueprint proposed count")
        accepted = _integer(aggregate["accepted"], "automation blueprint accepted count")
        rejected = _integer(aggregate["rejected"], "automation blueprint rejected count")
        expired = _integer(aggregate["expired"], "automation blueprint expired count")
        materialized = _integer(
            aggregate["materialized"],
            "automation blueprint materialized count",
        )
        realized_usage = _integer(
            aggregate["realized_usage"],
            "automation blueprint realized usage",
        )
        resolved = accepted + materialized + rejected
        return {
            "source": "postgresql:automation_blueprint_candidate",
            "mutation_controls": False,
            "count": len(candidates),
            "candidates": candidates,
            "metrics": {
                "proposed": proposed,
                "accepted": accepted,
                "rejected": rejected,
                "expired": expired,
                "materialized": materialized,
                "realized_usage": realized_usage,
                "candidate_precision": materialized / resolved if resolved else 0.0,
                "acceptance_rate": (accepted + materialized) / proposed if proposed else 0.0,
            },
        }

    async def _autonomy_measurement(self) -> Mapping[str, object]:
        rows = await self._fetch_all(
            "SELECT mode, entry, created_at FROM audit_log "
            "WHERE created_at >= now() - interval '30 days' "
            "AND entry->>'decision' IN ('auto', 'hil', 'abstain', 'deny') "
            "AND entry ? 'tier' ORDER BY seq DESC LIMIT 5000"
        )
        watermark_rows = await self._fetch_all(
            "SELECT MAX(created_at) AS observed_at FROM audit_log"
        )
        decisions = Counter(str(_json_mapping(row["entry"]).get("decision", "")) for row in rows)
        tier_counts = Counter(
            str(_json_mapping(row["entry"]).get("tier", "")).lower() for row in rows
        )
        total = len(rows)
        auto_resolved = decisions["auto"]
        adverse = decisions["abstain"] + decisions["deny"]
        finalized = auto_resolved + adverse
        pending = decisions["hil"]
        as_of = (
            _optional_timestamp(watermark_rows[0].get("observed_at")) if watermark_rows else None
        )
        return {
            "synthetic": False,
            "window_days": 30,
            "sample_size": total,
            "confidence": None,
            "source": {
                "name": "postgresql:audit_log",
                "kind": "audit",
                "as_of": as_of,
            },
            "rules": {
                "active": 0,
                "candidates_30d": 0,
                "promoted_30d": 0,
            },
            "success": {
                "auto_resolution_rate": _metric(
                    auto_resolved / total if total else None,
                    "higher",
                ),
                "human_touchpoints_per_100": _metric(
                    pending / total * 100 if total else None,
                    "lower",
                ),
                "mttr_seconds": _metric(None, "lower"),
                "change_lead_time_seconds": _metric(None, "lower"),
                "cost_per_resolved_event_usd": _metric(None, "lower"),
            },
            "leading": {
                "mixed_model_disagreement_rate": _metric(None, "lower"),
                "verifier_failure_rate": _metric(None, "lower"),
                "shadow_divergence_rate": _metric(None, "lower"),
            },
            "guards": [],
            "finalization": {
                "finalized_events": finalized,
                "pending_events": pending,
                "adverse_events": adverse,
            },
            "attribution": {
                "attributed_events": 0,
                "unattributed_events": total,
                "coverage": 0.0 if total else None,
            },
            "verticals": [
                {
                    "key": "unattributed",
                    "events": total,
                    "auto_resolved": auto_resolved,
                    "open_risks": pending + adverse,
                    "monthly_savings": 0.0,
                }
            ]
            if total
            else [],
            "tier": {
                "mix": {tier: count / total for tier, count in sorted(tier_counts.items()) if tier},
                "bands": {
                    "t0": [0.70, 0.80],
                    "t1": [0.15, 0.20],
                    "t2": [0.05, 0.10],
                },
            },
            "trend": {},
        }

    async def _conversation_delivery(self) -> Mapping[str, object]:
        state_rows = await self._fetch_all(
            "SELECT state, COUNT(*) AS count FROM conversation_outbound_delivery "
            "GROUP BY state ORDER BY state"
        )
        summary_rows = await self._fetch_all(
            "SELECT COUNT(*) AS delivery_count, "
            "COUNT(*) FILTER (WHERE duplicate_risk) AS duplicate_risk_count, "
            "COALESCE(SUM(GREATEST(attempt_count - 1, 0)), 0) AS retry_count, "
            "COUNT(*) FILTER (WHERE state = 'abandoned') AS abandonment_count, "
            "COUNT(terminal_at) AS latency_count, "
            "AVG(EXTRACT(EPOCH FROM (terminal_at - created_at)) * 1000) "
            "FILTER (WHERE terminal_at IS NOT NULL)::double precision AS latency_average, "
            "PERCENTILE_CONT(0.95) WITHIN GROUP ("
            "ORDER BY EXTRACT(EPOCH FROM (terminal_at - created_at)) * 1000"
            ") FILTER (WHERE terminal_at IS NOT NULL)::double precision AS latency_p95, "
            "(SELECT COUNT(*) FROM conversation_outbound_delivery_attempt) AS attempt_count, "
            "(SELECT COUNT(*) FROM conversation_outbound_delivery_acknowledgement) "
            "AS acknowledgement_count FROM conversation_outbound_delivery"
        )
        if len(summary_rows) != 1:
            raise ProjectionUnavailableError("conversation delivery summary is unavailable")
        summary = summary_rows[0]
        states = {
            str(row["state"]): _integer(row["count"], "conversation delivery state count")
            for row in state_rows
        }
        return {
            "source": "postgresql:conversation_outbound_delivery",
            "read_only": True,
            "mutations_available": False,
            "delivery_count": _integer(summary["delivery_count"], "conversation delivery count"),
            "states": states,
            "delivery_latency_ms": {
                "count": _integer(summary["latency_count"], "conversation delivery latency count"),
                "average": _optional_number(
                    summary["latency_average"], "conversation delivery average latency"
                ),
                "p95": _optional_number(
                    summary["latency_p95"], "conversation delivery p95 latency"
                ),
            },
            "duplicate_risk_count": _integer(
                summary["duplicate_risk_count"],
                "conversation delivery duplicate risk count",
            ),
            "retry_count": _integer(summary["retry_count"], "conversation delivery retry count"),
            "abandonment_count": _integer(
                summary["abandonment_count"],
                "conversation delivery abandonment count",
            ),
            "breaker_states": {},
            "attempt_count": _integer(
                summary["attempt_count"], "conversation delivery attempt count"
            ),
            "acknowledgement_count": _integer(
                summary["acknowledgement_count"],
                "conversation delivery acknowledgement count",
            ),
        }

    async def _forecast_learning(self) -> Mapping[str, object]:
        episode_rows = await self._fetch_all(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE closed_at IS NOT NULL) AS closed, "
            "COUNT(*) FILTER (WHERE closed_at IS NULL) AS open, "
            "COUNT(*) FILTER (WHERE closed_at IS NULL AND closure_due_at < now()) AS overdue, "
            "COUNT(*) FILTER (WHERE abstain_reason IS NOT NULL) AS abstained "
            "FROM forecast_episode"
        )
        outcome_rows = await self._fetch_all(
            "SELECT COALESCE(closure_reason, 'closed') AS label, COUNT(*) AS count "
            "FROM forecast_episode WHERE closed_at IS NOT NULL "
            "GROUP BY COALESCE(closure_reason, 'closed') ORDER BY label"
        )
        publication_rows = await self._fetch_all(
            "SELECT COUNT(*) FILTER ("
            "WHERE published_at IS NULL AND dead_lettered_at IS NULL"
            ") AS pending, "
            "COUNT(*) FILTER (WHERE dead_lettered_at IS NOT NULL) AS dead_lettered, "
            "MIN(available_at) FILTER ("
            "WHERE published_at IS NULL AND dead_lettered_at IS NULL"
            ") AS oldest_pending_at FROM forecast_publication_outbox"
        )
        if len(episode_rows) != 1 or len(publication_rows) != 1:
            raise ProjectionUnavailableError("forecast learning summary is unavailable")
        episodes = episode_rows[0]
        publication = publication_rows[0]
        total = _integer(episodes["total"], "forecast episode total")
        closed = _integer(episodes["closed"], "forecast closed count")
        return {
            "source": "postgresql:forecast_episode",
            "durable": True,
            "episodes": {
                "total": total,
                "closed": closed,
                "open": _integer(episodes["open"], "forecast open count"),
                "overdue": _integer(episodes["overdue"], "forecast overdue count"),
                "abstained": _integer(episodes["abstained"], "forecast abstained count"),
                "closure_completeness": closed / total if total else None,
            },
            "outcomes": [
                {
                    "label": str(row["label"]),
                    "miss_origin": None,
                    "count": _integer(row["count"], "forecast outcome count"),
                }
                for row in outcome_rows
            ],
            "publication": {
                "pending": _integer(
                    publication["pending"],
                    "forecast pending publication count",
                ),
                "dead_lettered": _integer(
                    publication["dead_lettered"],
                    "forecast dead-letter count",
                ),
                "oldest_pending_at": (
                    _required_timestamp(publication["oldest_pending_at"]).isoformat()
                    if publication["oldest_pending_at"] is not None
                    else None
                ),
            },
            "retention": {"pending": 0, "overdue": 0},
        }

    async def _operator_memory(self, query: ProjectionQuery) -> Mapping[str, object]:
        scope_kind = _last(query.params.get("scope_kind"))
        scope_ref = _last(query.params.get("scope_ref"))
        rows = await self._fetch_all(
            "SELECT id, scope_kind, scope_ref, category, body, source_event, source_ref, "
            "author, approved_by, created_at, superseded_by, ttl_seconds "
            "FROM operator_memory "
            "WHERE (%s::text IS NULL OR scope_kind = %s) "
            "AND (%s::text IS NULL OR scope_ref = %s) "
            "ORDER BY created_at DESC, id LIMIT 100",
            (scope_kind, scope_kind, scope_ref, scope_ref),
        )
        compactions = await self._fetch_all(
            "SELECT candidate_id, scope_kind, scope_ref, category, body, source_refs, "
            "proposed_by_agent, state, reviewed_by, review_reason "
            "FROM memory_compaction_candidate ORDER BY updated_at DESC, candidate_id LIMIT 100"
        )
        now = datetime.now(UTC)
        items = []
        for row in rows:
            created_at = _required_timestamp(row["created_at"])
            ttl_seconds = int(row["ttl_seconds"] or 0)
            expires_at = created_at + timedelta(seconds=ttl_seconds) if ttl_seconds else None
            superseded_by = _optional_text(row["superseded_by"])
            expired = expires_at is not None and expires_at <= now
            items.append(
                {
                    "id": str(row["id"]),
                    "scope_kind": str(row["scope_kind"]),
                    "scope_ref": str(row["scope_ref"]),
                    "category": str(row["category"]),
                    "body": str(row["body"]),
                    "source_event": str(row["source_event"]),
                    "source_ref": str(row["source_ref"]),
                    "author": str(row["author"]),
                    "approved_by": str(row["approved_by"]),
                    "approval_state": "approved",
                    "created_at": created_at.isoformat(),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "expired": expired,
                    "superseded_by": superseded_by,
                    "active": not expired and superseded_by is None,
                }
            )
        return {
            "items": items,
            "compactions": [
                {
                    "candidate_id": str(row["candidate_id"]),
                    "scope_kind": str(row["scope_kind"]),
                    "scope_ref": str(row["scope_ref"]),
                    "category": str(row["category"]),
                    "body": str(row["body"]),
                    "source_refs": _string_list(row["source_refs"]),
                    "proposed_by_agent": str(row["proposed_by_agent"]),
                    "state": str(row["state"]),
                    "reviewed_by": _optional_text(row["reviewed_by"]),
                    "review_reason": _optional_text(row["review_reason"]),
                }
                for row in compactions
            ],
        }

    async def _skills(self) -> Mapping[str, object]:
        sources = await self._fetch_all(
            "SELECT source.source_id, source.kind, source.enabled, refresh.last_refresh_at, "
            "refresh.error_count, refresh.last_error_kind "
            "FROM skill_source source LEFT JOIN skill_source_refresh_state refresh "
            "ON refresh.source_id = source.source_id ORDER BY source.source_id"
        )
        return {
            "source": "postgresql:skill_source",
            "execution_eligibility": False,
            "trust_rechecked_on_load": False,
            "agent": "runtime-registry",
            "available_tools": [],
            "installed_count": 0,
            "eligible_count": 0,
            "skills": [],
            "installed_bundle_count": 0,
            "eligible_bundle_count": 0,
            "bundles": [],
            "diagnostics": [
                {
                    "operation": "source.refresh",
                    "name": str(row["source_id"]),
                    "reference": str(row["kind"]),
                    "status": (
                        "disabled"
                        if not bool(row["enabled"])
                        else "error"
                        if int(row["error_count"] or 0) > 0
                        else "ready"
                    ),
                    "reason": str(row["last_error_kind"] or "source_registered"),
                    "digests": {},
                }
                for row in sources
            ],
            "mutation_controls": False,
        }

    async def _detection_readiness(self) -> Mapping[str, object]:
        rows = await self._fetch_all(
            "SELECT value, updated_at FROM state_kv "
            "WHERE key LIKE 'runtime:detection-readiness:%%' ORDER BY key"
        )
        targets = [_json_mapping(row["value"]) for row in rows]
        decisions = Counter(str(target.get("decision", "unknown")) for target in targets)
        observed = [
            _required_timestamp(row["updated_at"])
            for row in rows
            if row.get("updated_at") is not None
        ]
        decision_keys = (
            "ready",
            "partial",
            "blocked",
            "stale",
            "unauthorized",
            "unknown",
        )
        return {
            "source": "postgresql:state_kv:detection-readiness",
            "observed_at": max(observed).isoformat() if observed else None,
            "target_count": len(targets),
            "counts": {key: decisions.get(key, 0) for key in decision_keys},
            "targets": targets,
        }

    async def _configuration_baselines(self) -> Mapping[str, object]:
        rows = await self._fetch_all(
            "SELECT value, updated_at FROM state_kv "
            "WHERE key LIKE 'runtime:configuration-baseline:%%' "
            "ORDER BY updated_at DESC, key LIMIT 1"
        )
        if rows:
            return _json_mapping(rows[0]["value"])
        return {
            "baseline": {
                "version": "not-published",
                "scope": "none",
                "created_at": None,
                "document_name": "No published configuration baseline",
                "lifecycle": "not-published",
                "resource_count": 0,
                "topology_count": 0,
                "unknown_count": 0,
            },
            "versions": [],
            "drift": {
                "verdict": "not-evaluated",
                "observed_at": None,
                "finding_count": 0,
            },
            "knowledge": {
                "status": "not-indexed",
                "citation_count": 0,
                "citations": [],
            },
            "safety": {
                "mutation_count": 0,
                "approval_request_count": 0,
                "mitigation_execution_count": 0,
                "unsupported_claim_count": 0,
            },
            "performance": {
                "total_ms": 0.0,
                "observation_ms": 0.0,
                "knowledge_ms": 0.0,
            },
            "review": {
                "configured": False,
                "state": "not-configured",
                "completed_runs": 0,
                "required_runs": 0,
                "failed_attempts": 0,
            },
        }

    async def _fetch_all(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self.config.dsn),
                row_factory=dict_row,
                connect_timeout=self.config.connect_timeout_s,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.config.statement_timeout_ms),),
                )
                cursor = await connection.execute(statement, parameters)
                return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise ProjectionUnavailableError("durable runtime projection is unavailable") from exc


def _process_summary(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["process_id"]),
        "workflow_ref": str(row["workflow_ref"]),
        "workflow_version": str(row["workflow_version"]),
        "status": str(row["status"]),
        "current_step": str(row["current_step"]),
        "target_resource_id": str(row["target_resource_id"]),
        "updated_at": _timestamp(row["updated_at"]),
        "has_view": False,
    }


def _unavailable_process_control(
    *,
    process: Mapping[str, object],
    reason: str,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "authoritative": True,
        "principal_scoped": True,
        "available": False,
        "process_revision": process["revision"],
        "reason": reason,
        "step": None,
        "permitted_transitions": [],
        "acceptance_is_success": False,
    }


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise ProjectionUnavailableError("durable runtime timestamp is malformed")
    return value.isoformat()


def _required_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ProjectionUnavailableError("durable runtime timestamp is malformed")
    return value


def _optional_timestamp(value: object) -> str | None:
    return None if value is None else _timestamp(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _json_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError("durable runtime JSON object is malformed")
    return cast(dict[str, object], dict(value))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProjectionUnavailableError("durable runtime string list is malformed")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return float(value)


def _last(values: tuple[str, ...] | None) -> str | None:
    return values[-1] if values else None


def _metric(value: float | None, direction: str) -> dict[str, object]:
    return {"value": value, "baseline": None, "direction": direction}


def _workflow_approval_key(process_id: str, step_id: str, attempt: int) -> str:
    identity = f"{process_id}\0{step_id}"
    if attempt > 1:
        identity += f"\0{attempt}"
    return f"workflow:approval:{hashlib.sha256(identity.encode()).hexdigest()}"


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


__all__ = ["RuntimeProjectionReader", "RuntimeProjectionReaderConfig"]

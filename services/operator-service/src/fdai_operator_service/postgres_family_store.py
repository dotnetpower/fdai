"""PostgreSQL storage primitives for independently composed Operator families."""

# ruff: noqa: S608 - SQL clauses are module-owned; request values remain bound parameters.

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast
from uuid import uuid4

import anyio
import psycopg
from fdai_service_contracts import OperatorRole, SemanticInvestigationContinuation
from psycopg.rows import dict_row

from fdai_operator_service.environment import EXPECTED_DATABASE_ROLE
from fdai_operator_service.families.conversation.background_tasks import (
    BackgroundTaskProgressProjection,
    BackgroundTaskProjection,
)
from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.operations.contracts import (
    UNSELECTABLE_INSTANCE_DIRECTORY_TYPES,
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactLinkPage,
    InventoryInstanceActivity,
    InventoryInstanceActivityPage,
    InventoryInstanceEdge,
    InventoryInstanceNeighborhood,
    InventoryInstanceResource,
    InventoryInstanceResourcePage,
    InventoryProjectionSourceState,
    InventoryRelationshipDropClassification,
    InventoryRelationshipEvidence,
)
from fdai_operator_service.postgres_semantic_turn_store import (
    PostgresSemanticTurnRepository,
    SemanticTurnClaim,
    SemanticTurnConflictError,
    SemanticTurnStoreError,
    StoredSemanticResult,
    StoredSemanticTurn,
    rule_search_projection_key,
)
from fdai_operator_service.process_transition_projection import (
    ProcessTransitionDeniedError,
    authorize_process_transition,
    project_process_control,
)

_PROJECTION_PREFIX: Final = "operator-projection:"
_PROPOSAL_PREFIX: Final = "operator-proposal:"
_CONTEXT_SELECTION_PREFIX: Final = "context-selection:evaluation:"
_LOGGER = logging.getLogger(__name__)
_MAX_INSTANCE_NEIGHBORHOOD_DEPTH: Final = 8
_MAX_INSTANCE_NEIGHBORHOOD_LINKS: Final = 1_600
# A realtime event reports fresher state, not a whole Resource, so it enriches the snapshot
# record rather than replacing it. Replacing it dropped the name, location, and resource group.
_EFFECTIVE_RESOURCES_CTE: Final = (
    "WITH effective_resources AS ("
    "SELECT snapshot.resource_id, snapshot.resource_type, "
    "CASE WHEN overlay.resource_id IS NULL THEN snapshot.props "
    "ELSE snapshot.props || overlay.props END AS props, "
    "COALESCE(overlay.observed_at, snapshot.last_seen) AS last_seen "
    "FROM inventory_snapshot_resource snapshot "
    "LEFT JOIN inventory_realtime_resource overlay "
    "ON overlay.resource_id=snapshot.resource_id AND overlay.change_kind='upsert' "
    "WHERE snapshot.snapshot_id=%(snapshot_id)s "
    "AND NOT EXISTS (SELECT 1 FROM inventory_realtime_resource removed "
    "WHERE removed.resource_id=snapshot.resource_id AND removed.change_kind='delete') "
    "UNION ALL "
    "SELECT overlay.resource_id, overlay.resource_type, overlay.props, overlay.observed_at "
    "FROM inventory_realtime_resource overlay WHERE overlay.change_kind='upsert' "
    "AND NOT EXISTS (SELECT 1 FROM inventory_snapshot_resource snapshot "
    "WHERE snapshot.snapshot_id=%(snapshot_id)s "
    "AND snapshot.resource_id=overlay.resource_id)) "
)
_EFFECTIVE_LINKS_CTE: Final = (
    "WITH effective_links AS ("
    "SELECT snapshot.from_id, snapshot.from_type, snapshot.link_type, "
    "snapshot.to_id, snapshot.to_type, "
    "CASE WHEN overlay.from_id IS NULL THEN snapshot.props "
    "ELSE snapshot.props || overlay.props END AS props "
    "FROM inventory_snapshot_link snapshot "
    "LEFT JOIN inventory_realtime_link overlay "
    "ON overlay.from_id=snapshot.from_id AND overlay.link_type=snapshot.link_type "
    "AND overlay.to_id=snapshot.to_id AND overlay.change_kind='upsert' "
    "WHERE snapshot.snapshot_id=%(snapshot_id)s "
    "AND NOT EXISTS (SELECT 1 FROM inventory_realtime_link removed "
    "WHERE removed.from_id=snapshot.from_id AND removed.link_type=snapshot.link_type "
    "AND removed.to_id=snapshot.to_id AND removed.change_kind='delete') "
    "UNION ALL "
    "SELECT overlay.from_id, overlay.from_type, overlay.link_type, "
    "overlay.to_id, overlay.to_type, overlay.props "
    "FROM inventory_realtime_link overlay WHERE overlay.change_kind='upsert' "
    "AND NOT EXISTS (SELECT 1 FROM inventory_snapshot_link snapshot "
    "WHERE snapshot.snapshot_id=%(snapshot_id)s "
    "AND snapshot.from_id=overlay.from_id AND snapshot.link_type=overlay.link_type "
    "AND snapshot.to_id=overlay.to_id)) "
)
_BACKGROUND_TASK_STATUSES: Final = frozenset(
    {"queued", "claimed", "running", "succeeded", "failed", "cancelled", "timed_out", "unknown"}
)
_TERMINAL_BACKGROUND_TASK_STATUSES: Final = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "unknown"}
)
_BACKGROUND_COMPLETION_STATES: Final = frozenset(
    {"pending", "sending", "failed", "delivered", "abandoned"}
)
_CONVERSATION_TURN_COLUMNS: Final = (
    "turn.turn_id, turn.conversation_id, turn.turn_index, turn.role, turn.content, "
    "turn.recorded_at, turn.metadata, record.channel_id"
)
_READINESS_SQL: Final = """
SELECT (
           current_user = %(expected_role)s
       AND NOT login_role.rolsuper
       AND NOT login_role.rolcreaterole
       AND NOT login_role.rolcreatedb
       AND NOT login_role.rolreplication
       AND NOT login_role.rolbypassrls
       AND NOT pg_has_role(current_user, 'pg_read_all_data', 'MEMBER')
       AND NOT pg_has_role(current_user, 'pg_write_all_data', 'MEMBER')
    AND has_schema_privilege(current_user, 'public', 'USAGE')
    AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
       AND has_table_privilege(current_user, 'audit_log', 'SELECT')
       AND NOT has_table_privilege(current_user, 'audit_log', 'INSERT')
       AND NOT has_table_privilege(current_user, 'audit_log', 'UPDATE')
       AND NOT has_table_privilege(current_user, 'audit_log', 'DELETE')
       AND NOT has_table_privilege(current_user, 'audit_log', 'TRUNCATE')
       AND NOT has_table_privilege(current_user, 'audit_log', 'REFERENCES')
       AND NOT has_table_privilege(current_user, 'audit_log', 'TRIGGER')
       AND has_table_privilege(current_user, 'state_kv', 'SELECT')
       AND has_table_privilege(current_user, 'state_kv', 'INSERT')
    AND has_table_privilege(current_user, 'state_kv', 'UPDATE')
       AND NOT has_table_privilege(current_user, 'state_kv', 'DELETE')
       AND NOT has_table_privilege(current_user, 'state_kv', 'TRUNCATE')
       AND NOT has_table_privilege(current_user, 'state_kv', 'REFERENCES')
       AND NOT has_table_privilege(current_user, 'state_kv', 'TRIGGER')
    AND has_table_privilege(current_user, 'llm_invocation', 'SELECT')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'INSERT')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'DELETE')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'llm_invocation', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_snapshot', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_snapshot_resource', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_resource', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_snapshot_link', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_snapshot_link', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_active', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_active', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_realtime_resource', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_resource', 'TRIGGER')
    AND has_table_privilege(current_user, 'inventory_realtime_link', 'SELECT')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'INSERT')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'DELETE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'inventory_realtime_link', 'TRIGGER')
    AND has_table_privilege(current_user, 'conversation_record', 'SELECT')
    AND has_table_privilege(current_user, 'conversation_record', 'INSERT')
    AND has_table_privilege(current_user, 'conversation_record', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'conversation_record', 'DELETE')
    AND NOT has_table_privilege(current_user, 'conversation_record', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'conversation_record', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'conversation_record', 'TRIGGER')
    AND has_table_privilege(current_user, 'conversation_turn', 'SELECT')
    AND has_table_privilege(current_user, 'conversation_turn', 'INSERT')
    AND NOT has_table_privilege(current_user, 'conversation_turn', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'conversation_turn', 'DELETE')
    AND NOT has_table_privilege(current_user, 'conversation_turn', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'conversation_turn', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'conversation_turn', 'TRIGGER')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'SELECT')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'INSERT')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'DELETE')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'background_task_attempt', 'TRIGGER')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'SELECT')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'INSERT')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'DELETE')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'background_task_progress', 'TRIGGER')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'SELECT')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'INSERT')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'DELETE')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'background_task_completion', 'TRIGGER')
    AND has_table_privilege(current_user, 'operator_background_task_projection', 'SELECT')
    AND has_table_privilege(current_user, 'operator_background_task_projection', 'INSERT')
    AND has_table_privilege(current_user, 'operator_background_task_projection', 'UPDATE')
    AND has_table_privilege(current_user, 'operator_background_task_projection', 'DELETE')
    AND NOT has_table_privilege(current_user, 'operator_background_task_projection', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'operator_background_task_projection', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'operator_background_task_projection', 'TRIGGER')
    AND has_table_privilege(current_user, 'operator_background_task_progress', 'SELECT')
    AND has_table_privilege(current_user, 'operator_background_task_progress', 'INSERT')
    AND NOT has_table_privilege(current_user, 'operator_background_task_progress', 'UPDATE')
    AND has_column_privilege(
        current_user, 'operator_background_task_progress', 'task_id', 'UPDATE'
    )
    AND has_table_privilege(current_user, 'operator_background_task_progress', 'DELETE')
    AND NOT has_table_privilege(current_user, 'operator_background_task_progress', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'operator_background_task_progress', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'operator_background_task_progress', 'TRIGGER')
    AND has_table_privilege(
        current_user, 'operator_read_investigation_completion', 'SELECT'
    )
    AND has_table_privilege(
        current_user, 'operator_read_investigation_completion', 'INSERT'
    )
    AND NOT has_table_privilege(current_user, 'operator_read_investigation_completion', 'UPDATE')
    AND has_column_privilege(
        current_user, 'operator_read_investigation_completion', 'completion_id', 'UPDATE'
    )
    AND has_table_privilege(current_user, 'operator_read_investigation_completion', 'DELETE')
    AND NOT has_table_privilege(
        current_user, 'operator_read_investigation_completion', 'TRUNCATE'
    )
    AND NOT has_table_privilege(
        current_user, 'operator_read_investigation_completion', 'REFERENCES'
    )
    AND NOT has_table_privilege(current_user, 'operator_read_investigation_completion', 'TRIGGER')
    AND has_sequence_privilege(
        current_user, 'operator_read_investigation_completion_sequence_seq', 'USAGE'
    )
    AND has_table_privilege(current_user, 'process_runtime', 'SELECT')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'INSERT')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'DELETE')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'process_runtime', 'TRIGGER')
    AND has_table_privilege(current_user, 'process_event', 'SELECT')
    AND NOT has_table_privilege(current_user, 'process_event', 'INSERT')
    AND NOT has_table_privilege(current_user, 'process_event', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'process_event', 'DELETE')
    AND NOT has_table_privilege(current_user, 'process_event', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'process_event', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'process_event', 'TRIGGER')
    AND has_table_privilege(current_user, 'automation_blueprint_candidate', 'SELECT')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'INSERT')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'DELETE')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'automation_blueprint_candidate', 'TRIGGER')
    AND has_table_privilege(current_user, 'conversation_assurance_assessment', 'SELECT')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'INSERT')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'DELETE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_assessment', 'TRIGGER')
    AND has_table_privilege(current_user, 'conversation_assurance_dispute', 'SELECT')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'INSERT')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'DELETE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'conversation_assurance_dispute', 'TRIGGER')
    AND has_table_privilege(current_user, 'forecast_episode', 'SELECT')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'INSERT')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'DELETE')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'forecast_episode', 'TRIGGER')
    AND has_table_privilege(current_user, 'forecast_publication_outbox', 'SELECT')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'INSERT')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'DELETE')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'forecast_publication_outbox', 'TRIGGER')
    AND has_table_privilege(current_user, 'operator_memory', 'SELECT')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'INSERT')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'DELETE')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'operator_memory', 'TRIGGER')
    AND has_table_privilege(current_user, 'memory_compaction_candidate', 'SELECT')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'INSERT')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'DELETE')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'memory_compaction_candidate', 'TRIGGER')
    AND has_table_privilege(current_user, 'skill_source', 'SELECT')
    AND NOT has_table_privilege(current_user, 'skill_source', 'INSERT')
    AND NOT has_table_privilege(current_user, 'skill_source', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'skill_source', 'DELETE')
    AND NOT has_table_privilege(current_user, 'skill_source', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'skill_source', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'skill_source', 'TRIGGER')
    AND has_table_privilege(current_user, 'skill_source_refresh_state', 'SELECT')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'INSERT')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'UPDATE')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'DELETE')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'TRUNCATE')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'REFERENCES')
    AND NOT has_table_privilege(current_user, 'skill_source_refresh_state', 'TRIGGER')
       ) AS ready
  FROM pg_catalog.pg_roles AS login_role
 WHERE login_role.rolname = current_user
"""


class PostgresFamilyStoreUnavailableError(RuntimeError):
    """The authoritative PostgreSQL family store could not satisfy a request."""


class PostgresProposalConflictError(RuntimeError):
    """An idempotency key is already bound to different proposal content."""


class PostgresProcessNotVisibleError(RuntimeError):
    """A Process is absent from the authenticated principal's visible scope."""


PostgresFamilyStoreUnavailable = PostgresFamilyStoreUnavailableError
PostgresProposalConflict = PostgresProposalConflictError
PostgresSemanticTurnConflict = SemanticTurnConflictError


@dataclass(frozen=True, slots=True)
class PostgresFamilyStoreConfig:
    """Bound PostgreSQL connection and statement timeouts for family adapters."""

    dsn: str
    role: str = EXPECTED_DATABASE_ROLE
    statement_timeout_ms: int = 20_000
    connect_timeout_s: int = 10
    semantic_outbox_namespace: str | None = None

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PostgreSQL DSN MUST be non-empty")
        _psycopg_dsn(self.dsn)
        if self.role != EXPECTED_DATABASE_ROLE:
            raise ValueError(f"PostgreSQL role MUST be {EXPECTED_DATABASE_ROLE}")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgreSQL timeouts MUST be positive")


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """Durable inert proposal acceptance loaded from the service outbox namespace."""

    proposal_id: str
    accepted_at: str
    duplicate: bool
    record: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ActionProposalClaim:
    """One lease-fenced generic Operator proposal awaiting Core publication."""

    key: str
    claim_id: str
    principal_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class WebhookProposalClaim:
    """One lease-fenced normalized webhook proposal awaiting publication."""

    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class HilDecisionProposalClaim:
    """One lease-fenced durable human-approval decision awaiting publication."""

    key: str
    claim_id: str
    payload: Mapping[str, object]
    attempt: int


@dataclass(frozen=True, slots=True)
class ReadInvestigationProposalClaim:
    """One lease-fenced read proposal awaiting versioned Core publication."""

    key: str
    claim_id: str
    request_id: str
    principal_id: str
    idempotency_key: str
    correlation_id: str | None
    payload: Mapping[str, object]
    accepted_at: str
    attempt: int


@dataclass(frozen=True, slots=True)
class IncidentInterventionProposalClaim:
    """One lease-fenced Incident intervention awaiting versioned publication."""

    key: str
    claim_id: str
    request_id: str
    principal_id: str
    idempotency_key: str
    correlation_id: str
    payload: Mapping[str, object]
    accepted_at: str
    attempt: int


@dataclass(frozen=True, slots=True)
class StoredReplayEvent:
    """One monotonic audit event selected for an Operator replay stream."""

    sequence: int
    event: str
    data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StoredStateRecord:
    """One authoritative state record with the write time that orders its replay."""

    key: str
    value: Mapping[str, object]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredStatePage:
    """One bounded page of state records plus whether the scan proved complete coverage."""

    records: tuple[StoredStateRecord, ...]
    truncated: bool


class PostgresFamilyStore:
    """Read projections and atomically append proposal-only outbox records."""

    def __init__(self, config: PostgresFamilyStoreConfig) -> None:
        self._config = config
        self._semantic_turn_store = PostgresSemanticTurnRepository(
            fetch_all=self._fetch_all,
            insert_if_absent=self._insert_if_absent,
            outbox_namespace=config.semantic_outbox_namespace,
        )

    async def probe_readiness(self) -> bool:
        """Verify required projection tables, columns, grants, and connectivity."""
        rows = await self._fetch_all(
            _READINESS_SQL,
            {"expected_role": self._config.role},
        )
        return len(rows) == 1 and rows[0].get("ready") is True

    async def read_state(self, key: str) -> dict[str, object] | None:
        """Read one existing authoritative state record by its stable key."""
        rows = await self._fetch_all(
            "SELECT value FROM state_kv WHERE key = %(key)s",
            {"key": key},
        )
        return None if not rows else _json_object(rows[0].get("value"), label=key)

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        """Create one state record atomically and report whether this call won."""
        inserted, _ = await self._insert_if_absent(key=key, value=value)
        return inserted

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        """Replace one service-owned state record without applying external effects."""
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(
                        connection,
                        self._config.statement_timeout_ms,
                    )
                    await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key)
                        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        (key, json.dumps(dict(value), separators=(",", ":"), sort_keys=True)),
                    )
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL state store is unavailable"
            ) from exc

    async def find_state(
        self,
        *,
        prefix: str,
        field: str,
        value: str,
    ) -> dict[str, object] | None:
        """Find the newest state record matching one bounded JSON text field."""
        if not field.replace("_", "").isalnum():
            raise ValueError("state field MUST be an ASCII identifier")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = await self._fetch_all(
            """
            SELECT value
              FROM state_kv
             WHERE key LIKE %(prefix)s ESCAPE '\\'
               AND value ->> %(field)s = %(value)s
             ORDER BY updated_at DESC, key DESC
             LIMIT 1
            """,
            {"prefix": f"{escaped_prefix}%", "field": field, "value": value},
        )
        return None if not rows else _json_object(rows[0].get("value"), label=prefix)

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        """Read one explicitly materialized non-synthetic projection."""
        key = _projection_key(family, operation)
        rows = await self._fetch_all(
            "SELECT value FROM state_kv WHERE key = %(key)s",
            {"key": key},
        )
        if not rows:
            raise PostgresFamilyStoreUnavailable(
                f"authoritative {family} projection is unavailable for {operation}"
            )
        return _json_object(rows[0].get("value"), label=key)

    async def list_background_tasks(
        self,
        *,
        owner_principal_id: str,
        before_updated_at: datetime | None,
        before_task_id: str | None,
        limit: int,
    ) -> tuple[BackgroundTaskProjection, ...]:
        """Read one bounded task page filtered in SQL by authenticated owner."""

        _bounded_identifier("owner_principal_id", owner_principal_id)
        if not 1 <= limit <= 101:
            raise ValueError("background task page limit MUST be in [1, 101]")
        if (before_updated_at is None) != (before_task_id is None):
            raise ValueError("background task cursor MUST be complete")
        if before_task_id is not None:
            _bounded_identifier("before_task_id", before_task_id)
        rows = await self._fetch_all(
            """
            SELECT task.task_id, task.attempt_id,
                  task.task_kind,
                  task.status, task.revision,
                  task.created_at, task.updated_at, task.retention_until,
                  task.lease_expires_at,
                  task.budget,
                  task.usage,
                  task.request_summary,
                  task.request_truncated,
                  task.accountable_agent,
                  task.result_summary,
                  task.result_truncated,
                  task.evidence_refs,
                  task.evidence_truncated,
                  task.terminal_reason,
                  task.started_at,
                  task.finished_at,
                  task.completion_state,
                  task.progress_watermark
              FROM operator_background_task_projection AS task
             WHERE task.principal_id = %(owner_principal_id)s
               AND task.retention_until > CURRENT_TIMESTAMP
               AND (%(before_updated_at)s::timestamptz IS NULL
                    OR (task.updated_at, task.task_id)
                       < (%(before_updated_at)s::timestamptz, %(before_task_id)s))
             ORDER BY task.updated_at DESC, task.task_id DESC
             LIMIT %(limit)s
            """,
            {
                "owner_principal_id": owner_principal_id,
                "before_updated_at": before_updated_at,
                "before_task_id": before_task_id,
                "limit": limit,
            },
        )
        return tuple(_background_task_projection(row) for row in rows)

    async def read_background_task(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
    ) -> BackgroundTaskProjection | None:
        """Read one task only when the authenticated principal owns it."""

        _bounded_identifier("owner_principal_id", owner_principal_id)
        _bounded_identifier("task_id", task_id)
        rows = await self._fetch_all(
            """
            SELECT task.task_id, task.attempt_id,
                   task.task_kind,
                   task.status, task.revision,
                   task.created_at, task.updated_at, task.retention_until,
                   task.lease_expires_at,
                   task.budget,
                   task.usage,
                   task.request_summary,
                   task.request_truncated,
                   task.accountable_agent,
                   task.result_summary,
                   task.result_truncated,
                   task.evidence_refs,
                   task.evidence_truncated,
                   task.terminal_reason,
                   task.started_at,
                   task.finished_at,
                   task.completion_state,
                   task.progress_watermark,
                   COALESCE(
                       (
                           SELECT MAX(progress.progress_order)
                             FROM operator_background_task_progress AS progress
                            WHERE progress.principal_id = %(owner_principal_id)s
                              AND progress.task_id = task.task_id
                              AND progress.retention_until > CURRENT_TIMESTAMP
                       ),
                       0
                   ) AS latest_progress_order
              FROM operator_background_task_projection AS task
             WHERE task.principal_id = %(owner_principal_id)s
               AND task.task_id = %(task_id)s
               AND task.retention_until > CURRENT_TIMESTAMP
             LIMIT 1
            """,
            {"owner_principal_id": owner_principal_id, "task_id": task_id},
        )
        return None if not rows else _background_task_projection(rows[0])

    async def read_background_task_progress(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[BackgroundTaskProgressProjection, ...]:
        """Read monotonic progress through an owner-filtered task join."""

        _bounded_identifier("owner_principal_id", owner_principal_id)
        _bounded_identifier("task_id", task_id)
        if not -1 <= after_sequence <= 2**31:
            raise ValueError("background task progress cursor is outside the bounded range")
        if not 1 <= limit <= 256:
            raise ValueError("background task progress limit MUST be in [1, 256]")
        rows = await self._fetch_all(
            """
            SELECT progress.progress_sequence AS sequence,
                   progress.progress_order AS progress_order,
                   progress.progress_kind AS kind,
                   progress.progress_message AS message,
                   progress.progress_at AS at,
                   progress.usage
              FROM operator_background_task_progress AS progress
             WHERE progress.principal_id = %(owner_principal_id)s
               AND progress.task_id = %(task_id)s
               AND progress.retention_until > CURRENT_TIMESTAMP
               AND progress.progress_sequence > %(after_sequence)s
             ORDER BY progress.progress_sequence ASC
             LIMIT %(limit)s
            """,
            {
                "owner_principal_id": owner_principal_id,
                "task_id": task_id,
                "after_sequence": after_sequence,
                "limit": limit,
            },
        )
        return tuple(_background_task_progress(row) for row in rows)

    async def read_inventory_impact_context(self) -> InventoryImpactContext | None:
        """Read the exact active snapshot identity and cutoff without provider payloads."""

        rows = await self._fetch_all(
            "SELECT snapshot.id, snapshot.completed_at, snapshot.metadata "
            "FROM inventory_active AS active "
            "JOIN inventory_snapshot AS snapshot ON snapshot.id = active.snapshot_id "
            "WHERE active.singleton = TRUE "
            "AND snapshot.status = 'active' "
            "AND snapshot.completed_at IS NOT NULL",
            {},
        )
        if not rows:
            return None
        snapshot_id = str(rows[0].get("id") or "")
        if not snapshot_id:
            raise PostgresFamilyStoreUnavailable("active inventory snapshot identity is malformed")
        raw_metadata = rows[0].get("metadata")
        metadata = (
            {}
            if raw_metadata is None
            else _json_object(raw_metadata, label="active inventory metadata")
        )
        raw_reasons = metadata.get("relationship_drop_reasons", [])
        if not isinstance(raw_reasons, list) or any(
            not isinstance(reason, str) or not reason.strip() or len(reason) > 128
            for reason in raw_reasons
        ):
            raise PostgresFamilyStoreUnavailable(
                "active inventory relationship coverage is malformed"
            )
        relationship_drop_reasons = tuple(sorted(set(raw_reasons)))
        relationship_drop_classifications = _relationship_drop_classifications(
            metadata.get("relationship_drop_classifications", [])
        )
        projection_source_states = _projection_source_states(
            metadata.get("derived_source_states", [])
        )
        return InventoryImpactContext(
            snapshot_id=snapshot_id,
            observed_at=_stored_timestamp(
                rows[0].get("completed_at"),
                label="active inventory snapshot",
            ),
            relationship_drop_reasons=relationship_drop_reasons,
            relationship_drop_classifications=relationship_drop_classifications,
            projection_source_states=projection_source_states,
        )

    async def inventory_resource_exists(self, *, snapshot_id: str, resource_id: str) -> bool:
        """Check one exact Resource identity inside the selected snapshot."""

        rows = await self._fetch_all(
            "SELECT 1 AS present FROM inventory_snapshot_resource "
            "WHERE snapshot_id = %(snapshot_id)s AND resource_id = %(resource_id)s "
            "LIMIT 1",
            {"snapshot_id": snapshot_id, "resource_id": resource_id},
        )
        return bool(rows)

    async def read_inventory_outgoing_links(
        self,
        *,
        snapshot_id: str,
        source_ids: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactLinkPage:
        """Read one stable stored-direction frontier with an explicit edge bound."""

        if not source_ids or len(source_ids) > 1_000:
            raise ValueError("inventory impact frontier MUST contain 1 to 1000 Resources")
        if not link_types or len(link_types) > 16:
            raise ValueError("inventory impact link types MUST contain 1 to 16 values")
        if not 1 <= limit <= 1_000:
            raise ValueError("inventory impact link limit MUST be in [1, 1000]")
        rows = await self._fetch_all(
            "SELECT from_id, link_type, to_id "
            "FROM inventory_snapshot_link "
            "WHERE snapshot_id = %(snapshot_id)s "
            "AND from_id = ANY(%(source_ids)s) "
            "AND link_type = ANY(%(link_types)s) "
            "ORDER BY from_id, link_type, to_id "
            "LIMIT %(probe)s",
            {
                "snapshot_id": snapshot_id,
                "source_ids": list(source_ids),
                "link_types": list(link_types),
                "probe": limit + 1,
            },
        )
        return InventoryImpactLinkPage(
            edges=tuple(
                InventoryImpactEdge(
                    source=str(row.get("from_id") or ""),
                    target=str(row.get("to_id") or ""),
                    link_type=str(row.get("link_type") or ""),
                )
                for row in rows[:limit]
            ),
            truncated=len(rows) > limit,
        )

    async def read_inventory_instance_neighborhood(
        self,
        *,
        snapshot_id: str,
        root_id: str,
        link_types: tuple[str, ...],
        depth: int,
        limit: int,
    ) -> InventoryInstanceNeighborhood:
        """Read one bounded active-snapshot component without RG sibling inference."""

        if not root_id.strip() or len(root_id) > 1_024:
            raise ValueError("instance root_id MUST be a bounded non-empty string")
        if not link_types or len(link_types) > 16:
            raise ValueError("instance link types MUST contain 1 to 16 values")
        if not 1 <= depth <= _MAX_INSTANCE_NEIGHBORHOOD_DEPTH:
            raise ValueError("instance depth MUST be in [1, 8]")
        if not 1 <= limit <= 200:
            raise ValueError("instance resource limit MUST be in [1, 200]")
        root_rows = await self._fetch_all(
            _EFFECTIVE_RESOURCES_CTE
            + "SELECT resource_id, resource_type, props, last_seen FROM effective_resources "
            "WHERE resource_id=%(root_id)s",
            {
                "snapshot_id": snapshot_id,
                "root_id": root_id,
            },
        )
        if not root_rows:
            return InventoryInstanceNeighborhood(resources=(), edges=(), truncated=False)
        root_type = str(root_rows[0].get("resource_type") or "")
        selected = {root_id}
        frontier = {root_id}
        resource_truncated = False
        adjacent_truncated = False
        for _ in range(depth):
            if not frontier:
                break
            edge_rows = await self._fetch_all(
                _EFFECTIVE_LINKS_CTE
                + "SELECT from_id, from_type, link_type, to_id, to_type, props "
                "FROM effective_links WHERE link_type=ANY(%(link_types)s) "
                "AND ((from_id=ANY(%(frontier)s) AND NOT (to_id=ANY(%(selected)s))) "
                "OR (to_id=ANY(%(frontier)s) AND NOT (from_id=ANY(%(selected)s)))) "
                "ORDER BY LEAST(from_id, to_id), GREATEST(from_id, to_id), "
                "link_type, from_id, to_id LIMIT %(probe)s",
                {
                    "snapshot_id": snapshot_id,
                    "link_types": list(link_types),
                    "frontier": sorted(frontier),
                    "selected": sorted(selected),
                    "probe": _MAX_INSTANCE_NEIGHBORHOOD_LINKS + 1,
                },
            )
            if len(edge_rows) > _MAX_INSTANCE_NEIGHBORHOOD_LINKS:
                adjacent_truncated = True
                edge_rows = edge_rows[:_MAX_INSTANCE_NEIGHBORHOOD_LINKS]
            next_frontier: set[str] = set()
            for row in edge_rows:
                for endpoint, endpoint_type in (
                    (str(row.get("from_id") or ""), str(row.get("from_type") or "")),
                    (str(row.get("to_id") or ""), str(row.get("to_type") or "")),
                ):
                    if not endpoint or endpoint in selected:
                        continue
                    if len(selected) >= limit:
                        resource_truncated = True
                        continue
                    selected.add(endpoint)
                    if endpoint_type not in {"resource-group", "subscription"} or root_type in {
                        "resource-group",
                        "subscription",
                    }:
                        next_frontier.add(endpoint)
            frontier = next_frontier
        resource_rows = await self._fetch_all(
            _EFFECTIVE_RESOURCES_CTE
            + "SELECT resource_id, resource_type, props, last_seen FROM effective_resources "
            "WHERE resource_id = ANY(%(resource_ids)s) "
            "ORDER BY resource_id",
            {
                "snapshot_id": snapshot_id,
                "resource_ids": sorted(selected),
            },
        )
        induced_rows = await self._fetch_all(
            _EFFECTIVE_LINKS_CTE + "SELECT from_id, link_type, to_id, props FROM effective_links "
            "WHERE link_type = ANY(%(link_types)s) "
            "AND from_id = ANY(%(resource_ids)s) "
            "AND to_id = ANY(%(resource_ids)s) "
            "ORDER BY CASE WHEN from_id = %(root_id)s OR to_id = %(root_id)s "
            "THEN 0 ELSE 1 END, from_id, link_type, to_id "
            "LIMIT %(probe)s",
            {
                "snapshot_id": snapshot_id,
                "link_types": list(link_types),
                "resource_ids": sorted(selected),
                "root_id": root_id,
                "probe": _MAX_INSTANCE_NEIGHBORHOOD_LINKS + 1,
            },
        )
        selected_induced_rows = induced_rows[:_MAX_INSTANCE_NEIGHBORHOOD_LINKS]
        induced_truncated = len(induced_rows) > _MAX_INSTANCE_NEIGHBORHOOD_LINKS
        truncation_reasons = tuple(
            reason
            for reason, active in (
                ("adjacent_edge_limit", adjacent_truncated),
                ("resource_limit", resource_truncated),
                ("link_limit", induced_truncated),
            )
            if active
        )
        return InventoryInstanceNeighborhood(
            resources=tuple(
                InventoryInstanceResource(
                    resource_id=str(row.get("resource_id") or ""),
                    resource_type=str(row.get("resource_type") or ""),
                    properties=_json_object(
                        row.get("props"),
                        label="inventory instance Resource properties",
                    ),
                    last_seen=_optional_timestamp(row.get("last_seen")),
                )
                for row in resource_rows
            ),
            edges=tuple(
                InventoryInstanceEdge(
                    source=str(row.get("from_id") or ""),
                    target=str(row.get("to_id") or ""),
                    link_type=str(row.get("link_type") or ""),
                    evidence=_instance_relationship_evidence(row.get("props")),
                )
                for row in selected_induced_rows
            ),
            truncated=bool(truncation_reasons),
            truncation_reasons=truncation_reasons,
        )

    async def read_inventory_instances(
        self,
        *,
        snapshot_id: str,
        search: str | None,
        limit: int,
    ) -> InventoryInstanceResourcePage:
        """Read a bounded active-generation Resource directory with optional search."""

        if search is not None and (not search.strip() or len(search) > 256):
            raise ValueError("instance search MUST contain 1 to 256 characters")
        if not 1 <= limit <= 200:
            raise ValueError("instance directory limit MUST be in [1, 200]")
        pattern = f"%{_escape_like(search.strip())}%" if search is not None else None
        rows = await self._fetch_all(
            "SELECT resource_id, resource_type, props, last_seen "
            "FROM inventory_snapshot_resource "
            "WHERE snapshot_id = %(snapshot_id)s "
            "AND resource_type <> ALL(%(unselectable_types)s) "
            "AND (%(pattern)s::text IS NULL "
            "OR COALESCE(props ->> 'name', '') ILIKE %(pattern)s ESCAPE '\\' "
            "OR resource_type ILIKE %(pattern)s ESCAPE '\\' "
            "OR resource_id ILIKE %(pattern)s ESCAPE '\\') "
            "ORDER BY COALESCE(NULLIF(props ->> 'name', ''), resource_id), resource_id "
            "LIMIT %(probe)s",
            {
                "snapshot_id": snapshot_id,
                "pattern": pattern,
                "probe": limit + 1,
                "unselectable_types": list(UNSELECTABLE_INSTANCE_DIRECTORY_TYPES),
            },
        )
        return InventoryInstanceResourcePage(
            resources=tuple(
                InventoryInstanceResource(
                    resource_id=str(row.get("resource_id") or ""),
                    resource_type=str(row.get("resource_type") or ""),
                    properties=_json_object(
                        row.get("props"),
                        label="inventory instance directory Resource properties",
                    ),
                    last_seen=_optional_timestamp(row.get("last_seen")),
                )
                for row in rows[:limit]
            ),
            truncated=len(rows) > limit,
        )

    async def read_inventory_instance_activity(
        self,
        *,
        resource_id: str,
        limit: int,
    ) -> InventoryInstanceActivityPage:
        """Read newest durable audit facts with an exact structured Resource identity match."""

        if not resource_id.strip() or len(resource_id) > 1_024:
            raise ValueError("instance activity resource_id MUST be bounded")
        if not 1 <= limit <= 100:
            raise ValueError("instance activity limit MUST be in [1, 100]")
        rows = await self._fetch_all(
            "SELECT seq, correlation_id, actor, action_kind, entry, created_at "
            "FROM audit_log "
            "WHERE entry #>> '{payload,resource_id}' = %(resource_id)s "
            "ORDER BY seq DESC "
            "LIMIT %(probe)s",
            {"resource_id": resource_id, "probe": limit + 1},
        )
        activities: list[InventoryInstanceActivity] = []
        for row in rows[:limit]:
            sequence = row.get("seq")
            actor = row.get("actor")
            action_kind = row.get("action_kind")
            if (
                not isinstance(sequence, int)
                or not isinstance(actor, str)
                or not isinstance(action_kind, str)
            ):
                raise PostgresFamilyStoreUnavailable("instance activity row is malformed")
            entry = _json_object(row.get("entry"), label=f"audit_log[{sequence}].entry")
            payload = _json_object(entry.get("payload"), label=f"audit_log[{sequence}].payload")
            activities.append(
                InventoryInstanceActivity(
                    sequence=sequence,
                    action_kind=action_kind,
                    actor=actor,
                    recorded_at=_stored_timestamp(
                        row.get("created_at"),
                        label=f"audit_log[{sequence}]",
                    ),
                    correlation_id=_activity_correlation(row, payload),
                    facts=_instance_activity_facts(payload),
                )
            )
        return InventoryInstanceActivityPage(
            activities=tuple(activities),
            truncated=len(rows) > limit,
        )

    async def read_state_page(
        self,
        *,
        prefix: str,
        limit: int,
        match_field: str | None = None,
        match_value: str | None = None,
    ) -> StoredStatePage:
        """Read a bounded newest-first page and report whether more records were left behind."""
        if not prefix.strip():
            raise ValueError("state prefix MUST be a bounded non-empty string")
        if not 1 <= limit <= 1_000:
            raise ValueError("state page limit MUST be between 1 and 1000")
        if (match_field is None) != (match_value is None):
            raise ValueError("state page match field and value MUST be supplied together")
        if match_field is not None and not match_field.replace("_", "").isalnum():
            raise ValueError("state field MUST be an ASCII identifier")
        match_clause = "" if match_field is None else "   AND value ->> %(field)s = %(match)s\n"
        rows = await self._fetch_all(
            "SELECT key, value, updated_at\n"
            "  FROM state_kv\n"
            " WHERE key LIKE %(prefix)s ESCAPE '\\'\n"
            f"{match_clause}"
            " ORDER BY updated_at DESC, key DESC\n"
            " LIMIT %(probe)s",
            {
                "prefix": f"{_escape_like(prefix)}%",
                "probe": limit + 1,
                "field": match_field,
                "match": match_value,
            },
        )
        return StoredStatePage(
            records=tuple(
                StoredStateRecord(
                    key=str(row.get("key") or ""),
                    value=_json_object(row.get("value"), label=prefix),
                    updated_at=_stored_timestamp(row.get("updated_at"), label=prefix),
                )
                for row in rows[:limit]
            ),
            truncated=len(rows) > limit,
        )

    async def search_conversation_turns(
        self,
        *,
        principal_id: str,
        normalized_text: str,
        mode: str,
        tokens: tuple[str, ...],
        channels: tuple[str, ...],
        roles: tuple[str, ...],
        conversation_id: str | None,
        incident_id: str | None,
        correlation_id: str | None,
        recorded_after: datetime | None,
        recorded_before: datetime | None,
        candidate_limit: int,
    ) -> list[dict[str, Any]]:
        """Read bounded search candidates inside the authenticated principal scope."""

        clauses = ["turn.principal_id = %(principal_id)s"]
        parameters: dict[str, object] = {
            "principal_id": principal_id,
            "normalized_text": normalized_text,
            "candidate_limit": candidate_limit,
        }
        if channels:
            clauses.append("record.channel_id = ANY(%(channels)s)")
            parameters["channels"] = list(channels)
        if roles:
            clauses.append("turn.role = ANY(%(roles)s)")
            parameters["roles"] = list(roles)
        for field, sql, item in (
            ("conversation_id", "turn.conversation_id = %(conversation_id)s", conversation_id),
            ("incident_id", "turn.metadata ->> 'incident_id' = %(incident_id)s", incident_id),
            (
                "correlation_id",
                "turn.metadata ->> 'correlation_id' = %(correlation_id)s",
                correlation_id,
            ),
            ("recorded_after", "turn.recorded_at > %(recorded_after)s", recorded_after),
            ("recorded_before", "turn.recorded_at < %(recorded_before)s", recorded_before),
        ):
            if item is not None:
                clauses.append(sql)
                parameters[field] = item
        if mode == "phrase":
            clauses.append("turn.search_text LIKE %(phrase)s ESCAPE '\\'")
            parameters["phrase"] = f"%{_escape_like(normalized_text)}%"
        elif mode == "prefix":
            for index, token in enumerate(tokens):
                key = f"prefix_{index}"
                clauses.append(f"turn.search_text ~ %({key})s")
                parameters[key] = r"(^|[^[:alnum:]_])" + re.escape(token)
        else:
            for index, token in enumerate(tokens):
                key = f"term_{index}"
                clauses.append(f"turn.search_text LIKE %({key})s ESCAPE '\\'")
                parameters[key] = f"%{_escape_like(token)}%"
        return await self._fetch_all(
            f"SELECT {_CONVERSATION_TURN_COLUMNS}, "  # noqa: S608
            "GREATEST(similarity(turn.search_text, %(normalized_text)s), 0) AS sql_rank "
            "FROM conversation_turn AS turn "
            "JOIN conversation_record AS record "
            "ON record.principal_id = turn.principal_id "
            "AND record.conversation_id = turn.conversation_id "
            f"WHERE {' AND '.join(clauses)} "  # noqa: S608
            "ORDER BY sql_rank DESC, turn.recorded_at DESC, turn.turn_id "
            "LIMIT %(candidate_limit)s",
            parameters,
        )

    async def measure_conversation_turns(
        self,
        *,
        principal_id: str,
        channels: tuple[str, ...],
        conversation_id: str | None,
    ) -> dict[str, int]:
        """Measure only rows visible inside the authenticated principal scope."""

        clauses = ["turn.principal_id = %(principal_id)s"]
        parameters: dict[str, object] = {"principal_id": principal_id}
        if channels:
            clauses.append("record.channel_id = ANY(%(channels)s)")
            parameters["channels"] = list(channels)
        if conversation_id is not None:
            clauses.append("turn.conversation_id = %(conversation_id)s")
            parameters["conversation_id"] = conversation_id
        statement = (
            "SELECT COUNT(*) AS index_rows, "
            "COALESCE(SUM(octet_length(turn.content)), 0) AS index_bytes "
            "FROM conversation_turn AS turn "
            "JOIN conversation_record AS record "
            "ON record.principal_id = turn.principal_id "
            "AND record.conversation_id = turn.conversation_id "
            f"WHERE {' AND '.join(clauses)}"
        )
        rows = await self._fetch_all(statement, parameters)
        if len(rows) != 1:
            raise PostgresFamilyStoreUnavailable("conversation search measurements are unavailable")
        return {
            "index_rows": int(rows[0].get("index_rows", -1)),
            "index_bytes": int(rows[0].get("index_bytes", -1)),
        }

    async def read_conversation_search_context(
        self,
        *,
        principal_id: str,
        turn_id: str,
        before: int,
        after: int,
    ) -> list[dict[str, Any]]:
        """Read one scoped hit and bounded neighbors in a single SQL snapshot."""

        return await self._fetch_all(
            f"""
            WITH target AS (
                SELECT turn.conversation_id, turn.turn_index
                  FROM conversation_turn AS turn
                 WHERE turn.principal_id = %(principal_id)s
                   AND turn.turn_id = %(turn_id)s
            ), selected AS (
                (SELECT {_CONVERSATION_TURN_COLUMNS}, 'before' AS section
                   FROM conversation_turn AS turn
                   JOIN conversation_record AS record
                     ON record.principal_id = turn.principal_id
                    AND record.conversation_id = turn.conversation_id
                   JOIN target ON target.conversation_id = turn.conversation_id
                  WHERE turn.principal_id = %(principal_id)s
                    AND turn.turn_index < target.turn_index
                  ORDER BY turn.turn_index DESC
                  LIMIT %(before)s)
                UNION ALL
                (SELECT {_CONVERSATION_TURN_COLUMNS}, 'hit' AS section
                   FROM conversation_turn AS turn
                   JOIN conversation_record AS record
                     ON record.principal_id = turn.principal_id
                    AND record.conversation_id = turn.conversation_id
                  WHERE turn.principal_id = %(principal_id)s
                    AND turn.turn_id = %(turn_id)s)
                UNION ALL
                (SELECT {_CONVERSATION_TURN_COLUMNS}, 'after' AS section
                   FROM conversation_turn AS turn
                   JOIN conversation_record AS record
                     ON record.principal_id = turn.principal_id
                    AND record.conversation_id = turn.conversation_id
                   JOIN target ON target.conversation_id = turn.conversation_id
                  WHERE turn.principal_id = %(principal_id)s
                    AND turn.turn_index > target.turn_index
                  ORDER BY turn.turn_index ASC
                  LIMIT %(after)s)
            )
            SELECT * FROM selected
             ORDER BY turn_index, turn_id
            """,  # noqa: S608
            {
                "principal_id": principal_id,
                "turn_id": turn_id,
                "before": before,
                "after": after,
            },
        )

    async def read_conversation_lineage(
        self,
        *,
        principal_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Read one scoped conversation and its bounded ordered turn lineage."""

        rows = await self._fetch_all(
            """
            SELECT record.conversation_id, record.channel_id,
                   record.started_at, record.last_active,
                   ARRAY(
                       SELECT turn.turn_id
                         FROM conversation_turn AS turn
                        WHERE turn.principal_id = record.principal_id
                          AND turn.conversation_id = record.conversation_id
                        ORDER BY turn.turn_index
                        LIMIT 1000
                   ) AS turn_ids
              FROM conversation_record AS record
             WHERE record.principal_id = %(principal_id)s
               AND record.conversation_id = %(conversation_id)s
            """,
            {"principal_id": principal_id, "conversation_id": conversation_id},
        )
        return rows[0] if rows else None

    async def read_conversation_summaries(
        self,
        *,
        principal_id: str,
        before_last_active: datetime | None,
        before_conversation_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read one bounded newest-first conversation page inside the principal scope."""

        if (before_last_active is None) != (before_conversation_id is None):
            raise ValueError("conversation cursor MUST be complete")
        parameters: dict[str, object] = {"principal_id": principal_id, "limit": limit}
        cursor_clause = ""
        if before_last_active is not None:
            cursor_clause = (
                " AND (record.last_active, record.conversation_id)"
                " < (%(before_last_active)s, %(before_conversation_id)s)"
            )
            parameters["before_last_active"] = before_last_active
            parameters["before_conversation_id"] = before_conversation_id
        return await self._fetch_all(
            "SELECT record.conversation_id, record.channel_id, record.started_at,"
            " record.last_active, record.status,"
            " (SELECT turn.turn_id FROM conversation_turn AS turn"
            "   WHERE turn.principal_id = record.principal_id"
            "     AND turn.conversation_id = record.conversation_id"
            "     AND turn.role = 'operator'"
            "   ORDER BY turn.turn_index DESC LIMIT 1) AS latest_operator_turn_id,"
            " (SELECT turn.content FROM conversation_turn AS turn"
            "   WHERE turn.principal_id = record.principal_id"
            "     AND turn.conversation_id = record.conversation_id"
            "     AND turn.role = 'operator'"
            "   ORDER BY turn.turn_index LIMIT 1) AS first_operator_question"
            " FROM conversation_record AS record"
            " WHERE record.principal_id = %(principal_id)s"  # noqa: S608
            f"{cursor_clause}"
            " ORDER BY record.last_active DESC, record.conversation_id DESC"
            " LIMIT %(limit)s",
            parameters,
        )

    async def read_user_context_records(
        self,
        *,
        principal_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read every bounded durable user-context list inside the principal scope."""

        parameters: dict[str, object] = {"principal_id": principal_id, "limit": limit}
        preference = await self._fetch_all(
            "SELECT principal_id, locale, verbosity, timezone, share_with_learner, revision,"
            " answer_detail, answer_format, answer_preferences_enabled,"
            " answer_intent_detail, answer_intent_format"
            " FROM user_preference WHERE principal_id = %(principal_id)s",
            {"principal_id": principal_id},
        )
        memories = await self._fetch_all(
            "SELECT memory_id, category, body, source_turn_id, created_at, expires_at"
            " FROM user_memory_fact"
            " WHERE principal_id = %(principal_id)s AND superseded_by IS NULL"
            " ORDER BY created_at, memory_id LIMIT %(limit)s",
            parameters,
        )
        policies = await self._fetch_all(
            "SELECT policy_id, kind, enabled, revision, source_turn_id,"
            " briefing_spec, response_defaults"
            " FROM conversation_policy WHERE principal_id = %(principal_id)s"
            " ORDER BY policy_id LIMIT %(limit)s",
            parameters,
        )
        subscriptions = await self._fetch_all(
            "SELECT subscription_id, name, cron_expression, timezone, enabled,"
            " next_run_at, spec, revision"
            " FROM briefing_subscription WHERE principal_id = %(principal_id)s"
            " ORDER BY next_run_at, subscription_id LIMIT %(limit)s",
            parameters,
        )
        briefing_runs = await self._fetch_all(
            "SELECT run_id, title, body_markdown, status, item_count,"
            " evidence_refs, source_errors"
            " FROM briefing_run WHERE principal_id = %(principal_id)s"
            " ORDER BY scheduled_for DESC, run_id DESC LIMIT %(limit)s",
            parameters,
        )
        continuations = await self._fetch_all(
            "SELECT anchor_id, task_id, run_id, owner_principal_id, scope_ref, mode, origin,"
            " result_digest, result_summary, evidence_refs, observation_started_at,"
            " observation_ended_at, created_at, expires_at, state"
            " FROM scheduled_conversation_anchor"
            " WHERE owner_principal_id = %(principal_id)s"
            " ORDER BY created_at DESC, anchor_id DESC LIMIT %(limit)s",
            parameters,
        )
        return {
            "preference": preference,
            "memories": memories,
            "policies": policies,
            "subscriptions": subscriptions,
            "briefing_runs": briefing_runs,
            "scheduled_continuations": continuations,
        }

    async def read_context_selection_comparisons(
        self,
        *,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], str]:
        """Read the newest bounded context-selection shadow comparisons.

        Returns the decoded records newest-first with the revision derived from the
        newest ``updated_at``. No comparison is an authoritative empty answer rather
        than an unavailable projection, so it returns an empty tuple and revision "0".
        """
        if limit < 1 or limit > 500:
            raise ValueError("context-selection comparison limit MUST be between 1 and 500")
        rows = await self._fetch_all(
            """
            SELECT value, updated_at
              FROM state_kv
             WHERE key LIKE %(prefix)s ESCAPE '\\'
             ORDER BY updated_at DESC, key DESC
             LIMIT %(limit)s
            """,
            {"prefix": f"{_CONTEXT_SELECTION_PREFIX}%", "limit": limit},
        )
        records = tuple(
            _json_object(row.get("value"), label=_CONTEXT_SELECTION_PREFIX) for row in rows
        )
        newest = rows[0].get("updated_at") if rows else None
        revision = newest.isoformat() if isinstance(newest, datetime) else "0"
        return records, revision

    async def read_rule_search_projection(
        self,
        *,
        principal_id: str,
        query_digest: str,
    ) -> dict[str, object]:
        """Read one Rule-search projection for its exact principal and canonical query."""
        key = rule_search_projection_key(principal_id, query_digest)
        rows = await self._fetch_all(
            """
            SELECT value
              FROM state_kv
             WHERE key = %(key)s
               AND value ->> 'principal_id' = %(principal_id)s
               AND value ->> 'query_digest' = %(query_digest)s
            """,
            {
                "key": key,
                "principal_id": principal_id,
                "query_digest": query_digest,
            },
        )
        if not rows:
            raise PostgresFamilyStoreUnavailable(
                "authoritative Rule search projection is unavailable"
            )
        return _json_object(rows[0].get("value"), label=key)

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        """Atomically persist a typed proposal and return its durable outbox receipt."""
        request = {
            "family": family,
            "operation": operation,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
        }
        request_digest = _digest(request)
        proposal_id = f"operator-{request_digest[:32]}"
        accepted_at = datetime.now(UTC).isoformat()
        record: dict[str, object] = {
            "kind": "operator.proposal",
            "proposal_id": proposal_id,
            "request_digest": request_digest,
            "dispatch_status": "pending",
            "mode": "shadow",
            "accepted_at": accepted_at,
            **request,
        }
        key = _proposal_key(family, idempotency_key)
        inserted, stored = await self._insert_if_absent(key=key, value=record)
        stored_digest = stored.get("request_digest")
        if stored_digest != request_digest:
            raise PostgresProposalConflict(
                "idempotency key conflicts with a different durable Operator proposal"
            )
        stored_id = stored.get("proposal_id")
        stored_at = stored.get("accepted_at")
        if not isinstance(stored_id, str) or not isinstance(stored_at, str):
            raise PostgresFamilyStoreUnavailable("stored Operator proposal receipt is malformed")
        return StoredProposal(
            proposal_id=stored_id,
            accepted_at=stored_at,
            duplicate=not inserted,
            record=stored,
        )

    async def append_guarded_workflow_transition_proposal(
        self,
        *,
        operation: str,
        process_id: str,
        principal_id: str,
        principal_roles: frozenset[OperatorRole],
        idempotency_key: str,
        expected_revision: str,
        proposal_payload: Mapping[str, object],
    ) -> StoredProposal:
        """Atomically fence Process state and append one inert transition proposal."""
        request = {
            "family": "workflow",
            "operation": operation,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "payload": dict(proposal_payload),
        }
        request_digest = _digest(request)
        proposal_id = f"operator-{request_digest[:32]}"
        accepted_at = datetime.now(UTC).isoformat()
        record: dict[str, object] = {
            "kind": "operator.proposal",
            "proposal_id": proposal_id,
            "request_digest": request_digest,
            "dispatch_status": "pending",
            "mode": "shadow",
            "accepted_at": accepted_at,
            **request,
        }
        key = _proposal_key("workflow", idempotency_key)
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(connection, self._config.statement_timeout_ms)
                    existing_cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                        (key,),
                    )
                    existing_row = await existing_cursor.fetchone()
                    if existing_row is not None:
                        existing = _json_object(existing_row["value"], label=key)
                        if existing.get("request_digest") != request_digest:
                            raise PostgresProposalConflictError(
                                "idempotency key conflicts with a different durable "
                                "Operator proposal"
                            )
                        return _stored_proposal(existing, duplicate=True)

                    process_cursor = await connection.execute(
                        """
                        SELECT runtime.process_id, runtime.workflow_ref,
                               runtime.workflow_version, runtime.status,
                               runtime.current_step, runtime.target_resource_id,
                               runtime.started_at, runtime.updated_at,
                               runtime.correlation_id, runtime.revision
                          FROM process_runtime AS runtime
                          JOIN process_event AS created
                            ON created.process_id = runtime.process_id
                           AND created.kind = 'process.created'
                         WHERE runtime.process_id = %s
                           AND LOWER(BTRIM(created.payload #>>
                               '{resume,context,requester.principal}'))
                               = LOWER(BTRIM(%s))
                           FOR SHARE OF runtime
                        """,
                        (process_id, principal_id),
                    )
                    process = await process_cursor.fetchone()
                    if process is None:
                        raise PostgresProcessNotVisibleError("Process is not visible")
                    event_cursor = await connection.execute(
                        """
                        SELECT event_id, kind, recorded_at, correlation_id,
                               causation_id, step_id, attempt, payload
                          FROM process_event
                         WHERE process_id = %s
                         ORDER BY seq
                        """,
                        (process_id,),
                    )
                    events = list(await event_cursor.fetchall())
                    catalog_cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR SHARE",
                        ("operator-projection:workflow:workflow.catalog",),
                    )
                    catalog_row = await catalog_cursor.fetchone()
                    if catalog_row is None:
                        raise PostgresFamilyStoreUnavailableError(
                            "authoritative Workflow catalog projection is unavailable"
                        )
                    approval = await _read_workflow_approval_state(
                        connection,
                        process_id=process_id,
                        step_id=str(process["current_step"]),
                        events=events,
                    )
                    state = project_process_control(
                        process=process,
                        events=events,
                        workflow_catalog=_json_object(
                            catalog_row["value"],
                            label="operator-projection:workflow:workflow.catalog",
                        ),
                        principal_id=principal_id,
                        roles=principal_roles,
                        approval_state=approval,
                    )
                    if (
                        state.payload["mode"] == "enforce"
                        and OperatorRole.OWNER not in principal_roles
                    ):
                        raise ProcessTransitionDeniedError(
                            "Enforce Process transitions require Owner",
                            status_code=403,
                        )
                    authorize_process_transition(
                        operation=operation,
                        expected_revision=expected_revision,
                        state=state,
                    )
                    inserted = await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO NOTHING
                        RETURNING value
                        """,
                        (key, json.dumps(record, separators=(",", ":"), sort_keys=True)),
                    )
                    inserted_row = await inserted.fetchone()
                    if inserted_row is not None:
                        return StoredProposal(proposal_id, accepted_at, False, record)
                    raced_cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                        (key,),
                    )
                    raced_row = await raced_cursor.fetchone()
                    if raced_row is None:
                        raise PostgresFamilyStoreUnavailableError(
                            "stored Operator proposal disappeared"
                        )
                    raced = _json_object(raced_row["value"], label=key)
                    if raced.get("request_digest") != request_digest:
                        raise PostgresProposalConflictError(
                            "idempotency key conflicts with a different durable Operator proposal"
                        )
                    return _stored_proposal(raced, duplicate=True)
        except (
            PostgresFamilyStoreUnavailableError,
            PostgresProcessNotVisibleError,
            PostgresProposalConflictError,
        ):
            raise
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailableError(
                "authoritative PostgreSQL transition proposal store is unavailable"
            ) from exc

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> StoredProposal:
        """Atomically append one inert proposal and revision-fenced state snapshot."""
        if expected_revision < 0:
            raise ValueError("expected revision MUST be non-negative")
        next_revision = state_value.get("revision")
        if next_revision != expected_revision + 1:
            raise ValueError("state revision MUST advance expected revision by one")
        request = {
            "family": family,
            "operation": operation,
            "principal_id": principal_id,
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
        }
        request_digest = _digest(request)
        proposal_id = f"operator-{request_digest[:32]}"
        accepted_at = datetime.now(UTC).isoformat()
        record: dict[str, object] = {
            "kind": "operator.proposal",
            "proposal_id": proposal_id,
            "request_digest": request_digest,
            "dispatch_status": "pending",
            "mode": "shadow",
            "accepted_at": accepted_at,
            **request,
        }
        proposal_key = _proposal_key(family, idempotency_key)
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(connection, self._config.statement_timeout_ms)
                    inserted = await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO NOTHING
                        RETURNING key
                        """,
                        (
                            proposal_key,
                            json.dumps(record, separators=(",", ":"), sort_keys=True),
                        ),
                    )
                    inserted_row = await inserted.fetchone()
                    if inserted_row is None:
                        existing_cursor = await connection.execute(
                            "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                            (proposal_key,),
                        )
                        existing_row = await existing_cursor.fetchone()
                        if existing_row is None:
                            raise PostgresFamilyStoreUnavailable(
                                "stored Operator proposal disappeared"
                            )
                        existing = _json_object(existing_row[0], label=proposal_key)
                        if existing.get("request_digest") != request_digest:
                            raise PostgresProposalConflict(
                                "idempotency key conflicts with a different durable "
                                "Operator proposal"
                            )
                        return StoredProposal(
                            proposal_id=str(existing.get("proposal_id")),
                            accepted_at=str(existing.get("accepted_at")),
                            duplicate=True,
                            record=existing,
                        )
                    updated = await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        SELECT %s, %s::jsonb
                         WHERE %s = 0
                        ON CONFLICT (key)
                        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                              WHERE (state_kv.value ->> 'revision')::integer = %s
                        RETURNING key
                        """,
                        (
                            state_key,
                            json.dumps(dict(state_value), separators=(",", ":"), sort_keys=True),
                            expected_revision,
                            expected_revision,
                        ),
                    )
                    if await updated.fetchone() is None:
                        raise PostgresProposalConflict("state revision conflict")
        except (PostgresProposalConflict, PostgresFamilyStoreUnavailable):
            raise
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL proposal store is unavailable"
            ) from exc
        return StoredProposal(
            proposal_id=proposal_id,
            accepted_at=accepted_at,
            duplicate=False,
            record=record,
        )

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn:
        """Persist one v1.2 semantic request without publishing it in the transaction."""
        try:
            return await self._semantic_turn_store.append(
                principal_id=principal_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                envelope=envelope,
            )
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic turn outbox is unavailable"
            ) from exc

    async def claim_action_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ActionProposalClaim | None:
        """Lease the oldest pending or expired generic proposal for publication."""
        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                                 WHERE key LIKE %(proposal_prefix)s
                                     AND value ->> 'family' = 'conversation'
                                     AND value ->> 'operation' = 'chat.action.confirm'
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "claim_id": claim_id,
                "proposal_prefix": "operator-proposal:%",
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        value = _json_object(rows[0].get("value"), label="action proposal claim")
        principal_id = value.get("principal_id")
        payload = value.get("payload")
        attempt = value.get("attempt")
        if (
            not isinstance(key, str)
            or not isinstance(principal_id, str)
            or not isinstance(payload, Mapping)
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
        ):
            raise PostgresFamilyStoreUnavailable("action proposal claim is malformed")
        return ActionProposalClaim(
            key=key,
            claim_id=str(value.get("claim_id") or claim_id),
            principal_id=principal_id,
            payload=dict(payload),
            attempt=attempt,
        )

    async def claim_hil_decision_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> HilDecisionProposalClaim | None:
        """Lease the oldest pending or expired durable human-approval decision.

        The lease fences concurrent Operator replicas, and an expired lease is
        reclaimable, so a replica that crashed after its durable write cannot
        strand a recorded human decision behind an HTTP retry.
        """
        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(proposal_prefix)s
                   AND value ->> 'family' = 'iam'
                   AND value ->> 'operation' = 'hil.decision.enqueue'
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "claim_id": claim_id,
                "proposal_prefix": "operator-proposal:%",
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        value = _json_object(rows[0].get("value"), label="HIL decision proposal claim")
        payload = value.get("payload")
        attempt = value.get("attempt")
        if (
            not isinstance(key, str)
            or not isinstance(payload, Mapping)
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
        ):
            raise PostgresFamilyStoreUnavailable("HIL decision proposal claim is malformed")
        return HilDecisionProposalClaim(
            key=key,
            claim_id=str(value.get("claim_id") or claim_id),
            payload=dict(payload),
            attempt=attempt,
        )

    async def mark_hil_decision_published(self, *, idempotency_key: str) -> bool:
        """Close one durable decision record the immediate path already published."""
        if not idempotency_key.strip() or len(idempotency_key) > 512:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || jsonb_build_object(
                   'dispatch_status', 'published',
                   'published_at', NOW()
               ),
                   updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'dispatch_status' = 'pending'
         RETURNING value
            """,
            {"key": _proposal_key("iam", idempotency_key)},
        )
        return bool(rows)

    async def claim_webhook_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> WebhookProposalClaim | None:
        """Lease the oldest normalized Azure Monitor webhook proposal."""

        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(proposal_prefix)s
                   AND value ->> 'family' = 'operations'
                   AND value ->> 'operation' = 'webhook.azure_monitor'
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "claim_id": claim_id,
                "proposal_prefix": "operator-proposal:%",
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        value = _json_object(rows[0].get("value"), label="webhook proposal claim")
        payload = value.get("payload")
        attempt = value.get("attempt")
        if (
            not isinstance(key, str)
            or not isinstance(payload, Mapping)
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
        ):
            raise PostgresFamilyStoreUnavailable("webhook proposal claim is malformed")
        return WebhookProposalClaim(
            key=key,
            claim_id=str(value.get("claim_id") or claim_id),
            payload=dict(payload),
            attempt=attempt,
        )

    async def claim_read_investigation_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ReadInvestigationProposalClaim | None:
        """Lease the oldest pending read-investigation proposal for publication."""

        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                                 WHERE key LIKE %(proposal_prefix)s
                   AND (
                        (
                            value ->> 'family' = 'operations'
                            AND value ->> 'operation' = 'read_investigation.start'
                        )
                        OR (
                            value ->> 'family' = 'conversation'
                            AND value ->> 'operation' = 'background.cancel'
                        )
                   )
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "claim_id": claim_id,
                "proposal_prefix": "operator-proposal:%",
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        value = _json_object(rows[0].get("value"), label="read investigation proposal claim")
        proposal_id = value.get("proposal_id")
        principal_id = value.get("principal_id")
        idempotency_key = value.get("idempotency_key")
        accepted_at = value.get("accepted_at")
        payload = value.get("payload")
        attempt = value.get("attempt")
        if (
            not isinstance(key, str)
            or not isinstance(proposal_id, str)
            or not isinstance(principal_id, str)
            or not isinstance(idempotency_key, str)
            or not isinstance(accepted_at, str)
            or not isinstance(payload, Mapping)
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
        ):
            raise PostgresFamilyStoreUnavailable("read investigation proposal claim is malformed")
        correlation_id = payload.get("correlation_id")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise PostgresFamilyStoreUnavailable("read investigation correlation is malformed")
        return ReadInvestigationProposalClaim(
            key=key,
            claim_id=str(value.get("claim_id") or claim_id),
            request_id=proposal_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload=dict(payload),
            accepted_at=accepted_at,
            attempt=attempt,
        )

    async def claim_incident_intervention_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> IncidentInterventionProposalClaim | None:
        """Lease the oldest pending Incident intervention for publication."""

        _bounded_component("worker_id", worker_id)
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")
        claim_id = str(uuid4())
        rows = await self._fetch_all(
            """
            WITH candidate AS (
                SELECT key
                  FROM state_kv
                 WHERE key LIKE %(proposal_prefix)s
                   AND value ->> 'operation' = 'incident.intervention'
                   AND (
                        value ->> 'dispatch_status' = 'pending'
                        OR (
                            value ->> 'dispatch_status' = 'claimed'
                            AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                        )
                   )
                 ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                          value ->> 'accepted_at', key
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE state_kv AS proposal
               SET value = proposal.value || jsonb_build_object(
                   'dispatch_status', 'claimed',
                   'claim_id', %(claim_id)s::text,
                   'claim_worker_id', %(worker_id)s::text,
                   'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
                   'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
               ),
                   updated_at = NOW()
              FROM candidate
             WHERE proposal.key = candidate.key
         RETURNING proposal.key, proposal.value
            """,
            {
                "claim_id": claim_id,
                "proposal_prefix": "operator-proposal:%",
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        if not rows:
            return None
        key = rows[0].get("key")
        value = _json_object(rows[0].get("value"), label="Incident intervention claim")
        request_id = value.get("proposal_id")
        principal_id = value.get("principal_id")
        idempotency_key = value.get("idempotency_key")
        accepted_at = value.get("accepted_at")
        payload = value.get("payload")
        attempt = value.get("attempt")
        if (
            not isinstance(key, str)
            or not isinstance(request_id, str)
            or not isinstance(principal_id, str)
            or not isinstance(idempotency_key, str)
            or not isinstance(accepted_at, str)
            or not isinstance(payload, Mapping)
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
        ):
            raise PostgresFamilyStoreUnavailable("Incident intervention claim is malformed")
        correlation_id = payload.get("correlation_id")
        if not isinstance(correlation_id, str):
            raise PostgresFamilyStoreUnavailable("Incident intervention correlation is malformed")
        return IncidentInterventionProposalClaim(
            key=key,
            claim_id=str(value.get("claim_id") or claim_id),
            request_id=request_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload=dict(payload),
            accepted_at=accepted_at,
            attempt=attempt,
        )

    async def mark_proposal_published(self, *, key: str, claim_id: str) -> bool:
        """Close one active generic proposal claim after broker acceptance."""

        return await self.mark_action_proposal_published(key=key, claim_id=claim_id)

    async def release_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        """Release one active generic proposal claim for bounded retry."""

        return await self.release_action_proposal_claim(key=key, claim_id=claim_id)

    async def mark_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        """Close one malformed generic proposal claim without transport retry."""

        return await self.mark_action_proposal_rejected(
            key=key,
            claim_id=claim_id,
            reason_code=reason_code,
        )

    async def mark_action_proposal_published(self, *, key: str, claim_id: str) -> bool:
        """Close one active proposal claim after broker acceptance."""
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || jsonb_build_object(
                   'dispatch_status', %(state)s::text,
                   'published_at', NOW()
               ),
                   updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'dispatch_status' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
         RETURNING value
            """,
            {"state": "published", "key": key, "claim_id": claim_id},
        )
        return bool(rows)

    async def release_action_proposal_claim(self, *, key: str, claim_id: str) -> bool:
        """Release one active proposal claim for bounded retry."""
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = (value - 'claim_id' - 'claim_worker_id' - 'claim_expires_at')
                           || jsonb_build_object('dispatch_status', 'pending'),
                   updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'dispatch_status' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
         RETURNING value
            """,
            {"key": key, "claim_id": claim_id},
        )
        return bool(rows)

    async def mark_action_proposal_rejected(
        self,
        *,
        key: str,
        claim_id: str,
        reason_code: str,
    ) -> bool:
        """Close one invalid active claim without transport retry."""
        rows = await self._fetch_all(
            """
            UPDATE state_kv
               SET value = value || jsonb_build_object(
                   'dispatch_status', 'rejected',
                   'rejection_reason', %(reason_code)s
               ),
                   updated_at = NOW()
             WHERE key = %(key)s
               AND value ->> 'dispatch_status' = 'claimed'
               AND value ->> 'claim_id' = %(claim_id)s
         RETURNING value
            """,
            {"reason_code": reason_code, "key": key, "claim_id": claim_id},
        )
        return bool(rows)

    async def read_semantic_action_draft_source(
        self,
        *,
        principal_id: str,
        request_id: str,
        projection_id: str,
    ) -> dict[str, object] | None:
        """Read one exact principal-owned semantic action-draft projection."""
        rows = await self._fetch_all(
            """
                        SELECT result.value -> 'data' AS data
              FROM state_kv AS request
              JOIN state_kv AS result
                ON result.value ->> 'request_id' = request.value ->> 'request_id'
                         WHERE request.value ->> 'kind' = 'operator.semantic_turn'
                             AND result.value ->> 'kind' = 'operator.semantic_result'
                             AND request.value ->> 'principal_id' = %(principal_id)s
                             AND result.value ->> 'principal_id' = %(principal_id)s
               AND result.value ->> 'request_id' = %(request_id)s
               AND result.value ->> 'projection_id' = %(projection_id)s
                             AND result.value #>> '{data,status}' = 'action_draft'
             LIMIT 1
            """,
            {
                "principal_id": principal_id,
                "request_id": request_id,
                "projection_id": projection_id,
            },
        )
        return None if not rows else _json_object(rows[0].get("data"), label="action draft")

    async def claim_semantic_turn(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> SemanticTurnClaim | None:
        """Atomically lease the oldest eligible turn with replica-safe row locking."""
        try:
            return await self._semantic_turn_store.claim(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic turn outbox is unavailable"
            ) from exc

    async def mark_semantic_turn_published(self, *, key: str, claim_id: str) -> bool:
        """Compare-and-set one active claim to published after transport acceptance."""
        return await self._semantic_turn_store.mark_published(key=key, claim_id=claim_id)

    async def release_semantic_turn_claim(self, *, key: str, claim_id: str) -> bool:
        """Compare-and-set one failed claim back to pending for bounded retry."""
        return await self._semantic_turn_store.release_claim(key=key, claim_id=claim_id)

    async def read_semantic_turn(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None:
        """Read an accepted semantic turn only for its authenticated principal."""
        try:
            return await self._semantic_turn_store.read(
                principal_id=principal_id,
                proposal_id=proposal_id,
            )
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic turn outbox is unavailable"
            ) from exc

    async def project_semantic_turn_result(
        self,
        *,
        projection: Mapping[str, object],
    ) -> StoredSemanticResult:
        """Idempotently project a validated result against its owning durable request."""
        try:
            return await self._semantic_turn_store.project(projection=projection)
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic result projection is unavailable"
            ) from exc

    async def latest_semantic_investigation_continuation(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> SemanticInvestigationContinuation | None:
        """Resolve the latest prior continuation from principal-scoped durable results."""

        try:
            return await self._semantic_turn_store.latest_investigation_continuation(
                principal_id=principal_id,
                session_id=session_id,
            )
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic continuation is unavailable"
            ) from exc

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        """Replay ordered terminal events isolated by authenticated principal and request."""
        try:
            return await self._semantic_turn_store.replay(
                principal_id=principal_id,
                request_id=request_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except SemanticTurnStoreError as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative semantic result replay is unavailable"
            ) from exc

    async def replay(
        self,
        *,
        stream: str,
        principal_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[StoredReplayEvent, ...]:
        """Read principal-scoped monotonic records from the authoritative audit ledger."""
        _bounded_component("stream", stream)
        _bounded_component("principal_id", principal_id)
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence MUST be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("replay limit MUST be in [1, 500]")
        if stream.startswith("read-investigation:"):
            rows = await self._fetch_all(
                """
                SELECT sequence AS seq, event AS action_kind, data AS entry
                  FROM operator_read_investigation_completion
                 WHERE sequence > %(after_sequence)s
                   AND stream = %(stream)s
                   AND principal_id = %(principal_id)s
                 ORDER BY sequence ASC
                 LIMIT %(limit)s
                """,
                {
                    "after_sequence": after_sequence or 0,
                    "stream": stream,
                    "principal_id": principal_id,
                    "limit": limit,
                },
            )
        else:
            rows = await self._fetch_all(
                """
            SELECT seq, action_kind, entry
              FROM audit_log
             WHERE seq > %(after_sequence)s
               AND (action_kind = %(stream)s OR entry ->> 'stream' = %(stream)s)
                             AND entry ->> 'principal_id' = %(principal_id)s
             ORDER BY seq ASC
             LIMIT %(limit)s
            """,
                {
                    "after_sequence": after_sequence or 0,
                    "stream": stream,
                    "principal_id": principal_id,
                    "limit": limit,
                },
            )
        events: list[StoredReplayEvent] = []
        for row in rows:
            sequence = row.get("seq")
            event = row.get("action_kind")
            if not isinstance(sequence, int) or not isinstance(event, str):
                raise PostgresFamilyStoreUnavailable("audit replay row is malformed")
            events.append(
                StoredReplayEvent(
                    sequence=sequence,
                    event=event,
                    data=_json_object(row.get("entry"), label=f"audit_log[{sequence}].entry"),
                )
            )
        return tuple(events)

    async def _insert_if_absent(
        self,
        *,
        key: str,
        value: Mapping[str, object],
    ) -> tuple[bool, dict[str, object]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(
                        connection,
                        self._config.statement_timeout_ms,
                    )
                    cursor = await connection.execute(
                        """
                        INSERT INTO state_kv (key, value)
                        VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO NOTHING
                        RETURNING value
                        """,
                        (key, json.dumps(dict(value), separators=(",", ":"), sort_keys=True)),
                    )
                    inserted_row = await cursor.fetchone()
                    if inserted_row is not None:
                        return True, _json_object(inserted_row.get("value"), label=key)
                    cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR SHARE",
                        (key,),
                    )
                    existing_row = await cursor.fetchone()
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL proposal outbox is unavailable"
            ) from exc
        if existing_row is None:
            raise PostgresFamilyStoreUnavailable("durable Operator proposal disappeared")
        return False, _json_object(existing_row.get("value"), label=key)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        connection: psycopg.AsyncConnection[dict[str, Any]] | None = None
        try:
            connection = await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
                autocommit=True,
            )
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(statement, parameters)
            return list(await cursor.fetchall())
        except anyio.get_cancelled_exc_class():
            if connection is not None:
                await _cancel_and_close(
                    connection,
                    timeout_s=self._config.connect_timeout_s,
                )
                connection = None
            raise
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative PostgreSQL family store is unavailable"
            ) from exc
        finally:
            if connection is not None and not connection.closed:
                await connection.close()


class UnavailablePostgresFamilyStore(PostgresFamilyStore):
    """Fail immediately when PostgreSQL family storage is not configured."""

    def __init__(self) -> None:
        super().__init__(PostgresFamilyStoreConfig("postgresql://unavailable.invalid/fdai"))

    async def read_state(self, key: str) -> dict[str, object] | None:
        del key
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        del key, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        del key, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def find_state(
        self,
        *,
        prefix: str,
        field: str,
        value: str,
    ) -> dict[str, object] | None:
        del prefix, field, value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        del family, operation
        raise PostgresFamilyStoreUnavailable("authoritative projection is unavailable")

    async def list_background_tasks(
        self,
        *,
        owner_principal_id: str,
        before_updated_at: datetime | None,
        before_task_id: str | None,
        limit: int,
    ) -> tuple[BackgroundTaskProjection, ...]:
        del owner_principal_id, before_updated_at, before_task_id, limit
        raise PostgresFamilyStoreUnavailable("background task projection is unavailable")

    async def read_background_task(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
    ) -> BackgroundTaskProjection | None:
        del owner_principal_id, task_id
        raise PostgresFamilyStoreUnavailable("background task projection is unavailable")

    async def read_background_task_progress(
        self,
        *,
        owner_principal_id: str,
        task_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[BackgroundTaskProgressProjection, ...]:
        del owner_principal_id, task_id, after_sequence, limit
        raise PostgresFamilyStoreUnavailable("background task projection is unavailable")

    async def read_state_page(
        self,
        *,
        prefix: str,
        limit: int,
        match_field: str | None = None,
        match_value: str | None = None,
    ) -> StoredStatePage:
        del prefix, limit, match_field, match_value
        raise PostgresFamilyStoreUnavailable("authoritative PostgreSQL state is unavailable")

    async def read_rule_search_projection(
        self,
        *,
        principal_id: str,
        query_digest: str,
    ) -> dict[str, object]:
        del principal_id, query_digest
        raise PostgresFamilyStoreUnavailable("authoritative projection is unavailable")

    async def read_conversation_summaries(
        self,
        *,
        principal_id: str,
        before_last_active: datetime | None,
        before_conversation_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        del principal_id, before_last_active, before_conversation_id, limit
        raise PostgresFamilyStoreUnavailable("authoritative conversation history is unavailable")

    async def read_user_context_records(
        self,
        *,
        principal_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        del principal_id, limit
        raise PostgresFamilyStoreUnavailable("authoritative user context is unavailable")

    async def append_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del family, operation, principal_id, idempotency_key, payload
        raise PostgresFamilyStoreUnavailable("proposal outbox is unavailable")

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> StoredProposal:
        del (
            family,
            operation,
            principal_id,
            idempotency_key,
            payload,
            state_key,
            state_value,
            expected_revision,
        )
        raise PostgresFamilyStoreUnavailable("proposal outbox is unavailable")

    async def append_semantic_turn(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        request_digest: str,
        envelope: Mapping[str, object],
    ) -> StoredSemanticTurn:
        del principal_id, idempotency_key, request_digest, envelope
        raise PostgresFamilyStoreUnavailable("semantic turn outbox is unavailable")

    async def claim_hil_decision_proposal(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> HilDecisionProposalClaim | None:
        del worker_id, lease_seconds
        raise PostgresFamilyStoreUnavailable("HIL decision outbox is unavailable")

    async def mark_hil_decision_published(self, *, idempotency_key: str) -> bool:
        del idempotency_key
        raise PostgresFamilyStoreUnavailable("HIL decision outbox is unavailable")

    async def claim_semantic_turn(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> SemanticTurnClaim | None:
        del worker_id, lease_seconds
        raise PostgresFamilyStoreUnavailable("semantic turn outbox is unavailable")

    async def mark_semantic_turn_published(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        raise PostgresFamilyStoreUnavailable("semantic turn outbox is unavailable")

    async def release_semantic_turn_claim(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        raise PostgresFamilyStoreUnavailable("semantic turn outbox is unavailable")

    async def read_semantic_turn(
        self,
        *,
        principal_id: str,
        proposal_id: str,
    ) -> StoredSemanticTurn | None:
        del principal_id, proposal_id
        raise PostgresFamilyStoreUnavailable("semantic turn outbox is unavailable")

    async def project_semantic_turn_result(
        self,
        *,
        projection: Mapping[str, object],
    ) -> StoredSemanticResult:
        del projection
        raise PostgresFamilyStoreUnavailable("semantic result projection is unavailable")

    async def latest_semantic_investigation_continuation(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> SemanticInvestigationContinuation | None:
        del principal_id, session_id
        raise PostgresFamilyStoreUnavailable("semantic continuation is unavailable")

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        del principal_id, request_id, after_sequence, limit
        raise PostgresFamilyStoreUnavailable("semantic result replay is unavailable")

    async def replay(
        self,
        *,
        stream: str,
        principal_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[StoredReplayEvent, ...]:
        del stream, principal_id, after_sequence, limit
        raise PostgresFamilyStoreUnavailable("authoritative replay is unavailable")


def _projection_key(family: str, operation: str) -> str:
    _bounded_component("family", family)
    _bounded_component("operation", operation)
    return f"{_PROJECTION_PREFIX}{family}:{operation}"


def _background_task_projection(row: Mapping[str, object]) -> BackgroundTaskProjection:
    task_status = _required_row_text(row, "status")
    if task_status not in _BACKGROUND_TASK_STATUSES:
        raise PostgresFamilyStoreUnavailable("background task status is malformed")
    completion_state = _optional_row_text(row, "completion_state")
    if completion_state is not None and completion_state not in _BACKGROUND_COMPLETION_STATES:
        raise PostgresFamilyStoreUnavailable("background task completion_state is malformed")
    progress_watermark = _optional_row_integer(row, "progress_watermark", minimum=0)
    if task_status in _TERMINAL_BACKGROUND_TASK_STATUSES and progress_watermark is None:
        raise PostgresFamilyStoreUnavailable("background task progress_watermark is malformed")
    if task_status not in _TERMINAL_BACKGROUND_TASK_STATUSES and progress_watermark is not None:
        raise PostgresFamilyStoreUnavailable("background task progress_watermark is malformed")
    accountable_agent = _optional_row_text(row, "accountable_agent")
    if accountable_agent is not None and accountable_agent != "Heimdall":
        raise PostgresFamilyStoreUnavailable("background task accountable_agent is malformed")
    evidence_refs = _background_evidence_refs(row.get("evidence_refs"))
    return BackgroundTaskProjection(
        task_id=_required_row_text(row, "task_id"),
        attempt_id=_required_row_text(row, "attempt_id"),
        kind=_required_row_text(row, "task_kind"),
        status=task_status,
        revision=_required_row_integer(row, "revision"),
        created_at=_stored_timestamp(row.get("created_at"), label="background task creation"),
        updated_at=_stored_timestamp(row.get("updated_at"), label="background task update"),
        retention_until=_stored_timestamp(
            row.get("retention_until"), label="background task retention"
        ),
        progress_watermark=progress_watermark,
        latest_progress_order=_row_integer_or_default(
            row,
            "latest_progress_order",
            default=0,
            minimum=0,
        ),
        lease_expires_at=_optional_timestamp(row.get("lease_expires_at")),
        budget=cast(JsonObject, _json_object(row.get("budget"), label="background task budget")),
        usage=cast(JsonObject, _json_object(row.get("usage"), label="background task usage")),
        terminal_reason=_optional_row_text(row, "terminal_reason"),
        started_at=_optional_timestamp(row.get("started_at")),
        finished_at=_optional_timestamp(row.get("finished_at")),
        completion_state=completion_state,
        request_summary=_optional_row_text(row, "request_summary", maximum=500),
        request_truncated=_required_row_boolean(row, "request_truncated"),
        accountable_agent=accountable_agent,
        result_summary=_optional_row_text(row, "result_summary", maximum=2_000),
        result_truncated=_required_row_boolean(row, "result_truncated"),
        evidence_refs=evidence_refs,
        evidence_truncated=_required_row_boolean(row, "evidence_truncated"),
    )


def _background_evidence_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or len(value) > 16:
        raise PostgresFamilyStoreUnavailable("background task evidence_refs are malformed")
    refs = tuple(value)
    if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 256 for ref in refs):
        raise PostgresFamilyStoreUnavailable("background task evidence_refs are malformed")
    if len(set(refs)) != len(refs):
        raise PostgresFamilyStoreUnavailable("background task evidence_refs are malformed")
    return cast(tuple[str, ...], refs)


def _background_task_progress(
    row: Mapping[str, object],
) -> BackgroundTaskProgressProjection:
    return BackgroundTaskProgressProjection(
        sequence=_required_row_integer(row, "sequence", minimum=0),
        order=_row_integer_or_default(row, "progress_order", default=0, minimum=0),
        kind=_required_row_text(row, "kind"),
        message=_required_row_text(row, "message", maximum=1_000),
        at=_stored_timestamp(row.get("at"), label="background task progress"),
        usage=cast(
            JsonObject,
            _json_object(row.get("usage"), label="background task progress usage"),
        ),
    )


def _required_row_text(
    row: Mapping[str, object],
    field: str,
    *,
    maximum: int = 256,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PostgresFamilyStoreUnavailable(f"background task {field} is malformed")
    return value


def _optional_row_text(
    row: Mapping[str, object],
    field: str,
    *,
    maximum: int = 256,
) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    return _required_row_text(row, field, maximum=maximum)


def _required_row_boolean(row: Mapping[str, object], field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise PostgresFamilyStoreUnavailable(f"background task {field} is malformed")
    return value


def _required_row_integer(
    row: Mapping[str, object],
    field: str,
    *,
    minimum: int = 1,
) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailable(f"background task {field} is malformed")
    return value


def _optional_row_integer(
    row: Mapping[str, object],
    field: str,
    *,
    minimum: int = 0,
) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailable(f"background task {field} is malformed")
    return value


def _row_integer_or_default(
    row: Mapping[str, object],
    field: str,
    *,
    default: int,
    minimum: int = 0,
) -> int:
    value = row.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailable(f"background task {field} is malformed")
    return value


def _stored_timestamp(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    raise PostgresFamilyStoreUnavailable(f"{label} record has no write timestamp")


def _optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    return _stored_timestamp(value, label="optional inventory observation")


def _activity_correlation(
    row: Mapping[str, object],
    payload: Mapping[str, object],
) -> str | None:
    for value in (row.get("correlation_id"), payload.get("correlation_id")):
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            return value.strip()
    return None


def _instance_activity_facts(payload: Mapping[str, object]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for key in (
        "action_type",
        "decision",
        "mode",
        "outcome",
        "reason",
        "risk_verdict",
        "state",
        "tier",
        "verdict",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            facts[key] = value.strip()
    return facts


def _instance_relationship_evidence(value: object) -> InventoryRelationshipEvidence | None:
    if value is None:
        return None
    properties = _json_object(value, label="inventory instance relationship properties")
    raw_evidence = properties.get("provider_relationship_evidence")
    if raw_evidence is None:
        return _instance_observation_evidence(properties.get("link_observation_metadata"))
    evidence = _json_object(
        raw_evidence,
        label="inventory instance provider relationship evidence",
    )

    def required_text(key: str) -> str:
        raw = evidence.get(key)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
            raise PostgresFamilyStoreUnavailable(
                f"inventory instance relationship evidence {key} is malformed"
            )
        return raw.strip()

    freshness = evidence.get("freshness_ceiling_seconds")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1:
        raise PostgresFamilyStoreUnavailable(
            "inventory instance relationship evidence freshness is malformed"
        )
    return InventoryRelationshipEvidence(
        source_identity=required_text("source_identity"),
        source_property_path=required_text("source_property_path"),
        mapping_id=required_text("mapping_id"),
        evidence_method=required_text("evidence_method"),
        freshness_ceiling_seconds=freshness,
    )


def _instance_observation_evidence(value: object) -> InventoryRelationshipEvidence | None:
    if value is None:
        return None
    metadata = _json_object(value, label="inventory instance observation metadata")
    state_fact = _json_object(
        metadata.get("state_fact"),
        label="inventory instance observation state fact",
    )

    def required_text(source: Mapping[str, object], key: str) -> str:
        raw = source.get(key)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
            raise PostgresFamilyStoreUnavailable(
                f"inventory instance observation evidence {key} is malformed"
            )
        return raw.strip()

    expected_metadata_keys = {
        "state_fact",
        "verification_method",
        "verified",
        "verifier_identity",
        "verifier_revision",
        "verification_receipt_ref",
        "inventory_generation",
        "mapping_id",
        "mapping_revision",
        "source_schema_version",
        "source_schema_digest",
    }
    expected_state_keys = {
        "authority",
        "completeness",
        "conflicts",
        "effective_at",
        "evidence_cutoff",
        "evidence_refs",
        "freshness_ceiling_seconds",
        "lane",
        "recorded_at",
        "source_identity",
        "source_revision",
        "synthetic",
    }
    if set(metadata) != expected_metadata_keys or set(state_fact) != expected_state_keys:
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence shape is malformed"
        )
    if (
        metadata.get("verified") is not True
        or metadata.get("mapping_id") != "runtime-call-endpoint-identity"
        or metadata.get("mapping_revision") != "1.1.0"
        or metadata.get("source_schema_version") != "fdai.runtime-call-observation@1.1.0"
        or state_fact.get("lane") != "observed"
        or state_fact.get("authority") != "telemetry"
        or state_fact.get("synthetic") is not False
        or state_fact.get("conflicts") != []
    ):
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence is not verified"
        )
    freshness = state_fact.get("freshness_ceiling_seconds")
    completeness = state_fact.get("completeness")
    if (
        isinstance(freshness, bool)
        or not isinstance(freshness, int)
        or freshness < 1
        or completeness != 1.0
    ):
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence freshness is malformed"
        )
    evidence_refs = state_fact.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or len(evidence_refs) != 2
        or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
        or len(set(evidence_refs)) != 2
    ):
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence references are malformed"
        )
    verifier_identity = required_text(metadata, "verifier_identity")
    source_identity = required_text(state_fact, "source_identity")
    if verifier_identity.casefold() == source_identity.casefold():
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence verifier is not independent"
        )
    for key in ("verification_receipt_ref", "source_schema_digest"):
        digest = required_text(metadata, key)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise PostgresFamilyStoreUnavailable(
                "inventory instance observation evidence digest is malformed"
            )
    cutoff_raw = required_text(state_fact, "evidence_cutoff")
    try:
        cutoff = datetime.fromisoformat(cutoff_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence cutoff is malformed"
        ) from exc
    if cutoff.tzinfo is None:
        raise PostgresFamilyStoreUnavailable(
            "inventory instance observation evidence cutoff is malformed"
        )
    return InventoryRelationshipEvidence(
        source_identity=source_identity,
        source_property_path="caller_resource_ids,target_resource_ids",
        mapping_id=required_text(metadata, "mapping_id"),
        evidence_method=required_text(metadata, "verification_method"),
        freshness_ceiling_seconds=freshness,
        evidence_kind="observation",
        evidence_cutoff=cutoff,
    )


def _proposal_key(family: str, idempotency_key: str) -> str:
    _bounded_component("family", family)
    if not idempotency_key.strip() or len(idempotency_key) > 256:
        raise ValueError("idempotency_key MUST be a bounded non-empty string")
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_PROPOSAL_PREFIX}{family}:{digest}"


def _stored_proposal(
    value: Mapping[str, object],
    *,
    duplicate: bool,
) -> StoredProposal:
    proposal_id = value.get("proposal_id")
    accepted_at = value.get("accepted_at")
    if not isinstance(proposal_id, str) or not isinstance(accepted_at, str):
        raise PostgresFamilyStoreUnavailableError("stored Operator proposal receipt is malformed")
    return StoredProposal(proposal_id, accepted_at, duplicate, value)


async def _read_workflow_approval_state(
    connection: psycopg.AsyncConnection[dict[str, Any]],
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
    if (
        latest is None
        or cast(Mapping[str, object], latest["payload"]).get("step_kind") != "approval"
    ):
        return None
    attempts = [event.get("attempt", 1) for event in events]
    if any(not isinstance(attempt, int) or isinstance(attempt, bool) for attempt in attempts):
        raise PostgresFamilyStoreUnavailableError("workflow approval attempt is malformed")
    attempt = max(cast(list[int], attempts), default=1)
    identity = f"{process_id}\0{step_id}"
    if attempt > 1:
        identity += f"\0{attempt}"
    key = f"workflow:approval:{hashlib.sha256(identity.encode()).hexdigest()}"
    cursor = await connection.execute("SELECT value FROM state_kv WHERE key = %s FOR SHARE", (key,))
    row = await cursor.fetchone()
    if row is None:
        return None
    record = _json_object(row["value"], label=key)
    slots = record.get("slots")
    if not isinstance(slots, list) or any(not isinstance(slot, Mapping) for slot in slots):
        raise PostgresFamilyStoreUnavailableError("workflow approval slots are malformed")
    decision_keys = [
        f"hil_decision:{slot['idempotency_key']}"
        for slot in cast(list[Mapping[str, object]], slots)
        if isinstance(slot.get("idempotency_key"), str)
    ]
    if len(decision_keys) != len(slots) or not decision_keys:
        raise PostgresFamilyStoreUnavailableError("workflow approval slots are malformed")
    decision_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key = ANY(%s)",
        (decision_keys,),
    )
    decisions = [
        {
            "principal": str(value.get("approver_oid") or ""),
            "decision": str(value.get("decision") or ""),
        }
        for value in (
            _json_object(decision_row["value"], label="workflow approval decision")
            for decision_row in await decision_cursor.fetchall()
        )
    ]
    return {**record, "_external_decisions": decisions}


def _bounded_component(name: str, value: str) -> None:
    if not value.strip() or len(value) > 128:
        raise ValueError(f"{name} MUST be a bounded non-empty string")


def _bounded_identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > 256 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PostgresFamilyStoreUnavailable(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}


def _relationship_drop_classifications(
    value: object,
) -> tuple[InventoryRelationshipDropClassification, ...]:
    """Decode bounded mapping-specific coverage without provider resource identities."""

    if not isinstance(value, list) or len(value) > 256:
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship classifications are malformed"
        )
    allowed_unavailable_reasons = {
        "authorization_child_scope_unmodeled",
        "reference_not_observed",
        "source_outside_active_generation",
        "target_outside_active_generation",
        "target_provider_type_unmodeled",
        "unclassified",
    }
    classifications: list[InventoryRelationshipDropClassification] = []
    for raw_item in value:
        item = _json_object(raw_item, label="active inventory relationship classification")
        fields: dict[str, str] = {}
        for name, maximum in (
            ("reason", 128),
            ("mapping_id", 256),
            ("source_property_path", 512),
            ("source_provider_type", 512),
            ("target_provider_type", 512),
            ("unavailable_reason", 128),
        ):
            raw_field = item.get(name)
            if not isinstance(raw_field, str) or not raw_field.strip() or len(raw_field) > maximum:
                raise PostgresFamilyStoreUnavailable(
                    "active inventory relationship classification is malformed"
                )
            fields[name] = raw_field
        raw_count = item.get("count")
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or not 1 <= raw_count <= (2**31) - 1
            or fields["unavailable_reason"] not in allowed_unavailable_reasons
        ):
            raise PostgresFamilyStoreUnavailable(
                "active inventory relationship classification is malformed"
            )
        classifications.append(
            InventoryRelationshipDropClassification(
                reason=fields["reason"],
                mapping_id=fields["mapping_id"],
                source_property_path=fields["source_property_path"],
                source_provider_type=fields["source_provider_type"],
                target_provider_type=fields["target_provider_type"],
                unavailable_reason=fields["unavailable_reason"],
                count=raw_count,
            )
        )
    identities = [
        (
            item.reason,
            item.mapping_id,
            item.source_property_path,
            item.source_provider_type,
            item.target_provider_type,
            item.unavailable_reason,
        )
        for item in classifications
    ]
    if len(set(identities)) != len(identities):
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship classifications are duplicated"
        )
    return tuple(
        sorted(
            classifications,
            key=lambda item: (
                item.reason,
                item.mapping_id,
                item.source_property_path,
                item.source_provider_type,
                item.target_provider_type,
                item.unavailable_reason,
            ),
        )
    )


def _projection_source_states(value: object) -> tuple[InventoryProjectionSourceState, ...]:
    """Decode only reviewed no-authority source availability records."""

    if not isinstance(value, list) or len(value) > 8:
        raise PostgresFamilyStoreUnavailable("active inventory source states are malformed")
    allowed_sources = {
        "kubernetes_runtime_inventory",
        "runtime_call_graph",
        "postgres_role_evidence",
    }
    states: list[InventoryProjectionSourceState] = []
    for raw_item in value:
        item = _json_object(raw_item, label="active inventory source state")
        source = item.get("source")
        status = item.get("status")
        observed_at = item.get("observed_at")
        reason = item.get("reason")
        if (
            not isinstance(source, str)
            or source not in allowed_sources
            or status not in {"available", "unavailable"}
        ):
            raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
        if status == "available":
            if reason is not None or observed_at is None:
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            if not isinstance(observed_at, str):
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            try:
                parsed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PostgresFamilyStoreUnavailable(
                    "active inventory source state is malformed"
                ) from exc
            if parsed_at.tzinfo is None:
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            parsed_reason = None
        else:
            if (
                observed_at is not None
                or not isinstance(reason, str)
                or not reason.strip()
                or len(reason) > 128
            ):
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            parsed_at = None
            parsed_reason = reason
        states.append(
            InventoryProjectionSourceState(
                source=source,
                status=status,
                observed_at=parsed_at,
                reason=parsed_reason,
            )
        )
    if len({state.source for state in states}) != len(states):
        raise PostgresFamilyStoreUnavailable("active inventory source states are duplicated")
    return tuple(sorted(states, key=lambda state: state.source))


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


async def _set_statement_timeout(
    connection: psycopg.AsyncConnection[object],
    timeout_ms: int,
) -> None:
    await connection.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (str(timeout_ms),),
    )


async def _cancel_and_close(
    connection: psycopg.AsyncConnection[Any],
    *,
    timeout_s: int,
) -> None:
    """Finish query cancellation and close without masking the caller's cancellation."""
    try:
        with anyio.move_on_after(timeout_s, shield=True) as cancel_scope:
            await connection.cancel_safe(timeout=float(timeout_s))
        if cancel_scope.cancel_called:
            _LOGGER.warning("postgres_query_cancel_cleanup_timed_out")
    except Exception as exc:  # noqa: BLE001 - preserve the original cancellation
        _LOGGER.warning(
            "postgres_query_cancel_cleanup_failed",
            extra={"error_class": type(exc).__name__},
        )
    try:
        with anyio.CancelScope(shield=True):
            await connection.close()
    except Exception as exc:  # noqa: BLE001 - preserve the original cancellation
        _LOGGER.warning(
            "postgres_query_close_cleanup_failed",
            extra={"error_class": type(exc).__name__},
        )


__all__ = [
    "HilDecisionProposalClaim",
    "PostgresFamilyStore",
    "PostgresFamilyStoreConfig",
    "PostgresFamilyStoreUnavailable",
    "PostgresProcessNotVisibleError",
    "PostgresProposalConflict",
    "PostgresSemanticTurnConflict",
    "SemanticTurnClaim",
    "StoredProposal",
    "StoredReplayEvent",
    "StoredSemanticResult",
    "StoredSemanticTurn",
    "StoredStatePage",
    "StoredStateRecord",
    "UnavailablePostgresFamilyStore",
]

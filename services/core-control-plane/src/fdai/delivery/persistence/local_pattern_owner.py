"""Closed-world LOCAL validation source owners over existing StateStore rows.

Every mutation replaces the same canonical owner row. PostgreSQL qualification
locks those rows, so ordinary StateStore updates/deletes, including other sessions,
participate without a new epoch ledger or a cooperative writer-only convention.
These records are source facts; this owner never issues an admission or permission.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import RetainedReuseStatistics
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
)
from fdai.shared.contracts.models import Event, OntologyActionType
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.state_store import StateStore

from .postgres import PostgresStateStore
from .state_store_case_artifacts import StateStoreCaseHistoryArtifactStore

LOCAL_VENUE = "local-isolated-validation"


def local_dsn(dsn: str, *, venue: str) -> str:
    parts = conninfo_to_dict(dsn)
    loopback = {"127.0.0.1", "localhost", "::1"}
    if (
        venue != LOCAL_VENUE
        or parts.get("host") not in loopback
        or parts.get("hostaddr", parts["host"]) not in loopback
        or parts.get("port") != "5433"
    ):
        raise PermissionError("Pattern ownership requires the isolated local validation database")
    # Pin the numeric destination as well: PGHOSTADDR/PGSERVICE must not redirect
    # an apparently loopback configuration to another venue.
    return make_conninfo(dsn, hostaddr="::1" if parts["host"] == "::1" else "127.0.0.1")


def require_local_store(store: StateStore, *, venue: str) -> None:
    if not isinstance(store, PostgresStateStore):
        raise PermissionError("local Pattern ownership requires its PostgreSQL source backend")
    local_dsn(store._config.dsn, venue=venue)
    if conninfo_to_dict(store._config.dsn).get("hostaddr") not in {"127.0.0.1", "::1"}:
        raise PermissionError("local Pattern source connections require a pinned loopback address")


class LocalPatternArtifactStore(StateStoreCaseHistoryArtifactStore):
    """Retain and delete LOCAL artifacts through the same row-lock-enforced owner."""

    def __init__(self, *, store: StateStore, venue: str) -> None:
        require_local_store(store, venue=venue)
        super().__init__(store=store)

    async def delete(self, storage_ref: str) -> None:
        key = "catalog-review-case-artifact:" + hashlib.sha256(storage_ref.encode()).hexdigest()
        await self._store.delete_state(key)


def owner_key(kind: str, *identity: object) -> str:
    return f"local-pattern-owner:v1:{kind}:" + content_digest(list(identity)).removeprefix(
        "sha256:"
    )


def statistics_mapping(statistics: RetainedReuseStatistics) -> dict[str, Any]:
    value = asdict(statistics)
    value["observed_at"] = statistics.observed_at.isoformat()
    value["valid_until"] = statistics.valid_until.isoformat()
    return value


def verification_mapping(verification: CurrentReuseVerification) -> dict[str, Any]:
    value = asdict(verification)
    value.pop("decision_evidence")
    value.pop("evidence_attempt")
    value["observed_at"] = verification.observed_at.isoformat()
    value["evidence_refs"] = list(verification.evidence_refs)
    return value


def parse_verification(value: dict[str, Any]) -> CurrentReuseVerification:
    values = dict(value)
    values["observed_at"] = datetime.fromisoformat(values["observed_at"])
    values["evidence_refs"] = tuple(values["evidence_refs"])
    return CurrentReuseVerification(**values)


class LocalPatternOwner:
    """Explicit local source backend; never bind arbitrary external mutable callbacks."""

    def __init__(
        self, *, store: StateStore, admission: DecisionEvidenceAdmissionProvider, venue: str
    ) -> None:
        require_local_store(store, venue=venue)
        self.store, self._admission = store, admission

    async def retain_principal(
        self,
        *,
        context: FunctionInvocationContext,
        scope: str,
        purpose: str,
        allowed: bool,
        valid_until: datetime,
    ) -> None:
        await self.store.write_state(
            owner_key("principal", context.principal_ref, scope, purpose),
            {
                "context": context.model_dump(mode="json"),
                "scope": scope,
                "purpose": purpose,
                "allowed": allowed,
                "valid_until": valid_until.isoformat(),
            },
        )

    async def retain_statistics(
        self, statistics: RetainedReuseStatistics, *, authorized: bool
    ) -> None:
        await self.store.write_state(
            owner_key(
                "statistics",
                statistics.action_signature,
                statistics.case_ref,
                statistics.access_scope_digest,
            ),
            {"statistics": statistics_mapping(statistics), "authorized": authorized},
        )

    async def register_action(self, action: OntologyActionType) -> None:
        await self.store.write_state(
            owner_key("action", action.name), action.model_dump(mode="json")
        )

    async def retain_reuse(
        self,
        *,
        event: Event,
        action: LearnedAction,
        context: OperationalCaseContext,
        verification: CurrentReuseVerification,
    ) -> None:
        await self.store.write_state(
            owner_key("reuse", str(event.event_id), context.case_ref, action.signature),
            {
                "verification": verification_mapping(verification),
                "scope_digest": current_reuse_scope_digest(
                    event=event, action=action, context=context
                ),
            },
        )

    async def statistics(
        self, event: Event, match: SimilarityMatch, evidence_ref: str | None = None
    ) -> RetainedReuseStatistics | None:
        context = match.action.operational_case
        if context is None:
            return None
        raw = await self.store.read_state(
            owner_key(
                "statistics", match.action.signature, context.case_ref, context.access_scope_digest
            )
        )
        if raw is None or raw.get("authorized") is not True:
            return None
        values = dict(raw["statistics"])
        values["observed_at"] = datetime.fromisoformat(values["observed_at"])
        values["valid_until"] = datetime.fromisoformat(values["valid_until"])
        current = RetainedReuseStatistics(**values)
        return current if evidence_ref is None or current.evidence_ref == evidence_ref else None

    async def verify(
        self, *, event: Event, action: LearnedAction, context: OperationalCaseContext
    ) -> CurrentReuseVerification:
        raw = await self.store.read_state(
            owner_key("reuse", str(event.event_id), context.case_ref, action.signature)
        )
        if raw is None:
            raise LookupError("local current-reuse source is unavailable")
        observed = parse_verification(dict(raw["verification"]))
        scope = current_reuse_scope_digest(event=event, action=action, context=context)
        if raw.get("scope_digest") != scope:
            raise PermissionError("local current-reuse scope changed")
        admission = await self._admission.admit(
            evidence_digest=current_reuse_evidence_digest(observed),
            scope_digest=scope,
            purpose_id="current-case-reuse",
            source_revision=context.graph_digest,
        )
        return replace(observed, decision_evidence=admission)

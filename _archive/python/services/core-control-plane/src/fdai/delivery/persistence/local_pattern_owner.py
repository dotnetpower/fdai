"""Closed-world LOCAL validation source owners over existing StateStore rows.

Every mutation replaces the same canonical owner row. PostgreSQL qualification
locks those rows, so ordinary StateStore updates/deletes, including other sessions,
participate without a new epoch ledger or a cooperative writer-only convention.
These records are source facts; this owner never issues an admission or permission.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from jsonschema import Draft202012Validator
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from referencing import Registry

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import RetainedReuseStatistics
from fdai.core.tiers.t1_lightweight.retained_patterns import RetainedPatternRequest
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

    async def retain_authenticated_request(
        self,
        *,
        event_id: str,
        request: RetainedPatternRequest,
        receipt: OperatorAuthenticationReceipt,
    ) -> None:
        context = request.context
        if (
            not event_id.strip()
            or receipt.receipt_digest != context.authentication_receipt_ref
            or receipt.subject_id != context.principal_ref
            or tuple(receipt.groups) != tuple(context.principal_groups)
            or context.purposes != ("operations-review",)
            or not context.authentication_request_ref
        ):
            raise PermissionError("authenticated Pattern request does not match its receipt")
        await self.store.write_state(
            owner_key("authenticated_request", event_id),
            {
                "event_id": event_id,
                "request_id": context.authentication_request_ref,
                "context": context.model_dump(mode="json"),
                "access_scope_digest": request.access_scope_digest,
                "purpose": request.purpose,
                "failure_fingerprint": request.failure_fingerprint,
                "receipt": receipt.model_dump(mode="json"),
            },
        )

    async def request_for_event(
        self, event: Event, *, now: datetime | None = None
    ) -> RetainedPatternRequest | None:
        evaluated_at = now or datetime.now(UTC)
        raw = await self.store.read_state(owner_key("authenticated_request", str(event.event_id)))
        if raw is None or raw.get("event_id") != str(event.event_id):
            return None
        try:
            context = FunctionInvocationContext.model_validate(raw["context"])
            receipt = OperatorAuthenticationReceipt.model_validate(raw["receipt"])
            request = RetainedPatternRequest(
                context=context,
                access_scope_digest=str(raw["access_scope_digest"]),
                purpose=str(raw["purpose"]),
                failure_fingerprint=str(raw["failure_fingerprint"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not receipt.valid_at(evaluated_at)
            or receipt.receipt_digest != context.authentication_receipt_ref
            or receipt.subject_id != context.principal_ref
            or tuple(receipt.groups) != tuple(context.principal_groups)
            or raw.get("request_id") != context.authentication_request_ref
            or context.purposes != ("operations-review",)
        ):
            return None
        grant = await self.store.read_state(
            owner_key(
                "principal", context.principal_ref, request.access_scope_digest, request.purpose
            )
        )
        if (
            grant is None
            or grant.get("allowed") is not True
            or grant.get("context") != context.model_dump(mode="json")
            or grant.get("scope") != request.access_scope_digest
            or grant.get("purpose") != request.purpose
            or evaluated_at >= datetime.fromisoformat(str(grant["valid_until"]))
        ):
            return None
        return request

    async def retain_action_candidate(
        self,
        *,
        event_id: str,
        pattern_id: str,
        match: SimilarityMatch,
        statistics_ref: str,
    ) -> None:
        action = match.action
        context = action.operational_case
        raw_action = await self.store.read_state(owner_key("action", action.action_type))
        if raw_action is None or context is None or not event_id.strip() or not pattern_id.strip():
            raise PermissionError("candidate Pattern action requires a registered ActionType")
        registered = OntologyActionType.model_validate(raw_action)
        if (
            registered.name != action.action_type
            or registered.argument_schema is None
            or not Draft202012Validator(registered.argument_schema, registry=Registry()).is_valid(
                dict(action.params)
            )
        ):
            raise PermissionError(
                "candidate Pattern action parameters violate the registered schema"
            )
        await self.store.write_state(
            owner_key("candidate", event_id, pattern_id),
            {
                "event_id": event_id,
                "pattern_id": pattern_id,
                "score": match.score,
                "statistics_ref": statistics_ref,
                "action": {
                    "signature": action.signature,
                    "rule_id": action.rule_id,
                    "action_type": action.action_type,
                    "params": dict(action.params),
                    "incident_id": action.incident_id,
                    "success_rate": action.success_rate,
                    "reuse_count": action.reuse_count,
                    "context": context.to_mapping(),
                },
            },
        )

    async def resolve_action(
        self, event: Event, summary: dict[str, Any] | Any
    ) -> SimilarityMatch | None:
        pattern_id = str(summary.get("pattern_id", "")) if isinstance(summary, dict) else ""
        if not pattern_id:
            return None
        raw = await self.store.read_state(owner_key("candidate", str(event.event_id), pattern_id))
        if (
            raw is None
            or raw.get("event_id") != str(event.event_id)
            or raw.get("pattern_id") != pattern_id
        ):
            return None
        try:
            action_raw = raw["action"]
            context = OperationalCaseContext.from_mapping(action_raw["context"])
            action = LearnedAction(
                signature=str(action_raw["signature"]),
                rule_id=str(action_raw["rule_id"]),
                action_type=str(action_raw["action_type"]),
                params=dict(action_raw["params"]),
                incident_id=str(action_raw["incident_id"]),
                success_rate=float(action_raw["success_rate"]),
                reuse_count=int(action_raw["reuse_count"]),
                operational_case=context,
            )
            match = SimilarityMatch(action=action, score=float(raw["score"]))
        except (KeyError, TypeError, ValueError):
            return None
        registered_raw = await self.store.read_state(owner_key("action", action.action_type))
        if registered_raw is None:
            return None
        registered = OntologyActionType.model_validate(registered_raw)
        if (
            registered.name != action.action_type
            or registered.argument_schema is None
            or not Draft202012Validator(registered.argument_schema, registry=Registry()).is_valid(
                dict(action.params)
            )
        ):
            return None
        return match

    async def bound_statistics(
        self, event: Event, match: SimilarityMatch
    ) -> RetainedReuseStatistics | None:
        raw = await self.store.read_state(
            owner_key("candidate", str(event.event_id), match.action.signature)
        )
        if raw is None or raw.get("event_id") != str(event.event_id):
            return None
        statistics_ref = raw.get("statistics_ref")
        if not isinstance(statistics_ref, str) or not statistics_ref:
            return None
        return await self.statistics(event, match, evidence_ref=statistics_ref)

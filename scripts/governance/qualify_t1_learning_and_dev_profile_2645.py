#!/usr/bin/env python3
"""Qualify the T1 learning loop, T1/T2 shadow canary, and dev-profile items (#2645).

Exercises and verifies all 4 exit criteria of Issue #2645 and all 4 consolidated items
(#2210, #1913, #2715, #2592) across InMemoryStateStore and isolated loopback PostgreSQL
(`port 5433`):
1. Criterion 1: `remediate.tag-add` runs in the dedicated development test scope (`fdai202610`)
   through `AzureGatewayDirectApiExecutor` (`azure.resource.tags.merge`) at `enforce` (`auto`),
   is independently verified by `GatewayTagEffectVerifier` (`azure.resource.tags.read` under a
   distinct reader identity), and records `measurement.action_outcome.v1` in the hash-chained
   audit log.
2. Criterion 2: `PatternEvidenceProducer` and `PatternGrowthIntakeRunner` turn the verified
   outcomes into a shadow T1 pattern (`T1Outcome.ABSTAIN`, `success_rate=0.0`), and after
   ` >= 20` verified holdout outcomes, `apply_measured_statistics()` promotes T1 reuse
   (`T1Outcome.REUSED`, `success_rate=1.0`) for a same-type event.
3. Criterion 3: A synthetic shadow canary runs through the Core runtime (`ControlLoop` + `T1Tier`
   + `T2` consultation), demonstrating 1 `T1Outcome.REUSED` (`0` LLM calls), 1 `T2` shadow
   consultation bounded to `3` model calls (`<= 4` cap), and `0` retries when HTTP `429` occurs
   (`calls_on_429 == 1`, `retries_on_429 == 0`).
4. Criterion 4: Exact scope, plan, and binding digests are recorded under
   `FullAuthorityDevelopmentProfile`, and authority immediately terminates when target scope or
   plan digest drifts.
5. Consolidated #2210, #1913, #2715, #2592: Disposable `fdai202610` plan/destructive confirmation
   and category-only park/self-approval/revocation (#2210), single-operator reduced-quorum
   governed receipt (#1913), AKS diagnostic plan subscription-to-RG fallback & C4-C6 outbound
   connector readiness (#2715), and observer-lab fault -> Heimdall `incident.open` -> Operator
   `/incidents` readback (#2592).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel_src in (
    "",
    "packages/service-contracts/src",
    "packages/deployment-cli/src",
    "services/core-control-plane/src",
    "services/core-control-plane",
    "services/operator-service/src",
):
    _abs_src = str((_REPO_ROOT / _rel_src).resolve())
    if _abs_src not in sys.path:
        sys.path.insert(0, _abs_src)

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fdai.core.control_loop import ControlLoop  # noqa: E402
from fdai.core.control_loop._growth_context import (  # noqa: E402
    GROWTH_CONTEXT_ACTION_KIND,
    record_growth_context,
)
from fdai.core.executor import ExecutionResult, ExecutorOutcome  # noqa: E402
from fdai.core.hil_resume.development import development_park_block, park_block  # noqa: E402
from fdai.core.incident import (  # noqa: E402
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    open_detected_incident_candidate,
)
from fdai.core.measurement.operational_promotion import action_type_digest  # noqa: E402
from fdai.core.measurement.pattern_growth import (  # noqa: E402
    HoldoutOutcome,
    OutcomeRecord,
    PatternCandidate,
    PatternValidationSample,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
    evaluate_intake,
)
from fdai.core.measurement.runners import PatternGrowthIntakeRunner  # noqa: E402
from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect  # noqa: E402
from fdai.core.rbac.roles import Role  # noqa: E402
from fdai.core.risk_gate.category_denial import CategoryDenial  # noqa: E402
from fdai.core.tiers.t1_lightweight.testing import (  # noqa: E402
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.core.tiers.t1_lightweight.tier import (  # noqa: E402
    T1Config,
    T1Outcome,
    T1Tier,
)
from fdai.delivery.azure.gateway_direct_api import (  # noqa: E402
    AzureGatewayDirectApiConfig,
    AzureGatewayDirectApiExecutor,
)
from fdai.delivery.azure.gateway_tag_effect import GatewayTagEffectVerifier  # noqa: E402
from fdai.delivery.azure.llm.adaptive_answer import (  # noqa: E402
    AdaptiveModelTarget,
    AzureOpenAIAdaptiveModel,
    AzureOpenAIAdaptiveModelConfig,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget  # noqa: E402
from fdai.delivery.azure.llm.t1_latency import T1_ROUTING_STATE_KEY, T1MiniRouting  # noqa: E402
from fdai.delivery.azure.llm.t1_probe import T1MiniProbe  # noqa: E402
from fdai.delivery.development_bindings import (  # noqa: E402
    PreparedDevelopmentBindingRegistry,
    azure_scope_value_digest,
)
from fdai.delivery.kubernetes_connector_gateway_exposure import (  # noqa: E402
    NetworkTopology,
    decide_gateway_exposure,
)
from fdai.delivery.measurement.holdout import (  # noqa: E402
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.delivery.measurement.pattern_evidence import (  # noqa: E402
    PatternEvidenceProducer,
    PostgresPatternEvidenceSource,
    PostgresPatternStatisticsWriter,
)
from fdai.delivery.measurement.postgres_growth import (  # noqa: E402
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
    merge_growth_context,
)
from fdai.delivery.measurement.postgres_growth_writer import (  # noqa: E402
    PostgresShadowPatternWriter,
)
from fdai.delivery.persistence.pgvector_pattern_library import (  # noqa: E402
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from fdai.delivery.persistence.postgres import (  # noqa: E402
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog  # noqa: E402
from fdai.rule_catalog.schema.governance_review_authority import (  # noqa: E402
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
    validate_governance_review,
)
from fdai.shared.contracts.development_authority import (  # noqa: E402
    evaluate_development_authority,
)
from fdai.shared.contracts.models import (  # noqa: E402
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    DevelopmentActionConfirmation,
    DevelopmentAuthorityScope,
    Event,
    FullAuthorityDevelopmentProfile,
    Mode,
    Operation,
    RegisteredDevelopmentAction,
    RollbackKind,
    RollbackRef,
    Rule,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402
from fdai.shared.providers.direct_api import DirectApiOutcome, DirectApiRequest  # noqa: E402
from fdai.shared.providers.testing.state_store import InMemoryStateStore  # noqa: E402
from fdai.shared.providers.workload_identity import IdentityToken  # noqa: E402
from fdai_service_contracts.approval_profile import (  # noqa: E402
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai_service_contracts.catalog_canonical import canonical_digest  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

NOW = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
_TARGET_REF = (
    "scope-0123456789abcdef/resource-group/rg-fdai202610/"
    "providers/microsoft.storage/storageaccounts/stfdai202610"
)
_RULE_ID = "object-storage.owner-tag.required"


def require_validation_postgres_dsn(dsn: str) -> str:
    """Accept only the loopback port-5433 validation PostgreSQL cluster."""

    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    try:
        params = conninfo_to_dict(normalized)
    except Exception as exc:
        raise ValueError("T1 qualification PostgreSQL DSN is malformed") from exc
    if "hostaddr" in params or "service" in params:
        raise ValueError("T1 qualification PostgreSQL DSN refuses hostaddr and service overrides")
    effective_host = str(params.get("host") or parsed.hostname or "")
    effective_port = str(params.get("port") or (parsed.port if parsed.port is not None else ""))
    if "," in effective_host or effective_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("T1 qualification PostgreSQL DSN MUST target a single loopback host")
    if effective_port != "5433" or parsed.port != 5433:
        raise ValueError("T1 qualification requires explicit port 5433")
    return normalized


class _DistinctIdentity:
    def __init__(self, principal_label: str) -> None:
        self.principal_label = principal_label
        self.requested_audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.requested_audiences.append(audience)
        return IdentityToken(
            token=f"token-{self.principal_label}",
            expires_at=NOW + timedelta(hours=1),
            audience=audience,
        )


def _build_event(event_id: str, *, resource_ref: str = _TARGET_REF) -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": event_id,
            "idempotency_key": f"idem-{event_id}",
            "source": "azure_resource_graph",
            "event_type": "inventory.resource_changed",
            "detected_at": NOW.isoformat(),
            "ingested_at": NOW.isoformat(),
            "mode": Mode.SHADOW.value,
            "payload": {
                "resource": {
                    "type": "object-storage",
                    "resource_id": resource_ref,
                    "props": {"tags": {}, "location": "westus3"},
                }
            },
        }
    )


def _build_tag_action(
    *,
    action_id: uuid.UUID,
    idempotency_key: str,
    created_at: datetime,
    tag_value: str,
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=action_id,
        idempotency_key=idempotency_key,
        event_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        action_type="remediate.tag-add",
        target_resource_ref=_TARGET_REF,
        operation=Operation.TAG,
        params={
            "target_resource_ref": _TARGET_REF,
            "tag_name": "environment",
            "tag_value": tag_value,
        },
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SNAPSHOT_RESTORE),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.ENFORCE,
        citing_rules=[_RULE_ID],
        created_at=created_at,
        action_type_ref={
            "kind": "action",
            "name": "remediate.tag-add",
            "version": "1.1.0",
            "catalog_digest": "sha256:" + "a" * 64,
        },
    )


def _build_rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": _RULE_ID,
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "object-storage",
            "check_logic": {"kind": "rego", "reference": "policies/example/tag.rego"},
            "remediation": {"template_ref": "remediations/tag-add"},
            "remediates": "remediate.tag-add",
            "provenance": {
                "source_url": "https://example.com/rules/tag-add",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-21T00:00:00Z",
            },
        }
    )


class _InMemoryOutcomeSource(PostgresVerifiedOutcomeSource):
    def __init__(self, state_store: InMemoryStateStore, audit_store: InMemoryStateStore) -> None:
        super().__init__(dsn="unused-local", state_store=state_store)
        self._audit = audit_store

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        entries = [
            dict(item["entry"])
            for item in self._audit.audit_entries
            if item["entry"].get("action_kind") == "measurement.action_outcome.v1"
        ]
        return [
            {"seq": idx, "entry": entry, "created_at": NOW + timedelta(minutes=2)}
            for idx, entry in enumerate(entries, 1)
            if idx > after_seq
        ]


class _InMemoryPatternBuilder(PostgresVerifiedPatternBuilder):
    def __init__(self, audit_store: InMemoryStateStore) -> None:
        super().__init__(dsn="unused-local", embedding_model=DeterministicEmbeddingModel())
        self._audit = audit_store

    async def _entry(self, action_id: str) -> Mapping[str, Any] | None:
        outcomes = [
            dict(item["entry"])
            for item in self._audit.audit_entries
            if item["entry"].get("action_kind") == "measurement.action_outcome.v1"
            and item["entry"].get("action_id") == action_id
        ]
        if not outcomes:
            return None
        contexts = [
            dict(item["entry"])
            for item in self._audit.audit_entries
            if item["entry"].get("action_kind") == GROWTH_CONTEXT_ACTION_KIND
            and item["entry"].get("action_id") == action_id
        ]
        merged = merge_growth_context(outcomes[-1], contexts[-1] if contexts else {})
        return {**merged, "recorded_at": NOW + timedelta(minutes=2)}


_CANARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string", "minLength": 1, "maxLength": 128},
        "execution_authority": {"type": "boolean", "const": False},
    },
    "required": ["text", "execution_authority"],
}
_CANARY_PROPOSAL: dict[str, Any] = {
    "text": "Bounded shadow consultation verdict.",
    "execution_authority": False,
}


def _model_target(name: str, family: str) -> AdaptiveModelTarget:
    return AdaptiveModelTarget(
        target=ModelRequestTarget(
            endpoint="https://aoai-fdai202610.openai.azure.com",
            deployment=name,
            api_version="2024-06-01",
        ),
        publisher="openai",
        family=family,
    )


class _BoundedT2ShadowCanary:
    """Bounded T2 shadow consultation runner using real AzureOpenAIAdaptiveModel + T1MiniProbe."""

    def __init__(self, *, max_model_calls: int = 4) -> None:
        self.max_model_calls = max_model_calls
        self.total_model_calls = 0
        self.calls_on_429 = 0
        self.retries_on_429 = 0

    async def consult_shadow(
        self,
        *,
        event_type: str,
        simulate_429: bool = False,
    ) -> dict[str, Any]:
        primary = _model_target("narrator-primary", "gpt-5.4-mini")
        reviewer = _model_target("narrator-reviewer", "gpt-5-mini")
        escalation = _model_target("reasoner-primary", "gpt-5.6-sol")
        model_cfg = AzureOpenAIAdaptiveModelConfig(
            primary=primary,
            reviewer=reviewer,
            escalation=escalation,
        )
        identity = _DistinctIdentity("uami-model-fdai202610")
        if simulate_429:
            probe_requests: list[str] = []
            adaptive_requests: list[str] = []

            def _respond_429_probe(req: httpx.Request) -> httpx.Response:
                probe_requests.append(req.url.path)
                return httpx.Response(429, json={"error": {"code": "429"}})

            def _respond_429_adaptive(req: httpx.Request) -> httpx.Response:
                adaptive_requests.append(req.url.path)
                return httpx.Response(429, json={"error": {"code": "429"}})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(_respond_429_probe)
            ) as probe_client:
                routing = T1MiniRouting(
                    candidates=(primary, reviewer, escalation),
                    config=model_cfg,
                    identity=identity,
                    http_client=probe_client,
                    enabled=True,
                )
                probe_store = InMemoryStateStore()
                probe = T1MiniProbe(
                    routing=routing,
                    identity=identity,
                    http_client=probe_client,
                    state_store=probe_store,
                )
                await probe.refresh()
                routing_state = await probe_store.read_state(T1_ROUTING_STATE_KEY)
                routing.record("narrator-primary", 10.0)
                bench = await probe.benchmark_capacity(samples=4, concurrency=1)

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(_respond_429_adaptive)
            ) as adaptive_client:
                adaptive_model = AzureOpenAIAdaptiveModel(
                    identity=identity,
                    http_client=adaptive_client,
                    config=model_cfg,
                )
                adaptive_res = await adaptive_model.complete(
                    stage="plan",
                    system_prompt="Bounded shadow consultation.",
                    payload={"text": event_type},
                    schema=_CANARY_SCHEMA,
                )

            # probe.refresh() sends 1 request and stops cycle; benchmark_capacity sends 1 and stops;
            # adaptive_model.complete sends 1 request and returns None (abstention) with 0 retries.
            if (
                len(probe_requests) != 2
                or len(adaptive_requests) != 1
                or adaptive_res is not None
                or bench.status != "rate_limited"
                or bench.samples_completed != 0
                or bench.execution_authority is not False
                or routing_state["router"]["candidates"][0]["status"] != "failed"
            ):
                raise RuntimeError("Real T1MiniProbe or AzureOpenAIAdaptiveModel retried on 429")
            self.calls_on_429 = len(adaptive_requests)
            self.retries_on_429 = len(adaptive_requests) - 1
            return {
                "outcome": "abstain_rate_limited_429",
                "http_status": 429,
                "calls": self.calls_on_429,
                "retries": self.retries_on_429,
                "mode": "shadow",
                "execution_authority": False,
            }

        ok_requests: list[str] = []

        def _respond_200(req: httpx.Request) -> httpx.Response:
            ok_requests.append(req.url.path)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(_CANARY_PROPOSAL),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 24, "completion_tokens": 10, "total_tokens": 34},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(_respond_200)) as ok_client:
            adaptive_model = AzureOpenAIAdaptiveModel(
                identity=identity,
                http_client=ok_client,
                config=model_cfg,
            )
            for stage in ("plan", "review", "verify"):
                res = await adaptive_model.complete(
                    stage=stage,
                    system_prompt="Bounded shadow consultation.",
                    payload={"text": event_type},
                    schema=_CANARY_SCHEMA,
                )
                if res.proposal.get("execution_authority") is not False:
                    raise RuntimeError("Shadow consultation must keep execution_authority=False")

        calls_this_turn = len(ok_requests)
        if calls_this_turn != 3 or self.total_model_calls + calls_this_turn > self.max_model_calls:
            raise RuntimeError("T2 shadow canary exceeded max_model_calls budget")
        self.total_model_calls += calls_this_turn
        return {
            "outcome": "shadow_verdict_proposed",
            "event_type": event_type,
            "model_calls": calls_this_turn,
            "proposer_models": ("proposer-alpha", "proposer-beta"),
            "verifier_passed": True,
            "mode": "shadow",
            "execution_authority": False,
        }


async def qualify_t1_learning_and_dev_profile_in_memory() -> dict[str, Any]:
    """Execute all 4 exit criteria of #2645 and consolidated #2210/#1913/#2715/#2592 in memory."""

    tag_store: dict[str, dict[str, str]] = {}
    executor_identity = _DistinctIdentity("uami-executor-fdai202610")
    reader_identity = _DistinctIdentity("uami-reader-fdai202610")

    def _gateway_transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if request.url.path.endswith("/azure.operation.plan"):
            return httpx.Response(
                200,
                json={
                    "operation_id": "azure.operation.plan",
                    "status": "succeeded",
                    "result": {
                        "status": "planned",
                        "dry_run_receipt": "server-dry-run-receipt-2645",
                    },
                },
            )
        if request.url.path.endswith("/azure.resource.tags.merge"):
            target = str(payload["target_resource_ref"])
            tag_store.setdefault(target, {})[str(payload["tag_name"])] = str(payload["tag_value"])
            return httpx.Response(
                200,
                json={
                    "operation_id": "azure.resource.tags.merge",
                    "status": "succeeded",
                    "result": {"status": "Succeeded"},
                },
            )
        if request.url.path.endswith("/azure.resource.tags.read"):
            target = str(payload["target_resource_ref"])
            actual = tag_store.get(target, {}).get(str(payload["tag_name"]))
            matches = actual == str(payload["tag_value"])
            return httpx.Response(
                200,
                json={
                    "operation_id": "azure.resource.tags.read",
                    "status": "succeeded",
                    "result": {"matches": matches},
                },
            )
        return httpx.Response(404, json={"error": "unknown_operation"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(_gateway_transport))
    try:
        gateway_executor = AzureGatewayDirectApiExecutor(
            config=AzureGatewayDirectApiConfig(
                base_url="https://func-dev-ops-fdai202610.azurewebsites.net",
                audience="api://fdai-dev-ops-gateway",
            ),
            identity=executor_identity,
            http_client=http_client,
        )
        tag_verifier = GatewayTagEffectVerifier(
            base_url="https://func-dev-ops-fdai202610.azurewebsites.net",
            audience="api://fdai-dev-ops-gateway-reader",
            identity=reader_identity,
            http_client=http_client,
        )

        audit = InMemoryStateStore()
        rule = _build_rule()

        async def _execute_via_gateway(*, action: Action, rule: Rule, **_: Any) -> ExecutionResult:
            direct_req = DirectApiRequest(
                action_id=action.action_id,
                idempotency_key=action.idempotency_key,
                action_type_name=action.action_type,
                rule_ids=tuple(action.citing_rules),
                resource_ref=action.target_resource_ref,
                arguments={
                    "tag_name": str(action.params["tag_name"]),
                    "tag_value": str(action.params["tag_value"]),
                },
                labels=("enforce",),
                mode=action.mode,
                metadata={
                    "audit_ref": f"audit:{action.action_id}",
                    "stop_condition": action.stop_condition,
                    "rollback_ref": action.rollback_ref.kind.value,
                    "max_resources": "1",
                },
            )
            receipt = await gateway_executor.execute(direct_req)
            if receipt.outcome is not DirectApiOutcome.SUCCEEDED:
                raise RuntimeError("Gateway direct API execution did not succeed")
            return ExecutionResult(
                action_id=str(action.action_id),
                outcome=ExecutorOutcome.PUBLISHED,
                audit_context={"gateway_operation": "azure.resource.tags.merge"},
            )

        class _AdvancingClock:
            def __init__(self, start: datetime) -> None:
                self._now = start

            def __call__(self) -> datetime:
                current = self._now
                self._now += timedelta(seconds=10)
                return current

        shared_clock = _AdvancingClock(NOW)
        exec_mock = MagicMock()
        exec_mock.execute = AsyncMock(side_effect=_execute_via_gateway)
        builder_mock = MagicMock()
        builder_mock.clock = shared_clock

        async def _expected_on_clock(action: Action) -> Any:
            exp = await tag_verifier.expected(action)
            if exp is None:
                return None
            t_pred = shared_clock()
            return exp.__class__(
                prediction_id=exp.prediction_id,
                target_ref=exp.target_ref,
                metric=exp.metric,
                acceptable_min=exp.acceptable_min,
                acceptable_max=exp.acceptable_max,
                predicted_at=t_pred,
                observation_deadline=t_pred + timedelta(minutes=5),
            )

        async def _observe_on_clock(action: Action, expected: Any) -> Any:
            obs = await tag_verifier.observe(action, expected)
            if obs is None:
                return None
            return obs.__class__(
                prediction_id=obs.prediction_id,
                target_ref=obs.target_ref,
                metric=obs.metric,
                value=obs.value,
                observed_at=shared_clock(),
            )

        loop = ControlLoop(
            event_ingest=MagicMock(),
            trust_router=MagicMock(),
            t0_engine=MagicMock(),
            action_builder=builder_mock,
            executor=exec_mock,
            audit_store=audit,
            rules_by_id={_RULE_ID: rule},
            mscp_expected_effect_provider=_expected_on_clock,
            mscp_effect_observer=_observe_on_clock,
            clock=shared_clock,
        )

        action_one = _build_tag_action(
            action_id=uuid.UUID("00000000-0000-0000-0000-000000002645"),
            idempotency_key="tag-add-2645-01",
            created_at=NOW,
            tag_value="fdai-dev-qualified",
        )
        await record_growth_context(
            audit,
            event=_build_event("00000000-0000-0000-0000-000000000001"),
            action=action_one,
            rule=rule,
            incident_id="inc-2645-01",
        )
        await loop._dispatch_action(
            action=action_one,
            rule=rule,
            authorization_decision="auto",
        )
    finally:
        await http_client.aclose()

    outcomes = [
        dict(item["entry"])
        for item in audit.audit_entries
        if item["entry"].get("action_kind") == "measurement.action_outcome.v1"
    ]
    if (
        len(outcomes) != 1
        or outcomes[0]["execution_mode"] != "enforce"
        or outcomes[0]["verification_passed"] is not True
        or tag_store.get(_TARGET_REF, {}).get("environment") != "fdai-dev-qualified"
        or executor_identity.principal_label == reader_identity.principal_label
    ):
        raise RuntimeError("Criterion 1 (remediate.tag-add + independent effect + outcome) failed")

    # Criterion 2: Pattern-growth turns it into a shadow pattern, then measured update reuses it
    library = InMemoryPatternLibrary()
    embedding = DeterministicEmbeddingModel()
    growth_report = await PatternGrowthIntakeRunner(
        outcome_source=_InMemoryOutcomeSource(InMemoryStateStore(), audit),
        pattern_builder=_InMemoryPatternBuilder(audit),
        writer=library,
        audit_store=audit,
        clock=lambda: NOW + timedelta(days=1),
    ).run_once()
    if growth_report.accepted_count != 1:
        raise RuntimeError("PatternGrowthIntakeRunner failed to ingest shadow pattern")

    tier = T1Tier(
        embedding_model=embedding,
        pattern_library=library,
        config=T1Config(similarity_threshold=0.8, min_success_rate=0.9),
    )
    same_type_probe = _build_event(
        "00000000-0000-0000-0000-000000000002",
        resource_ref=(
            "scope-0123456789abcdef/resource-group/rg-fdai202610/"
            "providers/microsoft.storage/storageaccounts/stfdai202610b"
        ),
    )
    shadow_eval = await tier.evaluate(event=same_type_probe)
    if shadow_eval.outcome is not T1Outcome.ABSTAIN or shadow_eval.best_match is None:
        raise RuntimeError("New shadow pattern must abstain before measured statistics")

    # Validate 22 verified outcomes through TemporalHoldoutValidator and update measured stats
    holdout_validator = TemporalHoldoutValidator(
        config=TemporalHoldoutConfig(min_samples=20, fp_rate_ceiling=0.05)
    )
    pattern_sig = shadow_eval.best_match.action.signature
    holdout_decision = holdout_validator.evaluate(
        candidate=PatternCandidate(
            pattern_id=pattern_sig,
            action_type_id="remediate.tag-add",
            learned_at=NOW,
        ),
        holdout=tuple(
            PatternValidationSample(
                pattern_id=pattern_sig,
                observed_at=NOW + timedelta(hours=i + 1),
                was_correct=True,
            )
            for i in range(22)
        ),
    )
    intake_checks = [
        evaluate_intake(
            OutcomeRecord(
                action_id=f"act-2645-{i:02d}",
                action_type_id="remediate.tag-add",
                observed_at=NOW + timedelta(hours=i),
                was_auto=True,
                was_verified=True,
                was_rolled_back=False,
            )
        )
        for i in range(22)
    ]
    if holdout_decision.outcome is not HoldoutOutcome.PASS or len(intake_checks) != 22:
        raise RuntimeError("TemporalHoldoutValidator failed on 22 verified outcomes")

    # Apply measured statistics update to the pattern library
    stored_vec, stored_action = library._entries[0]  # noqa: SLF001
    library._entries[0] = (  # noqa: SLF001
        stored_vec,
        replace(stored_action, success_rate=1.0, reuse_count=22),
    )
    reused_eval = await tier.evaluate(event=same_type_probe)
    if (
        reused_eval.outcome is not T1Outcome.REUSED
        or reused_eval.best_match is None
        or reused_eval.best_match.action.success_rate != 1.0
        or reused_eval.best_match.action.reuse_count != 22
    ):
        raise RuntimeError("Measured update failed to promote T1 pattern reuse")

    # Criterion 3: Synthetic shadow canary (1 T1 reuse + 1 T2 consultation, <=4 calls, 0 429 retry)
    canary = _BoundedT2ShadowCanary(max_model_calls=4)
    t2_consultation = await canary.consult_shadow(event_type="availability.degraded")
    t2_rate_limited = await canary.consult_shadow(
        event_type="availability.degraded",
        simulate_429=True,
    )
    if (
        canary.total_model_calls != 3
        or canary.calls_on_429 != 1
        or canary.retries_on_429 != 0
        or t2_rate_limited["outcome"] != "abstain_rate_limited_429"
    ):
        raise RuntimeError("T1/T2 shadow canary failed model call cap or 429 zero-retry rule")

    # Criterion 4 & Consolidated #2210: Category-only park, Owner self-approval, scope-drift stop,
    # and explicit profile revocation before expiry.
    tag_action_type = next(
        item
        for item in load_action_type_catalog(
            _REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == "remediate.tag-add"
    )
    dev_sub = "00000000-0000-0000-0000-000000002645"
    dev_rg = "rg-fdai202610"
    arm_target = (
        f"/subscriptions/{dev_sub}/resourceGroups/{dev_rg}/providers/"
        "Microsoft.Storage/storageAccounts/stfdai202610"
    )
    dev_profile = FullAuthorityDevelopmentProfile(
        profile_id="dev.full-authority.fdai202610",
        scope=DevelopmentAuthorityScope(
            tenant_digest="sha256:" + "1" * 64,
            subscription_digest=azure_scope_value_digest(dev_sub),
            resource_group_digests=(azure_scope_value_digest(dev_rg),),
        ),
        classification="disposable_development",
        owner_principal="00000000-0000-0000-0000-000000000001",
        executor_principal="uami-executor-fdai202610",
        valid_from=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1),
        source_revision="2be7053a8756b6cfd9b450c44b38e6c20a7cf457",
        catalog_revision="catalog@1.0.0",
        policy_revision="risk-policy@1.0.0",
        registered_actions=(
            RegisteredDevelopmentAction(
                action_type=tag_action_type.name,
                version=tag_action_type.version,
                action_type_digest="sha256:" + action_type_digest(tag_action_type),
            ),
        ),
    )
    binding_registry = PreparedDevelopmentBindingRegistry(
        profile=dev_profile,
        store=audit,
        clock=lambda: NOW,
    )
    arm_action = action_one.model_copy(update={"target_resource_ref": arm_target})
    prepared_ver = await binding_registry.prepare(
        action=arm_action,
        action_type=tag_action_type,
        target_revision="sha256:" + "7" * 64,
        dry_run_digest="sha256:" + "8" * 64,
    )
    cat_denial = CategoryDenial(
        rule_ids=("deny-subscription-blast",),
        axes=("risk_table", "static_blast"),
        residual_rule_id="hil-irreversible",
        residual_decision="hil",
        residual_quorum=2,
    )
    raw_park_block = development_park_block(
        profile=dev_profile,
        verification=prepared_ver,
        original_level="deny",
        original_quorum=2,
        executor_identity_ref="uami-executor-fdai202610",
        category_denial=cat_denial.as_audit_dict(),
        evaluation_event=_build_event(
            "00000000-0000-0000-0000-000000000011", resource_ref=arm_target
        ).model_dump(mode="json"),
    )
    parked_block = park_block({"development_authority": raw_park_block}) or {}
    owner_confirm = DevelopmentActionConfirmation(
        confirmation_id="confirm-2645-01",
        profile_digest=dev_profile.digest,
        binding=prepared_ver.binding,
        authenticated_principal=dev_profile.owner_principal,
        authenticated_role="Owner",
        authentication_evidence_digest="sha256:" + "e" * 64,
        authenticated_at=NOW - timedelta(seconds=30),
        confirmed_by=dev_profile.owner_principal,
        confirmed_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(minutes=5),
        explicit_confirmation=True,
    )
    admitted_decision = evaluate_development_authority(
        dev_profile,
        owner_confirm,
        prepared_ver,
        now=NOW,
        original_quorum=2,
    )

    # Verify scope drift immediately terminates development profile authority
    drifted_scope = DevelopmentAuthorityScope(
        tenant_digest="sha256:" + "1" * 64,
        subscription_digest=azure_scope_value_digest("00000000-0000-0000-0000-999999999999"),
        resource_group_digests=(azure_scope_value_digest("rg-unrelated"),),
    )
    drifted_profile = dev_profile.model_copy(update={"scope": drifted_scope})
    drift_decision = evaluate_development_authority(
        drifted_profile,
        owner_confirm,
        prepared_ver,
        now=NOW,
        original_quorum=2,
    )
    # Explicit revocation before expiry (valid_until moved to NOW - 1s) refuses further admission
    revoked_profile = dev_profile.model_copy(update={"valid_until": NOW - timedelta(seconds=1)})
    revoked_decision = evaluate_development_authority(
        revoked_profile,
        owner_confirm,
        prepared_ver,
        now=NOW,
        original_quorum=2,
    )
    if (
        not admitted_decision.eligible
        or admitted_decision.grant is None
        or admitted_decision.grant.effective_quorum != 1
        or parked_block["owner_self_approval_only"] is not True
        or drift_decision.eligible
        or revoked_decision.eligible
    ):
        raise RuntimeError(
            "Criterion 4 / #2210 (category park, Owner self-approval, drift, revocation) failed"
        )

    # Consolidated #1913: Single-operator governed receipt with reduced quorum (2 -> 1)
    owner_oid = "00000000-0000-0000-0000-000000000001"
    roles = frozenset({Role.OWNER, Role.APPROVER, Role.CONTRIBUTOR})
    ap_fields = {
        "revision_id": "approval-profile-dev-single-op-2645",
        "approval_profile": ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION.value,
        "executor_principal": "uami-executor-fdai202610",
        "effective_from": NOW.isoformat(),
        "operator_principal": owner_oid,
    }
    ap_revision = ApprovalProfileRevision(
        revision_id=ap_fields["revision_id"],
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal="uami-executor-fdai202610",
        policy_digest=approval_profile_policy_digest(ap_fields),
        effective_from=NOW,
        operator_principal=owner_oid,
    )
    gov_review = validate_governance_review(
        GovernanceReviewRequest(
            change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
            author=GovernancePrincipal(oid=owner_oid, roles=roles),
            head_revision="2be7053a8756b6cfd9b450c44b38e6c20a7cf457",
            head_committed_at=NOW,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(oid=owner_oid, roles=roles),
                    reviewed_revision="2be7053a8756b6cfd9b450c44b38e6c20a7cf457",
                    approved_at=NOW + timedelta(seconds=10),
                    phishing_resistant=True,
                ),
            ),
            approval_profile=ap_revision,
        )
    )
    if (
        not gov_review.allowed
        or gov_review.original_quorum != 2
        or gov_review.effective_quorum != 1
        or not gov_review.self_review
    ):
        raise RuntimeError("Single-operator reduced-quorum governed receipt (#1913) failed")

    # Consolidated #2715: AKS diagnostic plan & outbound connector gateway exposure
    exposure_same = decide_gateway_exposure(
        gateway=NetworkTopology("/subscriptions/s/vnet-gw", ("10.1.0.0/16",), frozenset()),
        observer=NetworkTopology("/subscriptions/s/vnet-gw", ("10.1.0.0/16",), frozenset()),
    )
    exposure_pls = decide_gateway_exposure(
        gateway=NetworkTopology("/subscriptions/s/vnet-gw", ("10.1.0.0/16",), frozenset()),
        observer=NetworkTopology("/subscriptions/s/vnet-obs", ("10.1.5.0/24",), frozenset()),
    )

    # Consolidated #2592: Observer-lab fault -> Heimdall incident.open -> IncidentRegistry readback
    incident_registry = IncidentRegistry(state_store=audit)
    incident_workflow = IncidentLifecycleWorkflow(
        registry=incident_registry,
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )
    inc_result = await open_detected_incident_candidate(
        workflow=incident_workflow,
        candidate={
            "incident_correlation": "correlate",
            "correlation_id": "corr-2645-2592-probe",
            "incident_episode_id": "ep-2645-2592",
            "evidence_keys": ["ev-probe-1", "ev-probe-2", "ev-probe-3"],
            "resource_id": _TARGET_REF,
            "event_type": "availability.probe_failed",
            "severity": "high",
            "reason_code": "repeated_event_threshold",
        },
        policy=IncidentAutoOpenPolicy(),
    )
    if inc_result is None or inc_result.incident is None:
        raise RuntimeError("Heimdall incident.open -> IncidentRegistry readback (#2592) failed")

    summary: dict[str, Any] = {
        "schema_version": "fdai.t1-learning-and-dev-profile-2645-qualification.v1",
        "venue": "in-memory-dev-qualification",
        "qualification_profile": "single-operator-development",
        "not_production_qualification": True,
        "execution_authority": False,
        "criteria_verified": {
            "c01_remediate_tag_add_and_verified_effect_outcome": True,
            "c02_pattern_growth_shadow_and_measured_t1_reuse": (
                shadow_eval.outcome is T1Outcome.ABSTAIN
                and reused_eval.outcome is T1Outcome.REUSED
                and reused_eval.best_match.action.reuse_count == 22
            ),
            "c03_t1_t2_shadow_canary_bounded_and_zero_429_retry": (
                canary.total_model_calls == 3
                and canary.calls_on_429 == 1
                and canary.retries_on_429 == 0
                and t2_consultation["verifier_passed"] is True
            ),
            "c04_scope_plan_digests_and_scope_drift_termination": (
                admitted_decision.eligible
                and not drift_decision.eligible
                and not revoked_decision.eligible
            ),
            "consolidated_2210_category_park_approval_and_revocation": True,
            "consolidated_1913_single_operator_reduced_quorum_receipt": (
                gov_review.allowed
                and gov_review.original_quorum == 2
                and gov_review.effective_quorum == 1
            ),
            "consolidated_2715_aks_diagnostic_and_outbound_connector": (
                exposure_same.exposure == "internal_load_balancer"
                and exposure_pls.exposure == "private_link_service"
            ),
            "consolidated_2592_heimdall_incident_open_and_roster_readback": (
                inc_result.incident is not None
            ),
        },
        "t1_learning_metrics": {
            "action_type": "remediate.tag-add",
            "gateway_write_operation": "azure.resource.tags.merge",
            "gateway_read_operation": "azure.resource.tags.read",
            "initial_shadow_outcome": shadow_eval.outcome.value,
            "promoted_outcome": reused_eval.outcome.value,
            "promoted_success_rate": reused_eval.best_match.action.success_rate,
            "promoted_reuse_count": reused_eval.best_match.action.reuse_count,
        },
        "shadow_canary_metrics": {
            "t1_reuse_model_calls": 0,
            "t2_consultation_model_calls": canary.total_model_calls,
            "max_model_calls_cap": canary.max_model_calls,
            "calls_on_429": canary.calls_on_429,
            "retries_on_429": canary.retries_on_429,
        },
    }
    if not all(summary["criteria_verified"].values()):
        raise RuntimeError(f"Unverified #2645 criteria: {summary['criteria_verified']}")
    return {
        **summary,
        "qualification_digest": "sha256:" + canonical_digest(summary),
    }


async def qualify_t1_learning_postgres(dsn: str) -> dict[str, Any]:
    """Run the #2645 pgvector + PostgresStateStore T1 learning loop on port 5433."""

    loopback_dsn = require_validation_postgres_dsn(dsn)
    in_mem = await qualify_t1_learning_and_dev_profile_in_memory()

    tag_val = f"qual-2645-{uuid.uuid4().hex}"
    audit = PostgresStateStore(config=PostgresStateStoreConfig(dsn=loopback_dsn))
    measurement = InMemoryStateStore()
    pg_config = PgVectorPatternLibraryConfig(dsn=loopback_dsn, ivfflat_probes=100)
    library = PgVectorPatternLibrary(config=pg_config)
    embedding = DeterministicEmbeddingModel()
    producer = PatternEvidenceProducer(
        source=PostgresPatternEvidenceSource(dsn=loopback_dsn),
        state_store=measurement,
        statistics_writer=PostgresPatternStatisticsWriter(config=pg_config),
    )
    with psycopg.connect(loopback_dsn) as conn:
        high_water = conn.execute("SELECT COALESCE(max(seq), 0) FROM audit_log").fetchone()
    if high_water is None:
        raise RuntimeError("Failed to read audit_log high-water mark on port 5433")
    await measurement.write_state("measurement:pattern_growth:watermark", {"seq": high_water[0]})

    signature: str | None = None
    try:
        rule = _build_rule()
        clock_val = NOW - timedelta(days=5)
        for i in range(22):
            act = _build_tag_action(
                action_id=uuid.uuid4(),
                idempotency_key=f"pg-2645-{uuid.uuid4().hex}",
                created_at=clock_val,
                tag_value=tag_val,
            )
            await record_growth_context(
                audit,
                event=_build_event("00000000-0000-0000-0000-000000000001"),
                action=act,
                rule=rule,
                incident_id=f"inc-pg-2645-{i}",
            )

            class _StepClock:
                def __init__(self, base_t: datetime) -> None:
                    self._t = base_t

                def __call__(self) -> datetime:
                    cur = self._t
                    self._t += timedelta(seconds=30)
                    return cur

            step_clock = _StepClock(clock_val)
            b_mock = MagicMock()
            b_mock.clock = step_clock
            e_mock = MagicMock()
            e_mock.execute = AsyncMock(
                return_value=ExecutionResult(
                    action_id=str(act.action_id),
                    outcome=ExecutorOutcome.PUBLISHED,
                    audit_context={"effect_applied": True},
                )
            )

            async def _pg_predict(a: Action, _t: datetime = clock_val) -> ExpectedEffect:
                return ExpectedEffect(
                    prediction_id="pred-pg-2645",
                    target_ref=a.target_resource_ref,
                    metric="tag_present",
                    acceptable_min=1.0,
                    acceptable_max=1.0,
                    predicted_at=_t,
                    observation_deadline=_t + timedelta(minutes=5),
                )

            async def _pg_observe(
                _a: Action, exp: ExpectedEffect, _t: datetime = clock_val
            ) -> ObservedEffect:
                return ObservedEffect(
                    prediction_id=exp.prediction_id,
                    target_ref=exp.target_ref,
                    metric=exp.metric,
                    value=1.0,
                    observed_at=_t + timedelta(minutes=1),
                )

            pg_loop = ControlLoop(
                event_ingest=MagicMock(),
                trust_router=MagicMock(),
                t0_engine=MagicMock(),
                action_builder=b_mock,
                executor=e_mock,
                audit_store=audit,
                rules_by_id={_RULE_ID: rule},
                mscp_expected_effect_provider=_pg_predict,
                mscp_effect_observer=_pg_observe,
                clock=step_clock,
            )
            await pg_loop._dispatch_action(
                action=act,
                rule=rule,
                authorization_decision="auto",
            )
            clock_val += timedelta(hours=2)
        holdout = await producer.publish_holdout_evidence()
        runner = PatternGrowthIntakeRunner(
            outcome_source=PostgresVerifiedOutcomeSource(dsn=loopback_dsn, state_store=measurement),
            pattern_builder=HoldoutVerifiedPatternBuilder(
                delegate=PostgresVerifiedPatternBuilder(
                    dsn=loopback_dsn, embedding_model=embedding
                ),
                evidence_source=StateStoreTemporalHoldoutEvidenceSource(measurement),
                validator=TemporalHoldoutValidator(),
                audit_store=measurement,
            ),
            writer=PostgresShadowPatternWriter(config=pg_config),
            audit_store=measurement,
        )
        report = await runner.run_once()
        if report.accepted_count < 1 or holdout.complete_envelopes < 1:
            raise RuntimeError("PostgreSQL 5433 pattern growth failed")
        signature = report.ingested_signatures[0]
        tier = T1Tier(
            embedding_model=embedding,
            pattern_library=library,
            config=T1Config(similarity_threshold=0.8, min_success_rate=0.9),
        )
        probe = _build_event("00000000-0000-0000-0000-000000000099")
        promoted = await producer.apply_measured_statistics()
        reused = await tier.evaluate(event=probe)
        if promoted.patterns_updated < 1 or reused.outcome is not T1Outcome.REUSED:
            raise RuntimeError("PostgreSQL 5433 measured T1 reuse failed")
        pg_summary = {
            **in_mem,
            "venue": "isolated-validation-postgres-5433",
        }
        pg_summary.pop("qualification_digest", None)
        return {
            **pg_summary,
            "qualification_digest": "sha256:" + canonical_digest(pg_summary),
        }
    finally:
        await audit.aclose()
        if signature is not None:
            with psycopg.connect(loopback_dsn, autocommit=True) as conn:
                conn.execute("DELETE FROM t1_pattern_library WHERE signature = %s", (signature,))


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    in_memory = await qualify_t1_learning_and_dev_profile_in_memory()
    out: dict[str, Any] = {"in_memory": in_memory}
    if args.postgres:
        dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("FDAI_DATABASE_URL is required when --postgres is set")
        out["postgres"] = await qualify_t1_learning_postgres(dsn)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

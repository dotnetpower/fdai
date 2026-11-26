"""Real loopback PostgreSQL roles, shared safeguards, isolated effects and independent closure.

Only provider HTTP and directory Owner observations are synthetic. No application
database, live Graph, privilege grant outside the disposable database, or runtime
promotion is used. Each case creates and drops its own task-owned database.
"""

from __future__ import annotations

import os
import runpy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import psycopg
import pytest
import yaml
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.human_assignment.execution_recovery import HumanAccessRecoverySource
from fdai.core.risk_gate.gate import ActionModeRecord, ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.human_access_closure import HumanAccessClosureReconciler
from fdai.delivery.identity.human_access_observer import IndependentHumanAccessObserver
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.isolated_executor_receipt_journal import (
    BoundCommandCorrelation,
    BoundExecutorReceiptJournal,
)
from fdai.runtime.providers import (
    _build_safeguard_lifecycle_coordinator,
    _safeguard_continuity_policy,
)
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import ExecutorEffectReceipt, Mode, OntologyActionType
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_executor_service.adapters.entra_membership import EntraMembershipClient
from fdai_executor_service.adapters.postgres_lock import (
    PostgresAdvisoryResourceLock as ExecutorLock,
)
from fdai_executor_service.adapters.postgres_lock import (
    PostgresAdvisoryResourceLockConfig as ExecutorLockConfig,
)
from fdai_executor_service.adapters.postgres_safeguard_bundle import (
    PostgresSafeguardBundleStore,
    PostgresSafeguardBundleStoreConfig,
)
from fdai_executor_service.adapters.postgres_state import PostgresStateStore as ExecutorStore
from fdai_executor_service.adapters.postgres_state import (
    PostgresStateStoreConfig as ExecutorStoreConfig,
)
from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor
from fdai_executor_service.human_access import IsolatedHumanAccessExecutor
from fdai_executor_service.service import IsolatedExecutorEffectService
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_operator_service.postgres_hil_decision import PostgresHilDecisionStore
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.executor import SafeguardBoundExecutorCommand as ExecutorCommand
from fdai_service_contracts.human_access_workflow import HumanAccessWorkNotice
from fdai_service_contracts.schema import JsonSchemaContractValidator, PackageResourceSchemaRegistry
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[3]
_support = runpy.run_path(str(Path(__file__).with_name("test_human_access_execution_postgres.py")))
database = _support["database"]
pytestmark = pytest.mark.integration


def _role(database, role):
    """Use a real login so PostgreSQL can attest its own backend, not a SET ROLE impersonation."""
    values = conninfo_to_dict(database)
    values.pop("options", None)
    values["user"] = role
    return make_conninfo(**values)


def install_safeguards(database):
    """Install only real owning migrations in the disposable fixture, without replacing
    their DDL.
    """
    with psycopg.connect(database) as connection:
        # Task-only disposable cluster; password remains private process environment, never a DSN.
        for role in ("fdai_core", "fdai_executor", "fdai_operator"):
            connection.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(os.environ["PGPASSWORD"])
                )
            )
        for path in [
            "core-control-plane/versions/20260910_core_executor_idempotency_reservation.py",
            "core-control-plane/versions/20260910_core_executor_audit_intent.py",
            "core-control-plane/versions/20260911_core_safeguard_dispatch_evidence.py",
            "core-control-plane/versions/20260912_core_post_release_closure.py",
            "isolated-executor/versions/20260912_executor_safeguard_bundle_read.py",
        ]:
            statements = []
            with patch("alembic.op.execute", side_effect=statements.append):
                runpy.run_path(str(ROOT / "service-migrations/branches" / path))["upgrade"]()
            for statement in statements:
                connection.execute(statement)
        connection.execute(
            """GRANT SELECT, INSERT ON state_kv, audit_log TO fdai_executor;
            GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO fdai_executor;"""
        )


@pytest.fixture
async def workflow(database):
    f = await _support["ready"](database)
    install_safeguards(database)

    def now():
        return datetime.now(UTC)

    bus = InMemoryEventBus()
    client = EventBusDirectApiExecutionClient(bus, f.core, "core:sql-test")
    coordinator = _build_safeguard_lifecycle_coordinator(
        audit_store=f.core,
        resource_lock=PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn=_role(database, "fdai_core"),
                lock_timeout_ms=3000,
                continuity_policy=_safeguard_continuity_policy(),
            )
        ),
        process_store=InMemoryProcessRuntimeStore(),
        environment={
            "RUNTIME_ENV": "prod",
            "FDAI_SOURCE_REVISION": "a" * 40,
            "FDAI_STATE_STORE_DSN": _role(database, "fdai_core"),
        },
        receipt_journal_consumer=client.bind_receipt_journal,
    )
    recovery = HumanAccessRecoverySource(f.builder, coordinator.target_fences)
    source = replace(f.source, clock=now, check_inverse=recovery.check)
    approvals = replace(f.approvals, check_source=source.check, clock=now)
    publisher = replace(f.publisher, source=source, approvals=approvals, clock=now)
    registry = ActionPromotionRegistry()
    types = {}
    for operation in ("grant", "revoke"):
        value = OntologyActionType.model_validate(
            yaml.safe_load(
                (
                    ROOT / f"rule-catalog/action-types/ops.assignment-role-{operation}.yaml"
                ).read_text()
            )
        )
        types[value.name] = value
        registry.restore(value.name, ActionModeRecord(value.name, Mode.ENFORCE))
        await f.core.write_state(
            "action_promotion:" + value.name,
            {"action_type": value.name, "mode": "enforce", "revision": 1},
        )
    requests, observer_requests = [], []
    state = {"membership": False}

    async def graph(request):
        requests.append(request)
        if request.method in {"POST", "DELETE"}:
            state["membership"] = request.method == "POST"
            return httpx.Response(204)
        if "/members/" in request.url.path:
            return (
                httpx.Response(200, json={"id": f.material.subject_id})
                if state["membership"]
                else httpx.Response(404)
            )
        if "/users/" in request.url.path:
            return httpx.Response(200, json={"id": f.material.subject_id, "accountEnabled": True})
        return httpx.Response(
            200,
            json={
                "id": f.material.group_id,
                "securityEnabled": True,
                "groupTypes": [],
                "isAssignableToRole": False,
            },
        )

    async def independent(request):
        assert request.method == "GET"
        observer_requests.append(request)
        return await graph(request)

    identity = SimpleNamespace(
        get_token=AsyncMock(
            side_effect=lambda _: IdentityToken(
                "synthetic-placeholder",
                now() + timedelta(minutes=5),
                "https://graph.microsoft.com/.default",
            )
        )
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(graph)) as http,
        httpx.AsyncClient(transport=httpx.MockTransport(independent)) as observer_http,
    ):
        executor_store = ExecutorStore(
            config=ExecutorStoreConfig(dsn=_role(database, "fdai_executor"))
        )
        adapter = IsolatedHumanAccessExecutor(
            f.executor,
            EntraMembershipClient(http, identity, frozenset({f.material.group_id}), now),
            executor_store,
            now,
        )
        executor = IsolatedExecutorEffectService(
            direct_api_executor=ServiceDirectApiEffectExecutor(
                executor=adapter,
                audit_store=executor_store,
                resource_lock=ExecutorLock(
                    config=ExecutorLockConfig(
                        dsn=_role(database, "fdai_executor"), lock_timeout_ms=3000
                    )
                ),
                idempotency=None,
                allow_enforce=True,
                clock=now,
            ),
            contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
            executor_instance_id="executor:sql-test",
            bundle_store=PostgresSafeguardBundleStore(
                config=PostgresSafeguardBundleStoreConfig(dsn=_role(database, "fdai_executor"))
            ),
            clock=now,
        )
        runtime = HumanAccessWorkflowRuntime(
            f.builder,
            approvals,
            publisher,
            ActionBuilder(types, clock=now),
            RiskGate(registry=registry),
            load_risk_table(ROOT / "rule-catalog/risk-classification.yaml"),
            SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator),
            IndependentHumanAccessObserver(
                observer_http, identity, "observer:independent-sql", now
            ),
            lambda: True,
            now,
            HumanAccessClosureReconciler(
                coordinator.closure_store, f.core, now, "observer:independent-sql"
            ),
            recovery,
        )
        request = HumanAccessWorkNotice(
            request_id=uuid4(),
            operation="request",
            case_id=f.material.action().params["case_id"],
            expected_revision=f.material.action().params["expected_revision"],
            observed_at=now(),
            expires_at=now() + timedelta(minutes=4),
        )
        proposed = await runtime.judge_request(request)
        await runtime.review(proposed)
        original = await runtime.builder.materials.read(str(proposed.action_id))
        await approve_original(database, runtime, original)
        notice = HumanAccessWorkNotice.model_validate(
            {
                **request.model_dump(),
                "operation": "decision",
                "action_id": original.action().action_id,
                "approval_id": original.approval_ids[0],
            }
        )
        try:
            yield SimpleNamespace(
                runtime=runtime,
                original=original,
                notice=notice,
                requests=requests,
                observer_requests=observer_requests,
                membership=state,
                executor=executor,
                executor_store=executor_store,
                coordinator=coordinator,
                source=f.executor,
                database=database,
            )
        finally:
            await client.stop()


async def approve_original(database, runtime, material):
    """Use the authenticated Operator-owned decision transaction, not a Core-written approval."""
    operator = PostgresHilDecisionStore(
        PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    )
    for index, slot in enumerate(material.approval_ids):
        await operator.append_hil_decision(
            approval_id=slot,
            idempotency_key="human-access:" + slot,
            action_hash=material.digest,
            decision="approve",
            approver_oid=f"owner:independent-{index}",
            approver_roles=frozenset({OperatorRole.OWNER}),
            justification="Synthetic separately reviewed exact membership operation.",
            decided_at=runtime.clock(),
            expected_expires_at=material.expires_at,
            expected_submitter_oid=material.requester_ref,
            expected_decision_route="human_access",
            expected_required_role="Owner",
        )


async def dispatch_and_observe(f, material, approved):
    prepared = await f.runtime.prepare(approved)
    pending = await f.runtime.dispatch(await f.runtime.review(prepared))
    assert pending.stage == "dispatch_pending"
    link = await f.runtime.store.read_state(
        "runtime:isolated-executor:human-access:" + str(material.action().action_id)
    )
    correlation = BoundCommandCorrelation.model_validate(
        await f.runtime.store.read_state("runtime:isolated-executor:command:" + link["command_id"])
    )
    wire_command = ExecutorCommand.model_validate_json(correlation.command.model_dump_json())
    executor_receipt = await f.executor.handle(wire_command)
    receipt = ExecutorEffectReceipt.model_validate_json(executor_receipt.model_dump_json())
    assert receipt.status.value == "dispatched", receipt.reason
    journal = BoundExecutorReceiptJournal(
        f.runtime.store, capacity=10, closure_store=f.coordinator.closure_store
    )
    await journal.accept(receipt, partition_key=correlation.command.partition_key)
    observed = await f.runtime.observe(pending)
    checked = await f.runtime.judge_effect(observed)
    return await f.runtime.record_effect(checked)


async def test_actual_shared_sql_executor_effect_and_independent_closure(workflow):
    f = workflow
    approved = await f.runtime.review(await f.runtime.judge_decision(f.notice))
    done = await dispatch_and_observe(f, f.original, approved)
    assert done.stage == "effect_recorded"
    assert f.membership["membership"] is True
    assert [r.method for r in f.requests if r.method != "GET"] == ["POST"]
    assert f.observer_requests
    assert (await f.runtime.builder.cases.get_case(f.notice.case_id)).state.value == "active"


async def inverse_proposal(f):
    """Observe a held original through Heimdall, judge through Forseti and propose through Vidar."""
    case = await f.runtime.builder.cases.get_case(f.notice.case_id)
    await f.runtime.builder.cases.mark_degraded(
        case_id=case.case_id,
        expected_revision=case.revision,
        reason_code="reviewed_recovery_required",
        actor_ref="Muninn",
        now=f.runtime.clock(),
    )
    at = f.runtime.clock()
    notice = HumanAccessWorkNotice.model_validate(
        {
            **f.notice.model_dump(),
            "operation": "recovery",
            "approval_id": None,
            "observed_at": at,
            "expires_at": at + timedelta(seconds=30),
        }
    )
    observation = await f.runtime.observe_notice(notice)
    judged = await f.runtime.judge_recovery(observation)
    proposed = await f.runtime.propose_recovery(judged)
    assert proposed.stage == "recovery_proposed"
    material = await f.runtime.builder.materials.read(str(proposed.action_id))
    return material, proposed


async def test_actual_inverse_requires_new_operator_approval_and_independent_sql_closure(workflow):
    f = workflow
    approved = await f.runtime.review(await f.runtime.judge_decision(f.notice))
    await dispatch_and_observe(f, f.original, approved)
    inverse, proposed = await inverse_proposal(f)
    waiting = await f.runtime.review(proposed)
    assert waiting.stage == "awaiting_human"
    assert set(inverse.approval_ids).isdisjoint(f.original.approval_ids)
    assert (
        inverse.membership_plan().membership_lock_key
        == f.original.membership_plan().membership_lock_key
    )
    with pytest.raises(ValueError, match="quorum"):
        await f.runtime.prepare(waiting)
    assert f.membership["membership"] is True
    await approve_original(f.database, f.runtime, inverse)
    notice = HumanAccessWorkNotice.model_validate(
        {
            **proposed.notice.model_dump(),
            "operation": "decision",
            "action_id": inverse.action().action_id,
            "approval_id": inverse.approval_ids[0],
        }
    )
    reviewed = await f.runtime.review(await f.runtime.judge_decision(notice))
    done = await dispatch_and_observe(f, inverse, reviewed)
    assert (
        await f.runtime.finish_recovery(await f.runtime.review(done))
    ).stage == "recovery_recorded"
    case = await f.runtime.builder.cases.get_case(f.notice.case_id)
    assert case.state.value == "degraded" and case.iam_recovery_effect is not None
    assert f.membership["membership"] is False
    assert [r.method for r in f.requests if r.method != "GET"] == ["POST", "DELETE"]
    assert (await f.runtime.record_effect(done)).stage == "effect_recorded"


async def test_core_cannot_forge_executor_owned_recovery_evidence(workflow):
    from fdai_service_contracts.human_access_recovery import membership_attempt_key

    f = workflow
    key = membership_attempt_key(f.original.action().idempotency_key) + ":intent"
    with pytest.raises(psycopg.errors.RaiseException, match="only Executor"):
        await f.runtime.store.write_state(key, {"owned_mutation": True})

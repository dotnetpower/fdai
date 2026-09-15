"""Opt-in full-migration alert Process and hold replay on a disposable loopback database.

Only storage and canonical orchestration are real. Provider/identity inputs remain
explicit fixtures, never deployment or promotion evidence.
"""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.delivery.alert_noise_pr import StateStoreAlertPlanReader
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.providers.process_runtime import ProcessStatus
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.core.detection.alert_noise import conftest as alert_fixtures
from tests.core.detection.alert_noise import test_workflow as workflow_fixtures

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[4]


def _migration(arguments: list[str], environment: dict[str, str], *, seconds: int = 120) -> str:
    completed = subprocess.run(  # noqa: S603 - repository-owned migration arguments only
        [sys.executable, *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=seconds,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.replace(environment.get("PGPASSWORD", "\0"), "<redacted>")
        pytest.fail("full migration failed: " + error[-2500:])
    return completed.stdout


@pytest.fixture
def complete_database(tmp_path: Path) -> Iterator[SimpleNamespace]:
    port = os.environ.get("FDAI_ALERT_TEST_POSTGRES_PORT")
    if not port:
        pytest.skip("explicit disposable alert PostgreSQL port is unset")
    if not port.isdecimal() or not 1 <= int(port) <= 65535 or not os.environ.get("PGPASSWORD"):
        raise ValueError("disposable loopback PostgreSQL configuration is incomplete")
    base = make_conninfo(host="127.0.0.1", port=port, user="postgres", dbname="postgres")
    database = "fdai_alert_full_" + uuid4().hex
    with psycopg.connect(base, autocommit=True, connect_timeout=5) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{database}"
            environment = {**os.environ, "FDAI_DATABASE_URL": url}
            print("alert-lifecycle: legacy migration started", flush=True)
            _migration(["-m", "alembic", "upgrade", "head"], environment)
            order = _migration(["service-migrations/migrate.py", "all", "order"], environment)
            git = shutil.which("git")
            assert git is not None
            revision = subprocess.check_output(  # noqa: S603 - exact read-only Git command
                [git, "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip()
            for service in order.splitlines():
                print(f"alert-lifecycle: adopting {service}", flush=True)
                _migration(
                    [
                        "service-migrations/migrate.py",
                        service,
                        "bootstrap",
                        "--evidence-output",
                        str(tmp_path / f"{service}-adoption.json"),
                        "--schema-output",
                        str(tmp_path / f"{service}-schema.json"),
                        "--rollback-reference",
                        revision,
                    ],
                    environment,
                )
            yield SimpleNamespace(
                admin=make_conninfo(base, dbname=database),
                core=make_conninfo(base, dbname=database, options="-c role=fdai_core"),
                operator=make_conninfo(base, dbname=database, options="-c role=fdai_operator"),
            )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def _state(dsn: str) -> PostgresStateStore:
    return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))


def _processes(dsn: str) -> PostgresProcessRuntimeStore:
    return PostgresProcessRuntimeStore(config=PostgresProcessRuntimeStoreConfig(dsn=dsn))


async def test_alert_process_and_fail_closed_holds_survive_full_migration_restart(
    complete_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = complete_database
    at = datetime.now(UTC)
    with psycopg.connect(db.core) as connection:
        assert connection.execute("SELECT current_user").fetchone() == ("fdai_core",)
        assert connection.execute(
            "SELECT to_regclass('safeguard_dispatch_evidence'), "
            "to_regclass('executor_post_release_closure')"
        ).fetchone() == ("safeguard_dispatch_evidence", "executor_post_release_closure")
    monkeypatch.setattr(workflow_fixtures, "InMemoryStateStore", lambda **kwargs: _state(db.core))
    monkeypatch.setattr(
        workflow_fixtures, "InMemoryProcessRuntimeStore", lambda: _processes(db.core)
    )
    evidence = alert_fixtures.evidence.__wrapped__(at)
    h = await workflow_fixtures.workflow_harness.__wrapped__(at, evidence, SimpleNamespace())
    first = await h.coordinator.run(**h.inputs)
    assert first.mode.value == "shadow" and first.status is ProcessStatus.WAITING
    original_events = await h.processes.events(first.process_id)

    restarted_store, restarted_processes = _state(db.core), _processes(db.core)
    admissions = StateStoreDecisionEvidenceAdmissionProvider(store=restarted_store)
    approvals = StateStoreWorkflowApprovalProvider(restarted_store)
    orchestrator = WorkflowOrchestrator(
        planner=h.planner,
        action_types=h.actions,
        audit_store=restarted_store,
        process_store=restarted_processes,
        approval_provider=approvals,
        approval_decision_evidence_provider=admissions,
        action_dispatcher=EventBusWorkflowActionDispatcher(h.bus, "test:operator-request"),
    )
    restarted = AlertWorkflowCoordinator(
        **{
            **h.options,
            "store": restarted_store,
            "process_store": restarted_processes,
            "plans": StateStoreAlertPlanReader(store=restarted_store),
            "orchestrator": orchestrator,
        }
    )
    replay = await restarted.resume(process_id=first.process_id)
    assert replay == first
    assert await restarted_processes.events(first.process_id) == original_events
    holds = StateStoreAutomationHoldLedger(restarted_store)
    for target in h.plan.lock_refs:
        await holds.issue(
            target_ref=target, process_id=first.process_id, reason="effect_unconfirmed"
        )
    reopened = StateStoreAutomationHoldLedger(_state(db.core))
    for target in h.plan.lock_refs:
        assert await reopened.is_held(target_ref=target)
        assert not await reopened.recovery_eligible(
            target_ref=target, process_id=first.process_id, step_id="recover_update_routing"
        )
    assert await restarted_processes.get(first.process_id) == await h.processes.get(
        first.process_id
    )
    migration = runpy.run_path(
        str(
            ROOT
            / "service-migrations/branches/core-control-plane/versions"
            / "20260915_core_process_sequence.py"
        )
    )
    with psycopg.connect(db.admin, autocommit=True) as connection:

        def privileges():
            return connection.execute(
                "SELECT has_sequence_privilege('fdai_core', 'process_event_seq_seq', 'USAGE'), "
                "has_sequence_privilege('fdai_core', 'process_event_seq_seq', 'UPDATE'), "
                "has_sequence_privilege('fdai_operator', 'process_event_seq_seq', 'USAGE')"
            ).fetchone()

        assert privileges() == (True, False, False)
        with monkeypatch.context() as patch:
            patch.setattr(migration["op"], "execute", connection.execute)
            migration["downgrade"]()
            assert privileges() == (False, False, False)
            migration["upgrade"]()
            assert privileges() == (True, False, False)

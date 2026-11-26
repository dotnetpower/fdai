"""Bounded failure isolation for authenticated index reconciliation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fdai.agents import ContextIndexMessage, ContextIndexWorkerBindings
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal, Role
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.delivery.catalog_search.ontology_index_lifecycle import IndexScope
from fdai.delivery.catalog_search.ontology_index_workers import (
    IndexPreparationRequest,
    OntologyContextIndexWorkers,
)
from fdai.runtime.ontology_index_runtime import OntologyIndexRuntime
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.catalog_search.test_ontology_generation import _manifest


async def test_fresh_authenticated_query_recovers_expired_unprocessed_ingress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    principal = Principal(id="example-reader", role=Role.READER)
    digest = semantic_principal_scope_digest(principal=principal, purpose="operations-review")
    manifest = _manifest(scope_digest=digest)
    state = InMemoryStateStore()
    gateway = Mock(
        scan_snapshot=AsyncMock(
            return_value=Mock(
                graph=Mock(objects=(), source_generation="source-1"),
                ontology_release_digest=manifest.release_digest,
            )
        )
    )
    coordinator = OntologyIndexRuntime(
        store=state,
        gateway=gateway,
        manifest_for=Mock(return_value=manifest),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    coordinator.workers = Mock(
        query_function=AsyncMock(return_value={}),
        lifecycle=Mock(read=AsyncMock(return_value=Mock(active=None, revision=0))),
        transition_completed=AsyncMock(return_value=True),
        journal=Mock(replay=AsyncMock(return_value=None)),
    )
    publication = AsyncMock()
    monkeypatch.setattr("fdai.runtime.ontology_index_runtime.request_context_index", publication)
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref=principal.id,
        principal_scope_digest=digest,
        purposes=("operations-review",),
    )
    await coordinator.query("example-resource", 1, context)
    scope = next(iter(coordinator._enrollments.values())).scope
    runtime = Mock()
    await coordinator._reconcile_scope(runtime, scope)
    original = publication.await_args.args[1]
    now += timedelta(seconds=121)
    with pytest.raises(ValueError, match="expired"):
        await coordinator._reconcile_scope(runtime, scope)
    assert publication.await_count == 1
    await coordinator.query("example-resource", 1, context)
    await coordinator._reconcile_scope(runtime, scope)
    assert publication.await_count == 2
    renewed = publication.await_args.args[1]
    assert renewed.correlation_id != original.correlation_id
    assert IndexPreparationRequest.model_validate(renewed.body).requested_at == now
    assert state._state[
        f"ontology-index-request:v1:{original.correlation_id}"
    ] == original.model_dump(mode="json")
    await coordinator._reconcile_scope(runtime, scope)
    assert publication.await_args.args[1] == renewed


@pytest.mark.parametrize("drift", ["none", "groups", "role", "expired", "lifetime", "future"])
async def test_enrollment_source_is_resolvable_by_another_worker_replica(
    drift: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    state = InMemoryStateStore()
    principal = Principal(
        id="example-reader", role=Role.READER, groups=frozenset({"example-group"})
    )
    digest = semantic_principal_scope_digest(principal=principal, purpose="operations-review")
    manifest = Mock(principal_role=CeilingRole.READER, purposes=("operations-review",))
    manifest.coverage_receipt.principal_scope_digest = digest
    gateway = Mock()
    options = dict(
        store=state,
        gateway=gateway,
        manifest_for=Mock(return_value=manifest),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    ingress, replica = OntologyIndexRuntime(**options), OntologyIndexRuntime(**options)
    ingress.workers = Mock(query_function=AsyncMock(return_value={}))
    await ingress.query(
        "example-resource",
        1,
        FunctionInvocationContext(
            caller_agent="Bragi",
            principal_ref=principal.id,
            principal_groups=tuple(principal.groups),
            principal_scope_digest=digest,
            purposes=("operations-review",),
        ),
    )
    scope = IndexScope(
        principal_scope_digest=digest, role=CeilingRole.READER, purpose="operations-review"
    )
    key = f"ontology-index-enrollment:v1:{scope.digest}"
    persisted = dict(state._state[key])
    if drift == "groups":
        persisted["principal"] = {**persisted["principal"], "groups": ["example-other-group"]}
    elif drift == "role":
        persisted["principal"] = {**persisted["principal"], "role": Role.OWNER.value}
    elif drift == "expired":
        monkeypatch.setattr(replica, "_clock", lambda: now + timedelta(minutes=5))
    elif drift == "lifetime":
        persisted["expires_at"] = (now + timedelta(minutes=6)).isoformat()
    elif drift == "future":
        persisted.update(
            issued_at=(now + timedelta(seconds=6)).isoformat(),
            expires_at=(now + timedelta(minutes=5, seconds=6)).isoformat(),
        )
    if drift != "none":
        await state.write_state(key, persisted)
        with pytest.raises(PermissionError):
            await replica.source(scope)
        return
    assert await replica.source(scope) == (manifest, gateway)


@pytest.mark.parametrize("changed_claim", ["role", "groups", "purpose", "agent"])
async def test_enrollment_rejects_changed_claims_before_scope_or_query_admission(
    changed_claim: str,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    state = InMemoryStateStore()
    coordinator = OntologyIndexRuntime(
        store=state,
        gateway=Mock(),
        manifest_for=Mock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    workers = Mock(query_function=AsyncMock(return_value={}))
    coordinator.workers = workers
    principal = Principal(id="example-reader", role=Role.READER)
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref=principal.id,
        principal_scope_digest=semantic_principal_scope_digest(
            principal=principal, purpose="operations-review"
        ),
        purposes=("operations-review",),
    )
    changes = {
        "role": {"caller_role": CeilingRole.OWNER},
        "groups": {"principal_groups": ("example-new-group",)},
        "purpose": {"purposes": ("incident-response",)},
        "agent": {"caller_agent": "Thor"},
    }
    with pytest.raises(PermissionError):
        await coordinator.query(
            "example-resource", 1, context.model_copy(update=changes[changed_claim])
        )
    assert not coordinator._enrollments
    assert not state._state
    workers.query_function.assert_not_awaited()


async def test_new_authenticated_enrollment_reclaims_expired_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    coordinator = OntologyIndexRuntime(
        store=InMemoryStateStore(),
        gateway=Mock(),
        manifest_for=Mock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    coordinator.workers = Mock(query_function=AsyncMock(return_value={}))

    async def enroll(index: int) -> None:
        principal = Principal(id=f"example-reader-{index}", role=Role.READER)
        await coordinator.query(
            "example-resource",
            1,
            FunctionInvocationContext(
                caller_agent="Bragi",
                principal_ref=principal.id,
                principal_scope_digest=semantic_principal_scope_digest(
                    principal=principal, purpose="operations-review"
                ),
                purposes=("operations-review",),
            ),
        )

    for index in range(8):
        await enroll(index)
    with pytest.raises(ValueError, match="capacity"):
        await enroll(8)
    monkeypatch.setattr(coordinator, "_clock", lambda: now + timedelta(minutes=5))
    await enroll(8)
    assert len(coordinator._enrollments) == 1
    assert coordinator.workers.release_scope.call_count == 8


async def test_reconciliation_deadline_includes_lock_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    coordinator = OntologyIndexRuntime(
        store=InMemoryStateStore(),
        gateway=Mock(),
        manifest_for=Mock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    coordinator.workers = Mock()
    real_timeout = asyncio.timeout
    monkeypatch.setattr(
        "fdai.runtime.ontology_index_runtime.asyncio.timeout",
        lambda delay: real_timeout(min(delay, 0.01)),
    )
    async with coordinator._lock, real_timeout(0.2):
        with pytest.raises(TimeoutError):
            await coordinator.reconcile(Mock(agents={}))


@pytest.mark.parametrize("duplicate", [False, True])
async def test_owned_preparation_serializes_shared_projection_scope(
    monkeypatch: pytest.MonkeyPatch,
    duplicate: bool,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    workers = OntologyContextIndexWorkers(
        store=InMemoryStateStore(),
        snapshots=Mock(),
        vectors=Mock(),
        reader=Mock(),
        resolve_source=AsyncMock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
        projection_lock=ResourceLockManager(),
    )
    first_entered, second_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def prepare(_request: IndexPreparationRequest) -> object:
        nonlocal calls
        calls += 1
        (first_entered if calls == 1 else second_entered).set()
        await release.wait()
        return Mock(model_dump=Mock(return_value={}))

    monkeypatch.setattr(workers, "_prepare_source", prepare)
    replica = OntologyContextIndexWorkers(
        store=workers._store,
        snapshots=Mock(),
        vectors=Mock(),
        reader=Mock(),
        resolve_source=AsyncMock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
        projection_lock=workers._projection_lock,
    )
    monkeypatch.setattr(replica, "_prepare_source", prepare)
    scope = IndexScope(
        principal_scope_digest="sha256:" + "a" * 64,
        role=CeilingRole.READER,
        purpose="operations-review",
    )
    body = IndexPreparationRequest(
        scope=scope,
        source_generation="source-1",
        expected_revision=0,
        expected_active_digest=None,
        requested_at=now,
    ).model_dump(mode="json")
    async with asyncio.timeout(1):
        first = asyncio.create_task(
            workers.muninn(
                ContextIndexMessage.create(
                    phase="prepare", correlation_id="example-first", body=body
                )
            )
        )
        await first_entered.wait()
        second = asyncio.create_task(
            replica.muninn(
                ContextIndexMessage.create(
                    phase="prepare",
                    correlation_id="example-first" if duplicate else "example-second",
                    body=body,
                )
            )
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(second_entered.wait(), timeout=0.02)
        finally:
            release.set()
            await asyncio.gather(first, second)
    assert calls == (1 if duplicate else 2)


@pytest.mark.parametrize("failure", ["source", "publication"])
async def test_reconciliation_continues_after_independent_scope_or_publication_failure(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    coordinator = OntologyIndexRuntime(
        store=InMemoryStateStore(),
        gateway=Mock(),
        manifest_for=Mock(),
        clock=lambda: now,
        embedding_space_id="example-space",
        embedding_model_version="example-model",
        embedding_dimension=1,
    )
    workers = Mock(
        query_function=AsyncMock(return_value={}),
        bindings=ContextIndexWorkerBindings(
            muninn=AsyncMock(), heimdall=AsyncMock(), saga=AsyncMock()
        ),
    )
    coordinator.workers = workers
    for identifier in ("example-first", "example-second"):
        principal = Principal(id=identifier, role=Role.READER)
        await coordinator.query(
            "example-resource",
            1,
            FunctionInvocationContext(
                caller_agent="Bragi",
                principal_ref=identifier,
                principal_scope_digest=semantic_principal_scope_digest(
                    principal=principal, purpose="operations-review"
                ),
                purposes=("operations-review",),
            ),
        )
    reconcile = AsyncMock(
        side_effect=[ValueError("source unavailable"), None] if failure == "source" else None
    )
    monkeypatch.setattr(coordinator, "_reconcile_scope", reconcile)
    recover = AsyncMock(
        side_effect=RuntimeError("publication unavailable") if failure == "publication" else None
    )
    monkeypatch.setattr(
        "fdai.runtime.ontology_index_runtime.recover_context_index_publications", recover
    )
    with pytest.raises((ValueError, RuntimeError)):
        await coordinator.reconcile(Mock(agents={}))
    assert reconcile.await_count == 2
    if failure == "publication":
        monkeypatch.setattr(coordinator, "_clock", lambda: now + timedelta(minutes=5))
        with pytest.raises(RuntimeError):
            await coordinator.reconcile(Mock(agents={}))
        assert not coordinator._enrollments
        assert workers.release_scope.call_count == 2

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.postgres_test_context import PostgresTestContextOutbox
from fdai_operator_service.test_context_runtime import command_from_record
from fdai_service_contracts.test_context import TestContextRequest


def _record():
    now = datetime(2026, 9, 15, tzinfo=UTC)
    body = {
        "operation": "propose",
        "context_id": "example",
        "access_scope_digest": "a" * 64,
        "target_ref": "resource-example",
        "signal_code": "cpu_percent",
        "expected_revision": 0,
        "policy_revision": "policy:example",
        "source_ref": "turn:example",
        "semantic_receipt": "sha256:" + "b" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": now.isoformat(),
        "effective_to": (now + timedelta(hours=1)).isoformat(),
    }
    return {
        "operation": "test-context.propose",
        "principal_id": "operator-one",
        "idempotency_key": "request-one",
        "accepted_at": now.isoformat(),
        "payload": {
            "operation": "test-context.propose",
            "idempotency_key": "request-one",
            "scope": {
                "subject_id": "operator-one",
                "roles": ["Contributor"],
                "principal_kind": "human",
            },
            "body": body,
        },
    }


def _context_lifecycle_request(operation: str, *, expected_revision: int) -> dict[str, object]:
    request = dict(_record()["payload"]["body"])
    for key in ("expected_min", "expected_max", "effective_from", "effective_to"):
        request.pop(key)
    request.update(operation=operation, expected_revision=expected_revision)
    return request


def test_outbox_uses_authenticated_principal_and_original_request_time():
    command = command_from_record(_record())
    assert command.actor_id == "operator-one"
    assert command.actor_roles == ("Contributor",)
    assert command.execution_authority is False


@pytest.mark.parametrize("field_name", ["expected_min", "expected_max"])
@pytest.mark.parametrize("value", [True, False, "60", float("nan"), float("inf")])
def test_context_bounds_never_coerce_boolean_or_nonfinite_measurements(field_name, value):
    record = _record()
    record["payload"]["body"][field_name] = value
    with pytest.raises(ValueError):
        command_from_record(record)


@pytest.mark.parametrize("mutation", ["actor", "role", "operation", "idempotency", "body-actor"])
def test_outbox_rejects_command_identity_substitution(mutation):
    record = _record()
    if mutation == "actor":
        record["principal_id"] = "other"
    elif mutation == "role":
        record["payload"]["scope"]["roles"] = ["Reader"]
    elif mutation == "operation":
        record["operation"] = "test-context.review"
    elif mutation == "idempotency":
        record["idempotency_key"] = "other"
    else:
        record["payload"]["body"]["actor_id"] = "other"
    with pytest.raises(ValueError):
        command_from_record(record)


async def test_context_outbox_publishes_then_marks_the_exact_claim():
    from unittest.mock import AsyncMock

    from fdai_operator_service.test_context_runtime import TestContextBridge

    record = {**_record(), "proposal_id": "proposal-example", "attempt": 1}
    store = AsyncMock()
    store._fetch_all.return_value = [{"key": "outbox-example", "value": record}]
    store.mark_proposal_published.return_value = True
    publisher = AsyncMock()
    bridge = TestContextBridge(store=store, publisher=publisher, topic="fdai.events")
    assert await bridge.run_once()
    args = publisher.publish.await_args.args
    assert args[0] == "fdai.events"
    assert args[2]["attributes"]["actor_id"] == "operator-one"
    assert args[2]["event_type"] == "test_context.command.v1"
    store.mark_proposal_published.assert_awaited_once()
    store.release_proposal_claim.assert_not_awaited()


@pytest.mark.parametrize("error", [ConnectionError, ValueError, TypeError, TimeoutError])
async def test_context_outbox_transport_failure_retains_retryable_claim(error):
    from unittest.mock import AsyncMock

    from fdai_operator_service.test_context_runtime import TestContextBridge

    store = AsyncMock()
    store._fetch_all.return_value = [
        {
            "key": "outbox-example",
            "value": {**_record(), "proposal_id": "proposal-example", "attempt": 1},
        }
    ]
    publisher = AsyncMock()
    publisher.publish.side_effect = error("synthetic transport failure")
    assert not await TestContextBridge(
        store=store, publisher=publisher, topic="fdai.events"
    ).run_once()
    store.release_proposal_claim.assert_awaited_once()
    store.mark_proposal_published.assert_not_awaited()
    store.mark_proposal_rejected.assert_not_awaited()


@pytest.mark.parametrize("failure", ["unready", "invalid", "cancelled", "storage"])
async def test_result_consumer_failure_keeps_offset_and_clears_readiness(failure):
    import asyncio
    from unittest.mock import AsyncMock

    from fdai_operator_service.test_context_runtime import TestContextBridge

    class _Source:
        closed = False
        committed = False

        async def probe_readiness(self):
            return failure != "unready"

        async def subscribe(self, *_args):
            try:
                yield {"execution_authority": True}
                self.committed = True
            finally:
                self.closed = True

    source = _Source()
    bridge = TestContextBridge(
        store=AsyncMock(), publisher=AsyncMock(), topic="fdai.events", source=source
    )
    if failure in {"cancelled", "storage"}:
        bridge.consume = AsyncMock(
            side_effect=asyncio.CancelledError if failure == "cancelled" else OSError
        )
    expected = (
        asyncio.CancelledError
        if failure == "cancelled"
        else OSError
        if failure == "storage"
        else RuntimeError
        if failure == "unready"
        else ValueError
    )
    with pytest.raises(expected):
        await bridge._consume()
    assert not source.committed
    assert source.closed is (failure != "unready")
    assert not bridge.workers_ready() and not bridge._results_ready


def test_command_digest_is_stable_across_role_order_and_timezone():
    from fdai_service_contracts.ontology_query import content_digest

    first = _record()
    first["payload"]["scope"]["roles"] = ["Owner", "Contributor"]
    second = _record()
    second["payload"]["scope"]["roles"] = ["Contributor", "Owner"]
    second["accepted_at"] = "2026-09-15T09:00:00+09:00"
    assert content_digest(command_from_record(first).model_dump(mode="json")) == content_digest(
        command_from_record(second).model_dump(mode="json")
    )
    second["payload"]["scope"].pop("principal_kind")
    with pytest.raises(ValueError, match="human principal"):
        command_from_record(second)


async def test_result_consumer_probe_has_deadline_and_propagates_cancellation(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from fdai_operator_service.test_context_runtime import TestContextBridge

    timeout = asyncio.timeout
    requested = []

    def immediate_timeout(seconds):
        requested.append(seconds)
        return timeout(0)

    source = AsyncMock()

    async def stalled():
        await asyncio.Future()

    source.probe_readiness.side_effect = stalled
    bridge = TestContextBridge(
        store=AsyncMock(), publisher=AsyncMock(), topic="fdai.events", source=source
    )
    monkeypatch.setattr(asyncio, "timeout", immediate_timeout)
    with pytest.raises(TimeoutError):
        await bridge._consume()
    assert requested == [5] and not bridge._results_ready
    source.subscribe.assert_not_called()
    source.probe_readiness.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await bridge._consume()


async def test_explicit_start_recovers_terminal_workers_without_duplicate_live_tasks(caplog):
    import asyncio
    from unittest.mock import AsyncMock

    from fdai_operator_service.test_context_runtime import TestContextBridge

    bridge = TestContextBridge(
        store=AsyncMock(), publisher=AsyncMock(), topic="fdai.events", source=AsyncMock()
    )
    bridge._run = AsyncMock(side_effect=OSError("redacted source failure"))
    bridge._consume = AsyncMock(side_effect=ValueError("redacted invalid projection"))
    await bridge.start()
    first = (bridge._task, bridge._result_task)
    await asyncio.gather(*first, return_exceptions=True)
    assert not bridge.workers_ready()

    started = asyncio.Event()

    async def active():
        started.set()
        await asyncio.Future()

    bridge._run = active
    bridge._consume = active
    await bridge.start()
    await started.wait()
    second = (bridge._task, bridge._result_task)
    assert all(old is not new for old, new in zip(first, second, strict=True))
    await bridge.start()
    assert (bridge._task, bridge._result_task) == second
    await bridge.aclose()
    assert not bridge.workers_ready()
    assert "redacted" not in caplog.text
    assert sum(record.message == "test_context_worker_stopped" for record in caplog.records) == 2


@pytest.mark.integration
async def test_context_outbox_real_postgres_replay_claim_and_lease_recovery():
    import asyncio
    import os
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import psycopg
    from fdai_operator_service.postgres_family_store import (
        PostgresFamilyStore,
        PostgresFamilyStoreConfig,
    )
    from fdai_operator_service.test_context_runtime import TestContextBridge
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    dsn = os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    assert conninfo_to_dict(dsn).get("host") in {"127.0.0.1", "localhost", "::1"}
    schema = "context_outbox_test_" + uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema} -c statement_timeout=5000")
    try:
        async with await psycopg.AsyncConnection.connect(scoped_dsn) as connection:
            await connection.execute(
                "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
        store = PostgresFamilyStore(PostgresFamilyStoreConfig(scoped_dsn))
        record = _record()
        kwargs = {
            "family": "conversation",
            "operation": record["operation"],
            "principal_id": record["principal_id"],
            "idempotency_key": record["idempotency_key"],
            "payload": record["payload"],
        }
        original = await store.append_proposal(**kwargs)
        assert (
            await PostgresTestContextOutbox(store).read_test_context_command(
                proposal_id=original.proposal_id,
                principal_id="other-operator",
            )
            is None
        )
        pending = await PostgresTestContextOutbox(store).read_test_context_command(
            proposal_id=original.proposal_id,
            principal_id=record["principal_id"],
        )
        assert pending["dispatch_status"] == "pending"
        assert "payload" not in pending and "principal_id" not in pending
        replay = await store.append_proposal(**kwargs)
        assert replay.duplicate and replay.accepted_at == original.accepted_at
        await store.append_proposal(
            **{**kwargs, "operation": "chat.post", "idempotency_key": "unrelated"}
        )
        publisher = AsyncMock()
        first = TestContextBridge(store=store, publisher=publisher, topic="fdai.events")
        second = TestContextBridge(store=store, publisher=publisher, topic="fdai.events")
        assert sorted(await asyncio.gather(first.run_once(), second.run_once())) == [False, True]
        publisher.publish.assert_awaited_once()
        command = publisher.publish.await_args.args[2]["attributes"]
        assert datetime.fromisoformat(command["requested_at"]) == datetime.fromisoformat(
            original.accepted_at
        )
        async with await psycopg.AsyncConnection.connect(scoped_dsn) as connection:
            cursor = await connection.execute(
                "SELECT value->>'dispatch_status' FROM state_kv "
                "WHERE value->>'operation'='chat.post'"
            )
            assert await cursor.fetchone() == ("pending",)
            await connection.execute(
                "UPDATE state_kv SET value=value || jsonb_build_object("
                "'dispatch_status','claimed','claim_id','lost-worker',"
                "'claim_expires_at',NOW()-interval '1 second') "
                "WHERE value->>'operation'='test-context.propose'"
            )
        assert await first.run_once()
        assert publisher.publish.await_count == 2
        assert publisher.publish.await_args_list[0] == publisher.publish.await_args_list[1]
        assert not await first.run_once()
        published = await PostgresTestContextOutbox(store).read_test_context_command(
            proposal_id=original.proposal_id,
            principal_id=record["principal_id"],
        )
        assert published["dispatch_status"] == "published"
        from fdai_service_contracts.ontology_query import content_digest
        from fdai_service_contracts.test_context import TestContextApplication

        application = TestContextApplication(
            command_digest=content_digest(command),
            actor_id=record["principal_id"],
            request_key=record["idempotency_key"],
            context_id=command["request"]["context_id"],
            access_scope_digest=command["request"]["access_scope_digest"],
            target_ref=command["request"]["target_ref"],
            policy_revision=command["request"]["policy_revision"],
            revision=1,
            state="proposed",
            context_digest="sha256:" + "c" * 64,
        )
        await first.consume(application.model_dump(mode="json"))
        await second.consume(application.model_dump(mode="json"))
        applied = await PostgresTestContextOutbox(store).read_test_context_command(
            proposal_id=original.proposal_id, principal_id=record["principal_id"]
        )
        assert applied["context_application"] == application.model_dump(mode="json")
        for change in (
            {"context_digest": "sha256:" + "d" * 64},
            {"revision": 2},
            {"target_ref": "other"},
            {"state": "reviewed"},
        ):
            with pytest.raises(ValueError):
                await first.consume(application.model_copy(update=change).model_dump(mode="json"))
        with pytest.raises(LookupError):
            await first.consume(
                application.model_copy(update={"actor_id": "other"}).model_dump(mode="json")
            )
        from fdai_operator_service.families.conversation.contracts import (
            ConversationQuery,
            PrincipalScope,
        )
        from fdai_operator_service.family_adapters import PostgresConversationAdapters

        response = await PostgresConversationAdapters(store).read(
            ConversationQuery(
                operation="test-context.command-status",
                scope=PrincipalScope(record["principal_id"]),
                path_params={"proposal_id": original.proposal_id},
            )
        )
        assert response.body["policy_application"] == "recorded"
        assert response.body["current_authorization"] == "not_evaluated"
        assert "actor_id" not in response.body["context_application"]
    finally:
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=5) as connection:
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s", (schema,)
            )
            assert await cursor.fetchone() == (0,)


def _current_window() -> tuple[datetime, datetime]:
    """Return a validity window around the wall clock at which the choice source evaluates.

    A current window spans the present, and the expired and pending windows lie wholly before
    or after it, so no fixed date can turn a pending grant current or a current grant expired.
    """

    now = datetime.now(UTC).replace(microsecond=0)
    return now - timedelta(days=180), now + timedelta(days=185)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _choice_registry(
    *,
    duplicate_scope: bool = False,
    command_revoked: bool = False,
    transition_revoked: bool = False,
    transition_expired: bool = False,
    transition_not_yet_valid: bool = False,
    case_history_only: bool = False,
) -> str:
    import json

    start, end = _current_window()
    stamp = _stamp

    def grant(
        grant_id: str,
        *,
        operation: str,
        purpose: str,
        role: str = "Contributor",
        revoked: bool = False,
        expired: bool = False,
        not_yet_valid: bool = False,
    ) -> dict[str, object]:
        return {
            "grant_id": grant_id,
            "selector": {"kind": "app_role", "value": role},
            "case_scopes": ["case-one"],
            "operations": [operation],
            "purposes": [purpose],
            "reviewer": "reviewer-example",
            "valid_from": stamp(end - timedelta(days=1) if not_yet_valid else start),
            "valid_until": stamp(start + timedelta(days=1) if expired else end),
            "revoked": revoked,
        }

    scope = {
        "case_scope_id": "case-one",
        "access_scope_digest": "a" * 64,
        "resource_selectors": ["resource-example"],
        "purposes": ["case-history-read"]
        if case_history_only
        else ["operator-test-context-command", "test-context-transition"],
        "policy_revision": "policy:example",
        "valid_from": stamp(start),
        "valid_until": stamp(end),
        "revoked": False,
    }
    grants = [
        grant(
            "grant-command",
            operation="test-context.propose",
            purpose="operator-test-context-command",
            revoked=command_revoked,
        ),
        grant(
            "grant-propose-transition",
            operation="test-context.propose",
            purpose="test-context-transition",
            revoked=transition_revoked,
            expired=transition_expired,
            not_yet_valid=transition_not_yet_valid,
        ),
        grant(
            "grant-review",
            operation="test-context.review",
            purpose="test-context-transition",
            role="Approver",
        ),
        grant(
            "grant-revoke",
            operation="test-context.revoke",
            purpose="test-context-transition",
            role="Approver",
        ),
    ]
    if case_history_only:
        grants = [
            grant("grant-history", operation="case-history.read", purpose="case-history-read")
        ]
    scopes = [scope, {**scope, "case_scope_id": "case-two"}] if duplicate_scope else [scope]
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "registry_id": "fdai.operational-evidence.case-scope-grants",
            "revision": 7,
            "case_scopes": scopes,
            "principal_grants": grants,
            "reuse_grants": [],
        },
        separators=(",", ":"),
    )


def _transition_only_registry() -> str:
    import json

    document = json.loads(_choice_registry())
    document["principal_grants"] = [
        grant
        for grant in document["principal_grants"]
        if grant["selector"]["value"] == "Approver"
        and grant["purposes"] == ["test-context-transition"]
    ]
    return json.dumps(document, separators=(",", ":"))


def _many_scope_registry(count: int = 129) -> str:
    import json

    start, end = (_stamp(value) for value in _current_window())
    scopes = []
    case_scope_ids = []
    for index in range(count):
        scope_id = f"case-{index:03d}"
        case_scope_ids.append(scope_id)
        scopes.append(
            {
                "case_scope_id": scope_id,
                "access_scope_digest": f"{index + 1:064x}",
                "resource_selectors": [f"resource-{index:03d}"],
                "purposes": ["operator-test-context-command", "test-context-transition"],
                "policy_revision": "policy:example",
                "valid_from": start,
                "valid_until": end,
                "revoked": False,
            }
        )
    grants = []
    for batch, start_index in enumerate(range(0, count, 64)):
        scope_batch = case_scope_ids[start_index : start_index + 64]
        grants.extend(
            [
                {
                    "grant_id": f"grant-command-{batch}",
                    "selector": {"kind": "app_role", "value": "Contributor"},
                    "case_scopes": scope_batch,
                    "operations": ["test-context.propose"],
                    "purposes": ["operator-test-context-command"],
                    "reviewer": "reviewer-example",
                    "valid_from": start,
                    "valid_until": end,
                    "revoked": False,
                },
                {
                    "grant_id": f"grant-transition-{batch}",
                    "selector": {"kind": "app_role", "value": "Contributor"},
                    "case_scopes": scope_batch,
                    "operations": ["test-context.propose"],
                    "purposes": ["test-context-transition"],
                    "reviewer": "reviewer-example",
                    "valid_from": start,
                    "valid_until": end,
                    "revoked": False,
                },
            ]
        )
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "registry_id": "fdai.operational-evidence.case-scope-grants",
            "revision": 8,
            "case_scopes": scopes,
            "principal_grants": grants,
            "reuse_grants": [],
        },
        separators=(",", ":"),
    )


async def test_context_choices_are_principal_scoped_and_source_revisioned():
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    adapter = PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(_choice_registry()),
    )
    allowed = await adapter.read(
        ConversationQuery(
            operation="test-context.choices",
            scope=PrincipalScope("operator-one", roles=frozenset({"Contributor"})),
        )
    )
    denied = await adapter.read(
        ConversationQuery(
            operation="test-context.choices",
            scope=PrincipalScope("operator-two", roles=frozenset({"Reader"})),
        )
    )
    assert allowed.body["source_revision"].startswith("sha256:")
    assert allowed.body["choices"] == [
        {
            "case_scope_id": "case-one",
            "access_scope_digest": "a" * 64,
            "target_selectors": ["resource-example"],
            "policy_revision": "policy:example",
            "source_revision": allowed.body["source_revision"],
            "allowed_operations": ["propose"],
            "execution_authority": False,
        }
    ]
    assert denied.body["choices"] == []
    assert "grant_missing" in denied.body["unavailable_reasons"]


async def test_approver_transition_only_grant_does_not_match_core_review_admission() -> None:
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    source = TestContextChoiceSource.from_json_text(_transition_only_registry())
    query = ConversationQuery(
        operation="test-context.choices",
        scope=PrincipalScope("approver-one", roles=frozenset({"Approver"})),
    )
    response = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=source,
    ).read(query)
    assert response.body["choices"] == []
    assert (
        source.may_transition(
            query.scope,
            TestContextRequest.model_validate(
                _context_lifecycle_request("review", expected_revision=1)
            ),
        )
        is False
    )


async def test_context_choices_match_core_grant_admission_for_proposal() -> None:
    from fdai.core.operational_evidence.grant_registry_loader import load_grant_registry
    from fdai.core.operational_evidence.registry_json import content_pin
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    query = ConversationQuery(
        operation="test-context.choices",
        scope=PrincipalScope("operator-one", roles=frozenset({"Contributor"})),
    )
    for text, allowed in (
        (_choice_registry(), True),
        (_choice_registry(transition_revoked=True), False),
        (_choice_registry(transition_expired=True), False),
        (_choice_registry(transition_not_yet_valid=True), False),
    ):
        data = text.encode("utf-8")
        core = load_grant_registry(data, expected_pin=content_pin(data))
        assert bool(core.case_scopes)
        response = await PostgresConversationAdapters(
            None,  # type: ignore[arg-type]
            test_context_choices=TestContextChoiceSource.from_json_text(text),
        ).read(query)
        assert bool(response.body["choices"]) is allowed


async def test_context_choices_fail_closed_on_ambiguous_or_invalid_registry():
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    query = ConversationQuery(
        operation="test-context.choices",
        scope=PrincipalScope("operator-one", roles=frozenset({"Contributor"})),
    )
    ambiguous = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(
            _choice_registry(duplicate_scope=True)
        ),
    ).read(query)
    expired_transition = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(
            _choice_registry(transition_expired=True)
        ),
    ).read(query)
    future_transition = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(
            _choice_registry(transition_not_yet_valid=True)
        ),
    ).read(query)
    revoked_transition = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(
            _choice_registry(transition_revoked=True)
        ),
    ).read(query)
    case_history_only = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(
            _choice_registry(case_history_only=True)
        ),
    ).read(query)
    invalid = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text("{}"),
    ).read(query)
    assert ambiguous.body["choices"] == []
    assert ambiguous.body["unavailable_reasons"] == ["grant_registry_invalid"]
    assert expired_transition.body["choices"] == []
    assert expired_transition.body["unavailable_reasons"]
    assert future_transition.body["choices"] == []
    assert "grant_missing" in future_transition.body["unavailable_reasons"]
    assert revoked_transition.body["choices"] == []
    assert "grant_revoked" in revoked_transition.body["unavailable_reasons"]
    assert case_history_only.body["choices"] == []
    assert case_history_only.body["unavailable_reasons"] == ["no_test_context_scope"]
    assert invalid.body["choices"] == []
    assert invalid.body["unavailable_reasons"] == ["grant_registry_invalid"]


async def test_context_choices_bound_more_than_projection_limit_without_truncation() -> None:
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    response = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(_many_scope_registry()),
    ).read(
        ConversationQuery(
            operation="test-context.choices",
            scope=PrincipalScope("operator-one", roles=frozenset({"Contributor"})),
        )
    )
    assert response.body["choices"] == []
    assert response.body["unavailable_reasons"] == ["principal_scope_too_large"]


async def test_context_choices_bound_oversized_principal_scope_without_500() -> None:
    from fdai_operator_service.families.conversation.contracts import (
        ConversationQuery,
        PrincipalScope,
    )
    from fdai_operator_service.family_adapters import PostgresConversationAdapters
    from fdai_operator_service.test_context_choices import TestContextChoiceSource

    roles = frozenset({"Contributor", "Approver", "Owner", "Reader", "R1", "R2", "R3", "R4", "R5"})
    response = await PostgresConversationAdapters(
        None,  # type: ignore[arg-type]
        test_context_choices=TestContextChoiceSource.from_json_text(_choice_registry()),
    ).read(
        ConversationQuery(
            operation="test-context.choices",
            scope=PrincipalScope("operator-one", roles=roles),
        )
    )
    assert response.body["choices"] == []
    assert response.body["unavailable_reasons"] == ["principal_scope_too_large"]

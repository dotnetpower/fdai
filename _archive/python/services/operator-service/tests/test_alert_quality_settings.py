"""Offline scoped preference/CAS and HTTP regressions with explicit test-only stores.

No fixture represents PostgreSQL, Entra, transport or provider-readiness evidence.
The tests exercise the real preference adapter and routes without a runtime bridge.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from fdai_operator_service.alert_quality import (
    MAX_ALERT_QUALITY_BODY_BYTES,
    AlertQualityDependencies,
    alert_quality_dependencies_from_environment,
    build_alert_quality_routes,
)
from fdai_operator_service.alert_quality_settings import (
    ALERT_QUALITY_PREFERENCE_PREFIX,
    MAX_ALERT_QUALITY_REVISION,
    AlertQualityPreference,
    AlertQualityPreferenceConflictError,
    AlertQualitySettingsResponse,
    StateKvAlertQualityPreferenceStore,
)
from fdai_operator_service.alert_quality_store import (
    AlertQualitySnapshot,
    AlertQualityUnavailableError,
    alert_quality_binding_digest,
    alert_quality_requester_ref,
)
from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator
from fdai_operator_service.families.operations.contracts import EventProposal, ProposalReceipt
from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from pydantic import ValidationError
from starlette.applications import Starlette

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
SCOPE = "scope:one"
PRINCIPAL = "operator-subject-one"
OTHER_PRINCIPAL = "operator-subject-two"
SETTINGS = "/alert-quality/settings"
READ = f"/alert-quality?scope_ref={SCOPE}"
OWNER = {"Authorization": "Bearer owner"}
REQUEST = {"Authorization": "Bearer contributor", "Idempotency-Key": "request-one"}


class _State:
    """Test-only insert-if-absent implementation with observable, narrow read keys."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.reads: list[str] = []
        self.finds: list[str] = []
        self.creates: list[str] = []

    async def read_state(self, key: str) -> dict[str, object] | None:
        self.reads.append(key)
        return copy.deepcopy(self.records.get(key))

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        self.creates.append(key)
        if key in self.records:
            return False
        self.records[key] = copy.deepcopy(dict(value))
        return True

    async def find_state(self, *, prefix: str, field: str, value: str) -> dict[str, object] | None:
        self.finds.append(prefix)
        values = [
            record
            for key, record in self.records.items()
            if key.startswith(prefix) and record.get(field) == value
        ]
        return copy.deepcopy(values[-1]) if values else None


class _Writer:
    """An explicitly injected test-only inert proposal recorder, not a live outbox."""

    def __init__(self) -> None:
        self.proposals: list[EventProposal] = []

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        self.proposals.append(proposal)
        return ProposalReceipt(
            request_id="private-request",
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at=NOW.isoformat(),
            durably_queued=True,
        )


class _Source:
    """Synthetic scoped report source; settings reads must never invoke this reader."""

    def __init__(self) -> None:
        self.reads: list[str] = []

    async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot:
        self.reads.append(scope_ref)
        return AlertQualitySnapshot(
            binding_digest=alert_quality_binding_digest(principal_id, scope_ref),
            assessment=NoiseAssessment(
                evidence_digest="sha256:" + "a" * 64,
                policy_digest="sha256:" + "b" * 64,
                tenant_ref="tenant:example",
                scope_ref=scope_ref,
                observed_at=NOW - timedelta(minutes=1),
                valid_until=NOW + timedelta(hours=1),
                coverage="partial",
                reasons=("delivery-unavailable",),
                source_episodes=None,
                notification_attempts=None,
                confirmed_deliveries=None,
                acknowledgements=None,
                findings=(),
            ),
        )


def _verify(token: str) -> Mapping[str, object]:
    roles = {
        "reader": "Reader",
        "contributor": "Contributor",
        "approver": "Approver",
        "owner": "Owner",
        "other": "Owner",
        "breakglass": "BreakGlass",
    }
    if token not in roles:
        raise AuthenticationError("private identity detail")
    return {
        "oid": OTHER_PRINCIPAL if token == "other" else PRINCIPAL,
        "roles": [roles[token]],
        "idtyp": "user",
    }


async def _ready() -> bool:
    return True


def _harness(state: _State | None = None) -> tuple[_State, _Writer, AlertQualityDependencies]:
    state = _State() if state is None else state
    writer = _Writer()
    return (
        state,
        writer,
        AlertQualityDependencies(
            authenticator=OperatorAuthenticator(verifier=_verify, group_ids={}),
            principal_scopes={
                PRINCIPAL: frozenset({SCOPE, "scope:two"}),
                OTHER_PRINCIPAL: frozenset({SCOPE}),
            },
            source=_Source(),
            proposal_writer=writer,
            producer_ready=_ready,
            clock=lambda: NOW,
            preference_store=StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW),
        ),
    )


def _client(dependencies: AlertQualityDependencies) -> httpx.AsyncClient:
    app = Starlette(routes=list(build_alert_quality_routes(dependencies)))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _body(enabled: bool = False, revision: int = 0) -> dict[str, object]:
    return {"scope_ref": SCOPE, "enabled": enabled, "expected_revision": revision}


async def _save(
    store: StateKvAlertQualityPreferenceStore, revision: int = 0, enabled: bool = False
) -> AlertQualityPreference:
    return await store.set_enabled(
        scope_ref=SCOPE,
        enabled=enabled,
        expected_revision=revision,
        requester_ref=alert_quality_requester_ref(PRINCIPAL, SCOPE),
        before_commit=lambda: None,
    )


async def test_default_settings_are_explicit_unsaved_preferences_not_fabricated_state() -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
    assert response.status_code == 200
    assert response.json() == {
        "source": "alert-noise-governance",
        "scope_ref": SCOPE,
        "available": True,
        "enabled": True,
        "mode": "shadow",
        "execution_authority": False,
        "prerequisites": {
            "source_bound": True,
            "writer_bound": True,
            "producer_ready": True,
            "preference_store_available": True,
        },
        "unavailable_reason": None,
        "preference_state": "default",
        "revision": 0,
        "recorded_at": None,
    }
    assert response.headers["etag"] == '"0"' and response.headers["cache-control"] == "no-store"
    assert not state.creates and not writer.proposals
    assert not cast(_Source, dependencies.source).reads
    assert len(state.finds) == 1 and len(state.reads) == 1


@pytest.mark.parametrize(
    "missing,reason",
    [
        ("source", "source_unavailable"),
        ("proposal_writer", "writer_unavailable"),
        ("producer_ready", "producer_not_ready"),
        ("preference_store", "preference_store_unavailable"),
    ],
)
async def test_settings_prerequisites_do_not_imply_a_report_or_execution(
    missing: str, reason: str
) -> None:
    state, _, dependencies = _harness()
    dependencies = replace(dependencies, **{missing: None})
    async with _client(dependencies) as client:
        response = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
    body = AlertQualitySettingsResponse.model_validate_json(response.text, strict=True)
    assert body.available is False and body.unavailable_reason == reason
    assert body.mode == "shadow" and body.execution_authority is False
    assert body.recorded_at is None and not state.creates
    if missing == "preference_store":
        assert (
            body.preference_state == "unavailable"
            and body.enabled is None
            and body.revision is None
        )
        assert "etag" not in response.headers


@pytest.mark.parametrize(
    "token,read_status,write_status",
    [
        ("reader", 200, 403),
        ("contributor", 200, 403),
        ("approver", 200, 403),
        ("owner", 200, 200),
        ("breakglass", 403, 403),
        ("invalid", 401, 401),
    ],
)
async def test_settings_use_current_read_roles_and_human_owner_only_writes(
    token: str, read_status: int, write_status: int
) -> None:
    state, writer, dependencies = _harness()
    headers = {"Authorization": f"Bearer {token}", "X-Operator-Role": "Owner"}
    async with _client(dependencies) as client:
        read = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=headers)
        write = await client.put(SETTINGS, json=_body(), headers=headers)
    assert read.status_code == read_status and write.status_code == write_status
    assert len(state.creates) == (1 if write_status == 200 else 0)
    assert read.headers["cache-control"] == write.headers["cache-control"] == "no-store"
    assert not writer.proposals


async def test_settings_commit_one_immutable_audit_record_before_response_and_survive_restart() -> (
    None
):
    state, writer, dependencies = _harness()
    state.records["action_promotion:example"] = {"mode": "enforce"}
    state.records["operator-proposal:approved-example"] = {"status": "approved"}
    unrelated = copy.deepcopy(state.records)
    async with _client(dependencies) as client:
        saved = await client.put(SETTINGS, json=_body(), headers=OWNER)
    assert saved.status_code == 200 and saved.headers["etag"] == '"1"'
    assert saved.json()["enabled"] is False and saved.json()["mode"] == "shadow"
    assert saved.json()["preference_state"] == "recorded"
    assert saved.json()["recorded_at"] == "2026-09-14T12:00:00Z"
    assert len(state.creates) == 1 and state.reads[-1] == state.creates[0]
    record = state.records[state.creates[0]]
    assert record == {
        "kind": "operator.alert-quality.preference",
        "scope_ref": SCOPE,
        "revision": 1,
        "expected_revision": 0,
        "previous_digest": None,
        "enabled": False,
        "recorded_at": "2026-09-14T12:00:00Z",
        "requester_ref": alert_quality_requester_ref(PRINCIPAL, SCOPE),
        "execution_authority": False,
    }
    restarted = replace(
        dependencies, preference_store=StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW)
    )
    async with _client(restarted) as client:
        restored = await client.get(
            SETTINGS, params={"scope_ref": SCOPE}, headers={"Authorization": "Bearer other"}
        )
    assert restored.json() == saved.json()
    assert {key: state.records[key] for key in unrelated} == unrelated
    assert PRINCIPAL not in json.dumps(record) and PRINCIPAL not in saved.text
    assert "requester_ref" not in saved.json() and not writer.proposals


async def test_two_owners_share_one_scoped_revision_and_stale_put_is_a_conflict() -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        first = await client.put(SETTINGS, json=_body(), headers=OWNER)
        before = copy.deepcopy(state.records)
        stale = await client.put(
            SETTINGS, json=_body(True), headers={"Authorization": "Bearer other"}
        )
        duplicate = await client.put(SETTINGS, json=_body(), headers=OWNER)
        assert state.records == before
        second = await client.put(
            SETTINGS, json=_body(True, 1), headers={"Authorization": "Bearer other"}
        )
    assert first.status_code == second.status_code == 200
    assert stale.status_code == duplicate.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    records = [
        AlertQualityPreference.model_validate_json(json.dumps(state.records[key]))
        for key in state.creates
    ]
    assert len(records) == 2 and records[0].enabled is False and records[1].enabled is True
    assert records[1].previous_digest == digest_record(records[0])
    assert records[1].requester_ref == alert_quality_requester_ref(OTHER_PRINCIPAL, SCOPE)
    assert all(key.startswith(ALERT_QUALITY_PREFERENCE_PREFIX) for key in state.records)


@pytest.mark.parametrize("tag", ['"0"', "0"])
async def test_if_match_is_an_alternative_to_body_revision(tag: str) -> None:
    _, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.put(
            SETTINGS,
            json={"scope_ref": SCOPE, "enabled": False},
            headers={**OWNER, "If-Match": tag},
        )
    assert response.status_code == 200 and response.json()["revision"] == 1


@pytest.mark.parametrize(
    "tag",
    [
        "*",
        'W/"0"',
        '"0", "1"',
        "01",
        "-1",
        "1.0",
        "true",
        '" 0 "',
        '"0',
        str(MAX_ALERT_QUALITY_REVISION),
    ],
)
async def test_if_match_rejects_unbounded_weak_multiple_or_normalized_revisions(tag: str) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.put(
            SETTINGS,
            json={"scope_ref": SCOPE, "enabled": False},
            headers={**OWNER, "If-Match": tag},
        )
    assert response.status_code == 400 and not state.finds and not state.creates


async def test_missing_duplicate_or_competing_preconditions_never_read_or_write() -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        missing = await client.put(
            SETTINGS, json={"scope_ref": SCOPE, "enabled": False}, headers=OWNER
        )
        both = await client.put(SETTINGS, json=_body(), headers={**OWNER, "If-Match": '"0"'})
        duplicate = await client.put(
            SETTINGS,
            json={"scope_ref": SCOPE, "enabled": False},
            headers=[("Authorization", "Bearer owner"), ("If-Match", '"0"'), ("If-Match", '"0"')],
        )
    assert missing.status_code == 428 and missing.json()["error"]["code"] == "precondition_required"
    assert both.status_code == duplicate.status_code == 400
    assert not state.finds and not state.reads and not state.creates


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": 1},
        {"enabled": "false"},
        {"enabled": None},
        {"expected_revision": True},
        {"expected_revision": "0"},
        {"expected_revision": 0.0},
        {"expected_revision": -1},
        {"expected_revision": None},
        {"expected_revision": MAX_ALERT_QUALITY_REVISION},
        {"scope_ref": " scope:one "},
        {"scope_ref": "scope:one\n"},
        {"scope_ref": "*"},
        {"mode": "enforce"},
        {"authority": "enforce"},
        {"execution_authority": True},
        {"principal_id": OTHER_PRINCIPAL},
        {"requester_ref": "principal:caller"},
        {"scopes": []},
        {"revision": 1},
        {"prerequisites": {}},
        {"recorded_at": NOW.isoformat()},
    ],
)
async def test_put_accepts_only_strict_enabled_scope_and_revision(
    change: dict[str, object],
) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.put(SETTINGS, json={**_body(), **change}, headers=OWNER)
    assert response.status_code == 400 and not state.finds and not state.creates
    assert PRINCIPAL not in response.text and OTHER_PRINCIPAL not in response.text


@pytest.mark.parametrize(
    "raw",
    [
        b'{"scope_ref":"scope:one","enabled":true,"enabled":false,"expected_revision":0}',
        b'{"scope_ref":"scope:one","enabled":false,"expected_revision":0,"expected_revision":1}',
        b'{"scope_ref":"scope:one","scope_ref":"scope:two","enabled":false,"expected_revision":0}',
        b'{"scope_ref":"scope:one","enabled":NaN,"expected_revision":0}',
        b"null",
        b"[]",
        b"{}",
        b"{",
        b"\xff",
    ],
)
async def test_settings_reject_duplicate_members_and_invalid_json(raw: bytes) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.put(
            SETTINGS, content=raw, headers={**OWNER, "Content-Type": "application/json"}
        )
    assert response.status_code == 400 and not state.finds and not state.creates
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?scope_ref=scope:one&scope_ref=scope:two",
        "?scope_ref=scope:one&sample=1",
        "?scope_ref=" + "a" * 513,
    ],
)
async def test_settings_get_requires_one_scope_and_no_unknown_query(query: str) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get(SETTINGS + query, headers=OWNER)
    assert response.status_code == 400 and not state.finds and not state.reads


async def test_settings_put_body_bounds_and_query_apply_before_persistence() -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        oversized = await client.put(
            SETTINGS,
            content=b"x" * (MAX_ALERT_QUALITY_BODY_BYTES + 1),
            headers={**OWNER, "Content-Type": "application/json"},
        )
        query = await client.put(SETTINGS + "?scope_ref=scope:one", json=_body(), headers=OWNER)
        denied = await client.put(
            SETTINGS, json={**_body(), "scope_ref": "scope:denied"}, headers=OWNER
        )
    assert oversized.status_code == 413 and query.status_code == 400 and denied.status_code == 403
    assert not state.finds and not state.creates


async def test_preference_disable_preserves_report_and_accepted_work_but_blocks_new_requests() -> (
    None
):
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        first = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=REQUEST
        )
        accepted = copy.deepcopy(writer.proposals)
        saved = await client.put(SETTINGS, json=_body(), headers=OWNER)
        read = await client.get(READ, headers=REQUEST)
        blocked = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=REQUEST
        )
        other_scope = await client.get("/alert-quality?scope_ref=scope:two", headers=REQUEST)
    assert first.status_code == 202 and saved.status_code == 200 and blocked.status_code == 503
    assert writer.proposals == accepted and len(accepted) == 1
    assert read.json()["available"] is True and read.json()["assessment"] is not None
    assert read.json()["enabled"] is False and read.json()["requestable"] is False
    assert other_scope.json()["enabled"] is True and other_scope.json()["requestable"] is True
    assert len(state.creates) == 1


async def test_preference_is_reloaded_after_readiness_without_a_process_cache() -> None:
    _, writer, dependencies = _harness()
    store = cast(StateKvAlertQualityPreferenceStore, dependencies.preference_store)
    calls = 0

    async def readiness() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            await _save(store)
        return True

    changed = replace(dependencies, producer_ready=readiness)
    async with _client(changed) as client:
        read = await client.get(READ, headers=REQUEST)
        blocked = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=REQUEST
        )
        enabled = await client.put(SETTINGS, json=_body(True, 1), headers=OWNER)
        refreshed = await client.get(READ, headers=REQUEST)
    assert read.json()["requestable"] is False and blocked.status_code == 503
    assert enabled.status_code == 200 and refreshed.json()["requestable"] is True
    assert not writer.proposals


async def test_unbound_store_keeps_legacy_default_without_claiming_durable_settings() -> None:
    state, _, dependencies = _harness()
    dependencies = replace(dependencies, preference_store=None)
    async with _client(dependencies) as client:
        capability = await client.get(READ, headers=REQUEST)
        settings = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
        write = await client.put(SETTINGS, json=_body(), headers=OWNER)
    assert capability.json()["enabled"] is True and capability.json()["requestable"] is True
    assert settings.json()["available"] is False and settings.json()["enabled"] is None
    assert settings.json()["revision"] is None and write.status_code == 503
    assert not state.creates


@pytest.mark.parametrize(
    "tamper",
    [
        "extra",
        "enabled",
        "authority",
        "scope",
        "revision",
        "missing",
        "future",
        "kind",
    ],
)
async def test_corrupt_preferences_never_become_an_enabled_default(tamper: str) -> None:
    state, writer, dependencies = _harness()
    await _save(cast(StateKvAlertQualityPreferenceStore, dependencies.preference_store))
    record = state.records[state.creates[0]]
    changes: dict[str, tuple[str, object]] = {
        "extra": ("mode", "enforce"),
        "enabled": ("enabled", 1),
        "authority": ("execution_authority", 0),
        "scope": ("scope_ref", "scope:two"),
        "revision": ("revision", 2),
        "future": ("recorded_at", "2026-09-14T13:00:00Z"),
        "kind": ("kind", "unknown"),
    }
    if tamper == "missing":
        del record["execution_authority"]
    else:
        field, value = changes[tamper]
        record[field] = value
    before = copy.deepcopy(state.records)
    async with _client(dependencies) as client:
        read = await client.get(READ, headers=REQUEST)
        settings = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
        blocked = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=REQUEST
        )
        save = await client.put(SETTINGS, json=_body(True, 1), headers=OWNER)
    assert read.json()["assessment"] is not None and read.json()["available"] is True
    assert read.json()["enabled"] is False and read.json()["requestable"] is False
    assert (
        settings.json()["preference_state"] == "unavailable" and settings.json()["enabled"] is None
    )
    assert blocked.status_code == save.status_code == 503
    assert state.records == before and not writer.proposals


@pytest.mark.parametrize("stage", ["readiness", "state_read", "readback"])
@pytest.mark.parametrize("revoke", ["role", "scope"])
async def test_settings_revalidate_before_atomic_commit_and_after_every_response_await(
    stage: str, revoke: str
) -> None:
    claims: dict[str, object] = dict(_verify("owner"))

    def revoke_access() -> None:
        if revoke == "role":
            claims["roles"] = ["Reader"]
        else:
            object.__setattr__(dependencies, "principal_scopes", {})

    class RevokingState(_State):
        async def find_state(
            self, *, prefix: str, field: str, value: str
        ) -> dict[str, object] | None:
            result = await super().find_state(prefix=prefix, field=field, value=value)
            if stage == "state_read":
                revoke_access()
            return result

        async def read_state(self, key: str) -> dict[str, object] | None:
            result = await super().read_state(key)
            if stage == "readback" and result is not None:
                revoke_access()
            return result

    state, _, dependencies = _harness(RevokingState())

    async def readiness() -> bool:
        if stage == "readiness":
            revoke_access()
        return True

    dependencies = replace(
        dependencies,
        producer_ready=readiness,
        authenticator=OperatorAuthenticator(verifier=lambda _: claims, group_ids={}),
    )
    async with _client(dependencies) as client:
        response = await client.put(SETTINGS, json=_body(), headers=OWNER)
    assert response.status_code == 403 and "revision" not in response.json()
    assert len(state.creates) == (1 if stage == "readback" else 0)
    assert response.headers["cache-control"] == "no-store"


async def test_atomic_cas_competitors_do_not_overwrite_or_automatically_advance() -> None:
    class RacingState(_State):
        competitor: Callable[[], Awaitable[None]] | None = None

        async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
            if self.competitor is not None:
                competitor, self.competitor = self.competitor, None
                await competitor()
            return await super().create_state(key, value)

    state = RacingState()
    store = StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW)

    async def competitor() -> None:
        await _save(StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW), enabled=True)

    state.competitor = competitor
    with pytest.raises(AlertQualityPreferenceConflictError):
        await _save(store)
    record = await store.read(scope_ref=SCOPE)
    assert record is not None and record.enabled is True and record.revision == 1
    assert len(state.records) == 1 and len(state.creates) == 2


async def test_newest_hint_is_verified_and_successors_are_followed_with_a_bound() -> None:
    class OldHintState(_State):
        hint: dict[str, object] | None = None

        async def find_state(
            self, *, prefix: str, field: str, value: str
        ) -> dict[str, object] | None:
            actual = await super().find_state(prefix=prefix, field=field, value=value)
            return copy.deepcopy(self.hint) if self.hint is not None else actual

    state = OldHintState()
    store = StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW)
    first = await _save(store)
    second = await _save(store, revision=1, enabled=True)
    state.hint = first.model_dump(mode="json")
    assert await store.read(scope_ref=SCOPE) == second
    for revision in range(2, 10):
        state.hint = None
        await _save(store, revision=revision)
    state.hint = first.model_dump(mode="json")
    with pytest.raises(AlertQualityUnavailableError, match="busy"):
        await store.read(scope_ref=SCOPE)


@pytest.mark.parametrize("failure", ["write", "readback", "cancel", "truthy"])
async def test_persistence_failure_or_cancellation_cannot_claim_a_saved_preference(
    failure: str,
) -> None:
    class FailingState(_State):
        async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
            if failure == "write":
                raise RuntimeError("private-storage-detail")
            if failure == "cancel":
                raise asyncio.CancelledError
            inserted = await super().create_state(key, value)
            return cast(bool, 1) if failure == "truthy" else inserted

        async def read_state(self, key: str) -> dict[str, object] | None:
            if failure == "readback" and key in self.records:
                raise RuntimeError("private-storage-detail")
            return await super().read_state(key)

    state, _, dependencies = _harness(FailingState())
    async with _client(dependencies) as client:
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await client.put(SETTINGS, json=_body(), headers=OWNER)
        else:
            response = await client.put(SETTINGS, json=_body(), headers=OWNER)
            assert response.status_code == 503 and "private-storage" not in response.text
            assert "revision" not in response.json()
    assert len(state.records) == (1 if failure in {"readback", "truthy"} else 0)


async def test_naive_or_regressing_preference_clocks_fail_before_persistence() -> None:
    state = _State()
    store = StateKvAlertQualityPreferenceStore(state, clock=lambda: NOW)
    await _save(store)
    before = copy.deepcopy(state.records)
    for clock in (lambda: NOW.replace(tzinfo=None), lambda: NOW - timedelta(seconds=1)):
        with pytest.raises(AlertQualityUnavailableError):
            await _save(StateKvAlertQualityPreferenceStore(state, clock=clock), revision=1)
    assert state.records == before


def test_environment_factory_accepts_preference_binding_without_creating_a_fallback() -> None:
    state, writer, dependencies = _harness()
    result = alert_quality_dependencies_from_environment(
        authenticator=dependencies.authenticator,
        environ={},
        store=state,
        proposal_writer=writer,
        preference_store=dependencies.preference_store,
    )
    assert (
        result.preference_store is dependencies.preference_store and result.producer_ready is None
    )
    assert not result.principal_scopes and not state.records


@pytest.mark.parametrize(
    "change",
    [
        {"execution_authority": 0},
        {"mode": "enforce"},
        {"enabled": 1},
        {"revision": True},
        {"available": 1},
        {"requester_ref": PRINCIPAL},
        {"recorded_at": "2026-09-14T12:00:00Z"},
    ],
)
async def test_settings_response_cannot_invent_saved_state_or_authority(
    change: dict[str, object],
) -> None:
    _, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
    with pytest.raises(ValidationError):
        AlertQualitySettingsResponse.model_validate_json(
            json.dumps({**response.json(), **change}), strict=True
        )


@pytest.mark.parametrize("stage", ["readiness", "preference"])
async def test_settings_read_revalidates_current_identity_after_all_awaits(stage: str) -> None:
    claims: dict[str, object] = dict(_verify("owner"))

    class RevokingState(_State):
        async def find_state(
            self, *, prefix: str, field: str, value: str
        ) -> dict[str, object] | None:
            result = await super().find_state(prefix=prefix, field=field, value=value)
            if stage == "preference":
                claims["oid"] = OTHER_PRINCIPAL
            return result

    async def readiness() -> bool:
        if stage == "readiness":
            claims["oid"] = OTHER_PRINCIPAL
        return True

    _, _, dependencies = _harness(RevokingState())
    dependencies = replace(
        dependencies,
        producer_ready=readiness,
        authenticator=OperatorAuthenticator(verifier=lambda _: claims, group_ids={}),
    )
    async with _client(dependencies) as client:
        response = await client.get(SETTINGS, params={"scope_ref": SCOPE}, headers=OWNER)
    assert response.status_code == 403 and "revision" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert PRINCIPAL not in response.text and OTHER_PRINCIPAL not in response.text


async def test_saved_preference_is_not_a_promotion_or_a_producer_enablement_flag() -> None:
    state, writer, dependencies = _harness()

    async def not_ready() -> bool:
        return False

    dependencies = replace(dependencies, enabled=False, producer_ready=not_ready)
    async with _client(dependencies) as client:
        saved = await client.put(SETTINGS, json=_body(True), headers=OWNER)
        read = await client.get(READ, headers=REQUEST)
        rejected = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=REQUEST
        )
    assert saved.status_code == 200 and saved.json()["enabled"] is True
    assert saved.json()["available"] is False and saved.json()["mode"] == "shadow"
    assert saved.json()["unavailable_reason"] == "producer_not_ready"
    assert read.json()["enabled"] is True and read.json()["requestable"] is False
    assert read.json()["assessment"] is not None
    assert rejected.status_code == 503 and not writer.proposals and len(state.creates) == 1


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_settings_share_the_bounded_request_timeout(method: str) -> None:
    state, _, dependencies = _harness()

    async def stalled() -> bool:
        await asyncio.Future[None]()
        raise AssertionError("the deadline MUST cancel readiness")

    dependencies = replace(dependencies, producer_ready=stalled, timeout_seconds=0.001)
    async with _client(dependencies) as client:
        response = await client.request(
            method,
            SETTINGS,
            headers=OWNER,
            params={"scope_ref": SCOPE} if method == "GET" else None,
            json=_body() if method == "PUT" else None,
        )
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert not state.records and not state.creates


async def test_missing_or_tampered_predecessor_never_resets_preference_history() -> None:
    state, _, dependencies = _harness()
    store = cast(StateKvAlertQualityPreferenceStore, dependencies.preference_store)
    await _save(store)
    await _save(store, revision=1, enabled=True)
    first_key = state.creates[0]
    first_record = state.records.pop(first_key)
    with pytest.raises(AlertQualityUnavailableError):
        await store.read(scope_ref=SCOPE)
    state.records[first_key] = {**first_record, "enabled": True}
    # find_state's insertion-order hint now points at the altered predecessor.
    with pytest.raises(AlertQualityUnavailableError):
        await store.read(scope_ref=SCOPE)
    assert len(state.creates) == 2

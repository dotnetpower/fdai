"""H10 current-source contracts over local config and synthetic HTTP, never live Graph."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fdai.core.human_assignment.scoped_duties import (
    DutySubject,
    DutySubjectKind,
    ScopedDutyBinding,
    ScopedDutyInput,
    ScopedDutyPolicy,
    ScopedDutyValidationError,
)
from fdai.core.human_assignment.scoped_duty_planning import ScopedDutyPlanner
from fdai.core.stewardship import Duty
from fdai.delivery.identity.scoped_duty_catalog import FileScopedDutyCatalog
from fdai.delivery.identity.scoped_duty_directory import EntraDutySubjectResolver
from fdai.shared.providers.oncall_schedule import OnCallSchedule, OnCallShift

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
AGE = timedelta(minutes=5)
PRIMARY = "00000000-0000-0000-0000-000000000001"
BACKUP = "00000000-0000-0000-0000-000000000002"
GROUP = "00000000-0000-0000-0000-000000000003"
SCOPE = "scope:example"
ENDPOINT = f"https://graph.microsoft.com/v1.0/groups/{GROUP}/transitiveMembers/microsoft.graph.user"


def _config():
    return {
        "schema_version": "1.0.0",
        "scopes": [SCOPE],
        "shifts": [
            {
                "rotation": "schedule:example",
                "primary_oid": PRIMARY,
                "secondary_oid": BACKUP,
                "start": (AT - AGE).isoformat(),
                "until": (AT + AGE).isoformat(),
            }
        ],
    }


def _catalog(tmp_path, value=None):
    path = tmp_path / "scoped-duties.json"
    path.write_text(json.dumps(_config() if value is None else value), encoding="utf-8")
    return FileScopedDutyCatalog(path)


def _identity():
    return SimpleNamespace(get_token=AsyncMock(return_value=SimpleNamespace(token="synthetic")))


def _resolver(client, *, schedule=None, clock=None):
    return EntraDutySubjectResolver(client, _identity(), schedule, clock or (lambda: AT), AGE, 1.0)


def _person(ref=PRIMARY):
    return DutySubject(DutySubjectKind.PERSON, ref)


def _http(request):
    assert request.method == "GET" and request.url.host == "graph.microsoft.com"
    if request.url.path.endswith(f"/groups/{GROUP}"):
        return httpx.Response(200, json={"id": GROUP})
    if "transitiveMembers" in request.url.path:
        return httpx.Response(200, json={"value": [{"id": PRIMARY, "accountEnabled": True}]})
    ref = request.url.path.rsplit("/", 1)[-1]
    return httpx.Response(200, json={"id": ref, "accountEnabled": True})


async def test_catalog_revision_is_derived_current_and_exact(tmp_path):
    catalog = _catalog(tmp_path)
    original = catalog.validate()
    assert isinstance(catalog, OnCallSchedule)
    assert await catalog.read_scope(SCOPE, source_revision=original.revision) is not None
    for scope in ("scope:platform", SCOPE + "/child", "Scope:example", "*"):
        assert await catalog.read_scope(scope, source_revision=original.revision) is None
    assert await catalog.read_scope(SCOPE, source_revision="caller-claimed") is None
    changed = _config()
    changed["scopes"].append("scope:other")
    catalog.path.write_text(json.dumps(changed), encoding="utf-8")
    assert await catalog.read_scope(SCOPE, source_revision=original.revision) is None
    assert (await catalog.snapshot()).revision != original.revision


async def test_current_schedule_is_half_open_and_never_implicit(tmp_path):
    catalog = _catalog(tmp_path)
    assert await catalog.current(rotation="schedule:example", at=AT) is not None
    for rotation, at in (("unknown", AT), ("schedule:example", AT + AGE)):
        assert await catalog.current(rotation=rotation, at=at) is None
    with pytest.raises(ScopedDutyValidationError):
        await catalog.current(rotation="schedule:example", at=AT.replace(tzinfo=None))


@pytest.mark.parametrize("case", ["duplicate", "version", "naive", "overlap", "self", "unknown"])
def test_catalog_rejects_ambiguous_or_unversioned_configuration(tmp_path, case):
    value = _config()
    if case == "duplicate":
        value["scopes"] *= 2
    elif case == "version":
        value["schema_version"] = "2.0.0"
    elif case == "naive":
        value["shifts"][0]["start"] = AT.replace(tzinfo=None).isoformat()
    elif case == "overlap":
        value["shifts"] *= 2
    elif case == "self":
        value["shifts"][0]["secondary_oid"] = PRIMARY
    else:
        value["authority"] = True
    with pytest.raises(ScopedDutyValidationError):
        _catalog(tmp_path, value).validate()


@pytest.mark.parametrize("case", ["symlink", "fifo", "oversized", "duplicate_keys", "missing"])
def test_catalog_special_or_unbounded_files_fail_without_blocking(tmp_path, case):
    source = _catalog(tmp_path)
    if case == "symlink":
        target = tmp_path / "link.json"
        target.symlink_to(source.path)
        source = FileScopedDutyCatalog(target)
    elif case == "fifo":
        target = tmp_path / "pipe"
        os.mkfifo(target)
        source = FileScopedDutyCatalog(target)
    elif case == "oversized":
        source.path.write_bytes(b" " * 1_048_577)
    elif case == "duplicate_keys":
        source.path.write_text('{"schema_version":"1.0.0","schema_version":"1.0.0"}')
    else:
        source.path.unlink()
    with pytest.raises(ScopedDutyValidationError, match="unavailable or invalid"):
        source.validate()


@pytest.mark.parametrize("enabled", [None, "true", 1, {}, []])
async def test_current_person_requires_explicit_active_boolean(enabled):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"id": PRIMARY, "accountEnabled": enabled})
        )
    ) as client:
        with pytest.raises(ScopedDutyValidationError):
            await _resolver(client).resolve(_person(), at=AT)


async def test_exact_subject_mismatch_and_disabled_are_not_active_coverage():
    replies = iter(
        [{"id": BACKUP, "accountEnabled": True}, {"id": PRIMARY, "accountEnabled": False}]
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=next(replies)))
    ) as client:
        resolver = _resolver(client)
        with pytest.raises(ScopedDutyValidationError):
            await resolver.resolve(_person(), at=AT)
        result = await resolver.resolve(_person(), at=AT)
        assert result is not None and not result.people and result.complete


async def test_group_and_schedule_resolve_current_people_without_role_or_future_grants(tmp_path):
    catalog = _catalog(tmp_path)
    requests = []

    def handler(request):
        requests.append(request)
        return _http(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resolver = _resolver(client, schedule=catalog)
        group = await resolver.resolve(DutySubject(DutySubjectKind.GROUP, GROUP), at=AT)
        shift = await resolver.resolve(
            DutySubject(DutySubjectKind.SCHEDULE, "schedule:example"), at=AT
        )
        assert group is not None and shift is not None
        assert group.people == shift.people == (_person(),)
        assert shift.valid_until == AT + AGE
        assert shift.subject.kind is DutySubjectKind.SCHEDULE
        assert BACKUP not in {person.ref for person in shift.people}
        assert all(request.method == "GET" for request in requests)
        before = len(requests)
        assert await resolver.resolve(_person(), at=AT + AGE) is None
        assert await resolver.resolve(_person(), at=AT - AGE) is None
        assert len(requests) == before


async def test_schedule_outage_uses_independently_checked_static_fallback(tmp_path):
    catalog = _catalog(tmp_path, {"schema_version": "1.0.0", "scopes": [SCOPE], "shifts": []})
    revision = catalog.validate().revision
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http)) as client:
        resolver = _resolver(client, schedule=catalog)
        planner = ScopedDutyPlanner(resolver, catalog, lambda: AT, ScopedDutyPolicy(AGE, 1.0, 5.0))
        request = ScopedDutyInput(
            revision,
            (
                ScopedDutyBinding(
                    DutySubject(DutySubjectKind.SCHEDULE, "schedule:example"),
                    "Odin",
                    SCOPE,
                    Duty.PRIMARY,
                    AT - AGE,
                    AT + AGE,
                    _person(),
                ),
                ScopedDutyBinding(
                    _person(BACKUP), "Odin", SCOPE, Duty.BACKUP, AT - AGE, AT + AGE, None
                ),
            ),
        )
        plan = await planner.plan(request)
        assert plan.has_current_coverage and plan.bindings[0].used_fallback
        assert plan.coverage[0].primary_refs == (PRIMARY,)
        assert plan.coverage[0].backup_refs == (BACKUP,)
        assert not plan.execution_authority


@pytest.mark.parametrize("suffix", ["wrong_group", "host", "fragment", "empty", "repeated"])
async def test_group_continuation_cannot_change_source_or_loop(suffix):
    requests = []
    links = {
        "wrong_group": ENDPOINT.replace(GROUP, BACKUP),
        "host": ENDPOINT.replace("graph.microsoft.com", "example.com"),
        "fragment": ENDPOINT + "#unexpected",
        "empty": "",
        "repeated": ENDPOINT,
    }

    def handler(request):
        requests.append(request)
        if request.url.path.endswith(f"/groups/{GROUP}"):
            return httpx.Response(200, json={"id": GROUP})
        return httpx.Response(200, json={"value": [], "@odata.nextLink": links[suffix]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScopedDutyValidationError):
            await _resolver(client).resolve(DutySubject(DutySubjectKind.GROUP, GROUP), at=AT)
    assert len(requests) == 2


@pytest.mark.parametrize("case", ["duplicate", "overbound", "partial_user", "wrong_group"])
async def test_partial_group_evidence_never_becomes_complete(case):
    values = [{"id": PRIMARY, "accountEnabled": True}]
    if case == "duplicate":
        values *= 2
    elif case == "overbound":
        values *= 101
    elif case == "partial_user":
        values = [{"id": PRIMARY}]

    def handler(request):
        if request.url.path.endswith(f"/groups/{GROUP}"):
            return httpx.Response(200, json={"id": BACKUP if case == "wrong_group" else GROUP})
        return httpx.Response(200, json={"value": values})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScopedDutyValidationError):
            await _resolver(client).resolve(DutySubject(DutySubjectKind.GROUP, GROUP), at=AT)


async def test_complete_group_pages_are_canonical_and_redacted():
    def handler(request):
        if request.url.path.endswith(f"/groups/{GROUP}"):
            return httpx.Response(200, json={"id": GROUP})
        second = "$skiptoken" in request.url.params
        return httpx.Response(
            200,
            json={
                "value": [{"id": PRIMARY if second else BACKUP, "accountEnabled": True}],
                **({} if second else {"@odata.nextLink": ENDPOINT + "?$skiptoken=next"}),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _resolver(client).resolve(DutySubject(DutySubjectKind.GROUP, GROUP), at=AT)
        assert result is not None and result.complete
        assert result.people == (_person(), _person(BACKUP))
        assert GROUP not in result.provenance_ref


@pytest.mark.parametrize("status", [301, 403, 429, 503])
async def test_http_failure_has_no_redirect_retry_or_provider_body(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="private provider response", headers={"Location": "https://example.com"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(ScopedDutyValidationError) as caught:
            await _resolver(client).resolve(_person(), at=AT)
    assert len(calls) == 1 and "private" not in str(caught.value)


@pytest.mark.parametrize("body", [b" " * 131_073, b'{"id":"wrong","id":"other"}', b"[]"])
async def test_response_size_and_ambiguous_json_are_bounded(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(ScopedDutyValidationError):
            await _resolver(client).resolve(_person(), at=AT)


@pytest.mark.parametrize("finish", [AT + AGE, AT - timedelta(seconds=1)])
async def test_slow_read_or_clock_rollback_cannot_restart_freshness(finish):
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http)) as client:
        result = await _resolver(client, clock=Mock(side_effect=[AT, finish])).resolve(
            _person(), at=AT
        )
        assert result is None


async def test_expiring_schedule_is_not_extended_by_directory_read():
    schedule = SimpleNamespace(
        current=AsyncMock(
            return_value=OnCallShift(
                "schedule:example", PRIMARY, BACKUP, AT - AGE, AT + timedelta(seconds=1)
            )
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http)) as client:
        resolver = _resolver(
            client, schedule=schedule, clock=Mock(side_effect=[AT, AT + timedelta(seconds=1)])
        )
        assert (
            await resolver.resolve(DutySubject(DutySubjectKind.SCHEDULE, "schedule:example"), at=AT)
            is None
        )


async def test_invalid_identity_fails_before_token_and_cancellation_propagates():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http)) as client:
        resolver = _resolver(client)
        with pytest.raises(ScopedDutyValidationError):
            await resolver.resolve(_person("../other"), at=AT)
        resolver.identity.get_token.assert_not_awaited()
        resolver.identity.get_token.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await resolver.resolve(_person(), at=AT)

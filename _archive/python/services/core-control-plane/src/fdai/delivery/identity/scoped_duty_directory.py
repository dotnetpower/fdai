"""Strict current Entra duty observations, with no role or membership-write capability."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx

from fdai.core.human_assignment.scoped_duties import (
    MAX_PEOPLE_PER_EXPANSION,
    DutyResolution,
    DutySubject,
    DutySubjectKind,
    ScopedDutyValidationError,
    canonical_digest,
    utc_instant,
)
from fdai.delivery.identity.scoped_duty_catalog import exact_person_id
from fdai.shared.providers.oncall_schedule import OnCallSchedule, OnCallShift
from fdai.shared.providers.workload_identity import WorkloadIdentity

_GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_MAX_RESPONSE_BYTES = 131_072


@dataclass(frozen=True, slots=True)
class EntraDutySubjectResolver:
    """Read complete active people, never a truncated display roster or token claim.

    The observation freshness budget starts at the supplied query instant, before I/O;
    completion cannot extend it. Actual read start/end and shift identity bind provenance.
    Only present shifts are resolved, and the planner independently resolves fallback.
    All Graph calls are GETs to the fixed public endpoint with redirects and retries off.
    """

    client: httpx.AsyncClient
    identity: WorkloadIdentity
    schedule: OnCallSchedule | None
    clock: Callable[[], datetime]
    validity: timedelta
    timeout_seconds: float

    def __post_init__(self) -> None:
        if (
            not callable(self.clock)
            or not isinstance(self.validity, timedelta)
            or not timedelta(0) < self.validity <= timedelta(minutes=5)
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ScopedDutyValidationError("duty resolver requires bounded time and clock policy")

    async def resolve(self, subject: DutySubject, *, at: datetime) -> DutyResolution | None:
        """Return only a current complete observation; errors hold and cancellation propagates."""
        if not isinstance(subject, DutySubject):
            raise ScopedDutyValidationError("duty resolver requires a typed subject")
        instant = utc_instant(at)
        started = utc_instant(self.clock())
        expires = instant + self.validity
        if not instant <= started < expires:
            return None
        async with asyncio.timeout(self.timeout_seconds):
            shift: OnCallShift | None = None
            selected = subject
            if subject.kind is DutySubjectKind.SCHEDULE:
                if self.schedule is None:
                    return None
                shift = await self.schedule.current(rotation=subject.ref, at=started)
                if shift is None:
                    return None
                if (
                    not isinstance(shift, OnCallShift)
                    or shift.rotation != subject.ref
                    or not utc_instant(shift.start) <= started < utc_instant(shift.until)
                ):
                    raise ScopedDutyValidationError(
                        "schedule returned a different or inactive shift"
                    )
                selected = DutySubject(DutySubjectKind.PERSON, exact_person_id(shift.primary_oid))
                expires = min(expires, utc_instant(shift.until))
            identifier = exact_person_id(selected.ref)
            token = await self.identity.get_token(_GRAPH_SCOPE)
            headers = {"Authorization": f"Bearer {token.token}"}
            if selected.kind is DutySubjectKind.GROUP:
                people = await self._group(identifier, headers)
            else:
                person = await self._get(
                    f"{_GRAPH_ROOT}/users/{identifier}", headers, {"$select": "id,accountEnabled"}
                )
                people = () if person is None else _active_person(person, expected=identifier)
            finished = utc_instant(self.clock())
            if not started <= finished < expires:
                return None
            return DutyResolution(
                subject=subject,
                at=instant,
                people=people,
                observed_at=instant,
                valid_until=expires,
                provenance_ref="directory:entra:" + canonical_digest({"subject": subject}),
                provenance_digest=canonical_digest(
                    {
                        "subject": subject,
                        "people": people,
                        "query_at": instant,
                        "started_at": started,
                        "completed_at": finished,
                        "shift": shift,
                    }
                ),
                complete=True,
            )

    async def _group(self, identifier: str, headers: dict[str, str]) -> tuple[DutySubject, ...]:
        group = await self._get(f"{_GRAPH_ROOT}/groups/{identifier}", headers, {"$select": "id"})
        if group is None:
            return ()
        if group.get("id") != identifier:
            raise ScopedDutyValidationError("group response does not match its exact subject")
        endpoint = f"{_GRAPH_ROOT}/groups/{identifier}/transitiveMembers/microsoft.graph.user"
        url: str | None = endpoint
        params: dict[str, str] | None = {"$select": "id,accountEnabled", "$top": "100"}
        seen: set[str] = set()
        people: list[DutySubject] = []
        visited: set[str] = set()
        for _ in range(10):
            if url is None:
                return tuple(sorted(people, key=lambda item: item.ref))
            if url in visited:
                raise ScopedDutyValidationError("group expansion repeated a continuation")
            visited.add(url)
            page = await self._get(url, headers, params)
            if page is None:
                raise ScopedDutyValidationError("group expansion source became unavailable")
            values = page.get("value")
            if not isinstance(values, list):
                raise ScopedDutyValidationError("group expansion requires a complete user array")
            if len(values) > MAX_PEOPLE_PER_EXPANSION:
                raise ScopedDutyValidationError("group expansion exceeds its person bound")
            for value in values:
                if not isinstance(value, dict):
                    raise ScopedDutyValidationError("group expansion contains malformed identity")
                ref = exact_person_id(value.get("id"))
                if ref in seen or len(seen) >= MAX_PEOPLE_PER_EXPANSION:
                    raise ScopedDutyValidationError("group expansion is duplicate or over-bound")
                seen.add(ref)
                people.extend(_active_person(value, expected=ref))
            url = _next_link(page.get("@odata.nextLink"), endpoint)
            params = None
        if url is not None:
            raise ScopedDutyValidationError("group expansion did not finish within its page bound")
        return tuple(sorted(people, key=lambda item: item.ref))

    async def _get(
        self, url: str, headers: dict[str, str], params: dict[str, str] | None
    ) -> dict[str, object] | None:
        try:
            async with self.client.stream(
                "GET",
                url,
                headers=headers,
                params=params,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise ScopedDutyValidationError("current directory read is unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise ScopedDutyValidationError("current directory response is over-bound")
            body = json.loads(content, object_pairs_hook=_unique_object)
            if not isinstance(body, dict):
                raise ScopedDutyValidationError("current directory response MUST be an object")
            return body
        except (httpx.HTTPError, ValueError):
            raise ScopedDutyValidationError("current directory read failed closed") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ScopedDutyValidationError("current directory response contains duplicate keys")
        result[key] = value
    return result


def _active_person(value: dict[str, object], *, expected: str) -> tuple[DutySubject, ...]:
    if value.get("id") != expected or type(value.get("accountEnabled")) is not bool:
        raise ScopedDutyValidationError("current person identity or active state is unproven")
    if value["accountEnabled"] is False:
        return ()
    return (DutySubject(DutySubjectKind.PERSON, expected),)


def _next_link(value: object, endpoint: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ScopedDutyValidationError("group continuation MUST be a bounded URL")
    candidate, expected = urlsplit(value), urlsplit(endpoint)
    if (
        candidate.scheme != expected.scheme
        or candidate.netloc != expected.netloc
        or candidate.path != expected.path
        or candidate.fragment
    ):
        raise ScopedDutyValidationError("group continuation changed the exact source endpoint")
    return value


__all__ = ["EntraDutySubjectResolver"]

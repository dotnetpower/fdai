from __future__ import annotations

from datetime import UTC, datetime

import httpx
from starlette.applications import Starlette

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.skill_quarantine import SkillSourceRefreshState
from fdai.core.supply_chain.skill_source_admin import (
    ApprovedSkillCandidate,
    SkillSourceRevocationResult,
)
from fdai.delivery.read_api.routes.skill_sources import (
    SkillSourceRoutesConfig,
    make_skill_source_routes,
)

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _source(*, enabled: bool = True) -> SkillSource:
    return SkillSource(
        source_id="operations-skills",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example-org/skills",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills/example",
        authentication_audience_ref="github-app:reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3600,
        enabled=enabled,
    )


class Sources:
    def __init__(self, *, enabled: bool = True) -> None:
        self.source = _source(enabled=enabled)

    async def list(self, *, enabled_only: bool = False):  # type: ignore[no-untyped-def]
        return (self.source,) if not enabled_only or self.source.enabled else ()

    async def get(self, source_id: str):  # type: ignore[no-untyped-def]
        return self.source if source_id == self.source.source_id else None


class EmptyListStore:
    async def list(self, **_kwargs):  # type: ignore[no-untyped-def]
        return ()


class RefreshStates:
    async def get(self, source_id: str):  # type: ignore[no-untyped-def]
        if source_id != _source().source_id:
            return None
        return SkillSourceRefreshState(source_id=source_id, last_etag='"v1"')


class Administration:
    async def approve_candidate(self, **kwargs):  # type: ignore[no-untyped-def]
        return ApprovedSkillCandidate(
            source_id=kwargs["source_id"],
            candidate_id=kwargs["candidate_id"],
            skill_name="example.skill",
            version="1.0.0",
        )

    async def revoke_source(self, **kwargs):  # type: ignore[no-untyped-def]
        return SkillSourceRevocationResult(
            source_id=kwargs["source_id"],
            revoked_digests=("a" * 64,),
            disabled_artifact_ids=("example.skill",),
        )


def _app(role: Role, *, source_enabled: bool = True) -> Starlette:
    async def authorize(_request):  # type: ignore[no-untyped-def]
        return Principal(oid="operator", roles=frozenset({role}))

    empty = EmptyListStore()
    config = SkillSourceRoutesConfig(
        sources=Sources(enabled=source_enabled),  # type: ignore[arg-type]
        quarantine=empty,  # type: ignore[arg-type]
        candidates=empty,  # type: ignore[arg-type]
        revocations=empty,  # type: ignore[arg-type]
        refresh_states=RefreshStates(),  # type: ignore[arg-type]
        administration=Administration(),  # type: ignore[arg-type]
    )
    return Starlette(routes=make_skill_source_routes(config=config, authorize_principal=authorize))


async def _request(  # type: ignore[no-untyped-def]
    role: Role, method: str, path: str, *, source_enabled: bool = True, **kwargs
):
    transport = httpx.ASGITransport(app=_app(role, source_enabled=source_enabled))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


async def test_reader_can_browse_search_inspect_and_check_update() -> None:
    for path in (
        "/api/v1/skill-sources/browse",
        "/api/v1/skill-sources/search?q=platform",
        "/api/v1/skill-sources/operations-skills/inspect",
        "/api/v1/skill-sources/operations-skills/check-update",
        "/api/v1/skill-sources/operations-skills/candidates",
    ):
        response = await _request(Role.READER, "GET", path)
        assert response.status_code == 200, response.text
    inspect = await _request(
        Role.READER,
        "GET",
        "/api/v1/skill-sources/operations-skills/inspect",
    )
    assert inspect.json()["refresh"]["etag"] == '"v1"'


async def test_reader_cannot_approve_or_revoke() -> None:
    approve = await _request(
        Role.READER,
        "POST",
        "/api/v1/skill-sources/operations-skills/approve-candidate",
        json={"candidate_id": "skill-update-example"},
    )
    revoke = await _request(
        Role.READER,
        "POST",
        "/api/v1/skill-sources/operations-skills/revoke",
        json={"reason": "Publisher key was withdrawn."},
    )

    assert approve.status_code == 403
    assert revoke.status_code == 403


async def test_approver_installs_disabled_and_owner_revokes() -> None:
    approve = await _request(
        Role.APPROVER,
        "POST",
        "/api/v1/skill-sources/operations-skills/approve-candidate",
        json={"candidate_id": "skill-update-example"},
    )
    revoke = await _request(
        Role.OWNER,
        "POST",
        "/api/v1/skill-sources/operations-skills/revoke",
        json={"reason": "Publisher key was withdrawn."},
    )

    assert approve.status_code == 200
    assert approve.json()["enabled"] is False
    assert revoke.status_code == 200
    assert revoke.json()["disabled_artifact_ids"] == ["example.skill"]


async def test_disabled_source_is_hidden_from_browse_but_remains_inspectable() -> None:
    browse = await _request(
        Role.READER,
        "GET",
        "/api/v1/skill-sources/browse",
        source_enabled=False,
    )
    inspect = await _request(
        Role.READER,
        "GET",
        "/api/v1/skill-sources/operations-skills/inspect",
        source_enabled=False,
    )

    assert browse.json()["sources"] == []
    assert inspect.status_code == 200
    assert inspect.json()["source"]["enabled"] is False

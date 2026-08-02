"""Skill-source read projections and separately authorized lifecycle commands."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.core.skills.source_registry import SkillSourceStore
from fdai.core.supply_chain.skill_quarantine import (
    SkillQuarantineStore,
    SkillRevocationStore,
    SkillSourceRefreshStateStore,
    SkillUpdateCandidateStore,
)
from fdai.core.supply_chain.skill_source_admin import SkillSourceAdministrationService

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY: Final = 4_096


@dataclass(frozen=True, slots=True)
class SkillSourceRoutesConfig:
    sources: SkillSourceStore
    quarantine: SkillQuarantineStore
    candidates: SkillUpdateCandidateStore
    revocations: SkillRevocationStore
    refresh_states: SkillSourceRefreshStateStore
    administration: SkillSourceAdministrationService


def make_skill_source_routes(
    *,
    config: SkillSourceRoutesConfig,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def browse(request: Request) -> Response:
        await authorize_principal(request)
        sources = await config.sources.list(enabled_only=True)
        return JSONResponse({"count": len(sources), "sources": [_source(item) for item in sources]})

    async def search(request: Request) -> Response:
        await authorize_principal(request)
        query = request.query_params.get("q", "").strip().casefold()
        if not query or len(query) > 128:
            raise HTTPException(status_code=400, detail="skill source search q MUST be bounded")
        sources = await config.sources.list(enabled_only=True)
        matches = tuple(
            source
            for source in sources
            if query
            in " ".join(
                (source.source_id, source.location, source.owner, source.allowed_path)
            ).casefold()
        )
        return JSONResponse({"count": len(matches), "sources": [_source(item) for item in matches]})

    async def inspect(request: Request) -> Response:
        await authorize_principal(request)
        source_id = request.path_params["source_id"]
        source = await _source_or_404(config, source_id)
        quarantine = await config.quarantine.list(source_id=source_id)
        revocations = await config.revocations.list(source_id=source_id)
        refresh = await config.refresh_states.get(source_id)
        return JSONResponse(
            {
                "source": _source(source),
                "refresh": _refresh(refresh),
                "quarantine": [_artifact(item) for item in quarantine],
                "revocations": [_revocation(item) for item in revocations],
            }
        )

    async def check_update(request: Request) -> Response:
        await authorize_principal(request)
        source_id = request.path_params["source_id"]
        await _source_or_404(config, source_id)
        refresh = await config.refresh_states.get(source_id)
        candidates = await config.candidates.list(source_id=source_id)
        latest = candidates[-1] if candidates else None
        return JSONResponse(
            {
                "source_id": source_id,
                "refresh": _refresh(refresh),
                "update_available": latest is not None,
                "candidate": _candidate(latest) if latest is not None else None,
            }
        )

    async def candidates(request: Request) -> Response:
        await authorize_principal(request)
        source_id = request.path_params["source_id"]
        await _source_or_404(config, source_id)
        values = await config.candidates.list(source_id=source_id)
        return JSONResponse(
            {"count": len(values), "candidates": [_candidate(item) for item in values]}
        )

    async def approve(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.APPROVE_RUNTIME_HIL):
            raise HTTPException(status_code=403, detail="approver capability is required")
        body = await _body(request)
        candidate_id = _required_string(body, "candidate_id", maximum=256)
        approved = await config.administration.approve_candidate(
            source_id=request.path_params["source_id"],
            candidate_id=candidate_id,
            now=_request_time(request),
        )
        return JSONResponse(
            {
                "source_id": approved.source_id,
                "candidate_id": approved.candidate_id,
                "skill_name": approved.skill_name,
                "version": approved.version,
                "enabled": approved.enabled,
            }
        )

    async def revoke(request: Request) -> Response:
        principal = await authorize_principal(request)
        if Role.OWNER not in principal.roles:
            raise HTTPException(status_code=403, detail="Owner role is required")
        body = await _body(request)
        reason = _required_string(body, "reason", maximum=512)
        result = await config.administration.revoke_source(
            source_id=request.path_params["source_id"],
            reason=reason,
            revoked_at=_request_time(request),
        )
        return JSONResponse(
            {
                "source_id": result.source_id,
                "revoked_digests": list(result.revoked_digests),
                "disabled_artifact_ids": list(result.disabled_artifact_ids),
            }
        )

    prefix = "/api/v1/skill-sources"
    return (
        Route(f"{prefix}/browse", browse, methods=["GET"]),
        Route(f"{prefix}/search", search, methods=["GET"]),
        Route(f"{prefix}/{{source_id:str}}/inspect", inspect, methods=["GET"]),
        Route(f"{prefix}/{{source_id:str}}/check-update", check_update, methods=["GET"]),
        Route(f"{prefix}/{{source_id:str}}/candidates", candidates, methods=["GET"]),
        Route(f"{prefix}/{{source_id:str}}/approve-candidate", approve, methods=["POST"]),
        Route(f"{prefix}/{{source_id:str}}/revoke", revoke, methods=["POST"]),
    )


async def _source_or_404(config: SkillSourceRoutesConfig, source_id: str) -> Any:
    source = await config.sources.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="skill source not found")
    return source


def _source(value: Any) -> dict[str, Any]:
    return {
        "source_id": value.source_id,
        "kind": value.kind.value,
        "location": value.location,
        "trust_tier": value.trust_tier.value,
        "owner": value.owner,
        "allowed_path": value.allowed_path,
        "refresh_policy": value.refresh_policy.value,
        "refresh_interval_seconds": value.refresh_interval_seconds,
        "enabled": value.enabled,
    }


def _refresh(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "last_refresh_at": _timestamp(value.last_refresh_at),
        "next_refresh_at": _timestamp(value.next_refresh_at),
        "etag": value.last_etag,
        "last_revision": value.last_revision,
        "error_count": value.error_count,
        "retry_at": _timestamp(value.retry_at),
        "last_error_kind": value.last_error_kind,
    }


def _artifact(value: Any) -> dict[str, Any]:
    return {
        "quarantine_id": value.quarantine_id,
        "source_revision": value.source_revision,
        "artifact_digest": value.artifact_digest,
        "state": value.state.value,
        "verdict": value.verdict.value if value.verdict is not None else None,
        "fetched_at": value.fetched_at.isoformat(),
        "scanner_version": value.scanner_version,
        "findings": [
            {
                "scanner": finding.scanner,
                "code": finding.code,
                "severity": finding.severity.value,
                "path": finding.path,
                "detail": finding.detail,
            }
            for finding in value.findings
        ],
    }


def _candidate(value: Any) -> dict[str, Any]:
    return {
        "candidate_id": value.candidate_id,
        "quarantine_id": value.quarantine_id,
        "artifact_digest": value.artifact_digest,
        "prior_installed_digest": value.prior_installed_digest,
        "created_at": value.created_at.isoformat(),
        "disabled": value.disabled,
    }


def _revocation(value: Any) -> dict[str, Any]:
    return {
        "revocation_id": value.revocation_id,
        "artifact_digest": value.artifact_digest,
        "reason": value.reason,
        "revoked_at": value.revoked_at.isoformat(),
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="skill source request body exceeds cap")
    try:
        value = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="skill source body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="skill source body MUST be an object")
    return value


def _required_string(values: dict[str, Any], key: str, *, maximum: int) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"skill source {key} MUST be bounded")
    return value.strip()


def _request_time(request: Request) -> datetime:
    value = getattr(request.state, "skill_source_now", None)
    return value if isinstance(value, datetime) else datetime.now(tz=UTC)


__all__ = ["SkillSourceRoutesConfig", "make_skill_source_routes"]

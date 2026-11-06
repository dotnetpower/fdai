"""Audited transport settings and an untrusted, bounded Release Hub catalog preview."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    parse_lifecycle_release_manifest,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Column, Engine, Integer, MetaData, String, Table, Text, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route

from fdai_lifecycle_hub import domain, schemas
from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.errors import NotEnrolledError, UnknownInstallationError
from fdai_lifecycle_hub.migrations import begin_sqlite_write
from fdai_lifecycle_hub.planning import _draft, _sign
from fdai_lifecycle_hub.signing import HubSigningKey

if TYPE_CHECKING:
    from fdai_lifecycle_hub.store import HubStore

DEFAULT_RELEASE_HUB_ENDPOINT = "http://127.0.0.1:8091"
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
PREVIEW_TIMEOUT_SECONDS = 5
logger = logging.getLogger(__name__)
metadata = MetaData()
endpoint_settings = Table(
    "hub_release_endpoint",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("endpoint", String(2048)),
)
endpoint_events = Table(
    "hub_release_endpoint_event",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("revision", Integer, nullable=False),
    Column("endpoint", String(2048)),
    Column("actor", String(160), nullable=False),
    Column("reason", Text, nullable=False),
    Column("recorded_at", String(40), nullable=False),
)


def normalize_endpoint(value: str) -> str:
    """Accept an origin only; HTTP is confined to explicit loopback targets."""
    parsed = urlsplit(value)
    host = parsed.hostname
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or any(character in host for character in "\\%")
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("Release Hub endpoint must be an origin without credentials or a path.")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Release Hub endpoint port must be between 1 and 65535.")
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise ValueError("HTTP Release Hub endpoints must use an explicit loopback host.")
    elif parsed.scheme != "https" or port not in (None, 443):
        raise ValueError("Remote Release Hub endpoints require HTTPS on port 443.")
    canonical_host = host.encode("idna").decode("ascii").lower()
    authority = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    if port is not None and port != (80 if parsed.scheme == "http" else 443):
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


def prepare_connection_schema(engine: Engine) -> None:
    """Explicitly expand connection storage; serving never creates database tables."""
    with engine.begin() as connection:
        metadata.create_all(connection)


EndpointSource = Literal["saved", "environment", "local-default", "deployment"]


class ConnectionState(BaseModel):
    endpoint: str
    configured_endpoint: str | None
    revision: int
    source: EndpointSource
    editable: bool
    requires_migration: bool


class EndpointChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: str | None = Field(max_length=2048)
    revision: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str


class EndpointError(ValueError):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


class ConnectionStore:
    def __init__(self, engine: Engine, *, deployment_endpoint: str | None = None) -> None:
        self.engine = engine
        self.deployment_endpoint = (
            normalize_endpoint(deployment_endpoint) if deployment_endpoint is not None else None
        )
        configured = os.environ.get("FDAI_RELEASE_HUB_ENDPOINT")
        self.environment_endpoint = (
            normalize_endpoint(configured) if configured is not None else None
        )

    def status(self) -> ConnectionState:
        ready = inspect(self.engine).has_table(endpoint_settings.name)
        if not ready:
            logger.warning("release_hub_settings_require_migration")
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(endpoint_settings)).mappings().one_or_none()
                if ready
                else None
            )
        saved = row["endpoint"] if row is not None else None
        source: EndpointSource
        if self.deployment_endpoint is not None:
            endpoint, source = self.deployment_endpoint, "deployment"
        elif saved is not None:
            endpoint, source = saved, "saved"
        elif self.environment_endpoint is not None:
            endpoint, source = self.environment_endpoint, "environment"
        else:
            endpoint, source = DEFAULT_RELEASE_HUB_ENDPOINT, "local-default"
        return ConnectionState(
            endpoint=endpoint,
            configured_endpoint=saved,
            revision=row["revision"] if row is not None else 0,
            source=source,
            editable=ready and self.deployment_endpoint is None,
            requires_migration=not ready,
        )

    def change(self, change: EndpointChange, *, actor: str, clock: Clock) -> ConnectionState:
        if self.deployment_endpoint is not None:
            raise EndpointError(409, "release_hub_endpoint_is_deployment_owned")
        endpoint = normalize_endpoint(change.endpoint) if change.endpoint is not None else None
        target = endpoint if endpoint is not None else "local-default"
        if change.confirmation != f"connect release hub {target} {change.revision}":
            raise EndpointError(422, "release_hub_endpoint_confirmation_invalid")
        if len(change.reason.strip()) < 3:
            raise EndpointError(422, "release_hub_endpoint_reason_invalid")
        if not inspect(self.engine).has_table(endpoint_settings.name):
            raise EndpointError(503, "release_hub_settings_require_migration")
        try:
            with self.engine.begin() as connection:
                begin_sqlite_write(connection)
                row = (
                    connection.execute(select(endpoint_settings).with_for_update())
                    .mappings()
                    .one_or_none()
                )
                revision = row["revision"] if row is not None else 0
                if revision != change.revision:
                    raise EndpointError(409, "release_hub_endpoint_revision_changed")
                values = {"revision": revision + 1, "endpoint": endpoint}
                if row is None:
                    connection.execute(endpoint_settings.insert().values(id=1, **values))
                else:
                    connection.execute(
                        endpoint_settings.update()
                        .where(endpoint_settings.c.id == 1)
                        .values(**values)
                    )
                connection.execute(
                    endpoint_events.insert().values(
                        **values,
                        actor=actor,
                        reason=change.reason.strip(),
                        recorded_at=clock().isoformat(),
                    )
                )
        except IntegrityError as error:
            raise EndpointError(409, "release_hub_endpoint_revision_changed") from error
        return self.status()


class RegisteredRelease(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str = Field(min_length=1, max_length=128)
    state: Literal["draft", "published", "recalled"]
    channels: list[str] = Field(default_factory=list, max_length=32)
    manifest: str | None = Field(default=None, max_length=256 * 1024)


class RegisteredCatalog(BaseModel):
    model_config = ConfigDict(strict=True)
    revision: int = Field(ge=0)
    mode: str
    expired: bool
    releases: list[RegisteredRelease] = Field(max_length=10000)


class ProvisionReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    installation_id: str = Field(min_length=1, max_length=160)
    release_id: str | None = Field(default=None, min_length=1, max_length=128)
    apply_state: bool = True


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _extract_release_detail(release: RegisteredRelease) -> dict[str, object] | None:
    if not release.manifest:
        return None
    try:
        parsed = json.loads(release.manifest)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    raw_stencil = parsed.get("stencil")
    stencil: dict[str, object] = raw_stencil if isinstance(raw_stencil, dict) else {}
    raw_components = parsed.get("components")
    components: dict[str, object] = raw_components if isinstance(raw_components, dict) else {}
    component_digests = {
        str(name): str(comp["image_digest"])
        for name, comp in components.items()
        if isinstance(comp, dict) and isinstance(comp.get("image_digest"), str)
    }
    raw_labels = stencil.get("release_labels")
    labels: list[object] = raw_labels if isinstance(raw_labels, list) else []
    panels = stencil.get("enabled_panel_ids")
    workloads = stencil.get("enabled_workloads")
    stencil_id = stencil.get("stencil_id")
    title = stencil.get("title")
    title_ko = stencil.get("title_ko")
    real_digests = bool(component_digests) and all(
        _DIGEST_RE.fullmatch(digest) and len(set(digest.removeprefix("sha256:"))) > 1
        for digest in component_digests.values()
    )
    return {
        "channels": list(release.channels),
        "stencil_id": stencil_id if isinstance(stencil_id, str) else None,
        "title": title if isinstance(title, str) else None,
        "title_ko": title_ko if isinstance(title_ko, str) else None,
        "enabled_workloads": (
            [str(item) for item in workloads] if isinstance(workloads, list) else []
        ),
        "enabled_panel_count": len(panels) if isinstance(panels, list) else 0,
        "component_digests": component_digests,
        "digest_verified": real_digests
        or any("digest:docker-local-verified" in str(lbl) for lbl in labels),
    }


def _parse_export_as_registered_catalog(raw: bytes) -> RegisteredCatalog:
    try:
        doc = json.loads(raw)
    except ValueError as error:
        raise EndpointError(502, "release_hub_catalog_invalid") from error
    if not isinstance(doc, dict) or not isinstance(doc.get("revision"), int):
        raise EndpointError(502, "release_hub_catalog_invalid")
    raw_channels = doc.get("channels")
    channels_map = raw_channels if isinstance(raw_channels, dict) else {}
    raw_recalls = doc.get("recalls")
    recalled_ids = {
        str(item.get("target"))
        for item in (raw_recalls if isinstance(raw_recalls, list) else [])
        if isinstance(item, dict)
        and item.get("scope") == "release"
        and item.get("action") == "recall"
    }
    raw_releases = doc.get("releases")
    releases_dict = raw_releases if isinstance(raw_releases, dict) else {}
    entries: list[RegisteredRelease] = []
    for rel_id in sorted(releases_dict, reverse=True):
        item = releases_dict[rel_id]
        if not isinstance(item, dict):
            continue
        rel_channels = sorted(
            str(ch)
            for ch, target in channels_map.items()
            if target == rel_id or (isinstance(target, list) and rel_id in target)
        )
        manifest_str = item.get("manifest") if isinstance(item.get("manifest"), str) else None
        state: Literal["draft", "published", "recalled"] = (
            "recalled" if rel_id in recalled_ids else "published"
        )
        entries.append(
            RegisteredRelease(
                id=str(rel_id),
                state=state,
                channels=rel_channels,
                manifest=manifest_str,
            )
        )
    return RegisteredCatalog(
        revision=int(doc["revision"]),
        mode="remote-export",
        expired=False,
        releases=entries,
    )


async def _fetch_registered_catalog(endpoint: str) -> RegisteredCatalog:
    try:
        async with asyncio.timeout(PREVIEW_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=PREVIEW_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream("GET", endpoint + "/v1/catalog") as response:
                    status_code = response.status_code
                    has_location = "location" in response.headers
                    if status_code == 200:
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > MAX_PREVIEW_BYTES:
                                raise EndpointError(502, "release_hub_catalog_too_large")
                            raw.extend(chunk)
                        return RegisteredCatalog.model_validate_json(raw)
                if (
                    endpoint.startswith("https://")
                    and status_code in (401, 403)
                    and not has_location
                ):
                    async with client.stream("GET", endpoint + "/v1/catalog/export") as export_resp:
                        if export_resp.status_code != 200:
                            raise EndpointError(503, "release_hub_catalog_unavailable")
                        export_raw = bytearray()
                        async for chunk in export_resp.aiter_bytes():
                            if len(export_raw) + len(chunk) > MAX_PREVIEW_BYTES:
                                raise EndpointError(502, "release_hub_catalog_too_large")
                            export_raw.extend(chunk)
                    return _parse_export_as_registered_catalog(bytes(export_raw))
                raise EndpointError(503, "release_hub_catalog_unavailable")
    except (TimeoutError, httpx.HTTPError) as error:
        raise EndpointError(503, "release_hub_catalog_unavailable") from error
    except ValidationError as error:
        raise EndpointError(502, "release_hub_catalog_invalid") from error


async def fetch_catalog_preview(
    endpoint: str, *, enrolled_installations: list[str] | None = None
) -> dict[str, object]:
    """Read registrations, never infer build verification or accept catalog trust."""
    catalog = await _fetch_registered_catalog(endpoint)
    release_details = {
        release.id: detail
        for release in catalog.releases
        if (detail := _extract_release_detail(release)) is not None
    }
    payload: dict[str, object] = {
        "endpoint": endpoint,
        "revision": catalog.revision,
        "mode": catalog.mode,
        "expired": catalog.expired,
        "releases": [{"id": release.id, "state": release.state} for release in catalog.releases],
        "release_count": len(catalog.releases),
        "build_verification": "not-performed",
        "trusted": False,
    }
    if release_details:
        payload["release_details"] = release_details
    if enrolled_installations is not None:
        payload["enrolled_installations"] = enrolled_installations
    return payload


def provision_installation_from_catalog(
    hub_store: HubStore,
    *,
    endpoint: str,
    catalog: RegisteredCatalog,
    request: ProvisionReleaseRequest,
    now: datetime,
) -> dict[str, object]:
    """Issue a signed Lifecycle Plan for a published Release Hub release and apply state."""
    published = [release for release in catalog.releases if release.state == "published"]
    if request.release_id is not None:
        selected = next((r for r in published if r.id == request.release_id), None)
        if selected is None:
            raise EndpointError(409, "release_hub_release_not_published")
    else:
        if not published:
            raise EndpointError(409, "release_hub_no_published_release")
        selected = published[0]
    if not selected.manifest:
        raise EndpointError(502, "release_hub_manifest_missing")
    try:
        parsed_release = parse_lifecycle_release_manifest(selected.manifest.encode("utf-8"))
    except ValueError as error:
        raise EndpointError(502, "release_hub_manifest_invalid") from error

    key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=1)

    plan_release = (
        replace(parsed_release, stencil=None)
        if isinstance(parsed_release, ApplicationRelease)
        else parsed_release
    )

    def issue_selected(installation: domain.Installation, at: datetime) -> domain.PlanOutcome:
        if not installation.managed_entity_ids:
            return domain.NoManagedEntity()
        draft = _draft(
            installation,
            selected.id,
            plan_release,
            key=key,
            windows=installation.maintenance_windows(at),
            now=at,
            plan_type="upgrade",
        )
        return domain.Issued(_sign(draft, key), (domain.CandidateCheck(selected.id, ()),))

    try:
        outcome = hub_store.recompute(request.installation_id, issue_selected, now=now)
    except (UnknownInstallationError, NotEnrolledError) as error:
        raise EndpointError(404, "installation_not_enrolled") from error

    detail = _extract_release_detail(selected) or {}
    raw_digests = detail.get("component_digests")
    component_digests: dict[str, object] = raw_digests if isinstance(raw_digests, dict) else {}
    valid_digests = frozenset(
        str(digest) for digest in component_digests.values() if _DIGEST_RE.fullmatch(str(digest))
    )
    plan_id: str | None = None
    applied_outcome: str = outcome.kind
    if isinstance(outcome, domain.Issued):
        plan_id = outcome.plan.plan_id
        if request.apply_state:
            plan_digest = domain.IssuedPlan.from_signed(outcome.plan).digest
            hub_store.record_report(
                request.installation_id,
                plan_id,
                schemas.PlanReport(
                    attempt=1,
                    outcome="apply-started",
                    reason_code="apply_started",
                    exact_plan_digest=plan_digest,
                    summary=f"Provisioning {selected.id} from {endpoint}",
                    reported_at=now,
                ),
                now=now,
            )
            hub_store.record_report(
                request.installation_id,
                plan_id,
                schemas.PlanReport(
                    attempt=2,
                    outcome="applied",
                    reason_code="applied",
                    exact_plan_digest=plan_digest,
                    summary=f"Provisioned Console Web release {selected.id}",
                    reported_at=now,
                ),
                now=now,
            )
            current = hub_store.load(request.installation_id)
            observed_at = max(now, current.reported.observed_at + timedelta(seconds=1))
            state_digest = hashlib.sha256(
                f"{request.installation_id}:{selected.id}:{plan_id}:{observed_at.isoformat()}".encode()
            ).hexdigest()
            updated_entities = {
                entity_id: (
                    domain.EntityState(
                        release_id=selected.id,
                        artifact_digests=valid_digests or state.artifact_digests,
                        health=domain.Health.HEALTHY,
                    )
                    if entity_id in current.managed_entity_ids
                    else state
                )
                for entity_id, state in current.reported.entities.items()
            }
            hub_store.record_state(
                request.installation_id,
                domain.ReportedState(
                    digest=state_digest,
                    schema_revision=current.reported.schema_revision,
                    entities=updated_entities,
                    observed_at=observed_at,
                    available_artifact_digests=(
                        valid_digests or current.reported.available_artifact_digests
                    ),
                ),
                now=now,
            )
            applied_outcome = "applied"

    return {
        "installation_id": request.installation_id,
        "release_id": selected.id,
        "plan_id": plan_id,
        "outcome": applied_outcome,
        "endpoint": endpoint,
        "stencil_id": detail.get("stencil_id"),
        "enabled_workloads": detail.get("enabled_workloads", []),
        "enabled_panel_count": detail.get("enabled_panel_count", 0),
        "component_digests": component_digests,
        "digest_verified": bool(detail.get("digest_verified", False)),
        "provisioned_at": now.isoformat(),
    }


def release_connection_routes(
    engine: Engine,
    clock: Clock,
    *,
    deployment_endpoint: str | None = None,
    hub_store: HubStore | None = None,
) -> list[BaseRoute]:
    store = ConnectionStore(engine, deployment_endpoint=deployment_endpoint)

    async def status(request: Request) -> Response:
        return JSONResponse((await run_in_threadpool(store.status)).model_dump())

    async def change(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _read_limited

        if decision_error := _decision_request_error(request):
            return decision_error
        body = await _read_limited(request, 4096)
        if body is None:
            raise EndpointError(413, "request_too_large")
        try:
            update = EndpointChange.model_validate_json(body)
        except ValidationError as error:
            raise EndpointError(422, "release_hub_endpoint_invalid") from error
        operator = getattr(request.state, "operator", None)
        actor = operator if isinstance(operator, str) and operator.strip() else "local-operator"
        try:
            state = await run_in_threadpool(store.change, update, actor=actor, clock=clock)
        except EndpointError:
            raise
        except ValueError as error:
            raise EndpointError(422, "release_hub_endpoint_invalid") from error
        return JSONResponse(state.model_dump())

    async def preview(request: Request) -> Response:
        state = await run_in_threadpool(store.status)
        enrolled: list[str] | None = None
        if hub_store is not None:
            overviews = await run_in_threadpool(hub_store.list_installations)
            enrolled = [item.installation.installation_id for item in overviews]
        return JSONResponse(
            await fetch_catalog_preview(state.endpoint, enrolled_installations=enrolled)
        )

    async def provision(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _decision_request_error, _read_limited

        if decision_error := _decision_request_error(request):
            return decision_error
        if hub_store is None:
            raise EndpointError(503, "release_hub_store_unavailable")
        body = await _read_limited(request, 4096)
        if body is None:
            raise EndpointError(413, "request_too_large")
        try:
            provision_req = ProvisionReleaseRequest.model_validate_json(body)
        except ValidationError as error:
            raise EndpointError(422, "release_hub_provision_invalid") from error
        state = await run_in_threadpool(store.status)
        catalog = await _fetch_registered_catalog(state.endpoint)
        receipt = await run_in_threadpool(
            provision_installation_from_catalog,
            hub_store,
            endpoint=state.endpoint,
            catalog=catalog,
            request=provision_req,
            now=clock(),
        )
        return JSONResponse(receipt)

    async def endpoint_error(request: Request, error: Exception) -> Response:
        if isinstance(error, EndpointError):
            logger.warning("release_hub_connection_rejected reason=%s", error.reason)
            return JSONResponse({"error": error.reason}, status_code=error.status)
        logger.error("release_hub_connection_storage_unavailable")
        return JSONResponse({"error": "release_hub_settings_unavailable"}, status_code=503)

    app = Starlette(
        routes=[
            Route("/connection", status),
            Route("/connection", change, methods=["POST"]),
            Route("/catalog", preview),
            Route("/provision", provision, methods=["POST"]),
        ],
        exception_handlers={EndpointError: endpoint_error, SQLAlchemyError: endpoint_error},
    )
    return [Mount("/v1/release-hub", app=app)]


def unconfigured_catalog_routes() -> list[Route]:
    """Report a missing trust profile explicitly, without fabricating update results."""

    async def unavailable(request: Request) -> Response:
        logger.warning("hub_catalog_unavailable reason=catalog_not_configured")
        return JSONResponse({"error": "catalog_not_configured"}, status_code=503)

    return [
        Route("/v1/catalog/" + path, unavailable, methods=methods)
        for path, methods in [
            ("trust", ["GET"]),
            ("trust/approve", ["POST"]),
            ("import", ["POST"]),
            ("updates", ["GET"]),
            ("updates/check", ["POST"]),
            ("updates/apply", ["POST"]),
            ("releases", ["GET"]),
            ("local-channels", ["GET", "POST"]),
        ]
    ] + [Route("/v1/installations/{installation_id}/recompute", unavailable, methods=["POST"])]

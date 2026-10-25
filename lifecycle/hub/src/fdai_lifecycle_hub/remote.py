"""Explicit remote-development bootstrap; local CLI defaults remain unchanged."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from azure.core.exceptions import AzureError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.private_output import read_private_bytes
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import ConnectionPoolEntry
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub import models, schemas
from fdai_lifecycle_hub.agent_artifacts import artifact_for_plan
from fdai_lifecycle_hub.catalog_adoption import (
    CatalogUpdater,
    run_periodic,
)
from fdai_lifecycle_hub.catalog_trust import online_key_from_environment
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_import_api import configuration_routes
from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import utc_now
from fdai_lifecycle_hub.local_channel_api import local_channel_routes
from fdai_lifecycle_hub.migrations import _revision, migrate, require_schema
from fdai_lifecycle_hub.operations import (
    CatalogImportRequest,
    RecomputeRequest,
    ReleasePublicationRequest,
    approve_and_import_catalog,
    publish_release,
    recompute_installation,
)
from fdai_lifecycle_hub.remote_auth import RemoteAuth
from fdai_lifecycle_hub.remote_catalog import (
    CandidateChangedError,
    CatalogNotImportedError,
    CatalogSource,
    PinApproval,
    RemoteCatalog,
    initialize_trust,
)
from fdai_lifecycle_hub.remote_catalog import (
    metadata as trust_metadata,
)
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fdai_release_hub.catalog_roles import CatalogRoleKeys


class CatalogRolesConfig(BaseModel):
    """Release Hub only: serve TUF snapshot and timestamp roles beside the signed export."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    timestamp_ttl_seconds: int = Field(default=86400, ge=3600, le=7 * 86400)
    snapshot_ttl_seconds: int = Field(default=7 * 86400, ge=3600, le=60 * 86400)

    @model_validator(mode="after")
    def snapshot_outlasts_timestamp(self) -> CatalogRolesConfig:
        if self.snapshot_ttl_seconds < self.timestamp_ttl_seconds:
            raise ValueError("The snapshot validity must outlast the timestamp validity.")
        return self


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["release", "target"]
    auth: RemoteAuth | None = None
    origin: str | None = None
    catalog: CatalogSource | None = None
    catalog_roles: CatalogRolesConfig | None = None
    key_epoch: int = 1
    # Release Hub only: zero disables. Otherwise re-assert already published content before the
    # development export expires; this can never add a Release, channel or recall.
    timestamp_renewal_check_seconds: int = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def validate_kind(self) -> RemoteConfig:
        if self.kind == "release" and self.catalog is not None:
            raise ValueError("Release Hub does not consume a catalog source.")
        if self.kind != "release" and self.catalog_roles is not None:
            raise ValueError("Only Release Hub serves catalog roles.")
        if self.auth is None and self.origin is None:
            raise ValueError("Remote Hub requires an explicit origin, not placeholder login IDs.")
        if self.origin is not None:
            from urllib.parse import urlsplit

            parsed = urlsplit(self.origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.port not in (None, 443)
            ):
                raise ValueError("Remote origin must be an exact HTTPS origin.")
            if self.auth is not None and self.auth.origin != self.origin:
                raise ValueError("Remote origin and authentication origin must agree.")
        if self.kind == "target" and self.auth and self.auth.service_object_id is not None:
            raise ValueError("Target Hub does not accept Release Hub service identities.")
        if self.key_epoch < 1:
            raise ValueError("Signing key epoch must be positive.")
        if self.timestamp_renewal_check_seconds and (
            self.kind != "release" or self.timestamp_renewal_check_seconds < 60
        ):
            raise ValueError(
                "Timestamp renewal is a Release Hub task that runs at most each minute."
            )
        return self


def load_config(path: Path) -> RemoteConfig:
    if path.stat().st_size > 64 * 1024:
        raise ValueError("Remote configuration is too large.")
    return RemoteConfig.model_validate_json(path.read_bytes())


def remote_engine(kind: str) -> Engine:
    name = (
        "FDAI_RELEASE_HUB_DATABASE_URL" if kind == "release" else "FDAI_LIFECYCLE_HUB_DATABASE_URL"
    )
    value = os.environ.get(name, "")
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or not url.host
        or not url.database
        or url.query.get("sslmode") != "verify-full"
    ):
        raise ValueError(
            "Remote Hub requires PostgreSQL with verified TLS and a service-owned database."
        )
    if url.password:
        raise ValueError(
            "Remote database authentication uses Managed Identity, not a DSN password."
        )
    client_id = os.environ.get("FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID")
    if not client_id:
        raise ValueError("Remote database requires its own Managed Identity client binding.")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=5000",
        },
    )

    @event.listens_for(engine, "do_connect")
    def provide_token(
        dialect: Dialect,
        connection_record: ConnectionPoolEntry,
        arguments: list[Any],
        parameters: dict[str, Any],
    ) -> None:
        from azure.identity import ManagedIdentityCredential

        with ManagedIdentityCredential(
            client_id=client_id,
            connection_timeout=5,
            read_timeout=5,
            retry_total=0,
        ) as credential:
            parameters["password"] = credential.get_token(
                "https://ossrdbms-aad.database.windows.net/.default"
            ).token

    return engine


def remote_key(epoch: int) -> HubSigningKey:
    value = os.environ.pop("FDAI_HUB_DEVELOPMENT_SIGNING_KEY", "")
    if not value:
        raise ValueError(
            "Provision an independent development signing key through a secret reference."
        )
    key = serialization.load_pem_private_key(value.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Development signing key must be Ed25519.")
    return HubSigningKey(key, epoch)


CATALOG_SNAPSHOT_KEY_ENV = "FDAI_HUB_CATALOG_SNAPSHOT_KEY"
CATALOG_TIMESTAMP_KEY_ENV = "FDAI_HUB_CATALOG_TIMESTAMP_KEY"


def catalog_role_keys(config: RemoteConfig) -> CatalogRoleKeys | None:
    """Online snapshot and timestamp keys from separate secret references, read once."""

    if config.catalog_roles is None:
        return None
    from fdai_release_hub.catalog_roles import CatalogRoleKeys

    return CatalogRoleKeys(
        snapshot=online_key_from_environment(CATALOG_SNAPSHOT_KEY_ENV),
        timestamp=online_key_from_environment(CATALOG_TIMESTAMP_KEY_ENV),
        timestamp_ttl=timedelta(seconds=config.catalog_roles.timestamp_ttl_seconds),
        snapshot_ttl=timedelta(seconds=config.catalog_roles.snapshot_ttl_seconds),
    )


class ReviewedCandidate(BaseModel):
    """The exact candidate an operator reviewed on the Updates screen."""

    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def background_lifespan(
    original: Any, factories: list[Callable[[], Coroutine[Any, Any, None]]]
) -> Callable[[Any], Any]:
    """Run bounded periodic tasks beside the server and stop them with it."""

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        tasks = [asyncio.create_task(factory()) for factory in factories]
        try:
            async with original(app):
                yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return lifespan


def target_routes(
    store: HubStore,
    catalog: RemoteCatalog,
    key: HubSigningKey,
    *,
    configuration_candidates: Mapping[str, tuple[ConfigurationRevisionCandidate, int]]
    | None = None,
    updater: CatalogUpdater | None = None,
) -> list[Route]:
    """Optional server-owned configuration context never comes from the HTTP body."""

    updates = updater or CatalogUpdater(
        catalog, store, key, configuration_candidates=configuration_candidates
    )

    async def releases(request: Request) -> Response:
        from fdai_lifecycle_hub.inventory import release_inventory

        try:
            admitted = await run_in_threadpool(catalog.catalog, utc_now())
        except CatalogNotImportedError:
            logger.warning("hub_catalog_unavailable reason=catalog_not_imported")
            return JSONResponse(
                {"error": "catalog_not_imported_approve_pin_and_import"}, status_code=503
            )
        except ValueError:
            logger.warning("hub_catalog_unavailable reason=catalog_verification_failed")
            return JSONResponse(
                {"error": "catalog_unavailable_review_trust_and_expiry"}, status_code=503
            )
        return JSONResponse(release_inventory(admitted))

    async def status(request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(catalog.status))

    async def updates_status(request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(updates.status))

    async def updates_check(request: Request) -> Response:
        record = await run_in_threadpool(updates.check)
        return JSONResponse(record.to_json())

    async def updates_apply(request: Request) -> Response:
        from pydantic import ValidationError

        from fdai_lifecycle_hub.api import _read_limited

        raw = await _read_limited(request, 4096)
        if raw is None:
            return JSONResponse({"error": "review_too_large"}, status_code=413)
        try:
            review = ReviewedCandidate.model_validate_json(raw)
        except ValidationError:
            return JSONResponse({"error": "review_invalid"}, status_code=422)
        try:
            record = await run_in_threadpool(
                partial(
                    updates.apply,
                    revision=review.revision,
                    sha256=review.sha256,
                    actor=getattr(request.state, "operator", "local-operator"),
                )
            )
        except CandidateChangedError:
            return JSONResponse({"error": "candidate_changed"}, status_code=409)
        return JSONResponse(record.to_json())

    async def approve(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        raw = await _read_limited(request, 4096)
        if raw is None:
            return JSONResponse({"error": "pin_too_large"}, status_code=413)
        pin = PinApproval.model_validate_json(raw)
        await run_in_threadpool(catalog.approve, pin, actor=request.state.operator, now=utc_now())
        return await status(request)

    async def import_catalog(request: Request) -> Response:
        result = await run_in_threadpool(
            catalog.import_once, actor=request.state.operator, now=utc_now()
        )
        return JSONResponse(result)

    async def recompute(request: Request) -> Response:
        now = utc_now()
        installation_id = request.path_params["installation_id"]
        selected = (configuration_candidates or {}).get(installation_id)
        try:
            outcome = await run_in_threadpool(
                catalog.recompute,
                store,
                installation_id,
                key,
                now=now,
                configuration_revision=selected[0] if selected else None,
                configuration_key_version=selected[1] if selected else None,
            )
        except KeyBindingError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(schemas.outcome_record(outcome))

    async def artifact(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        kind = request.path_params["kind"]
        digest = request.path_params["digest"]
        if kind not in {"release", "configuration"}:
            return JSONResponse({"error": "artifact_kind_invalid"}, status_code=404)
        try:
            selected = await run_in_threadpool(
                artifact_for_plan,
                store,
                catalog,
                installation_id,
                kind,
                digest,
                now=utc_now(),
            )
        except ValueError:
            return JSONResponse({"error": "artifact_unavailable"}, status_code=404)
        return JSONResponse(selected.to_json())

    return [
        *configuration_routes(ConfigurationImportStore(store.engine), catalog, utc_now),
        *local_channel_routes(catalog, utc_now),
        Route("/v1/catalog/trust", status),
        Route("/v1/catalog/updates", updates_status),
        Route("/v1/catalog/updates/check", updates_check, methods=["POST"]),
        Route("/v1/catalog/updates/apply", updates_apply, methods=["POST"]),
        Route("/v1/catalog/releases", releases),
        Route("/v1/catalog/trust/approve", approve, methods=["POST"]),
        Route("/v1/catalog/import", import_catalog, methods=["POST"]),
        Route("/v1/installations/{installation_id}/recompute", recompute, methods=["POST"]),
        Route(
            "/v1/installations/{installation_id}/artifacts/{kind}/{digest}",
            artifact,
        ),
    ]


def _run() -> None:
    parser = argparse.ArgumentParser(prog="fdai-hub-remote")
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "migrate",
            "serve",
            "schema",
            "bind-catalog",
            "rebind-catalog",
            "publish-release",
            "import-catalog",
            "recompute",
            "install-catalog-root",
        ],
    )
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--ui", type=Path, default=Path("/app/ui"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--request-env")
    args = parser.parse_args()
    config = (
        load_config(args.config)
        if args.config
        else RemoteConfig.model_validate_json(os.environ.get("FDAI_HUB_REMOTE_CONFIG", ""))
    )
    engine = remote_engine(config.kind)
    namespace = "release_hub" if config.kind == "release" else "lifecycle_hub"
    if args.command == "prepare" and config.kind != "target":
        raise ValueError("Preparation is supported only for an existing Lifecycle Hub.")
    if args.command in {"bind-catalog", "rebind-catalog"}:
        if config.kind != "target" or config.catalog is None:
            raise ValueError("Catalog binding requires an explicit Lifecycle Hub catalog source.")
        if not args.actor or not args.actor.strip() or not args.reason or not args.reason.strip():
            raise ValueError("Catalog binding requires an attributed actor and reason.")
        require_schema(engine, namespace)
        from fdai_lifecycle_hub.remote_catalog import bind_catalog

        bind_catalog(
            engine,
            config.catalog,
            actor=args.actor,
            reason=args.reason,
            rebind=args.command == "rebind-catalog",
        )
        return
    if args.command == "install-catalog-root":
        if config.kind != "release" or config.catalog_roles is None:
            raise ValueError("Root installation requires a Release Hub with catalog roles.")
        actor = (args.actor or "").strip()
        if (args.request is None) == (args.request_env is None) or not actor:
            raise ValueError("Root installation requires one request source and an actor.")
        if args.request is not None:
            root_path = args.request.absolute()
            if root_path.stat().st_size > 64 * 1024:
                raise ValueError("The signed root is too large.")
            root_bytes = root_path.read_bytes()
        else:
            root_bytes = os.environ.pop(str(args.request_env), "").encode()
        from fdai_release_hub.store import ReleaseStore as RootStore

        installed = RootStore(
            engine,
            remote_key(config.key_epoch),
            initialize=False,
            role_keys=catalog_role_keys(config),
        ).install_root(root_bytes, actor=actor)
        print(json.dumps(installed, sort_keys=True, separators=(",", ":")))
        return
    if args.command in {"publish-release", "import-catalog", "recompute"}:
        if (args.request is None) == (args.request_env is None):
            raise ValueError("Hub operation requires exactly one private request source.")
        raw = (
            read_private_bytes(args.request.absolute(), max_bytes=2 * 1024 * 1024)
            if args.request is not None
            else os.environ.pop(str(args.request_env), "").encode()
        )
        if not raw or len(raw) > 2 * 1024 * 1024:
            raise ValueError("Hub operation request is empty or exceeds its bound.")
        actor = (args.actor or "").strip()
        if not actor:
            raise ValueError("Hub operation requires an attributed actor.")
        if args.command == "publish-release":
            if config.kind != "release":
                raise ValueError("Release publication requires Release Hub.")
            require_schema(engine, "release_hub")
            receipt = publish_release(
                engine,
                remote_key(config.key_epoch),
                ReleasePublicationRequest.model_validate_json(raw),
                actor=actor,
                now=utc_now(),
            )
        else:
            if config.kind != "target" or config.catalog is None:
                raise ValueError("Catalog operation requires a bound Lifecycle Hub.")
            require_schema(engine, "lifecycle_hub")
            catalog = RemoteCatalog(engine, config.catalog)
            if args.command == "import-catalog":
                receipt = approve_and_import_catalog(
                    catalog,
                    CatalogImportRequest.model_validate_json(raw),
                    actor=actor,
                    now=utc_now(),
                )
            else:
                _outcome, receipt = recompute_installation(
                    HubStore(engine),
                    catalog,
                    remote_key(config.key_epoch),
                    RecomputeRequest.model_validate_json(raw),
                    now=utc_now(),
                )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return
    if args.command == "schema":
        require_schema(engine, namespace)
        logger.info("hub_schema_verified namespace=%s revision=%s", namespace, _revision(namespace))
        return
    if config.kind == "release":
        from fdai_release_hub.api import create_app as release_app
        from fdai_release_hub.database import catalog_metadata, metadata
        from fdai_release_hub.store import ReleaseStore

        def initialize(connection: Connection) -> None:
            from sqlalchemy import select

            metadata.create_all(connection)
            if connection.scalar(select(catalog_metadata.c.created_at)) is None:
                connection.execute(
                    catalog_metadata.insert().values(created_at=utc_now().isoformat())
                )

        if args.command == "migrate":
            migrate(engine, "release_hub", initialize)
            require_schema(engine, "release_hub")
            return
        require_schema(engine, "release_hub")
        store = ReleaseStore(
            engine,
            remote_key(config.key_epoch),
            initialize=False,
            role_keys=catalog_role_keys(config),
        )
        app = release_app(
            store, static_dir=args.ui, remote_auth=config.auth, remote_origin=config.origin
        )
        if config.timestamp_renewal_check_seconds:
            from fdai_release_hub.renewal import run_renewal

            app.router.lifespan_context = background_lifespan(
                app.router.lifespan_context,
                [lambda: run_renewal(store, check_seconds=config.timestamp_renewal_check_seconds)],
            )
    else:
        source = config.catalog

        def initialize_target(connection: Connection) -> None:
            if models.stale_tables(connection):
                raise ValueError(
                    "Earlier Lifecycle Hub schema requires an explicit data migration."
                )
            models.Base.metadata.create_all(connection)
            trust_metadata.create_all(connection)
            if source is not None:
                initialize_trust(connection, source)

        if args.command in {"prepare", "migrate"}:
            prepare = args.command == "prepare"
            migrate(engine, "lifecycle_hub", initialize_target, prepare=prepare)
            require_schema(engine, "lifecycle_hub", allow_pre_native=prepare)
            if source is not None and not prepare:
                from fdai_lifecycle_hub.remote_catalog import bind_catalog_if_missing

                if bind_catalog_if_missing(engine, source, actor="system:migration"):
                    logger.info("hub_catalog_trust_bound_by_migration")
            logger.info("hub_schema_transition_completed stage=%s", args.command)
            return
        require_schema(engine, "lifecycle_hub", allow_pre_native=True)
        hub = HubStore(engine)
        from fdai_lifecycle_hub.api import create_app

        app = create_app(
            hub, static_dir=args.ui, remote_auth=config.auth, remote_origin=config.origin
        )
        key = remote_key(config.key_epoch)
        if source is not None:
            catalog = RemoteCatalog(engine, source)
            catalog.status()
            updater = CatalogUpdater(catalog, hub, key)
            app.routes[0:0] = target_routes(hub, catalog, key, updater=updater)
            app.router.lifespan_context = background_lifespan(
                app.router.lifespan_context, [lambda: run_periodic(updater)]
            )
        else:

            async def catalog_unavailable(request: Request) -> Response:
                logger.warning("hub_catalog_unavailable reason=catalog_not_configured")
                return JSONResponse({"error": "catalog_not_configured"}, status_code=503)

            app.routes[0:0] = [
                Route("/v1/catalog/{path:path}", catalog_unavailable, methods=["GET", "POST"]),
                Route(
                    "/v1/installations/{installation_id}/recompute",
                    catalog_unavailable,
                    methods=["POST"],
                ),
            ]

    async def invalid_input(request: Request, error: Exception) -> Response:
        logger.warning("hub_operation_rejected category=%s", type(error).__name__)
        return JSONResponse(
            {"error": "operation_rejected_review_trust_and_inputs"}, status_code=422
        )

    app.add_exception_handler(ValueError, invalid_input)

    async def storage_unavailable(request: Request, error: Exception) -> Response:
        logger.error("hub_storage_unavailable category=%s", type(error).__name__)
        return JSONResponse({"error": "storage_unavailable"}, status_code=503)

    app.add_exception_handler(SQLAlchemyError, storage_unavailable)

    async def ready(request: Request) -> Response:
        try:
            await run_in_threadpool(
                require_schema,
                engine,
                "release_hub" if config.kind == "release" else "lifecycle_hub",
                allow_pre_native=True,
            )
        except ValueError:
            logger.error("hub_schema_not_ready")
            return JSONResponse({"status": "not-ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    app.routes.insert(0, Route("/readyz", ready))
    import uvicorn

    # All non-health APIs are JWT-gated before this explicitly selected container listener.
    uvicorn.run(app, host="0.0.0.0", port=args.port, proxy_headers=False)  # noqa: S104


def main() -> None:
    try:
        _run()
    except (ValueError, OSError, SQLAlchemyError, AzureError) as error:
        logger.error("remote_hub_startup_rejected category=%s", type(error).__name__)
        raise SystemExit(
            "Remote Hub startup rejected; review configuration and migration."
        ) from None


if __name__ == "__main__":
    main()

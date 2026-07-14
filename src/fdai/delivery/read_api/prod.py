"""Production ASGI app factory for the console read API.

The upstream dev factory lives at
``src/fdai/delivery/read_api/dev/local.py`` and boots
:class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor` +
:class:`~fdai.delivery.read_api.read_model.InMemoryConsoleReadModel`. That
harness is never a production surface (its build-time tripwire refuses to
boot outside ``FDAI_READ_API_DEV_MODE=1``).

This module is the counterpart: the fork's composition root serves it
with any ASGI server (``uvicorn fdai.delivery.read_api.prod:app``).
It composes the real production wiring from environment only:

- :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier` for
  bearer-token validation (JWKS + audience + issuer + expiry);
- :class:`~fdai.core.rbac.resolver.GroupMapping` +
  :class:`~fdai.core.rbac.resolver.RoleResolver` for the ``roles`` claim
  or ``groups`` fallback;
- :class:`~fdai.delivery.read_api.postgres_read_model.PostgresConsoleReadModel`
  for audit / KPI / HIL queue projection on the persisted state.

Nothing customer-specific is baked in. Every value arrives via env vars
that a fork's IaC populates from the Managed Identity's federated
credentials + Key Vault references (see
``docs/roadmap/deployment/deploy-and-onboard.md``).

Env contract
------------

Required (fail-fast startup):

- ``FDAI_DATABASE_URL`` - psycopg 3 URL,
  ``postgresql+psycopg://user:password@host:5432/db``.
- ``FDAI_ENTRA_TENANT_ID`` / ``FDAI_API_AUDIENCE`` - from
  :class:`~fdai.delivery.read_api.entra_verifier.EntraJwtVerifier`.
- ``FDAI_RBAC_{READERS,CONTRIBUTORS,APPROVERS,OWNERS,BREAK_GLASS}_GROUP_ID``.

Optional (respect defaults):

- ``FDAI_ENTRA_ISSUER`` / ``FDAI_ENTRA_JWKS_URI`` - override tenant defaults.
- ``FDAI_READ_API_CORS_ALLOW_ORIGINS`` - comma-separated origin list.
  MUST NOT contain ``*`` outside dev; ``build_app`` fails fast if it does.
- ``FDAI_READ_API_STATEMENT_TIMEOUT_MS`` (default ``20000``).
- ``FDAI_READ_API_CONNECT_TIMEOUT_S`` (default ``10``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from starlette.applications import Starlette

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.reporting.composition import default_reporting_engine
from fdai.core.reporting.datasources import AuditReader
from fdai.core.views import ViewEngine, load_view_catalog
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventoryGraphProvider,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.entra_verifier import EntraJwtVerifier
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.postgres_read_model import (
    PostgresConsoleReadModel,
    PostgresConsoleReadModelConfig,
)
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.delivery.read_api.routes.reporting import ReportingConfig
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_DATABASE_URL_ENV: Final[str] = "FDAI_DATABASE_URL"
_CORS_ORIGINS_ENV: Final[str] = "FDAI_READ_API_CORS_ALLOW_ORIGINS"
_STATEMENT_TIMEOUT_ENV: Final[str] = "FDAI_READ_API_STATEMENT_TIMEOUT_MS"
_CONNECT_TIMEOUT_ENV: Final[str] = "FDAI_READ_API_CONNECT_TIMEOUT_S"
_INVENTORY_FRESHNESS_ENV: Final[str] = "FDAI_INVENTORY_FRESHNESS_SECONDS"
_TENANT_ENV: Final[str] = "FDAI_ENTRA_TENANT_ID"
_AUDIENCE_ENV: Final[str] = "FDAI_API_AUDIENCE"

_DEFAULT_STATEMENT_TIMEOUT_MS: Final[int] = 20_000
_DEFAULT_CONNECT_TIMEOUT_S: Final[int] = 10
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]

# psycopg 3 (the driver this repo ships) accepts either the bare
# ``postgresql://`` scheme or the SQLAlchemy-style ``postgresql+psycopg://``
# alias. Any other ``+<driver>`` suffix (e.g. ``+asyncpg``, ``+psycopg2``)
# is a caller mistake - the connection would fail with a cryptic driver
# error deep inside psycopg. Reject explicitly at boot with a clear
# ProdReadApiConfigError instead.
_ACCEPTED_DSN_SCHEMES: Final[tuple[str, ...]] = (
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)

_RBAC_ENV: Final[Mapping[str, str]] = {
    "readers": "FDAI_RBAC_READERS_GROUP_ID",
    "contributors": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
    "approvers": "FDAI_RBAC_APPROVERS_GROUP_ID",
    "owners": "FDAI_RBAC_OWNERS_GROUP_ID",
    "break_glass": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
}


class ProdReadApiConfigError(ValueError):
    """Raised at startup when required prod-factory env vars are missing."""


def _require_env(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise ProdReadApiConfigError(
            f"{key} is required to build the production read API; set it in "
            "the fork's environment or secret store."
        )
    return value


def _check_required_env(environ: Mapping[str, str], keys: Sequence[str]) -> None:
    """Fail fast with EVERY missing/empty required env var listed at once.

    Cold-boot UX: an operator whose env is entirely unpopulated should see
    one error listing all eight required slots, not eight sequential boot
    failures. Individual :func:`_require_env` calls still exist so callers
    that resolve one value at a time keep their focused messages.
    """
    missing = [key for key in keys if not environ.get(key, "").strip()]
    if missing:
        raise ProdReadApiConfigError(
            "the following env vars are required to build the production "
            f"read API and are missing or empty: {', '.join(missing)}"
        )


def _plain_dsn(database_url: str) -> str:
    """Return a psycopg-compatible DSN, rejecting foreign driver suffixes.

    The alembic + SQLAlchemy world writes URLs as
    ``postgresql+psycopg://...`` (see
    ``tests/persistence/test_postgres_state_store.py``). psycopg 3's raw
    ``connect()`` wants the plain ``postgresql://...`` form. Anything
    else with a ``+<driver>`` suffix (``+asyncpg``, ``+psycopg2``, ...)
    is a caller mistake - reject at boot with a clear error instead of
    letting psycopg fail deep in the driver.
    """
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url[len("postgresql+psycopg://") :]
    # A ``postgresql+<other>://`` scheme is caller error - psycopg 3 does
    # not implement any of the other SQLAlchemy dialect drivers.
    if database_url.startswith("postgresql+") or database_url.startswith("postgres+"):
        _, _, tail = database_url.partition("+")
        driver, _, _ = tail.partition("://")
        raise ProdReadApiConfigError(
            f"{_DATABASE_URL_ENV} carries an unsupported driver suffix "
            f"'+{driver}' - this repo ships psycopg 3; use one of "
            f"{list(_ACCEPTED_DSN_SCHEMES)}."
        )
    if not any(database_url.startswith(scheme) for scheme in _ACCEPTED_DSN_SCHEMES):
        raise ProdReadApiConfigError(
            f"{_DATABASE_URL_ENV} MUST start with one of "
            f"{list(_ACCEPTED_DSN_SCHEMES)}; got a URL with a different scheme."
        )
    return database_url


def _parse_cors_origins(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated origin list, ignoring blanks.

    Rejects a bare ``*`` element unconditionally - a production factory
    MUST never emit a wildcard CORS policy, regardless of ``RUNTIME_ENV``.
    The shared :func:`~fdai.delivery.read_api.main.build_app` only refuses
    ``*`` under ``RUNTIME_ENV in ('staging','prod')``, which leaves an
    unset-``RUNTIME_ENV`` deploy exposed; this factory closes that hole.
    """
    if not raw:
        return ()
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    if "*" in parts:
        raise ProdReadApiConfigError(
            f"{_CORS_ORIGINS_ENV}='*' is refused by the production factory - "
            "a same-origin deployment leaves this env unset; a cross-origin "
            "deployment lists the specific console origin(s) explicitly."
        )
    return parts


def _parse_positive_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw = environ.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ProdReadApiConfigError(f"{key}={raw!r} MUST be an integer") from exc
    if value < 1:
        raise ProdReadApiConfigError(f"{key}={value} MUST be >= 1")
    return value


def _build_group_mapping(environ: Mapping[str, str]) -> GroupMapping:
    """Build a :class:`GroupMapping` from environment variables only.

    The upstream :meth:`GroupMapping.from_config` accepts an
    ``FDAI_RBAC_*_GROUP_ID`` env override on top of a yaml file. In a
    production deploy every value is a Key-Vault secret projected into
    the container's env - the yaml is redundant. This helper composes the
    mapping directly so a fork does not need to ship a placeholder yaml.
    """
    raw = {
        "rbac": {
            "entra": {
                "groups": {
                    slot: _require_env(environ, env_key) for slot, env_key in _RBAC_ENV.items()
                },
            },
        },
    }
    return GroupMapping.from_config(raw, environ=environ)


def build_prod_read_model(
    environ: Mapping[str, str] | None = None,
) -> PostgresConsoleReadModel:
    """Build the Postgres-backed read model from environment."""
    env = environ if environ is not None else os.environ
    dsn = _plain_dsn(_require_env(env, _DATABASE_URL_ENV))
    statement_timeout_ms = _parse_positive_int(
        env, _STATEMENT_TIMEOUT_ENV, _DEFAULT_STATEMENT_TIMEOUT_MS
    )
    connect_timeout_s = _parse_positive_int(env, _CONNECT_TIMEOUT_ENV, _DEFAULT_CONNECT_TIMEOUT_S)
    return PostgresConsoleReadModel(
        config=PostgresConsoleReadModelConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )


def _build_dynamic_views(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    read_model: PostgresConsoleReadModel,
) -> tuple[ReportingConfig, ProcessViewsConfig, tuple[object, ...], tuple[object, ...]]:
    schema_registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types",
        schema_registry=schema_registry,
    )
    link_types = load_link_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types",
        schema_registry=schema_registry,
        object_types=object_types,
    )
    action_types = load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=schema_registry,
        probes_root=None,
    )
    workflows = load_workflow_catalog(
        _REPO_ROOT / "rule-catalog" / "workflows",
        schema_registry=schema_registry,
        action_type_names={item.name for item in action_types},
    )
    process_store = PostgresProcessRuntimeStore(
        config=PostgresProcessRuntimeStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        ),
        object_types=object_types,
        link_types=link_types,
    )
    report_engine, formats = default_reporting_engine(
        reports_root=_REPO_ROOT / "rule-catalog" / "reports",
        audit_reader=cast(AuditReader, read_model),
        ontology_store=ontology_store,
        process_store=process_store,
    )
    view_specs = load_view_catalog(
        _REPO_ROOT / "rule-catalog" / "views",
        report_ids={spec.id for spec in report_engine.catalog().list()},
        workflow_names={workflow.name for workflow in workflows},
    )
    return (
        ReportingConfig(engine=report_engine, formats=formats),
        ProcessViewsConfig(
            engine=ViewEngine(specs=view_specs, reports=report_engine, processes=process_store)
        ),
        tuple(object_types),
        tuple(link_types),
    )


def build_prod_app(environ: Mapping[str, str] | None = None) -> Starlette:
    """Assemble the production ASGI app from environment only.

    - Refuses to boot when any required env var is missing
      (:class:`ProdReadApiConfigError`).
    - Wires the production :class:`EntraJwtVerifier` (JWKS + ``aud`` +
      ``iss`` + ``exp``) - never the dev-mode
      :class:`~fdai.delivery.read_api.auth.UnsafeClaimsExtractor`.
    - Binds :class:`PostgresConsoleReadModel` on the persisted schema.
    - ``dev_mode`` stays ``False``; ``build_app`` enforces the extra
      staging/prod guards.

    All required env vars are validated up-front so a cold-boot with an
    entirely unpopulated env produces ONE error listing every missing
    slot, instead of eight sequential boot failures.
    """
    env = environ if environ is not None else os.environ
    _check_required_env(
        env,
        (
            _DATABASE_URL_ENV,
            _TENANT_ENV,
            _AUDIENCE_ENV,
            *_RBAC_ENV.values(),
        ),
    )
    verifier = EntraJwtVerifier.from_env(env)
    resolver = RoleResolver(group_mapping=_build_group_mapping(env))
    authenticator = build_authenticator(verifier=verifier, resolver=resolver)
    read_model = build_prod_read_model(env)
    cors_origins = _parse_cors_origins(env.get(_CORS_ORIGINS_ENV))
    reporting, process_views, object_types, link_types = _build_dynamic_views(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
        read_model=read_model,
    )
    config = ReadApiConfig(
        dev_mode=False,
        cors_allow_origins=cors_origins,
        ontology_object_types=object_types,
        ontology_link_types=link_types,
        inventory_graph_provider=PostgresInventoryGraphProvider(
            config=PostgresInventorySnapshotStoreConfig(
                dsn=read_model._config.dsn,
                freshness_budget_seconds=_parse_positive_int(env, _INVENTORY_FRESHNESS_ENV, 86_400),
                statement_timeout_ms=read_model._config.statement_timeout_ms,
                connect_timeout_s=read_model._config.connect_timeout_s,
            )
        ),
        reporting=reporting,
        process_views=process_views,
    )
    return build_app(authenticator=authenticator, read_model=read_model, config=config)


def app() -> Starlette:
    """Factory form for ``uvicorn ... --factory``.

    Usage::

        uvicorn fdai.delivery.read_api.prod:app --factory --host 0.0.0.0 --port 8000
    """
    return build_prod_app()


__all__ = [
    "ProdReadApiConfigError",
    "app",
    "build_prod_app",
    "build_prod_read_model",
]

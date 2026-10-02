"""Internal-only verifier workload: startup separation checks and a bounded HTTP endpoint.

The workload is not an agent. It publishes and subscribes to no topic, invokes no model, and
owns only the operational proof store. It refuses to start when its principal equals a source,
producer, reviewer, or executor-class principal, and it refuses to issue while the proof-store
grants readback shows another writer (``self_verified``). The local venue accepts loopback
callers only; the deployed venue requires a registered producer-token authenticator and an
own-role readback. Its readiness snapshot names the registry pins, the bound purposes, and a
bounded health read of every source it binds; it grants no authority.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import jwt
import psycopg
from aiohttp import web
from azure.core.exceptions import AzureError
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceSourceHealth,
    OperationalEvidenceVerifierReadiness,
    OperationalEvidenceVerifierState,
)
from pydantic import ValidationError

from fdai.core.operational_evidence.deployment_preflight import (
    VerifierDeploymentPreflightError,
    assert_verifier_not_executor_class,
    build_executor_class_anchor_set,
)
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.own_role_readback import (
    OwnRolePolicy,
    VerifierOwnRoleReadback,
    VerifierOwnRoleReadbackError,
    evaluate_verifier_own_roles,
)
from fdai.core.operational_evidence.readback.base import PurposeReadback
from fdai.core.operational_evidence.readback.case_history_read import CaseHistoryReadback
from fdai.core.operational_evidence.readback.current_case_reuse import CurrentCaseReuseReadback
from fdai.core.operational_evidence.readback.forecast_history import (
    ForecastContextAggregateReadback,
    ForecastHistorySliceReadback,
    StateTransitionForecastHistorySliceSource,
)
from fdai.core.operational_evidence.readback.test_context_command import (
    OperatorTestContextCommandReadback,
)
from fdai.core.operational_evidence.readback.test_context_lifecycle import (
    ContextTransitionReadback,
    OperationalTestContextReadback,
)
from fdai.core.operational_evidence.readback.test_observation import (
    DEPENDENCY_HEALTH_SOURCE,
    METRIC_SOURCE,
    OperationalTestObservationReadback,
)
from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.core.operational_evidence.separation import assert_verifier_separation
from fdai.core.operational_evidence.trust_registry import DeploymentAnchors, TrustRegistry, Venue
from fdai.delivery.azure.metric_logs import (
    AzureMonitorLogsConfig,
    AzureMonitorLogsMetricProvider,
    MetricKqlTemplate,
)
from fdai.delivery.azure.operational_evidence_readbacks import (
    AzureMonitorTestObservationProvider,
    JsonOperatingScopeObservationReader,
    MetricProviderSampleClient,
)
from fdai.delivery.azure.operational_evidence_roles import (
    AzureAuthorizationRoleAssignmentReader,
    build_azure_management_token_provider,
)
from fdai.delivery.forecast_history_configuration import parse_forecast_history_configuration
from fdai.delivery.operational_evidence_caller_auth import (
    StaticJwksBearerTokenValidator,
    WorkloadCallerAuthenticator,
)
from fdai.delivery.operational_evidence_configuration import (
    CALLER_TOKEN_AUDIENCE_ENV,
    CALLER_TOKEN_ISSUER_ENV,
    CALLER_TOKEN_JWKS_ENV,
    OBSERVATION_METRIC_QUERIES_ENV,
    OWN_ROLE_ALLOWED_SCOPES_ENV,
    OWN_ROLE_READBACK_SCOPES_ENV,
    PRODUCER_ID,
    VERIFIER_ID,
    VERIFIER_VERSION,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
    string_list,
)
from fdai.delivery.operational_evidence_transport import ISSUANCE_PATH, READINESS_PATH
from fdai.delivery.persistence.postgres_current_case_reuse import PostgresCurrentCaseReuseSource
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    PostgresOperationalProofReader,
    PostgresOperationalProofWriter,
)
from fdai.delivery.persistence.postgres_operational_evidence_grants import (
    read_proof_store_grants,
)
from fdai.delivery.persistence.postgres_operational_evidence_sources import (
    PostgresSemanticAuthenticationReceiptSource,
    PostgresTestContextEvidenceSources,
)
from fdai.delivery.persistence.postgres_state_transitions import (
    PostgresStateTransitionStore,
    PostgresStateTransitionStoreConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken

_LOGGER = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 16_384


class CallerAuthenticator(Protocol):
    """Map one HTTP caller to the principal its producer anchor must equal."""

    def authenticate(self, request: web.Request) -> str | None: ...


class OwnRoleReader(Protocol):
    """Read this verifier workload's own role assignments."""

    async def read(self) -> VerifierOwnRoleReadback: ...


@dataclass(frozen=True, slots=True)
class _TokenProviderWorkloadIdentity:
    provider: object

    async def get_token(self, audience: str) -> IdentityToken:
        token = await self.provider.get_token(audience)  # type: ignore[attr-defined]
        return IdentityToken(
            token=token.token, expires_at=datetime.max.replace(tzinfo=UTC), audience=audience
        )


@dataclass(frozen=True, slots=True)
class LoopbackCallerAuthenticator:
    """Local venue only: a loopback peer is the one configured local producer principal."""

    principal: str

    def authenticate(self, request: web.Request) -> str | None:
        try:
            peer = ipaddress.ip_address(request.remote or "")
        except ValueError:
            return None
        return self.principal if peer.is_loopback else None


@dataclass(slots=True)
class VerifierReadiness:
    """Current capability state; only ``ready`` issues."""

    state: str = "unavailable"
    reasons: tuple[str, ...] = ("not_probed",)
    probed_at: datetime | None = None
    source_health: dict[str, OperationalEvidenceSourceHealth] = field(default_factory=dict)


def build_verifier_app(
    engine: OperationalEvidenceVerifierEngine,
    *,
    caller: CallerAuthenticator,
    readiness: Callable[[], VerifierReadiness],
) -> web.Application:
    """Return the two-route application; neither route accepts evidence content."""

    async def issue(request: web.Request) -> web.StreamResponse:
        principal = caller.authenticate(request)
        if principal is None:
            return web.json_response({"error": "caller_unauthenticated"}, status=401)
        if request.content_length is None or request.content_length > _MAX_REQUEST_BYTES:
            return web.json_response({"error": "request_bound_exceeded"}, status=413)
        try:
            issuance = OperationalEvidenceIssuanceRequest.model_validate_json(await request.read())
        except (ValidationError, ValueError):
            return web.json_response({"error": "request_invalid"}, status=422)
        if readiness().state != "ready":
            outcome = OperationalEvidenceIssuanceResponse.unavailable(issuance)
        else:
            outcome = await engine.issue(issuance, caller_principal=principal)
        return web.Response(body=outcome.model_dump_json(), content_type="application/json")

    async def ready(_: web.Request) -> web.StreamResponse:
        current = readiness()
        pins = engine.current_pins()
        if pins is None:
            return web.json_response({"error": "registry_unavailable"}, status=503)
        snapshot = OperationalEvidenceVerifierReadiness(
            state=OperationalEvidenceVerifierState(current.state),
            reasons=() if current.state == "ready" else tuple(sorted(set(current.reasons))),
            verifier_id=engine.identity.verifier_id,
            verifier_version=engine.identity.verifier_version,
            trust_registry_pin=pins.trust_pin,
            grant_registry_pin=pins.grant_pin,
            bound_purposes=tuple(sorted(engine.bound_purposes())),
            source_health=dict(current.source_health),
            probed_at=current.probed_at,
        )
        return web.Response(body=snapshot.model_dump_json(), content_type="application/json")

    app = web.Application(client_max_size=_MAX_REQUEST_BYTES)
    app.router.add_post(ISSUANCE_PATH, issue)
    app.router.add_get(READINESS_PATH, ready)
    return app


@dataclass(frozen=True, slots=True)
class VerifierWorkload:
    """A started verifier: its engine, readiness probe, and registry history."""

    engine: OperationalEvidenceVerifierEngine
    readiness: VerifierReadiness
    probe: Callable[[], Awaitable[VerifierReadiness]]
    history: RegistryHistory
    caller: CallerAuthenticator
    deployed_venue: bool


def build_verifier_workload(
    env: Mapping[str, str],
    *,
    root: Path,
    clock: Callable[[], datetime] | None = None,
    caller_authenticator: CallerAuthenticator | None = None,
    own_role_reader: OwnRoleReader | None = None,
) -> VerifierWorkload:
    """Load pinned registries, refuse identity equality, and bind real local sources."""

    settings = OperationalEvidenceSettings.from_environment(env)
    deployed = settings.execution_venue is Venue.DEPLOYED
    if settings.execution_venue not in {Venue.LOCAL, Venue.DEPLOYED}:
        raise RuntimeError("operational evidence verifier venue is unsupported or invalid")
    history = load_registry_history(settings, root=root)
    anchors = load_anchors(settings)
    trust = history.current.trust
    anchor_ids = {
        verifier.trust_anchor_id
        for entry in trust.purposes.values()
        for verifier in entry.verifiers
        if verifier.verifier_id == VERIFIER_ID
    }
    principals = {anchors.principal(anchor) for anchor in anchor_ids}
    if len(principals) != 1 or None in principals or not settings.verifier_dsn:
        raise RuntimeError("operational evidence verifier principal or store is unbound")
    verifier_principal = str(next(iter(principals)))
    if deployed:
        try:
            executor_principals = build_executor_class_anchor_set(settings.executor_anchor_inputs())
        except VerifierDeploymentPreflightError as exc:
            raise RuntimeError("deployed verifier executor anchors are unbound") from exc
        assert_verifier_not_executor_class(
            verifier_principal=verifier_principal,
            executor_class_principals=executor_principals,
        )
    else:
        executor_principals = frozenset(
            string_list(settings.executor_principals_json, label="executor principals")
        )
    assert_verifier_separation(
        trust,
        anchors,
        verifier_principal=verifier_principal,
        executor_class_principals=executor_principals,
    )
    store = PostgresOperationalEvidenceConfig(
        dsn=settings.verifier_dsn, expected_role=VERIFIER_ROLE
    )
    sources = PostgresTestContextEvidenceSources(store)
    semantic_receipts = PostgresSemanticAuthenticationReceiptSource(store)
    current_case_reuse = PostgresCurrentCaseReuseSource(store)
    readiness = VerifierReadiness()
    members = string_list(settings.writer_members_json, label="writer members")
    caller = caller_authenticator or (
        _deployed_caller_authenticator(settings, trust, anchors) if deployed else None
    )
    if caller is None:
        producer = _producer_principal(trust, anchors)
        if producer is None:
            raise RuntimeError("operational evidence producer anchor is unbound")
        caller = LoopbackCallerAuthenticator(producer)
    role_reader = (
        own_role_reader or _configured_role_reader(env, settings, verifier_principal)
        if deployed
        else own_role_reader
    )
    observation_provider = (
        _configured_observation_provider(env, settings, verifier_principal) if deployed else None
    )

    async def probe() -> VerifierReadiness:
        state = "unavailable"
        reasons: tuple[str, ...] = ("not_probed",)
        source_health: dict[str, OperationalEvidenceSourceHealth] = {}
        try:
            readback = await read_proof_store_grants(store, allowed_writer_members=members)
        except (OSError, RuntimeError, ValueError, psycopg.Error) as exc:
            _LOGGER.warning(
                "operational_evidence_writer_readback_unavailable",
                extra={"error_type": type(exc).__name__},
            )
            state, reasons = "unavailable", ("writer_readback_unavailable",)
        else:
            grant_reasons = readback.self_verified_reasons()
            state = "self_verified" if grant_reasons else "ready"
            reasons = grant_reasons
        if deployed and state == "ready":
            if role_reader is None:
                state, reasons = "unavailable", ("role_readback_unavailable",)
            else:
                try:
                    own_roles = await role_reader.read()
                    role_reasons = evaluate_verifier_own_roles(
                        own_roles,
                        policy=OwnRolePolicy(
                            verifier_principal_id=verifier_principal,
                            allowed_role_scopes=_allowed_role_scopes(
                                settings.allowed_role_scopes_json
                            ),
                        ),
                    )
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    VerifierOwnRoleReadbackError,
                    httpx.HTTPError,
                    jwt.PyJWTError,
                    AzureError,
                    psycopg.Error,
                ) as exc:
                    _LOGGER.warning(
                        "operational_evidence_own_role_readback_unavailable",
                        extra={"error_type": type(exc).__name__},
                    )
                    role_reasons = ("role_readback_unavailable",)
                if role_reasons:
                    state, reasons = "unavailable", role_reasons
        source_health = {
            **(await sources.source_health()),
            **(await semantic_receipts.source_health()),
            **(await current_case_reuse.source_health()),
        }
        if observation_provider is not None:
            source_health[METRIC_SOURCE] = OperationalEvidenceSourceHealth.HEALTHY
            source_health[DEPENDENCY_HEALTH_SOURCE] = OperationalEvidenceSourceHealth.HEALTHY
        readiness.state = state
        readiness.reasons = reasons
        readiness.source_health = source_health
        readiness.probed_at = datetime.now(UTC)
        return readiness

    async def blocked() -> bool:
        return readiness.state != "ready"

    readbacks: list[PurposeReadback] = [
        CaseHistoryReadback(receipts=semantic_receipts),
        OperatorTestContextCommandReadback(commands=sources),
        ContextTransitionReadback(commands=sources, history=sources, audit=sources),
        OperationalTestContextReadback(commands=sources, history=sources, audit=sources),
        CurrentCaseReuseReadback(source=current_case_reuse),
    ]
    if observation_provider is not None:
        readbacks.append(OperationalTestObservationReadback(provider=observation_provider))
    forecast_sources = env.get("FDAI_FORECAST_HISTORY_SOURCES_JSON", "").strip()
    forecast_producers = env.get("FDAI_FORECAST_HISTORY_PRODUCERS_JSON", "").strip()
    if forecast_sources:
        try:
            forecast_configuration = parse_forecast_history_configuration(
                bindings_json=forecast_sources,
                producers_json=forecast_producers or None,
            )
        except ValueError as exc:
            raise RuntimeError(
                "operational evidence forecast history bindings are invalid"
            ) from exc
        forecast_slice_source = StateTransitionForecastHistorySliceSource(
            store=PostgresStateTransitionStore(
                config=PostgresStateTransitionStoreConfig(
                    dsn=settings.verifier_dsn,
                    statement_timeout_ms=1_000,
                    connect_timeout_s=1,
                )
            ),
            bindings=forecast_configuration.bindings,
        )
        readbacks.extend(
            (
                ForecastHistorySliceReadback(source=forecast_slice_source),
                ForecastContextAggregateReadback(source=forecast_slice_source),
            )
        )

    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity(verifier_id=VERIFIER_ID, verifier_version=VERIFIER_VERSION),
        history=lambda: history,
        anchors=anchors,
        readbacks=tuple(readbacks),
        writer=PostgresOperationalProofWriter(store),
        lineage=PostgresOperationalProofReader(store),
        clock=clock,
        issuance_blocked=blocked,
    )
    return VerifierWorkload(
        engine=engine,
        readiness=readiness,
        probe=probe,
        history=history,
        caller=caller,
        deployed_venue=deployed,
    )


async def serve(env: Mapping[str, str], *, root: Path, host: str, port: int) -> None:
    """Run the verifier until cancelled; local venue refuses non-loopback binds."""

    deployed = OperationalEvidenceSettings.from_environment(env).execution_venue is Venue.DEPLOYED
    if not deployed and not ipaddress.ip_address(host).is_loopback:
        raise RuntimeError("the local verifier binds loopback addresses only")
    workload = build_verifier_workload(env, root=root)
    await workload.probe()
    if workload.deployed_venue and workload.readiness.state != "ready":
        raise RuntimeError("deployed operational evidence verifier startup checks failed")
    app = build_verifier_app(
        workload.engine,
        caller=workload.caller,
        readiness=lambda: workload.readiness,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    _LOGGER.info(
        "operational_evidence_verifier_started",
        extra={"state": workload.readiness.state, "port": port},
    )
    try:
        while True:
            await asyncio.sleep(30)
            await workload.probe()
    finally:
        await runner.cleanup()


def main(argv: list[str] | None = None) -> int:
    """Start the loopback verifier from deployment environment variables."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(os.environ, root=arguments.root, host=arguments.host, port=arguments.port))
    return 0


__all__ = [
    "READINESS_PATH",
    "CallerAuthenticator",
    "LoopbackCallerAuthenticator",
    "VerifierReadiness",
    "VerifierWorkload",
    "build_verifier_app",
    "build_verifier_workload",
    "main",
    "serve",
]


def _producer_principal(trust: TrustRegistry, anchors: DeploymentAnchors) -> str | None:
    return next(
        (
            anchors.principal(item.anchor_id)
            for entry in trust.purposes.values()
            for item in entry.producers
            if item.producer_id == PRODUCER_ID
        ),
        None,
    )


def _deployed_caller_authenticator(
    settings: OperationalEvidenceSettings,
    trust: TrustRegistry,
    anchors: DeploymentAnchors,
) -> CallerAuthenticator:
    producer = _producer_principal(trust, anchors)
    if (
        producer is None
        or not settings.caller_token_issuer
        or not settings.caller_token_audience
        or not settings.caller_token_jwks_json
    ):
        missing = ", ".join(
            key
            for key, value in {
                CALLER_TOKEN_ISSUER_ENV: settings.caller_token_issuer,
                CALLER_TOKEN_AUDIENCE_ENV: settings.caller_token_audience,
                CALLER_TOKEN_JWKS_ENV: settings.caller_token_jwks_json,
            }.items()
            if not value
        )
        raise RuntimeError(
            "a deployed verifier requires a workload caller authenticator"
            + (f" ({missing})" if missing else "")
        )
    return WorkloadCallerAuthenticator(
        expected_issuer=settings.caller_token_issuer,
        expected_audience=settings.caller_token_audience,
        registered_producer_principal=producer,
        validator=StaticJwksBearerTokenValidator(
            issuer=settings.caller_token_issuer,
            audience=settings.caller_token_audience,
            jwks_json=settings.caller_token_jwks_json,
        ),
    )


def _configured_role_reader(
    env: Mapping[str, str], settings: OperationalEvidenceSettings, verifier_principal: str
) -> OwnRoleReader | None:
    if settings.own_role_assignments_json:
        raise RuntimeError("deployed verifier own-role readback cannot come from environment")
    if not settings.allowed_role_scopes_json:
        raise RuntimeError(f"{OWN_ROLE_ALLOWED_SCOPES_ENV} is required in deployed venue")
    scopes = string_list(
        settings.role_readback_scopes_json,
        label="role readback scopes",
    )
    if not scopes:
        raise RuntimeError(f"{OWN_ROLE_READBACK_SCOPES_ENV} is required in deployed venue")
    client = httpx.AsyncClient(timeout=2.0)
    return AzureAuthorizationRoleAssignmentReader(
        client=client,
        token_provider=build_azure_management_token_provider(
            env,
            client_id=env.get("FDAI_MI_CLIENT_ID", "").strip()
            or env.get("AZURE_CLIENT_ID", "").strip(),
        ),
        principal_id=verifier_principal,
        scopes=scopes,
    )


def _configured_observation_provider(
    env: Mapping[str, str], settings: OperationalEvidenceSettings, verifier_principal: str
) -> AzureMonitorTestObservationProvider | None:
    if not (
        settings.observation_metric_workspace_id
        or settings.observation_metric_queries_json
        or settings.observation_scope_rows_json
    ):
        return None
    if not (
        settings.observation_metric_workspace_id
        and settings.observation_metric_queries_json
        and settings.observation_scope_rows_json
    ):
        raise RuntimeError(
            "operational evidence observation readback requires metric workspace, "
            "metric queries, and scope rows"
        )
    token_provider = build_azure_management_token_provider(
        env,
        client_id=env.get("FDAI_MI_CLIENT_ID", "").strip()
        or env.get("AZURE_CLIENT_ID", "").strip(),
    )
    queries = _metric_templates(settings.observation_metric_queries_json)
    metric_provider = AzureMonitorLogsMetricProvider(
        config=AzureMonitorLogsConfig(
            workspace_id=settings.observation_metric_workspace_id,
            queries=queries,
        ),
        identity=_TokenProviderWorkloadIdentity(token_provider),
        http_client=httpx.AsyncClient(timeout=2.0),
    )
    return AzureMonitorTestObservationProvider(
        metrics=MetricProviderSampleClient(metric_provider),
        scope=JsonOperatingScopeObservationReader(settings.observation_scope_rows_json),
        source_anchor=verifier_principal,
    )


def _metric_templates(raw: str) -> dict[str, MetricKqlTemplate]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{OBSERVATION_METRIC_QUERIES_ENV} is not valid JSON") from exc
    if not isinstance(decoded, dict) or not decoded:
        raise RuntimeError(f"{OBSERVATION_METRIC_QUERIES_ENV} must be a non-empty object")
    templates: dict[str, MetricKqlTemplate] = {}
    for name, value in decoded.items():
        if not isinstance(name, str) or not isinstance(value, Mapping):
            raise RuntimeError(f"{OBSERVATION_METRIC_QUERIES_ENV} entries are malformed")
        label_columns = value.get("label_columns", [])
        if not isinstance(label_columns, list) or any(
            not isinstance(item, str) for item in label_columns
        ):
            raise RuntimeError(f"{OBSERVATION_METRIC_QUERIES_ENV} label columns are malformed")
        templates[name] = MetricKqlTemplate(
            kql=str(value.get("kql") or ""),
            value_column=str(value.get("value_column") or ""),
            timestamp_column=str(value.get("timestamp_column") or "TimeGenerated"),
            label_columns=tuple(label_columns),
        )
    return templates


def _allowed_role_scopes(raw: str) -> dict[str, tuple[str, ...]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{OWN_ROLE_ALLOWED_SCOPES_ENV} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{OWN_ROLE_ALLOWED_SCOPES_ENV} must be a JSON object")
    allowed: dict[str, tuple[str, ...]] = {}
    for role, scopes in value.items():
        if not isinstance(role, str) or not isinstance(scopes, list):
            raise RuntimeError(f"{OWN_ROLE_ALLOWED_SCOPES_ENV} entries are malformed")
        normalized = tuple(str(scope).rstrip("/") for scope in scopes if str(scope).strip())
        if not normalized:
            raise RuntimeError(f"{OWN_ROLE_ALLOWED_SCOPES_ENV} entry has no scopes")
        allowed[role] = normalized
    return allowed


if __name__ == "__main__":  # pragma: no cover - manual local entry point
    raise SystemExit(main())

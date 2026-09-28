"""Internal-only verifier workload: startup separation checks and a bounded HTTP endpoint.

The workload is not an agent. It publishes and subscribes to no topic, invokes no model, and
owns only the operational proof store. It refuses to start when its principal equals a source,
producer, reviewer, or executor-class principal, and it refuses to issue while the proof-store
grants readback shows another writer (``self_verified``). The local venue accepts loopback
callers only; a deployed venue requires a workload caller authenticator, which this module does
not provide, so it refuses to start there.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from aiohttp import web
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
)
from pydantic import ValidationError

from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.readback.test_context_command import (
    OperatorTestContextCommandReadback,
)
from fdai.core.operational_evidence.readback.test_context_lifecycle import (
    ContextTransitionReadback,
    OperationalTestContextReadback,
)
from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.core.operational_evidence.separation import assert_verifier_separation
from fdai.core.operational_evidence.trust_registry import Venue
from fdai.delivery.operational_evidence_configuration import (
    PRODUCER_ID,
    VERIFIER_ID,
    VERIFIER_VERSION,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
    string_list,
)
from fdai.delivery.operational_evidence_transport import ISSUANCE_PATH
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
    PostgresTestContextEvidenceSources,
)

READINESS_PATH = "/v1/operational-evidence/readiness"
_LOGGER = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 16_384


class CallerAuthenticator(Protocol):
    """Map one HTTP caller to the principal its producer anchor must equal."""

    def authenticate(self, request: web.Request) -> str | None: ...


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
        return web.json_response(
            {
                "state": current.state,
                "reasons": list(current.reasons),
                "bound_purposes": sorted(engine.bound_purposes()),
                "execution_authority": False,
            }
        )

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
    local_producer_principal: str


def build_verifier_workload(
    env: Mapping[str, str],
    *,
    root: Path,
    clock: Callable[[], datetime] | None = None,
) -> VerifierWorkload:
    """Load pinned registries, refuse identity equality, and bind real local sources."""

    settings = OperationalEvidenceSettings.from_environment(env)
    if settings.execution_venue is not Venue.LOCAL:
        raise RuntimeError(
            "a deployed verifier requires a workload caller authenticator that is not bound"
        )
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
    assert_verifier_separation(
        trust,
        anchors,
        verifier_principal=verifier_principal,
        executor_class_principals=string_list(
            settings.executor_principals_json, label="executor principals"
        ),
    )
    store = PostgresOperationalEvidenceConfig(
        dsn=settings.verifier_dsn, expected_role=VERIFIER_ROLE
    )
    sources = PostgresTestContextEvidenceSources(store)
    readiness = VerifierReadiness()
    members = string_list(settings.writer_members_json, label="writer members")

    async def probe() -> VerifierReadiness:
        try:
            readback = await read_proof_store_grants(store, allowed_writer_members=members)
        except (OSError, RuntimeError, ValueError) as exc:
            readiness.state, readiness.reasons = "unavailable", (type(exc).__name__,)
        else:
            reasons = readback.self_verified_reasons()
            readiness.state = "self_verified" if reasons else "ready"
            readiness.reasons = reasons
        readiness.probed_at = datetime.now(UTC)
        return readiness

    async def blocked() -> bool:
        return readiness.state != "ready"

    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity(verifier_id=VERIFIER_ID, verifier_version=VERIFIER_VERSION),
        history=lambda: history,
        anchors=anchors,
        readbacks=(
            OperatorTestContextCommandReadback(commands=sources),
            ContextTransitionReadback(commands=sources, history=sources, audit=sources),
            OperationalTestContextReadback(commands=sources, history=sources, audit=sources),
        ),
        writer=PostgresOperationalProofWriter(store),
        lineage=PostgresOperationalProofReader(store),
        clock=clock,
        issuance_blocked=blocked,
    )
    producer = next(
        (
            anchors.principal(item.anchor_id)
            for entry in trust.purposes.values()
            for item in entry.producers
            if item.producer_id == PRODUCER_ID
        ),
        None,
    )
    if producer is None:
        raise RuntimeError("operational evidence producer anchor is unbound")
    return VerifierWorkload(
        engine=engine,
        readiness=readiness,
        probe=probe,
        history=history,
        local_producer_principal=producer,
    )


async def serve(env: Mapping[str, str], *, root: Path, host: str, port: int) -> None:
    """Run the local verifier until cancelled; refuse any non-loopback bind address."""

    if not ipaddress.ip_address(host).is_loopback:
        raise RuntimeError("the local verifier binds loopback addresses only")
    workload = build_verifier_workload(env, root=root)
    await workload.probe()
    app = build_verifier_app(
        workload.engine,
        caller=LoopbackCallerAuthenticator(workload.local_producer_principal),
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


if __name__ == "__main__":  # pragma: no cover - manual local entry point
    raise SystemExit(main())

"""Settings reports a purpose available only from a current, matching verifier readiness.

The verifier readiness endpoint is observed once with a bounded read. Configuration alone never
proves availability, each failed prerequisite names itself, and availability grants no authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from aiohttp import web
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.operational_evidence_configuration import (
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
)
from fdai.delivery.operational_evidence_readiness import (
    BOUND_READBACK_PURPOSES,
    observe_verifier_readiness,
    operational_evidence_projection,
)
from fdai.delivery.operational_evidence_server import (
    LoopbackCallerAuthenticator,
    VerifierReadiness,
    build_verifier_app,
)
from fdai.delivery.operational_evidence_transport import READINESS_PATH
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceSourceHealth,
    OperationalEvidenceVerifierReadiness,
)

from tests.core.operational_evidence.support import NOW, MemoryProofStore
from tests.delivery.test_operational_evidence_readiness import _environment, readiness_snapshot

_BOUND = {f"operational-evidence.{purpose}" for purpose in BOUND_READBACK_PURPOSES}
_OUTBOX = "operator-service.test-context-outbox"
_STORE = "core-control-plane.test-context-store"
_ALL_HEALTHY = {
    "azure.resource-existence": OperationalEvidenceSourceHealth.HEALTHY,
    "azure.resource-graph-changes": OperationalEvidenceSourceHealth.HEALTHY,
    "azure-monitor.metrics": OperationalEvidenceSourceHealth.HEALTHY,
    "azure.activity-log": OperationalEvidenceSourceHealth.HEALTHY,
    "core-control-plane.action-audit": OperationalEvidenceSourceHealth.HEALTHY,
    "core-control-plane.case-history": OperationalEvidenceSourceHealth.HEALTHY,
    "core-control-plane.safety-receipts": OperationalEvidenceSourceHealth.HEALTHY,
    "core-control-plane.test-context-store": OperationalEvidenceSourceHealth.HEALTHY,
    "deployment.case-scope-grants": OperationalEvidenceSourceHealth.HEALTHY,
    "inventory.incarnation-ledger": OperationalEvidenceSourceHealth.HEALTHY,
    "inventory.observation-journal": OperationalEvidenceSourceHealth.HEALTHY,
    "inventory.current-snapshot": OperationalEvidenceSourceHealth.HEALTHY,
    "operating-scope.dependency-health": OperationalEvidenceSourceHealth.HEALTHY,
    "operator-service.authentication-receipts": OperationalEvidenceSourceHealth.HEALTHY,
    "operator-service.test-context-outbox": OperationalEvidenceSourceHealth.HEALTHY,
}


def _rows(env: dict[str, str], readiness: object) -> dict[str, dict[str, Any]]:
    rows = operational_evidence_projection(
        env,
        now=NOW,
        verifier_readiness=readiness,  # type: ignore[arg-type]
    )
    return {str(row["key"]): row for row in rows}


def _prerequisites(row: dict[str, Any]) -> dict[str, bool]:
    return {item["name"]: item["satisfied"] for item in row["prerequisites"]}


def test_configuration_alone_never_proves_availability(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    for readiness in (
        None,
        {"state": "ready", "bound_purposes": sorted(BOUND_READBACK_PURPOSES)},
        {**readiness_snapshot(env), "execution_authority": True},
    ):
        rows = _rows(env, readiness)
        assert not any(row["available"] for row in rows.values())
        command = rows["operational-evidence.operator-test-context-command"]
        assert command["reason"] in {
            "verifier readiness is not observed",
            "verifier readiness is malformed",
        }
        assert _prerequisites(command)["verifier_readiness_current"] is False
        assert _prerequisites(command)["source_readback_bound"] is True
    available = _rows(env, readiness_snapshot(env))
    assert {key for key, row in available.items() if row["available"]} == _BOUND
    for key in _BOUND:
        prerequisites = _prerequisites(available[key])
        assert all(prerequisites.values()), prerequisites
        assert available[key]["capability_state"] == "available"
        assert available[key]["authority_mode"] == "shadow"
        assert available[key]["execution_authority"] is False
        assert available[key]["promotion_authority"] is False


@pytest.mark.parametrize(
    ("overrides", "prerequisite", "reason"),
    [
        (
            {"probed_at": (NOW - timedelta(seconds=121)).isoformat()},
            "verifier_readiness_current",
            "verifier readiness is not current",
        ),
        (
            {"probed_at": (NOW + timedelta(seconds=31)).isoformat()},
            "verifier_readiness_current",
            "verifier readiness is not current",
        ),
        (
            {"probed_at": None},
            "verifier_readiness_current",
            "verifier readiness is not current",
        ),
        (
            {"verifier_id": "another-verifier"},
            "verifier_readiness_current",
            "verifier readiness names another verifier identity",
        ),
        (
            {"trust_registry_pin": "sha256:" + "f" * 64},
            "verifier_readiness_current",
            "verifier registry pins differ from the pinned registries",
        ),
        (
            {"grant_registry_pin": "sha256:" + "f" * 64},
            "verifier_readiness_current",
            "verifier registry pins differ from the pinned registries",
        ),
        (
            {"state": "unavailable", "reasons": ["writer_readback_unavailable"]},
            "writer_exclusive_proof_store",
            "verifier readiness with a writer-exclusive proof store is not observed",
        ),
        (
            {"bound_purposes": ["operational-test-context", "test-context-transition"]},
            "verifier_bound_purpose",
            "the verifier has not bound a source readback for this purpose",
        ),
        (
            {"verifier_version": "9.9.9"},
            "verifier_binding_active",
            "the observed verifier version has no active binding for this purpose",
        ),
        (
            {"source_health": {_STORE: "healthy", _OUTBOX: "unavailable"}},
            "declared_sources_healthy",
            "declared sources are not healthy: " + _OUTBOX,
        ),
        (
            {"source_health": {_STORE: "healthy"}},
            "declared_sources_healthy",
            "declared sources are not healthy: " + _OUTBOX,
        ),
    ],
)
def test_each_failed_prerequisite_is_reported_without_authority(
    tmp_path: Path, overrides: dict[str, object], prerequisite: str, reason: str
) -> None:
    env = _environment(tmp_path)
    row = _rows(env, readiness_snapshot(env, **overrides))[
        "operational-evidence.operator-test-context-command"
    ]
    assert row["available"] is False and row["ready"] is False
    assert row["reason"] == reason and row["unavailable_reason"] == reason
    assert _prerequisites(row)[prerequisite] is False
    assert row["capability_state"] == "unavailable"
    assert row["execution_authority"] is False and row["promotion_authority"] is False


def test_an_unhealthy_store_source_holds_only_the_purposes_that_declare_it(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    rows = _rows(env, readiness_snapshot(env, source_health={_OUTBOX: "healthy"}))
    assert rows["operational-evidence.operator-test-context-command"]["available"] is True
    for purpose in ("operational-test-context", "test-context-transition"):
        assert rows[f"operational-evidence.{purpose}"]["reason"] == (
            "declared sources are not healthy: " + _STORE
        )


def test_integration_projection_passes_the_observed_snapshot(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    snapshot = OperationalEvidenceVerifierReadiness.model_validate(
        readiness_snapshot(env, probed_at=datetime.now(UTC).isoformat())
    )
    unobserved = {str(row["key"]): row for row in integration_projection(env)}
    observed = {
        str(row["key"]): row
        for row in integration_projection(env, operational_evidence_readiness=snapshot)
    }
    assert not any(unobserved[key]["available"] for key in _BOUND)
    assert all(observed[key]["available"] for key in _BOUND)


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_observer_reads_nothing_while_issuance_is_disabled_or_unbound(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    env = _environment(tmp_path)
    async with _mock_client(handler) as client:
        disabled = {**env, "FDAI_OPERATIONAL_EVIDENCE_ENABLED": "0"}
        unbound = {**env, "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": ""}
        for values in (disabled, unbound):
            assert await observe_verifier_readiness(values, client=client) is None
    assert requests == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"state": "ready"}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"state": "ready", "bound_purposes": []}),
        httpx.Response(200, content=b"{" + b" " * 9000 + b"}"),
    ],
)
async def test_observer_treats_every_failure_as_unobserved(
    tmp_path: Path, response: httpx.Response
) -> None:
    env = _environment(tmp_path)
    async with _mock_client(lambda _request: response) as client:
        assert await observe_verifier_readiness(env, client=client) is None


async def test_observer_refuses_a_plain_http_endpoint_off_loopback(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    env = {**_environment(tmp_path), "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": "http://verifier"}
    async with _mock_client(handler) as client:
        assert await observe_verifier_readiness(env, client=client) is None
    assert requests == []


class _BoundReadbacks:
    """Declares the bound purposes; readiness never reads a source through it."""

    purposes = frozenset(BOUND_READBACK_PURPOSES)

    async def read(self, context: object) -> object:  # pragma: no cover - never issued here
        raise AssertionError("readiness must not issue")


async def test_verifier_endpoint_snapshot_makes_bound_purposes_available(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    settings = OperationalEvidenceSettings.from_environment(env)
    registries = load_registry_history(settings, root=tmp_path)
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registries,
        anchors=load_anchors(settings),
        readbacks=(_BoundReadbacks(),),
        writer=MemoryProofStore(),
        clock=lambda: NOW,
    )
    readiness = VerifierReadiness(
        state="ready",
        reasons=(),
        probed_at=NOW - timedelta(seconds=5),
        source_health=dict(_ALL_HEALTHY),
    )
    runner = web.AppRunner(
        build_verifier_app(
            engine, caller=LoopbackCallerAuthenticator("fdai_core"), readiness=lambda: readiness
        )
    )
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    live_env = {**env, "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": f"http://{host}:{port}"}
    try:
        async with httpx.AsyncClient() as client:
            raw = (await client.get(f"http://{host}:{port}{READINESS_PATH}")).json()
        observed = await observe_verifier_readiness(live_env)
        readiness.state, readiness.reasons = "self_verified", ("foreign_insert_grant",)
        blocked = await observe_verifier_readiness(live_env)
    finally:
        await runner.cleanup()
    assert raw["execution_authority"] is False and raw["promotion_authority"] is False
    assert raw["trust_registry_pin"] == env["FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN"]
    assert observed is not None and blocked is not None
    assert {key for key, row in _rows(live_env, observed).items() if row["available"]} == _BOUND
    blocked_rows = _rows(live_env, blocked)
    assert not any(row["available"] for row in blocked_rows.values())
    assert {blocked_rows[key]["capability_state"] for key in _BOUND} == {"self_verified"}

"""Bounded issuance transport, in-flight coalescing, forged bodies, and the verifier endpoint."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from aiohttp import web
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.owner_outcome import (
    OperationalEvidenceRequester,
    request_operational_evidence,
)
from fdai.core.operational_evidence.readback.test_context_command import (
    OperatorTestContextCommandReadback,
)
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai.delivery.operational_evidence_server import (
    READINESS_PATH,
    LoopbackCallerAuthenticator,
    VerifierReadiness,
    build_verifier_app,
)
from fdai.delivery.operational_evidence_transport import (
    ISSUANCE_PATH,
    BoundedOperationalEvidenceIssuer,
    HttpOperationalEvidenceTransport,
    InProcessOperationalEvidenceTransport,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLookup,
)

from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    REQUESTER,
    REQUESTER_GROUP,
    SCOPE,
    MemoryProofStore,
    OperatorOutbox,
    anchors,
    command_from_row,
    history,
)

_LOOKUP = {
    "evidence_digest": "sha256:" + "e" * 64,
    "scope_digest": "sha256:" + SCOPE,
    "purpose_id": "operator-test-context-command",
    "source_revision": POLICY,
}


def _provider(store: MemoryProofStore) -> OperationalEvidenceAdmissionProvider:
    registry = history()
    return OperationalEvidenceAdmissionProvider(
        reader=store,
        history=lambda: registry,
        anchors=anchors(),
        verifier_id="operational-evidence-verifier",
        clock=lambda: NOW,
    )


def _requester(issuer: Any, store: MemoryProofStore) -> OperationalEvidenceRequester:
    return OperationalEvidenceRequester(
        issuer=issuer,
        outcomes=_provider(store),
        producer_id="core-control-plane",
        producer_version="1.0.0",
    )


async def _attempt(requester: OperationalEvidenceRequester, **lookup: str) -> Any:
    return await request_operational_evidence(
        requester,
        **{**_LOOKUP, **lookup},
        locator={"idempotency_key": "context-key"},
        clock=lambda: NOW,
    )


class _Recording:
    def __init__(self, respond: Any) -> None:
        self.calls = 0
        self._respond = respond

    async def send(self, request: OperationalEvidenceIssuanceRequest) -> Any:
        self.calls += 1
        return await self._respond(request)


async def test_deadline_ends_the_attempt_as_unavailable_without_retry() -> None:
    async def slow(request: OperationalEvidenceIssuanceRequest) -> Any:
        await asyncio.sleep(1)
        raise AssertionError("unreachable")

    transport = _Recording(slow)
    issuer = BoundedOperationalEvidenceIssuer(transport, timeout_seconds=0.05)
    attempt = await _attempt(_requester(issuer, MemoryProofStore()))
    assert attempt.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
    assert transport.calls == 1


@pytest.mark.parametrize("status", [429, 503, 500])
async def test_throttle_or_outage_is_one_attempt_and_unavailable(status: int) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(status, json={"error": "busy"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = HttpOperationalEvidenceTransport(client, base_url="http://127.0.0.1:8791")
        attempt = await _attempt(
            _requester(BoundedOperationalEvidenceIssuer(transport), MemoryProofStore())
        )
    assert attempt.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
    assert calls == ["http://127.0.0.1:8791" + ISSUANCE_PATH]


async def test_forged_response_body_admits_nothing_after_re_read() -> None:
    store = MemoryProofStore()
    forged_status = {"value": "issued"}

    def handler(request: httpx.Request) -> httpx.Response:
        sent = OperationalEvidenceIssuanceRequest.model_validate_json(request.content)
        body = OperationalEvidenceIssuanceResponse(
            attempt_id=sent.attempt_id,
            lookup_digest=sent.lookup.lookup_digest,
            status=OperationalEvidenceIssuanceStatus(forged_status["value"]),
            record_digest="sha256:" + "9" * 64,
        )
        return httpx.Response(200, content=body.model_dump_json())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        requester = _requester(
            BoundedOperationalEvidenceIssuer(
                HttpOperationalEvidenceTransport(client, base_url="https://verifier.internal")
            ),
            store,
        )
        claimed = await _attempt(requester)
        assert claimed.status is OperationalEvidenceIssuanceStatus.ISSUED
        assert await _provider(store).admit(**_LOOKUP) is None
        forged_status["value"] = "rejected"
        rejected = await _attempt(requester)
    assert rejected.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
    assert rejected.rejection is None


async def test_identical_in_flight_requests_coalesce_and_later_ones_start_fresh() -> None:
    release = asyncio.Event()

    async def held(request: OperationalEvidenceIssuanceRequest) -> Any:
        await release.wait()
        return OperationalEvidenceIssuanceResponse.unavailable(request)

    transport = _Recording(held)
    requester = _requester(BoundedOperationalEvidenceIssuer(transport), MemoryProofStore())
    first = asyncio.create_task(_attempt(requester))
    second = asyncio.create_task(_attempt(requester))
    await asyncio.sleep(0)
    release.set()
    assert (await first) == (await second)
    assert transport.calls == 1
    await _attempt(requester)
    assert transport.calls == 2


async def test_outcome_accepts_only_the_rejection_its_own_attempt_named() -> None:
    outbox = OperatorOutbox()
    row = outbox.add(
        "propose",
        principal=REQUESTER,
        group=REQUESTER_GROUP,
        roles=("Contributor",),
        accepted_at=NOW - timedelta(minutes=20),
        expected_revision=0,
    )
    command = command_from_row(row).model_dump(mode="json")
    store = MemoryProofStore()
    registry = history()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registry,
        anchors=anchors(),
        readbacks=(OperatorTestContextCommandReadback(commands=outbox),),
        writer=store,
        clock=lambda: NOW,
    )
    requester = _requester(
        BoundedOperationalEvidenceIssuer(
            InProcessOperationalEvidenceTransport(engine, caller_principal="fdai_core")
        ),
        store,
    )
    lookup = {**_LOOKUP, "evidence_digest": content_digest(command)}
    first = await request_operational_evidence(
        requester,
        **lookup,
        locator={"idempotency_key": row.record["idempotency_key"]},
        clock=lambda: NOW,
    )
    assert first.rejection is not None and first.rejection.rejection_class.value == "stale"
    older = first.rejection
    later = OperationalEvidenceIssuanceResponse(
        attempt_id="0" * 32,
        lookup_digest=older.lookup_digest,
        status=OperationalEvidenceIssuanceStatus.REJECTED,
        record_digest=older.record_digest,
    )
    assert await _provider(store).outcome(later, lookup=OperationalEvidenceLookup(**lookup)) is None
    second = await request_operational_evidence(
        requester,
        **lookup,
        locator={"idempotency_key": row.record["idempotency_key"]},
        clock=lambda: NOW,
    )
    assert second.rejection is not None
    assert second.rejection.record_digest != older.record_digest
    assert len(store.rejections) == 2


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://verifier.internal", True),
        ("http://127.0.0.1:8791", True),
        ("http://verifier.internal", False),
        ("ftp://127.0.0.1", False),
    ],
)
async def test_verifier_endpoint_requires_https_or_loopback(url: str, valid: bool) -> None:
    async with httpx.AsyncClient() as client:
        if valid:
            HttpOperationalEvidenceTransport(client, base_url=url)
        else:
            with pytest.raises(ValueError, match="HTTPS or a loopback"):
                HttpOperationalEvidenceTransport(client, base_url=url)


async def test_loopback_verifier_endpoint_gates_issuance_on_readiness() -> None:
    outbox = OperatorOutbox()
    row = outbox.add(
        "propose",
        principal=REQUESTER,
        group=REQUESTER_GROUP,
        roles=("Contributor",),
        accepted_at=NOW - timedelta(minutes=1),
        expected_revision=0,
    )
    store = MemoryProofStore()
    registry = history()
    engine = OperationalEvidenceVerifierEngine(
        identity=VerifierIdentity("operational-evidence-verifier", "1.0.0"),
        history=lambda: registry,
        anchors=anchors(),
        readbacks=(OperatorTestContextCommandReadback(commands=outbox),),
        writer=store,
        clock=lambda: NOW,
    )
    readiness = VerifierReadiness(state="self_verified", reasons=("foreign_insert_grant",))
    app = build_verifier_app(
        engine, caller=LoopbackCallerAuthenticator("fdai_core"), readiness=lambda: readiness
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    base = f"http://{host}:{port}"
    command = command_from_row(row).model_dump(mode="json")
    try:
        async with httpx.AsyncClient() as client:
            requester = _requester(
                BoundedOperationalEvidenceIssuer(
                    HttpOperationalEvidenceTransport(client, base_url=base)
                ),
                store,
            )
            lookup = {**_LOOKUP, "evidence_digest": content_digest(command)}
            locator = {"idempotency_key": row.record["idempotency_key"]}
            blocked = await request_operational_evidence(
                requester, **lookup, locator=locator, clock=lambda: NOW
            )
            assert blocked.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
            assert store.admissions == [] and store.rejections == []
            state = (await client.get(base + READINESS_PATH)).json()
            assert state["state"] == "self_verified"
            assert state["execution_authority"] is False
            readiness.state, readiness.reasons = "ready", ()
            issued = await request_operational_evidence(
                requester, **lookup, locator=locator, clock=lambda: NOW
            )
            assert issued.status is OperationalEvidenceIssuanceStatus.ISSUED
            assert await _provider(store).admit(**lookup) is not None
            invalid = await client.post(base + ISSUANCE_PATH, content=b"{}")
            assert invalid.status_code == 422
    finally:
        await runner.cleanup()


async def test_proof_store_outage_is_unavailable_not_an_error() -> None:
    import psycopg

    class _Down:
        async def newest_admissions(self, *_args: object, **_kwargs: object) -> Any:
            raise psycopg.OperationalError("proof store unreachable")

        async def rejection(self, **_kwargs: object) -> Any:
            raise ConnectionRefusedError("proof store unreachable")

    registry = history()
    provider = OperationalEvidenceAdmissionProvider(
        reader=_Down(),  # type: ignore[arg-type]
        history=lambda: registry,
        anchors=anchors(),
        verifier_id="operational-evidence-verifier",
        clock=lambda: NOW,
    )
    assert await provider.admit(**_LOOKUP) is None
    response = OperationalEvidenceIssuanceResponse(
        attempt_id="d" * 32,
        lookup_digest=OperationalEvidenceLookup(**_LOOKUP).lookup_digest,
        status=OperationalEvidenceIssuanceStatus.REJECTED,
        record_digest="sha256:" + "8" * 64,
    )
    assert await provider.outcome(response, lookup=OperationalEvidenceLookup(**_LOOKUP)) is None

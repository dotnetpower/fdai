"""Offline route and immutable-replay contracts; all evidence here is synthetic.

The ASGI transport, verifier, readiness and state doubles are test-only. These
checks do not assert PostgreSQL, broker, Entra, Azure or runtime readiness.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from fdai_operator_service.alert_quality import (
    ALERT_QUALITY_ROUTE_MANIFEST,
    MAX_ALERT_QUALITY_BODY_BYTES,
    PRINCIPAL_SCOPES_ENV,
    AlertQualityDependencies,
    AlertQualityResponse,
    AlertQualityScopesResponse,
    alert_quality_dependencies_from_environment,
    build_alert_quality_routes,
    parse_alert_quality_principal_scopes,
)
from fdai_operator_service.alert_quality_store import (
    ALERT_QUALITY_PREFIX,
    AlertQualityConflictError,
    AlertQualitySnapshot,
    AlertQualityStaleError,
    AlertQualityUnavailableError,
    StateKvAlertQualityStore,
    alert_quality_binding_digest,
    alert_quality_requester_ref,
)
from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator
from fdai_operator_service.families.operations.contracts import (
    EventProposal,
    ProposalConflictError,
    ProposalReceipt,
)
from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertTreatment
from pydantic import ValidationError
from starlette.applications import Starlette

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
PRINCIPAL = "operator-subject-one"
OTHER_PRINCIPAL = "operator-subject-two"
SCOPE = "scope:one"
READ_PATH = f"/alert-quality?scope_ref={SCOPE}"
EVIDENCE = "sha256:" + "a" * 64
POLICY = "sha256:" + "c" * 64
HEADERS = {"Authorization": "Bearer contributor", "Idempotency-Key": "request-one"}


def _assessment(**changes: object) -> NoiseAssessment:
    values: dict[str, object] = {
        "evidence_digest": EVIDENCE,
        "policy_digest": POLICY,
        "tenant_ref": "tenant:example",
        "scope_ref": SCOPE,
        "observed_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(hours=1),
        "coverage": "complete",
        "reasons": (),
        "source_episodes": 12,
        "notification_attempts": 18,
        "confirmed_deliveries": 15,
        "acknowledgements": None,
        "findings": (),
    }
    values.update(changes)
    return NoiseAssessment.model_validate(values)


def _treatment(**changes: object) -> dict[str, object]:
    return {
        "kind": "routing",
        "target_ref": "rule:one",
        "replacement_group_ref": "group:replacement",
        "remove_group_ref": "group:previous",
        **changes,
    }


def _plan(**changes: object) -> AlertChangePlan:
    values: dict[str, object] = {
        "action_type": "ops.update-alert-routing",
        "tenant_ref": "tenant:example",
        "scope_ref": SCOPE,
        "requester_ref": alert_quality_requester_ref(PRINCIPAL, SCOPE),
        "evidence_digest": EVIDENCE,
        "policy_digest": POLICY,
        "target_revision": "sha256:" + "d" * 64,
        "treatment": AlertTreatment.model_validate(_treatment()),
        "service_refs": ("service:one",),
        "lock_refs": ("group:previous", "group:replacement", "rule:one"),
        "created_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=30),
        "max_execution_seconds": 60,
        "max_observation_seconds": 120,
        "max_recovery_seconds": 60,
        "rollback_ref": "sha256:" + "f" * 64,
    }
    values.update(changes)
    return AlertChangePlan.model_validate(values)


def _proposal(**changes: object) -> dict[str, object]:
    return {"scope_ref": SCOPE, "evidence_digest": EVIDENCE, "treatment": _treatment(), **changes}


class _State:
    """Test-only atomic insertion double; deliberately offers no replacement method."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.reads: list[str] = []
        self.finds: list[str] = []
        self.creates: list[str] = []

    async def read_state(self, key: str) -> dict[str, object] | None:
        self.reads.append(key)
        return copy.deepcopy(self.records.get(key))

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        self.creates.append(key)
        if key in self.records:
            return False
        self.records[key] = copy.deepcopy(dict(value))
        return True

    async def find_state(self, *, prefix: str, field: str, value: str) -> dict[str, object] | None:
        self.finds.append(prefix)
        matches = [
            record
            for key, record in self.records.items()
            if key.startswith(prefix) and record.get(field) == value
        ]
        return copy.deepcopy(matches[-1]) if matches else None


class _Writer:
    """Test-only outbox with the production writer's exact-key conflict semantics."""

    def __init__(self) -> None:
        self.proposals: dict[str, EventProposal] = {}
        self.durable = True

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        existing = self.proposals.get(proposal.idempotency_key)
        if existing is not None and existing != proposal:
            raise ProposalConflictError("private outbox conflict detail")
        self.proposals[proposal.idempotency_key] = proposal
        return ProposalReceipt(
            request_id="private-request-id",
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at=NOW.isoformat(),
            durably_queued=self.durable,
        )


def _verify(token: str) -> Mapping[str, object]:
    roles = {
        "reader": ["Reader"],
        "contributor": ["Contributor"],
        "approver": ["Approver"],
        "owner": ["Owner"],
        "breakglass": ["BreakGlass"],
        "unassigned": [],
        "other": ["Contributor"],
        "workload": ["Reader"],
    }
    if token not in roles:
        raise AuthenticationError("private authentication detail")
    return {
        "oid": OTHER_PRINCIPAL if token == "other" else PRINCIPAL,
        "idtyp": "app" if token == "workload" else "user",
        "roles": roles[token],
    }


async def _ready() -> bool:
    return True


def _harness() -> tuple[_State, _Writer, AlertQualityDependencies]:
    state, writer = _State(), _Writer()
    return (
        state,
        writer,
        AlertQualityDependencies(
            authenticator=OperatorAuthenticator(verifier=_verify, group_ids={}),
            principal_scopes={PRINCIPAL: frozenset({SCOPE}), OTHER_PRINCIPAL: frozenset({SCOPE})},
            source=StateKvAlertQualityStore(state, clock=lambda: NOW),
            proposal_writer=writer,
            producer_ready=_ready,
            clock=lambda: NOW,
        ),
    )


def _client(dependencies: AlertQualityDependencies) -> httpx.AsyncClient:
    app = Starlette(routes=list(build_alert_quality_routes(dependencies)))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def _seed(dependencies: AlertQualityDependencies, *, with_plan: bool = False) -> None:
    source = cast(StateKvAlertQualityStore, dependencies.source)
    await source.persist_assessment(
        principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=_assessment()
    )
    if with_plan:
        await source.persist_plan(principal_id=PRINCIPAL, scope_ref=SCOPE, plan=_plan())


def test_route_builder_matches_its_explicit_method_path_name_manifest() -> None:
    _, _, dependencies = _harness()
    routes = build_alert_quality_routes(dependencies)
    assert isinstance(routes, tuple)
    assert len(routes) == 6
    assert (
        tuple(
            (method, route.path, route.name)
            for route in routes
            for method in sorted(route.methods or ())
            if method != "HEAD"
        )
        == ALERT_QUALITY_ROUTE_MANIFEST
    )


@pytest.mark.parametrize("method,path", [(row[0], row[1]) for row in ALERT_QUALITY_ROUTE_MANIFEST])
async def test_each_route_authenticates_without_a_parent_auth_wrapper(
    method: str, path: str
) -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.request(method, path, json={"authority": "enforce"})
    assert response.status_code == 401
    assert response.json() == {"error": {"status": 401, "code": "unauthenticated"}}
    assert not state.reads and not state.finds and not writer.proposals


@pytest.mark.parametrize(
    "token,get_status,post_status",
    [
        ("reader", 200, 403),
        ("contributor", 200, 202),
        ("approver", 200, 202),
        ("owner", 200, 202),
        ("breakglass", 403, 403),
        ("unassigned", 403, 403),
    ],
)
@pytest.mark.parametrize("path", ["/alert-quality/assess", "/alert-quality/proposals"])
async def test_role_floors_come_only_from_current_authentication(
    token: str, get_status: int, post_status: int, path: str
) -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    headers = {**HEADERS, "Authorization": f"Bearer {token}", "X-Operator-Role": "Owner"}
    body = _proposal() if path.endswith("proposals") else {"scope_ref": SCOPE}
    async with _client(dependencies) as client:
        read = await client.get(READ_PATH, headers=headers)
        request = await client.post(path, headers=headers, json=body)
    assert read.status_code == get_status
    assert request.status_code == post_status
    assert bool(writer.proposals) is (post_status == 202)


@pytest.mark.parametrize(
    "method,path",
    [(row[0], row[1]) for row in ALERT_QUALITY_ROUTE_MANIFEST if row[1] != "/alert-quality/scopes"],
)
async def test_denied_scope_never_reads_an_authoritative_source(method: str, path: str) -> None:
    state, writer, dependencies = _harness()
    headers = {**HEADERS, "Authorization": "Bearer owner"}
    async with _client(dependencies) as client:
        if method == "GET":
            response = await client.get(path, params={"scope_ref": "scope:denied"}, headers=headers)
        else:
            body = (
                _proposal(scope_ref="scope:denied")
                if path.endswith("proposals")
                else {"scope_ref": "scope:denied"}
            )
            if method == "PUT":
                body.update(enabled=False, expected_revision=0)
            response = await client.request(method, path, json=body, headers=headers)
    assert response.status_code == 403
    assert not state.reads and not state.finds and not state.creates and not writer.proposals


async def test_missing_setup_and_ambiguous_default_do_not_manufacture_a_report() -> None:
    state, _, dependencies = _harness()
    missing = replace(dependencies, principal_scopes={})
    async with _client(missing) as client:
        response = await client.get("/alert-quality", headers=HEADERS)
        denied = await client.get(READ_PATH, headers=HEADERS)
        discovery = await client.get("/alert-quality/scopes", headers=HEADERS)
    assert response.status_code == 400 and denied.status_code == 403
    assert discovery.json() == {
        "source": "alert-noise-governance",
        "scope_refs": [],
        "execution_authority": False,
    }
    for scopes in (frozenset({SCOPE}), frozenset({SCOPE, "scope:two"})):
        selected = replace(dependencies, principal_scopes={PRINCIPAL: scopes})
        async with _client(selected) as client:
            response = await client.get("/alert-quality", headers=HEADERS)
        assert response.status_code == 400  # Even a single scope requires an explicit selector.
    assert not state.reads and not state.finds


async def test_missing_backend_get_is_explicit_and_post_is_not_queued() -> None:
    _, writer, dependencies = _harness()
    async with _client(replace(dependencies, source=None)) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
        post = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] == "source_unavailable"
    assert response.json()["assessment"] is None
    assert post.status_code == 503 and not writer.proposals


@pytest.mark.parametrize("missing", ["producer_ready", "proposal_writer"])
async def test_unbound_producer_or_writer_cannot_accept_an_orphan(missing: str) -> None:
    state, writer, dependencies = _harness()
    closed = replace(dependencies, **{missing: None})
    async with _client(closed) as client:
        response = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 503
    assert not writer.proposals and not state.creates


@pytest.mark.parametrize("value", [False, 1, "ready"])
async def test_producer_readiness_requires_true_not_a_truthy_receipt(value: object) -> None:
    _, writer, dependencies = _harness()

    async def probe() -> bool:
        return cast(bool, value)

    async with _client(replace(dependencies, producer_ready=probe)) as client:
        response = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 503 and not writer.proposals


async def test_disabled_preference_preserves_read_evidence_without_request_authority() -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    async with _client(replace(dependencies, enabled=False)) as client:
        read = await client.get(READ_PATH, headers=HEADERS)
        post = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert read.json()["available"] is True and read.json()["enabled"] is False
    assert read.json()["requestable"] is False
    assert read.json()["authority"] == "shadow"
    assert post.status_code == 503 and not writer.proposals


@pytest.mark.parametrize(
    "field",
    [
        "authority",
        "roles",
        "principal_id",
        "requester_ref",
        "receipt",
        "assessment",
        "observations",
        "url",
    ],
)
@pytest.mark.parametrize("path", ["/alert-quality/assess", "/alert-quality/proposals"])
async def test_request_models_reject_caller_authority_evidence_identity_and_urls(
    field: str, path: str
) -> None:
    state, writer, dependencies = _harness()
    body = _proposal() if path.endswith("proposals") else {"scope_ref": SCOPE}
    body[field] = {"private": "caller-created-observation"}
    async with _client(dependencies) as client:
        response = await client.post(path, json=body, headers=HEADERS)
    assert response.status_code == 400
    assert response.json() == {"error": {"status": 400, "code": "invalid_request"}}
    assert "caller-created" not in response.text
    assert not state.reads and not state.finds and not state.creates and not writer.proposals


@pytest.mark.parametrize(
    "treatment",
    [
        _treatment(authority="enforce"),
        _treatment(target_ref="https://example.com/rule"),
        _treatment(starts_at="2026-09-14T12:00:00Z"),
        _treatment(remove_group_ref=" group:previous "),
        {
            "kind": "evaluation",
            "target_ref": "rule:one",
            "evaluation": {
                "metric_ref": "metric:cpu",
                "operator": "above",
                "threshold": "90",
                "window_seconds": 300,
                "frequency_seconds": 60,
                "aggregation": "average",
            },
        },
    ],
)
async def test_nested_treatment_is_strict_and_has_exactly_one_axis(
    treatment: dict[str, object],
) -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/proposals", json=_proposal(treatment=treatment), headers=HEADERS
        )
    assert response.status_code == 400
    assert not state.finds and not writer.proposals


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b"{",
        b'{"scope_ref": true}',
        b'{"scope_ref":"scope:one","scope_ref":"scope:two"}',
    ],
)
async def test_bad_json_and_duplicate_fields_are_content_free(raw: bytes) -> None:
    _, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess",
            content=raw,
            headers={**HEADERS, "Content-Type": "application/json"},
        )
    assert response.status_code == 400 and not writer.proposals
    assert response.json()["error"]["code"] == "invalid_request"


async def test_streamed_body_cap_is_enforced_without_content_length() -> None:
    state, writer, dependencies = _harness()

    async def oversized() -> AsyncIterator[bytes]:
        yield b'{"scope_ref":"'
        yield b"a" * MAX_ALERT_QUALITY_BODY_BYTES
        raise AssertionError("the parser read beyond the body cap")

    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess",
            content=oversized(),
            headers={**HEADERS, "Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert not state.finds and not writer.proposals


@pytest.mark.parametrize(
    "query",
    [
        "?scope_ref=scope:one&scope_ref=scope:two",
        "?principal_id=other",
        "?scope_ref=https://example.com",
    ],
)
async def test_get_rejects_unknown_or_ambiguous_query_fields(query: str) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get("/alert-quality" + query, headers=HEADERS)
    assert response.status_code == 400 and not state.finds


async def test_pending_acceptance_retains_exact_internal_principal_and_key_only() -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    proposal = next(iter(writer.proposals.values()))
    assert response.status_code == 202
    assert proposal.operation == "alert_noise.assess" and proposal.principal_id == PRINCIPAL
    assert proposal.payload == {
        "scope_ref": SCOPE,
        "request_idempotency_key": "request-one",
        "requester_ref": alert_quality_requester_ref(PRINCIPAL, SCOPE),
    }
    assert (
        proposal.idempotency_key == proposal.correlation_id == response.headers["X-Correlation-ID"]
    )
    assert response.json()["unavailable_reason"] == "assessment_pending"
    assert response.json()["assessment"] is None and response.json()["plans"] == []
    assert PRINCIPAL not in response.text and "private-request-id" not in response.text
    assert not state.creates


async def test_exact_retries_deduplicate_and_changed_body_or_operation_conflicts() -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    async with _client(dependencies) as client:
        first = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
        duplicate = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
        changed = await client.post(
            "/alert-quality/proposals",
            json=_proposal(treatment=_treatment(target_ref="rule:two")),
            headers=HEADERS,
        )
        operation = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert first.status_code == duplicate.status_code == 202
    assert first.json() == duplicate.json()
    assert changed.status_code == operation.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"
    assert len(writer.proposals) == 1
    assert next(iter(writer.proposals.values())).operation == "alert_noise.propose"


async def test_idempotency_is_principal_scoped_but_not_payload_or_scope_scoped() -> None:
    _, writer, dependencies = _harness()
    dependencies = replace(
        dependencies,
        principal_scopes={
            PRINCIPAL: frozenset({SCOPE, "scope:two"}),
            OTHER_PRINCIPAL: frozenset({SCOPE}),
        },
    )
    async with _client(dependencies) as client:
        first = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
        other = await client.post(
            "/alert-quality/assess",
            json={"scope_ref": SCOPE},
            headers={**HEADERS, "Authorization": "Bearer other"},
        )
        changed_scope = await client.post(
            "/alert-quality/assess", json={"scope_ref": "scope:two"}, headers=HEADERS
        )
    assert first.status_code == other.status_code == 202 and changed_scope.status_code == 409
    assert len(writer.proposals) == 2
    assert {row.principal_id for row in writer.proposals.values()} == {PRINCIPAL, OTHER_PRINCIPAL}


@pytest.mark.parametrize("key", ["", " ", "https://example.com", "a" * 257])
async def test_invalid_idempotency_is_rejected_before_read_or_enqueue(key: str) -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess",
            json={"scope_ref": SCOPE},
            headers={**HEADERS, "Idempotency-Key": key},
        )
    assert response.status_code == 400 and not writer.proposals and not state.finds


async def test_non_durable_receipt_and_producer_failure_never_claim_acceptance() -> None:
    _, writer, dependencies = _harness()
    writer.durable = False
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 503 and "private-request-id" not in response.text

    async def failed_probe() -> bool:
        raise RuntimeError("https://example.com/private-provider-detail")

    writer.proposals.clear()
    async with _client(replace(dependencies, producer_ready=failed_probe)) as client:
        response = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    assert response.status_code == 503 and not writer.proposals
    assert "private-provider" not in response.text


async def test_current_report_and_plans_roundtrip_without_synthesizing_acknowledgements() -> None:
    _, _, dependencies = _harness()
    await _seed(dependencies, with_plan=True)
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = AlertQualityResponse.model_validate_json(response.text, strict=True)
    assert body.available and body.requestable and body.authority == "shadow"
    assert body.assessment == _assessment() and body.plans == (_plan(),)
    assert body.assessment.acknowledgements is None
    assert body.model_dump(mode="json") == response.json()
    assert PRINCIPAL not in response.text


@pytest.mark.parametrize("kind", ["suppression", "evaluation"])
async def test_other_treatment_axes_enqueue_only_typed_selectors(kind: str) -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    treatment: dict[str, object] = {"kind": kind, "target_ref": "rule:one"}
    if kind == "suppression":
        treatment.update(
            processing_rule_ref="processing:one",
            starts_at="2026-09-14T13:00:00+00:00",
            ends_at="2026-09-14T14:00:00+00:00",
        )
    else:
        treatment["evaluation"] = {
            "metric_ref": "metric:cpu",
            "operator": "above",
            "threshold": 90.0,
            "window_seconds": 300,
            "frequency_seconds": 60,
            "aggregation": "average",
        }
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/proposals", json=_proposal(treatment=treatment), headers=HEADERS
        )
    assert response.status_code == 202 and response.json()["plans"] == []
    assert next(iter(writer.proposals.values())).payload["treatment"] == (
        AlertTreatment.model_validate(treatment).model_dump(mode="json")
    )


async def test_duplicate_authentication_and_idempotency_headers_are_rejected() -> None:
    _, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        for headers, status in (
            ([("Authorization", "Bearer reader"), ("Authorization", "Bearer owner")], 401),
            (
                [
                    ("Authorization", "Bearer contributor"),
                    ("Idempotency-Key", "one"),
                    ("Idempotency-Key", "two"),
                ],
                400,
            ),
        ):
            response = await client.post(
                "/alert-quality/assess", headers=headers, json={"scope_ref": SCOPE}
            )
            assert response.status_code == status
    assert not writer.proposals


@pytest.mark.parametrize(
    "change",
    [
        {"authority": "enforce"},
        {"available": 1},
        {"enabled": "true"},
        {"caller_receipt": {}},
        {"requestable": 1},
        {"requestable": "true"},
        {"requestable": None},
        {"requestable": True},
    ],
)
def test_public_response_model_has_strict_fields_and_no_extra_authority(
    change: dict[str, object],
) -> None:
    value = {
        "source": "alert-noise-governance",
        "available": False,
        "enabled": True,
        "authority": "shadow",
        "unavailable_reason": "assessment_missing",
        "assessment": None,
        "plans": [],
        **change,
    }
    with pytest.raises(ValidationError):
        AlertQualityResponse.model_validate_json(json.dumps(value), strict=True)


async def test_cross_principal_reads_and_exact_replay_cannot_find_another_report() -> None:
    state, _, dependencies = _harness()
    await _seed(dependencies, with_plan=True)
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers={"Authorization": "Bearer other"})
    assert response.json()["available"] is True  # Producer readiness is not report existence.
    assert response.json()["requestable"] is True
    assert response.json()["assessment"] is None
    assert response.json()["plans"] == []
    source = StateKvAlertQualityStore(state, clock=lambda: NOW)
    assert (
        await source.replay_assessment(
            principal_id=OTHER_PRINCIPAL, scope_ref=SCOPE, evidence_digest=EVIDENCE
        )
        is None
    )
    assert (
        await source.replay_plan(
            principal_id=OTHER_PRINCIPAL, scope_ref=SCOPE, plan_digest=digest_record(_plan())
        )
        is None
    )
    assert await source.read(principal_id=PRINCIPAL, scope_ref="scope:two") is None
    assert all(key.startswith(ALERT_QUALITY_PREFIX) for key in state.records)
    assert PRINCIPAL not in json.dumps(state.records)
    assert OTHER_PRINCIPAL not in json.dumps(state.records)


@pytest.mark.parametrize("future", [False, True])
async def test_expired_or_future_injected_reports_cannot_support_a_current_claim(
    future: bool,
) -> None:
    _, writer, dependencies = _harness()
    report = _assessment(
        observed_at=NOW + timedelta(minutes=1) if future else NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(hours=1) if future else NOW,
    )

    class Source:
        async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot:
            return AlertQualitySnapshot(
                binding_digest=alert_quality_binding_digest(principal_id, scope_ref),
                assessment=report,
                plans=() if future else (_plan(),),
            )

    async with _client(replace(dependencies, source=Source())) as client:
        read = await client.get(READ_PATH, headers=HEADERS)
        post = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
    assert read.json()["unavailable_reason"] == "assessment_not_current"
    assert read.json()["available"] is (not future)
    assert read.json()["requestable"] is (not future)
    assert read.json()["assessment"] == (None if future else report.model_dump(mode="json"))
    assert read.json()["plans"] == ([] if future else [_plan().model_dump(mode="json")])
    assert post.status_code == 409 and not writer.proposals
    if not future:
        async with _client(replace(dependencies, source=Source())) as client:
            reassess = await client.post(
                "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
            )
        assert reassess.status_code == 202 and len(writer.proposals) == 1


async def test_foreign_projection_and_raw_subject_disclosure_fail_closed() -> None:
    _, _, dependencies = _harness()

    class Source:
        async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot:
            return AlertQualitySnapshot(
                binding_digest=alert_quality_binding_digest(OTHER_PRINCIPAL, scope_ref),
                assessment=_assessment(),
            )

    async with _client(replace(dependencies, source=Source())) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.json()["unavailable_reason"] == "source_unavailable"
    store = cast(StateKvAlertQualityStore, dependencies.source)
    with pytest.raises(AlertQualityUnavailableError):
        await store.persist_assessment(
            principal_id=PRINCIPAL,
            scope_ref=SCOPE,
            assessment=_assessment(reasons=(f"subject:{PRINCIPAL}",)),
        )


async def test_authentication_and_producer_are_rechecked_after_source_read() -> None:
    _, writer, dependencies = _harness()
    claims: dict[str, object] = {"oid": PRINCIPAL, "idtyp": "user", "roles": ["Contributor"]}

    class Source:
        async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot:
            claims["roles"] = ["Reader"]
            return AlertQualitySnapshot(
                binding_digest=alert_quality_binding_digest(principal_id, scope_ref),
                assessment=_assessment(),
            )

    changed = replace(
        dependencies,
        source=Source(),
        authenticator=OperatorAuthenticator(verifier=lambda _: claims, group_ids={}),
    )
    async with _client(changed) as client:
        response = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
    assert response.status_code == 403 and not writer.proposals

    await _seed(dependencies)
    readiness = iter((True, False))

    async def lost_binding() -> bool:
        return next(readiness)

    async with _client(replace(dependencies, producer_ready=lost_binding)) as client:
        response = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
    assert response.status_code == 503 and not writer.proposals


async def test_reports_and_plans_are_exact_immutable_replay_across_store_recreation() -> None:
    state, _, dependencies = _harness()
    await _seed(dependencies, with_plan=True)
    before = copy.deepcopy(state.records)
    restarted = StateKvAlertQualityStore(state, clock=lambda: NOW + timedelta(hours=2))
    assert not await restarted.persist_assessment(
        principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=_assessment()
    )
    assert not await restarted.persist_plan(principal_id=PRINCIPAL, scope_ref=SCOPE, plan=_plan())
    assert (
        await restarted.replay_assessment(
            principal_id=PRINCIPAL, scope_ref=SCOPE, evidence_digest=EVIDENCE
        )
        == _assessment()
    )
    assert (
        await restarted.replay_plan(
            principal_id=PRINCIPAL, scope_ref=SCOPE, plan_digest=digest_record(_plan())
        )
        == _plan()
    )
    assert state.records == before


async def test_older_equal_cutoff_and_reused_report_identity_cannot_replace_current() -> None:
    state, _, dependencies = _harness()
    await _seed(dependencies)
    source = cast(StateKvAlertQualityStore, dependencies.source)
    before = copy.deepcopy(state.records)
    for report, error in (
        (
            _assessment(
                evidence_digest="sha256:" + "b" * 64, observed_at=NOW - timedelta(minutes=6)
            ),
            AlertQualityStaleError,
        ),
        (_assessment(evidence_digest="sha256:" + "b" * 64), AlertQualityConflictError),
        (_assessment(source_episodes=13), AlertQualityConflictError),
    ):
        with pytest.raises(error):
            await source.persist_assessment(
                principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=report
            )
    assert state.records == before


async def test_newer_report_preserves_history_and_holds_old_plan_publication() -> None:
    state, _, dependencies = _harness()
    await _seed(dependencies, with_plan=True)
    source = cast(StateKvAlertQualityStore, dependencies.source)
    newer = _assessment(
        evidence_digest="sha256:" + "b" * 64, observed_at=NOW - timedelta(seconds=30)
    )
    assert await source.persist_assessment(
        principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=newer
    )
    current = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE)
    assert current is not None and current.assessment == newer and current.plans == ()
    with pytest.raises(AlertQualityStaleError):
        await source.persist_plan(principal_id=PRINCIPAL, scope_ref=SCOPE, plan=_plan())
    assert (
        await source.replay_assessment(
            principal_id=PRINCIPAL, scope_ref=SCOPE, evidence_digest=EVIDENCE
        )
        == _assessment()
    )
    assert all(key.startswith(ALERT_QUALITY_PREFIX) for key in state.records)


@pytest.mark.parametrize("tamper", ["extra", "authority", "numeric_authority", "cutoff"])
async def test_malformed_stored_reports_are_unavailable_not_empty_success(tamper: str) -> None:
    state, _, dependencies = _harness()
    await _seed(dependencies)
    key = next(key for key in state.records if ":report:" in key)
    report = cast(dict[str, object], state.records[key]["assessment"])
    if tamper == "extra":
        report["caller_observation"] = "untrusted"
    elif tamper == "cutoff":
        report["observed_at"] = (NOW - timedelta(minutes=4)).isoformat()
    else:
        report["execution_authority"] = True if tamper == "authority" else 0
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.json()["unavailable_reason"] == "source_unavailable"
    assert response.json()["assessment"] is None and response.json()["plans"] == []


async def test_losing_index_insert_rechecks_newer_winner_without_overwriting_it() -> None:
    class RacingState(_State):
        before_index: Callable[[], Awaitable[None]] | None = None

        async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
            if ":index:" in key and self.before_index is not None:
                callback, self.before_index = self.before_index, None
                await callback()
            return await super().create_state(key, value)

    state = RacingState()
    source = StateKvAlertQualityStore(state, clock=lambda: NOW)
    newer = _assessment(
        evidence_digest="sha256:" + "b" * 64, observed_at=NOW - timedelta(minutes=1)
    )

    async def competitor() -> None:
        assert await source.persist_assessment(
            principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=newer
        )

    state.before_index = competitor
    with pytest.raises(AlertQualityStaleError):
        await source.persist_assessment(
            principal_id=PRINCIPAL, scope_ref=SCOPE, assessment=_assessment()
        )
    snapshot = await source.read(principal_id=PRINCIPAL, scope_ref=SCOPE)
    assert snapshot is not None and snapshot.assessment == newer
    assert len([key for key in state.records if ":index:" in key]) == 1


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "[]",
        '{"operator-subject-one":["*"]}',
        '{"operator-subject-one":["https://example.com"]}',
        '{"operator-subject-one":["scope:one","scope:one"]}',
        '{"operator-subject-one":true}',
        '{"operator-subject-one":[],"operator-subject-one":["scope:one"]}',
    ],
)
def test_private_scope_configuration_rejects_ambiguous_or_unbounded_authority(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid private alert quality scope configuration"):
        parse_alert_quality_principal_scopes({PRINCIPAL_SCOPES_ENV: raw})


def test_private_entra_subjects_remain_exact_internal_bindings_and_defaults_stay_closed() -> None:
    subject = "00000000-0000-0000-0000-000000000001"
    parsed = parse_alert_quality_principal_scopes(
        {PRINCIPAL_SCOPES_ENV: json.dumps({subject: [SCOPE]})}
    )
    assert parsed[subject] == frozenset({SCOPE})
    assert subject not in alert_quality_requester_ref(subject, SCOPE)
    assert alert_quality_binding_digest(subject, SCOPE) != alert_quality_binding_digest(
        subject, "scope:two"
    )
    state, writer, dependencies = _harness()
    production = alert_quality_dependencies_from_environment(
        authenticator=dependencies.authenticator,
        environ={PRINCIPAL_SCOPES_ENV: json.dumps({PRINCIPAL: [SCOPE]})},
        store=state,
        proposal_writer=writer,
    )
    assert isinstance(production.source, StateKvAlertQualityStore)
    assert production.producer_ready is None
    assert production.proposal_writer is writer
    assert not parse_alert_quality_principal_scopes({})


async def test_http_surface_has_no_observation_or_plan_materialization_route() -> None:
    state, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        observation = await client.post(
            "/alert-quality/observations",
            json=_assessment().model_dump(mode="json"),
            headers=HEADERS,
        )
        report = await client.post(
            "/alert-quality", json=_assessment().model_dump(mode="json"), headers=HEADERS
        )
    assert observation.status_code == 404 and report.status_code == 405
    assert not state.creates and not writer.proposals


@pytest.mark.parametrize("token", ["reader", "contributor", "approver", "owner"])
async def test_scope_discovery_is_exact_sorted_private_and_independent_of_producer(
    token: str,
) -> None:
    state, writer, dependencies = _harness()
    scopes = frozenset(f"scope:{number:02d}" for number in range(64))

    async def unused_probe() -> bool:
        raise AssertionError("scope discovery MUST NOT probe the producer")

    dependencies = replace(
        dependencies,
        principal_scopes={PRINCIPAL: scopes, OTHER_PRINCIPAL: frozenset({"scope:private"})},
        producer_ready=unused_probe,
    )
    async with _client(dependencies) as client:
        response = await client.get(
            "/alert-quality/scopes", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.json() == {
        "source": "alert-noise-governance",
        "scope_refs": sorted(scopes),
        "execution_authority": False,
    }
    decoded = AlertQualityScopesResponse.model_validate_json(response.text)
    assert decoded.scope_refs == tuple(sorted(scopes))
    assert response.headers["cache-control"] == "no-store"
    assert PRINCIPAL not in response.text and OTHER_PRINCIPAL not in response.text
    assert "scope:private" not in response.text
    assert not state.reads and not state.finds and not state.creates and not writer.proposals


@pytest.mark.parametrize(
    "query", ["?scope_ref=scope:one", "?principal_id=other", "?x=", "?" + "x" * 513]
)
async def test_scope_discovery_accepts_no_query(query: str) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get("/alert-quality/scopes" + query, headers=HEADERS)
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert not state.reads and not state.finds


@pytest.mark.parametrize("scopes", [[], [SCOPE]])
async def test_scope_discovery_returns_only_the_authenticated_binding(scopes: list[str]) -> None:
    _, _, dependencies = _harness()
    dependencies = replace(dependencies, principal_scopes={OTHER_PRINCIPAL: frozenset(scopes)})
    async with _client(dependencies) as client:
        response = await client.get("/alert-quality/scopes", headers=HEADERS)
    assert response.json()["scope_refs"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"execution_authority": 0},
        {"execution_authority": True},
        {"subject_id": PRINCIPAL},
        {"scope_refs": [SCOPE, SCOPE]},
        {"scope_refs": ["scope:two", SCOPE]},
        {"scope_refs": ["scope:one\n"]},
        {"scope_refs": [False]},
        {"scope_refs": [f"scope:{number:02d}" for number in range(65)]},
    ],
)
def test_discovery_model_refuses_scope_repair_or_authority(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AlertQualityScopesResponse.model_validate_json(
            json.dumps(
                {
                    "source": "alert-noise-governance",
                    "scope_refs": [SCOPE],
                    "execution_authority": False,
                    **change,
                }
            ),
            strict=True,
        )


async def test_scope_discovery_never_exposes_a_subject_embedded_in_a_scope() -> None:
    _, _, dependencies = _harness()
    dependencies = replace(
        dependencies, principal_scopes={PRINCIPAL: frozenset({f"scope:{PRINCIPAL}"})}
    )
    async with _client(dependencies) as client:
        response = await client.get("/alert-quality/scopes", headers=HEADERS)
    assert response.status_code == 503 and PRINCIPAL not in response.text


@pytest.mark.parametrize(
    "token,requestable",
    [
        ("reader", False),
        ("contributor", True),
        ("approver", True),
        ("owner", True),
    ],
)
async def test_first_assessment_capability_does_not_require_a_report(
    token: str, requestable: bool
) -> None:
    state, _, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.json() == {
        "source": "alert-noise-governance",
        "available": True,
        "enabled": True,
        "requestable": requestable,
        "authority": "shadow",
        "unavailable_reason": None,
        "assessment": None,
        "plans": [],
    }
    assert not state.creates


@pytest.mark.parametrize("ready_value", [False, 1, "ready", None])
@pytest.mark.parametrize("expired", [False, True])
async def test_unready_producer_does_not_discard_retained_read_evidence(
    ready_value: object, expired: bool
) -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies, with_plan=True)

    async def not_ready() -> bool:
        return cast(bool, ready_value)

    dependencies = replace(
        dependencies,
        producer_ready=not_ready,
        clock=lambda: NOW + timedelta(hours=2) if expired else NOW,
    )
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
        post = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=HEADERS
        )
    body = response.json()
    assert body["available"] is True and body["requestable"] is False
    assert body["assessment"] == _assessment().model_dump(mode="json")
    assert body["plans"] == [_plan().model_dump(mode="json")]
    assert body["unavailable_reason"] == ("assessment_not_current" if expired else None)
    assert post.status_code == 503 and not writer.proposals


@pytest.mark.parametrize("missing", ["proposal_writer", "producer_ready"])
async def test_unbound_request_dependencies_veto_requests_but_preserve_reports(
    missing: str,
) -> None:
    _, _, dependencies = _harness()
    await _seed(dependencies)
    async with _client(replace(dependencies, **{missing: None})) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.json()["available"] is True
    assert response.json()["requestable"] is False
    assert response.json()["assessment"] is not None


async def test_producer_probe_failure_preserves_evidence_without_exception_content() -> None:
    _, _, dependencies = _harness()
    await _seed(dependencies)

    async def unavailable() -> bool:
        raise RuntimeError("private-provider-detail")

    async with _client(replace(dependencies, producer_ready=unavailable)) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.json()["available"] is True and response.json()["requestable"] is False
    assert response.json()["assessment"] is not None and "private-provider" not in response.text


@pytest.mark.parametrize("seed", [False, True])
@pytest.mark.parametrize("revoke", ["role", "identity", "scope"])
async def test_read_revalidates_after_readiness_even_without_a_first_report(
    seed: bool, revoke: str
) -> None:
    _, _, dependencies = _harness()
    if seed:
        await _seed(dependencies)
    claims: dict[str, object] = dict(_verify("contributor"))

    async def readiness() -> bool:
        if revoke == "role":
            claims["roles"] = ["Reader"]
        elif revoke == "identity":
            claims["oid"] = OTHER_PRINCIPAL
        else:
            object.__setattr__(dependencies, "principal_scopes", {})
        return True

    dependencies = replace(
        dependencies,
        producer_ready=readiness,
        authenticator=OperatorAuthenticator(verifier=lambda _: claims, group_ids={}),
    )
    async with _client(dependencies) as client:
        response = await client.get(READ_PATH, headers=HEADERS)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert "assessment" not in response.json() and PRINCIPAL not in response.text


@pytest.mark.parametrize("path", ["/alert-quality/assess", "/alert-quality/proposals"])
@pytest.mark.parametrize("stage", ["readiness", "writer"])
async def test_request_revalidates_before_enqueue_and_after_durable_writer(
    path: str, stage: str
) -> None:
    _, _, dependencies = _harness()
    await _seed(dependencies)
    claims: dict[str, object] = dict(_verify("contributor"))

    class RevokingWriter(_Writer):
        async def propose(self, proposal: EventProposal) -> ProposalReceipt:
            receipt = await super().propose(proposal)
            claims["roles"] = ["Reader"]
            return receipt

    async def readiness() -> bool:
        if stage == "readiness":
            claims["roles"] = ["Reader"]
        return True

    writer = RevokingWriter()
    dependencies = replace(
        dependencies,
        proposal_writer=writer,
        producer_ready=readiness,
        authenticator=OperatorAuthenticator(verifier=lambda _: claims, group_ids={}),
    )
    async with _client(dependencies) as client:
        response = await client.post(
            path,
            json=_proposal() if path.endswith("proposals") else {"scope_ref": SCOPE},
            headers=HEADERS,
        )
    assert response.status_code == 403
    assert len(writer.proposals) == (1 if stage == "writer" else 0)
    assert "x-correlation-id" not in response.headers
    assert response.headers["cache-control"] == "no-store"


async def test_proposal_expiry_is_rechecked_after_the_last_readiness_await() -> None:
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    instant = NOW
    calls = 0

    async def readiness() -> bool:
        nonlocal instant, calls
        calls += 1
        if calls == 2:
            instant = _assessment().valid_until
        return True

    dependencies = replace(dependencies, producer_ready=readiness, clock=lambda: instant)
    async with _client(dependencies) as client:
        response = await client.post("/alert-quality/proposals", json=_proposal(), headers=HEADERS)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "evidence_not_current"
    )
    assert calls == 2 and not writer.proposals


async def test_workload_reader_may_discover_and_read_but_is_never_requestable() -> None:
    _, writer, dependencies = _harness()
    principal = dependencies.authenticator.authenticate("Bearer workload")
    dependencies = replace(
        dependencies, principal_scopes={principal.subject_id: frozenset({SCOPE})}
    )
    headers = {**HEADERS, "Authorization": "Bearer workload"}
    async with _client(dependencies) as client:
        discovery = await client.get("/alert-quality/scopes", headers=headers)
        read = await client.get(READ_PATH, headers=headers)
        post = await client.post(
            "/alert-quality/assess", json={"scope_ref": SCOPE}, headers=headers
        )
    assert discovery.status_code == read.status_code == 200
    assert read.json()["available"] is True and read.json()["requestable"] is False
    assert discovery.json()["scope_refs"] == [SCOPE]
    assert post.status_code == 403 and not writer.proposals
    assert principal.subject_id not in discovery.text and principal.subject_id not in read.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", READ_PATH),
        ("POST", "/alert-quality/assess"),
        ("POST", "/alert-quality/proposals"),
    ],
)
async def test_request_deadline_never_queues_or_returns_fabricated_evidence(
    method: str, path: str
) -> None:
    _, writer, dependencies = _harness()

    async def stalled() -> bool:
        await asyncio.Future[None]()
        raise AssertionError("a cancelled readiness probe MUST NOT finish")

    dependencies = replace(dependencies, producer_ready=stalled, timeout_seconds=0.001)
    body = _proposal() if path.endswith("proposals") else {"scope_ref": SCOPE}
    async with _client(dependencies) as client:
        response = await client.request(
            method,
            path,
            headers=HEADERS,
            json=None if method == "GET" else body,
        )
    assert response.status_code == (200 if method == "GET" else 503)
    assert response.headers["cache-control"] == "no-store" and not writer.proposals
    if method == "GET":
        assert response.json()["available"] is False and response.json()["requestable"] is False
        assert response.json()["assessment"] is None and response.json()["plans"] == []


async def test_duplicate_nested_treatment_members_are_rejected_before_evidence_reads() -> None:
    state, writer, dependencies = _harness()
    raw = json.dumps(_proposal()).replace(
        '"target_ref": "rule:one"', '"target_ref":"rule:one","target_ref":"rule:two"'
    )
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/proposals",
            content=raw,
            headers={**HEADERS, "Content-Type": "application/json"},
        )
    assert response.status_code == 400
    assert not state.finds and not state.creates and not writer.proposals

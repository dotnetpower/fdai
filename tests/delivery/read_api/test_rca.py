"""RCA (root-cause analysis) projection and GET-only route tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import AuditItem, InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.rca_projection import project_rca


def _item(
    seq: int,
    correlation_id: str | None,
    *,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    action_kind: str = "control.stage",
    mode: str = "shadow",
    entry: dict[str, object] | None = None,
) -> AuditItem:
    return AuditItem(
        seq=seq,
        event_id=event_id,
        correlation_id=correlation_id,
        actor="fdai.core.rca",
        action_kind=action_kind,
        mode=mode,
        entry=entry or {},
        entry_hash=f"hash-{seq}",
        previous_hash=f"hash-{seq - 1}",
        recorded_at=f"2026-07-14T10:{seq:02d}:00+00:00",
    )


def _rca_item(
    seq: int,
    correlation_id: str,
    *,
    tier: str,
    outcome: str = "grounded",
    cause: str | None = "public network access left open",
    confidence: float | None = 0.9,
    citations: list[dict[str, str]] | None = None,
    remediation_ref: str | None = "storage.disable-public-access",
    reason: str = "matched control names the violated policy",
) -> AuditItem:
    return _item(
        seq,
        correlation_id,
        action_kind="rca.hypothesis",
        entry={
            "rca_outcome": outcome,
            "rca_reason": reason,
            "rca_tier": tier,
            "rca_cause": cause,
            "rca_confidence": confidence,
            "rca_citations": citations
            if citations is not None
            else [{"kind": "rule", "ref": "storage.public-access"}],
            "rca_remediation_ref": remediation_ref,
        },
    )


def test_projection_orders_hypotheses_newest_first_with_citations() -> None:
    items = (
        _rca_item(1, "corr-1", tier="t0"),
        _rca_item(
            3,
            "corr-1",
            tier="t2",
            cause="novel latency spike",
            confidence=0.6,
            citations=[
                {"kind": "event", "ref": "evt-9"},
                {"kind": "telemetry", "ref": "aks-prod/nodepool-1"},
            ],
        ),
    )
    view = project_rca(items, correlation_id="corr-1")
    assert view.correlation_id == "corr-1"
    assert [h.tier for h in view.hypotheses] == ["t2", "t0"]
    first = view.hypotheses[0]
    assert first.grounded is True
    assert first.confidence == 0.6
    assert [(c.kind, c.ref) for c in first.citations] == [
        ("event", "evt-9"),
        ("telemetry", "aks-prod/nodepool-1"),
    ]


def test_projection_retains_structured_causal_chain() -> None:
    item = _rca_item(1, "corr-chain", tier="t1")
    item.entry["rca_causal_chain"] = {
        "root_event_id": "change-1",
        "failure_event_id": "failure-1",
        "confidence": 0.82,
        "ambiguity": 1,
        "hops": [
            {
                "cause_event_id": "change-1",
                "effect_event_id": "failure-1",
                "cause_resource_ref": "service-a",
                "effect_resource_ref": "service-b",
                "lead_seconds": 75.0,
                "relationship": "dependency",
                "confidence": 0.82,
            }
        ],
    }
    hypothesis = project_rca((item,), correlation_id="corr-chain").hypotheses[0]
    assert hypothesis.causal_chain is not None
    assert hypothesis.causal_chain.root_event_id == "change-1"
    assert hypothesis.causal_chain.hops[0].lead_seconds == 75.0
    assert hypothesis.to_dict()["causal_chain"]["hops"][0]["relationship"] == "dependency"


def test_malformed_causal_chain_is_unavailable_not_partial() -> None:
    item = _rca_item(1, "corr-bad-chain", tier="t1")
    item.entry["rca_causal_chain"] = {
        "root_event_id": "change-1",
        "failure_event_id": "failure-1",
        "confidence": 0.82,
        "ambiguity": 1,
        "hops": [{"cause_event_id": "change-1"}],
    }
    hypothesis = project_rca((item,), correlation_id="corr-bad-chain").hypotheses[0]
    assert hypothesis.causal_chain is None


def test_abstained_hypothesis_is_marked_not_grounded() -> None:
    items = (
        _rca_item(
            1,
            "corr-abstain",
            tier="t2",
            outcome="abstained",
            cause=None,
            confidence=None,
            citations=[],
            remediation_ref=None,
        ),
    )
    view = project_rca(items, correlation_id="corr-abstain")
    hypothesis = view.hypotheses[0]
    assert hypothesis.outcome == "abstained"
    assert hypothesis.grounded is False
    assert hypothesis.cause is None
    assert hypothesis.confidence is None
    assert hypothesis.citations == ()


def test_projection_composes_linked_response_plan() -> None:
    items = (
        _rca_item(1, "corr-resp", tier="t0"),
        _item(
            2,
            "corr-resp",
            action_kind="risk_gate.shadow_authority",
            mode="enforce",
            entry={
                "decision": "auto",
                "rollback_reference": "pr-42",
            },
        ),
    )
    view = project_rca(items, correlation_id="corr-resp")
    assert view.response is not None
    assert view.response.verdict == "auto"
    assert view.response.decision == "auto"
    assert view.response.mode == "enforce"
    assert view.response.rollback_reference == "pr-42"
    assert view.response.action_kind == "risk_gate.shadow_authority"


def test_projection_without_action_rows_has_no_response() -> None:
    items = (_rca_item(1, "corr-only-rca", tier="t1"),)
    view = project_rca(items, correlation_id="corr-only-rca")
    assert view.response is None
    assert len(view.hypotheses) == 1


def test_malformed_citations_are_dropped_not_raised() -> None:
    items = (
        _rca_item(
            1,
            "corr-bad-cite",
            tier="t0",
            citations=[
                {"kind": "rule", "ref": "ok"},
                {"kind": "rule"},  # missing ref
                {"ref": "no-kind"},  # missing kind
            ],
        ),
    )
    view = project_rca(items, correlation_id="corr-bad-cite")
    assert [(c.kind, c.ref) for c in view.hypotheses[0].citations] == [("rule", "ok")]


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    yield


def _client() -> tuple[TestClient, InMemoryConsoleReadModel]:
    mapping = GroupMapping(
        reader_group_id="reader",
        contributor_group_id="contributor",
        approver_group_id="approver",
        owner_group_id="owner",
        break_glass_group_id="break-glass",
    )
    auth = build_authenticator(
        verifier=lambda _: {"oid": "unused"},
        resolver=RoleResolver(group_mapping=mapping),
    )
    read_model = InMemoryConsoleReadModel()
    app = build_app(
        authenticator=auth,
        read_model=read_model,
        config=ReadApiConfig(dev_mode=True),
    )
    return TestClient(app), read_model


def test_rca_route_returns_view_and_is_get_only(dev_env: None) -> None:
    del dev_env
    client, read_model = _client()
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "correlation_id": "corr-target",
            "action_kind": "rca.hypothesis",
            "rca_outcome": "grounded",
            "rca_tier": "t0",
            "rca_cause": "public access open",
            "rca_confidence": 0.95,
            "rca_citations": [{"kind": "rule", "ref": "storage.public-access"}],
            "rca_reason": "matched control",
        },
        action_kind="rca.hypothesis",
    )
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "correlation_id": "corr-target",
            "action_kind": "risk_gate.shadow_authority",
            "decision": "auto",
            "rollback_reference": "pr-7",
        },
        action_kind="risk_gate.shadow_authority",
    )
    response = client.get("/rca?correlation=corr-target")
    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == "corr-target"
    assert len(body["hypotheses"]) == 1
    assert body["hypotheses"][0]["tier"] == "t0"
    assert body["hypotheses"][0]["grounded"] is True
    assert body["response"]["verdict"] == "auto"
    assert body["response"]["rollback_reference"] == "pr-7"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, "/rca").status_code == 405


def test_rca_route_requires_correlation(dev_env: None) -> None:
    del dev_env
    client, _ = _client()
    assert client.get("/rca").status_code == 400
    assert client.get("/rca?correlation=").status_code == 400


def test_rca_route_empty_incident_returns_no_hypotheses(dev_env: None) -> None:
    del dev_env
    client, _ = _client()
    response = client.get("/rca?correlation=corr-unknown")
    assert response.status_code == 200
    body = response.json()
    assert body["hypotheses"] == []
    assert body["response"] is None

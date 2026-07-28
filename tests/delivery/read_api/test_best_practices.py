"""Integration tests for the read-only Best Practice catalog projection."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.shared.contracts.models import BestPractice

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _controls() -> tuple[BestPractice, ...]:
    return load_best_practice_catalog(
        _REPO_ROOT / "rule-catalog" / "best-practices",
        strict=False,
    )


def _client(controls: tuple[BestPractice, ...] | None = None) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            best_practice_controls=_controls() if controls is None else controls,
        ),
    )
    return TestClient(app)


def test_list_exposes_all_current_waf_controls() -> None:
    body = _client().get("/best-practices").json()
    assert body["total"] == 21
    assert body["filtered_total"] == 21
    assert body["facets"]["by_pillar"] == {
        "operational_excellence": 11,
        "reliability": 10,
    }
    assert {item["control_id"] for item in body["controls"]} == {
        *(f"RE:{index:02d}" for index in range(1, 11)),
        *(f"OE:{index:02d}" for index in range(1, 12)),
    }


def test_list_never_infers_runtime_compliance_from_definitions() -> None:
    body = _client().get("/best-practices").json()
    assert body["evaluation_source"] == "not_connected"
    assert body["facets"]["by_status"] == {"unknown": 21}
    assert all(item["status"] == "unknown" for item in body["controls"])
    assert all(item["satisfied_requirement_count"] == 0 for item in body["controls"])


def test_list_orders_by_severity_then_control_id() -> None:
    controls = _client().get("/best-practices").json()["controls"]
    ranks = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    keys = [(-ranks[item["severity"]], item["control_id"]) for item in controls]
    assert keys == sorted(keys)


def test_filters_search_and_pagination_compose() -> None:
    client = _client()
    reliability = client.get(
        "/best-practices",
        params={"pillar": "reliability", "status": "unknown"},
    ).json()
    assert reliability["filtered_total"] == 10
    assert all(item["pillar"] == "reliability" for item in reliability["controls"])

    search = client.get("/best-practices", params={"q": "disaster recovery"}).json()
    assert [item["control_id"] for item in search["controls"]] == ["RE:09"]

    page = client.get("/best-practices", params={"limit": "3", "offset": "2"}).json()
    assert page["filtered_total"] == 21
    assert len(page["controls"]) == 3
    assert page["offset"] == 2


def test_detail_exposes_requirements_and_provenance_without_evidence() -> None:
    body = _client().get("/best-practices/RE:09").json()
    assert body["control_id"] == "RE:09"
    assert body["requirements"]
    assert len(body["requirements"]) == body["requirement_count"]
    assert all(item["status"] == "unknown" for item in body["requirements"])
    assert all(item["evidence_refs"] == [] for item in body["requirements"])
    assert body["provenance"]["source_url"].startswith("https://learn.microsoft.com/")


def test_detail_accepts_catalog_id_and_rejects_unknown_id() -> None:
    client = _client()
    assert client.get("/best-practices/azure-waf.reliability.re-09").status_code == 200
    assert client.get("/best-practices/missing").status_code == 404


def test_invalid_paging_is_rejected() -> None:
    client = _client()
    assert client.get("/best-practices", params={"limit": "0"}).status_code == 400
    assert client.get("/best-practices", params={"limit": "201"}).status_code == 400
    assert client.get("/best-practices", params={"offset": "-1"}).status_code == 400
    assert client.get("/best-practices", params={"limit": "many"}).status_code == 400


def test_routes_are_get_only_and_optional() -> None:
    client = _client()
    assert client.post("/best-practices").status_code == 405
    assert client.post("/best-practices/RE:09").status_code == 405
    empty = _client(controls=())
    assert empty.get("/best-practices").status_code == 404

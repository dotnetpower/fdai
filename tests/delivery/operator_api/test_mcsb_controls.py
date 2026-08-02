"""Integration tests for the read-only versioned MCSB projection."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog, load_mcsb_catalogs

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _catalogs() -> tuple[McsbCatalog, ...]:
    return load_mcsb_catalogs(
        _ROOT / "rule-catalog" / "compliance" / "mcsb",
        strict=False,
    )


def _client(catalogs: tuple[McsbCatalog, ...] | None = None) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            mcsb_catalogs=_catalogs() if catalogs is None else catalogs,
        ),
    )
    return TestClient(app)


def test_list_defaults_to_complete_v1_without_claiming_compliance() -> None:
    body = _client().get("/mcsb-controls").json()

    assert body["benchmark"]["benchmark_version"] == "v1"
    assert body["total"] == 86
    assert body["facets"]["by_coverage"] == {
        "unmapped": 61,
        "partial": 16,
        "manual": 9,
    }
    assert body["evaluation_source"] == "catalog_crosswalk"
    assert "status" not in body["controls"][0]


def test_filters_search_and_paging_compose() -> None:
    client = _client()
    partial_network = client.get(
        "/mcsb-controls",
        params={"domain": "NS", "coverage": "partial"},
    ).json()
    assert {item["control_id"] for item in partial_network["controls"]} == {
        "NS-2",
        "NS-5",
        "NS-8",
    }

    search = client.get("/mcsb-controls", params={"q": "standing access"}).json()
    assert [item["control_id"] for item in search["controls"]] == ["PA-2"]

    page = client.get("/mcsb-controls", params={"limit": "5", "offset": "3"}).json()
    assert len(page["controls"]) == 5
    assert page["filtered_total"] == 86


def test_v2_preview_exposes_imported_controls_without_claiming_coverage() -> None:
    body = _client().get("/mcsb-controls", params={"version": "v2-preview"}).json()

    assert body["total"] == 81
    assert body["benchmark"]["status"] == "preview"
    assert body["benchmark"]["control_import_status"] == "complete"
    assert body["facets"]["by_coverage"] == {"unmapped": 81}
    assert body["facets"]["by_domain"]["AI"] == 7
    assert any(item["control_id"] == "AI-1" for item in body["controls"])
    assert body["benchmark"]["policy_profiles"] == [
        {
            "profile_id": "compliance.security-center.preview-microsoft-cloud-security-benc",
            "policy_ref_count": 410,
        }
    ]


def test_detail_exposes_implementation_refs_and_pinned_source() -> None:
    body = _client().get("/mcsb-controls/v1/DP-3").json()

    assert body["coverage"] == "partial"
    assert body["rule_ids"] == [
        "object-storage.https-only.required",
        "object-storage.min-tls-version",
        "postgresql-server.ssl-enforcement",
    ]
    assert body["runtime_observation_ids"] == ["mysql-tls"]
    assert body["source"]["content_hash"].startswith("sha256:")


def test_invalid_version_control_and_paging_are_rejected() -> None:
    client = _client()
    assert client.get("/mcsb-controls", params={"version": "v3"}).status_code == 400
    assert client.get("/mcsb-controls/v1/MISSING-1").status_code == 404
    assert client.get("/mcsb-controls", params={"limit": "0"}).status_code == 400
    assert client.get("/mcsb-controls", params={"offset": "-1"}).status_code == 400


def test_routes_are_get_only_and_optional() -> None:
    client = _client()
    assert client.post("/mcsb-controls").status_code == 405
    assert client.post("/mcsb-controls/v1/DP-3").status_code == 405
    assert _client(catalogs=()).get("/mcsb-controls").status_code == 404

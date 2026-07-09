"""Integration tests for the ``/rules`` rule-catalog GET route."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _rule(
    rule_id: str,
    *,
    severity: Severity,
    category: Category,
    source: RuleSource,
    resource_type: str,
    cost: float | None = None,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=source,
        severity=severity,
        category=category,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl", cost_impact_monthly_usd=cost),
        remediates="remediate.example",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _active() -> tuple[Rule, ...]:
    return (
        _rule(
            "disk.unattached",
            severity=Severity.LOW,
            category=Category.COST,
            source=RuleSource.AZURE_ADVISOR,
            resource_type="disk",
            cost=12.5,
        ),
        _rule(
            "object-storage.public-access.deny",
            severity=Severity.CRITICAL,
            category=Category.SECURITY,
            source=RuleSource.MCSB,
            resource_type="object-storage",
        ),
    )


def _collected() -> tuple[Rule, ...]:
    return (
        _rule(
            "azure-builtin.aaa",
            severity=Severity.MEDIUM,
            category=Category.SECURITY,
            source=RuleSource.AZURE_POLICY,
            resource_type="azure.resource",
        ),
        _rule(
            "kube-bench.bbb",
            severity=Severity.HIGH,
            category=Category.SECURITY,
            source=RuleSource.KUBE_BENCH,
            resource_type="kubernetes-cluster.etcd",
        ),
        _rule(
            "azure-builtin.ccc",
            severity=Severity.LOW,
            category=Category.RELIABILITY,
            source=RuleSource.AZURE_POLICY,
            resource_type="azure.resource",
        ),
    )


def _client(*, active: bool = True, collected: bool = True) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            rule_catalog_rules=_active() if active else (),
            rule_catalog_collected_rules=_collected() if collected else (),
        ),
    )
    return TestClient(app)


def _client_with_roots(policies_root: object, remediation_root: object) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            rule_catalog_rules=_active(),
            rule_catalog_policies_root=policies_root,
            rule_catalog_remediation_root=remediation_root,
        ),
    )
    return TestClient(app)


def test_rules_returns_totals_and_facets() -> None:
    body = _client().get("/rules").json()
    assert body["total"] == 5
    assert body["filtered_total"] == 5
    assert body["facets"]["by_origin"] == {"collected": 3, "active": 2}
    assert body["facets"]["by_category"] == {"security": 3, "cost": 1, "reliability": 1}
    assert body["facets"]["by_severity"] == {"low": 2, "critical": 1, "high": 1, "medium": 1}
    assert body["resource_type_count"] == 4


def test_rules_tagged_with_origin() -> None:
    rules = _client().get("/rules").json()["rules"]
    by_id = {r["id"]: r["origin"] for r in rules}
    assert by_id["disk.unattached"] == "active"
    assert by_id["azure-builtin.aaa"] == "collected"


def test_rules_ordered_severity_desc_then_id() -> None:
    ids = [r["id"] for r in _client().get("/rules").json()["rules"]]
    assert ids == [
        "object-storage.public-access.deny",  # critical
        "kube-bench.bbb",  # high
        "azure-builtin.aaa",  # medium
        "azure-builtin.ccc",  # low, id < disk
        "disk.unattached",  # low
    ]


def test_origin_filter() -> None:
    body = _client().get("/rules", params={"origin": "collected"}).json()
    assert body["filtered_total"] == 3
    assert all(r["origin"] == "collected" for r in body["rules"])


def test_category_and_severity_filters_compose() -> None:
    body = _client().get("/rules", params={"category": "security", "severity": "high"}).json()
    assert body["filtered_total"] == 1
    assert body["rules"][0]["id"] == "kube-bench.bbb"


def test_search_matches_id_or_resource_type() -> None:
    by_id = _client().get("/rules", params={"q": "disk"}).json()
    assert {r["id"] for r in by_id["rules"]} == {"disk.unattached"}
    by_resource = _client().get("/rules", params={"q": "etcd"}).json()
    assert {r["id"] for r in by_resource["rules"]} == {"kube-bench.bbb"}


def test_pagination_pages_through_filtered_set() -> None:
    page1 = _client().get("/rules", params={"limit": "2", "offset": "0"}).json()
    assert page1["filtered_total"] == 5
    assert len(page1["rules"]) == 2
    page2 = _client().get("/rules", params={"limit": "2", "offset": "2"}).json()
    assert len(page2["rules"]) == 2
    assert page1["rules"][0]["id"] != page2["rules"][0]["id"]


def test_rule_summary_shape() -> None:
    disk = next(
        r for r in _client().get("/rules").json()["rules"] if r["id"] == "disk.unattached"
    )
    assert disk["origin"] == "active"
    assert disk["severity"] == "low"
    assert disk["category"] == "cost"
    assert disk["source"] == "azure_advisor"
    assert disk["resource_type"] == "disk"
    assert disk["check_logic"] == {"kind": "rego", "reference": "policies/x.rego"}
    assert disk["remediation"]["cost_impact_monthly_usd"] == 12.5
    assert disk["remediates"] == "remediate.example"
    assert disk["provenance"] == {
        "source_url": "https://example.com/x",
        "license": "MIT",
        "redistribution": "embeddable",
    }


def test_invalid_limit_and_offset_rejected() -> None:
    client = _client()
    assert client.get("/rules", params={"limit": "0"}).status_code == 400
    assert client.get("/rules", params={"limit": "9999"}).status_code == 400
    assert client.get("/rules", params={"offset": "-1"}).status_code == 400
    assert client.get("/rules", params={"limit": "abc"}).status_code == 400


def test_route_registered_when_only_collected_wired() -> None:
    body = _client(active=False).get("/rules").json()
    assert body["total"] == 3
    assert body["facets"]["by_origin"] == {"collected": 3}


def test_route_absent_when_no_tier_configured() -> None:
    client = _client(active=False, collected=False)
    assert client.get("/rules").status_code == 404


def test_route_is_get_only() -> None:
    assert _client().post("/rules").status_code == 405


def test_detail_returns_full_projection() -> None:
    body = _client().get("/rules/disk.unattached", params={"origin": "active"}).json()
    assert body["id"] == "disk.unattached"
    assert body["origin"] == "active"
    # Detail-only fields the summary omits.
    assert "parameters" in body
    assert "applies_to" in body
    assert body["provenance"]["content_hash"] == "sha256:0"
    assert body["provenance"]["resolved_ref"] == "0" * 40
    # No content roots wired -> bodies are null, not an error.
    assert body["check_logic_body"] is None
    assert body["remediation_body"] is None


def test_detail_resolves_bodies_from_roots(tmp_path: Path) -> None:
    policies_root = tmp_path / "policies"
    policies_root.mkdir()
    (policies_root / "x.rego").write_text("package x\ndefault allow = false\n", encoding="utf-8")
    remediation_root = tmp_path / "remediation"
    remediation_root.mkdir()
    (remediation_root / "x.tftpl").write_text('resource "null_resource" {}\n', encoding="utf-8")

    client = _client_with_roots(policies_root, remediation_root)
    body = client.get("/rules/disk.unattached", params={"origin": "active"}).json()
    assert body["check_logic_body"] == "package x\ndefault allow = false\n"
    assert body["remediation_body"] == 'resource "null_resource" {}\n'


def test_detail_sandbox_rejects_out_of_root_reference(tmp_path: Path) -> None:
    # A secret sits outside the policies root; a traversal reference MUST
    # NOT be served even though the file exists.
    (tmp_path / "secret.rego").write_text("SECRET", encoding="utf-8")
    policies_root = tmp_path / "policies"
    policies_root.mkdir()

    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    rule = Rule(
        schema_version="1.0.0",
        id="traversal.attempt",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="disk",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/../secret.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.example",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            rule_catalog_rules=(rule,),
            rule_catalog_policies_root=policies_root,
        ),
    )
    body = TestClient(app).get("/rules/traversal.attempt").json()
    assert body["check_logic_body"] is None


def test_detail_unknown_id_returns_404() -> None:
    assert _client().get("/rules/does.not.exist").status_code == 404


def test_detail_falls_back_to_id_without_origin() -> None:
    body = _client().get("/rules/kube-bench.bbb").json()
    assert body["id"] == "kube-bench.bbb"
    assert body["origin"] == "collected"


def test_detail_is_get_only() -> None:
    assert _client().post("/rules/disk.unattached").status_code == 405


def test_detail_explanation_from_rego_metadata(tmp_path: Path) -> None:
    policies_root = tmp_path / "policies"
    policies_root.mkdir()
    (policies_root / "x.rego").write_text(
        "# METADATA\n"
        "# title: Disk must be attached\n"
        "# description: |\n"
        "#   An unattached disk still bills. Remove it.\n"
        "# custom:\n"
        "#   severity: low\n"
        "package x\n"
        "default allow := false\n",
        encoding="utf-8",
    )
    client = _client_with_roots(policies_root, tmp_path / "missing")
    body = client.get("/rules/disk.unattached", params={"origin": "active"}).json()
    exp = body["explanation"]
    assert exp["source"] == "rego_metadata"
    assert exp["title"] == "Disk must be attached"
    assert "An unattached disk still bills." in exp["description"]


def test_detail_explanation_absent_without_metadata() -> None:
    # No policies root wired -> no rego body -> no metadata -> null title.
    exp = _client().get("/rules/disk.unattached", params={"origin": "active"}).json()["explanation"]
    assert exp["title"] is None
    assert exp["source"] is None


def test_findings_not_evaluated_without_provider() -> None:
    body = _client().get("/rules/disk.unattached/findings", params={"origin": "active"}).json()
    assert body["evaluated"] is False
    assert body["findings"] == []


def test_findings_from_provider() -> None:
    async def provider(rule_id: str, origin: str) -> list[dict[str, object]]:
        return [
            {
                "resource_id": "/subscriptions/x/rg/y/disks/orphan-1",
                "resource_name": "orphan-1",
                "severity": "low",
                "problem": "disk is unattached (managed_by is empty)",
            }
        ]

    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            rule_catalog_rules=_active(),
            rule_catalog_findings_provider=provider,
        ),
    )
    body = TestClient(app).get("/rules/disk.unattached/findings").json()
    assert body["evaluated"] is True
    assert body["finding_count"] == 1
    assert body["findings"][0]["resource_name"] == "orphan-1"
    assert "unattached" in body["findings"][0]["problem"]


def test_findings_unknown_rule_404() -> None:
    assert _client().get("/rules/does.not.exist/findings").status_code == 404


def test_findings_is_get_only() -> None:
    assert _client().post("/rules/disk.unattached/findings").status_code == 405

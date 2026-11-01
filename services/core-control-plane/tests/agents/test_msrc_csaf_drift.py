"""Pantheon agent integration tests for MSRC CSAF vulnerability drift and review."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.saga import Saga
from fdai.core.security.csaf import (
    CsafAssessmentRequest,
    CsafScopedResource,
    MsrcCsafAssessmentRuntime,
    MsrcCsafReviewError,
    build_csaf_review_package,
    msrc_csaf_drift_payload,
)
from fdai.rule_catalog.schema.msrc_csaf import load_msrc_csaf_crosswalk_catalog
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
CROSSWALK_PATH = REPO_ROOT / "rule-catalog" / "collected" / "msrc-csaf" / "crosswalk.json"
_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _sample_csaf_package(
    *, workload_id: str = "payments-prod", fixed_all: bool = False
) -> dict[str, object]:
    catalog = load_msrc_csaf_crosswalk_catalog(CROSSWALK_PATH)
    target_cves = {"CVE-2026-20001", "CVE-2026-20002"}
    target_prods = {"AZURE-AKS-1.28", "AZURE-STORAGE-TLS"}
    active_vuln_mappings = tuple(
        m for m in catalog.vulnerability_mappings if m.cve_id in target_cves
    )
    from fdai.rule_catalog.schema.wara_assessment import canonical_digest

    trimmed_advisories = []
    for adv in catalog.advisories:
        vulns = tuple(v for v in adv.vulnerabilities if v.cve_id in target_cves)
        prods = tuple(p for p in adv.products if p.product_id in target_prods)
        if vulns and prods:
            trimmed_advisories.append(
                adv.model_copy(update={"vulnerabilities": vulns, "products": prods})
            )
    adv_json = [a.model_dump(mode="json") for a in trimmed_advisories]
    prods_filtered = tuple(p for p in catalog.product_mappings if p.product_id in target_prods)
    raw_cat = {
        "schema_version": "1.0.0",
        "source_id": "msrc_csaf",
        "source_revision": catalog.source_revision,
        "advisories_digest": canonical_digest(adv_json),
        "product_mappings": [p.model_dump(mode="json") for p in prods_filtered],
        "vulnerability_mappings": [m.model_dump(mode="json") for m in active_vuln_mappings],
        "advisories": adv_json,
    }
    raw_cat["crosswalk_digest"] = canonical_digest(raw_cat)
    clean_catalog = catalog.model_validate(raw_cat)
    runtime = MsrcCsafAssessmentRuntime(clean_catalog)
    resources = (
        CsafScopedResource(
            resource_id="aks-01",
            provider_resource_type="Microsoft.ContainerService/managedClusters",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"kubernetes_version": "1.28.9" if fixed_all else "1.28.4"},
        ),
        CsafScopedResource(
            resource_id="st-01",
            provider_resource_type="Microsoft.Storage/storageAccounts",
            observed_at=_NOW - timedelta(minutes=5),
            properties={"minimum_tls_version": "1.2"},
        ),
    )
    result = runtime.assess(
        CsafAssessmentRequest(
            assessment_id="csaf-agent-test",
            source_revision=clean_catalog.source_revision,
            crosswalk_digest=clean_catalog.crosswalk_digest,
            advisories_digest=clean_catalog.advisories_digest,
            ontology_release="ontology-v1",
            inventory_generation="inv-gen-001",
            workload_id=workload_id,
            resources=resources,
            evaluated_at=_NOW,
            recorded_at=_NOW + timedelta(seconds=1),
        )
    )
    return build_csaf_review_package(result)


async def test_heimdall_publishes_msrc_csaf_drift_to_forseti_and_saga() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus, msrc_csaf_drift_projector=msrc_csaf_drift_payload)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    bus.subscribe("object.drift", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)

    pkg = _sample_csaf_package()
    assert await heimdall.publish_msrc_csaf_drift(pkg) is True
    drift_msg = bus.messages_on("object.drift")[-1]
    assert drift_msg.principal == "Heimdall"
    assert drift_msg.payload["event_type"] == "msrc_csaf.vulnerability_drift"
    assert drift_msg.payload["decision"] == "urgent"
    assert drift_msg.payload["authority_ceiling"] == "shadow"
    assert drift_msg.payload["grants_authority"] is False
    assert heimdall.behavior_snapshot()["msrc_csaf_drift:urgent"] == 1

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    assert verdict["correlation_id"] == drift_msg.payload["correlation_id"]
    entries = saga.audit_chain.entries_for_correlation(str(drift_msg.payload["correlation_id"]))
    assert len(entries) == 1 and entries[0].topic == "object.verdict"


async def test_heimdall_holds_msrc_csaf_drift_without_projector_and_rejects_authority_claim() -> (
    None
):
    pkg = _sample_csaf_package()
    assert await Heimdall().publish_msrc_csaf_drift(pkg) is False
    invalid = dict(pkg, grants_authority=True)
    with pytest.raises(MsrcCsafReviewError, match="authority"):
        await Heimdall(msrc_csaf_drift_projector=msrc_csaf_drift_payload).publish_msrc_csaf_drift(
            invalid
        )


async def test_heimdall_drift_tool_orders_msrc_csaf_reviews_by_utc_timestamp() -> None:
    """Regression for C-07: UTC ordering across timezone offsets and naive timestamp rejection."""
    store = InMemoryStateStore()
    older_kst = _sample_csaf_package(workload_id="payments-prod", fixed_all=False)
    newer_utc = _sample_csaf_package(workload_id="payments-prod", fixed_all=True)

    # 2026-10-08T02:00:00+09:00 is 2026-10-07T17:00:00Z (older than 2026-10-08T01:00:00+00:00!)
    await store.write_state(
        "runtime:msrc-csaf-review:payments-prod:rev1",
        {"package": older_kst, "recorded_at": "2026-10-08T02:00:00+09:00"},
    )
    await store.write_state(
        "runtime:msrc-csaf-review:payments-prod:rev2",
        {"package": newer_utc, "recorded_at": "2026-10-08T01:00:00+00:00"},
    )
    # Naive timestamp must be withheld
    await store.write_state(
        "runtime:msrc-csaf-review:naive:rev3",
        {"package": older_kst, "recorded_at": "2026-10-09T01:00:00"},
    )

    heimdall = Heimdall(state_store=store)
    envelope = await heimdall.on_conversation_turn(
        "Are any workloads exposed to MSRC CSAF vulnerabilities?",
        {"conversation_tool": "read_drift_status", "trace_ref": "trace-csaf"},
    )
    assert envelope["answer"] is not None
    assert "Latest MSRC CSAF reviews cover 1 workloads: 0 urgent" in envelope["answer"]

    introspection = await heimdall.introspect(
        "Are any workloads exposed to MSRC CSAF vulnerabilities?",
        {"conversation_tool": "read_drift_status", "trace_ref": "trace-csaf"},
    )
    facts = introspection.facts
    assert facts["msrc_csaf_reviews_read"] == 2
    assert facts["msrc_csaf_reviews_withheld"] == 1
    assert facts["msrc_csaf_urgent_workload_count"] == 0
    assert facts["msrc_csaf_incomplete_workload_count"] == 0
    assert facts["msrc_csaf_zero_risk_certified_count"] == 1
    (latest,) = facts["msrc_csaf_latest_decisions"]
    assert latest["decision"] == "clear"
    assert latest["critical_affected_count"] == 0
    assert latest["top_cve_ids"] == []
    assert latest["recorded_at"] == "2026-10-08T01:00:00+00:00"

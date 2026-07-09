"""Tests for the demo findings provider (real-eval-over-synthetic)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fdai.delivery.read_api.demo_findings import (
    SYNTHETIC_INVENTORY,
    build_demo_findings_provider,
)
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

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICIES_ROOT = REPO_ROOT / "policies"


def _disk_rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="disk.unattached",
        version="1.0.0",
        source=RuleSource.AZURE_ADVISOR,
        severity=Severity.LOW,
        category=Category.COST,
        resource_type="disk",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/disk/unattached.rego"),
        remediation=Remediation(template_ref="remediation/disk/remove_orphan_disk.tftpl"),
        remediates="remediate.remove-orphan-resource",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.REFERENCE_ONLY,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


class _StubResult:
    def __init__(self, denied: bool, reason: str | None) -> None:
        self.denied = denied
        self.context = {"deny_reason": reason} if reason else {}


class _StubEvaluator:
    """Denies any ``disk`` whose ``managed_by`` is empty (mirrors the real Rego)."""

    def evaluate(self, rule: Rule, props: dict) -> _StubResult | None:
        if rule.resource_type != "disk":
            return None
        if props.get("managed_by") == "":
            return _StubResult(True, "disk_unattached")
        return _StubResult(False, None)


async def _call(provider, rule_id: str) -> list:
    return list(await provider(rule_id, "active"))


@pytest.mark.asyncio
async def test_provider_maps_deny_to_finding_with_stub() -> None:
    provider = build_demo_findings_provider(
        rules_by_id={"disk.unattached": _disk_rule()},
        policies_root=POLICIES_ROOT,
        evaluator=_StubEvaluator(),
    )
    findings = await _call(provider, "disk.unattached")
    assert len(findings) == 1
    f = findings[0]
    assert f["resource_name"] == "demo-disk-orphan"
    assert f["severity"] == "low"
    assert f["problem"] == "Disk unattached"  # humanized deny_reason
    assert f["context"] == {"deny_reason": "disk_unattached"}


@pytest.mark.asyncio
async def test_provider_unknown_rule_returns_empty() -> None:
    provider = build_demo_findings_provider(
        rules_by_id={},
        policies_root=POLICIES_ROOT,
        evaluator=_StubEvaluator(),
    )
    assert await _call(provider, "nope") == []


def test_inventory_is_customer_agnostic() -> None:
    # Only the all-zero placeholder subscription id may appear.
    for res in SYNTHETIC_INVENTORY:
        assert "00000000-0000-0000-0000-000000000000" in res.resource_id
        assert res.resource_name.startswith("demo") or res.resource_name.startswith("demost")


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
@pytest.mark.asyncio
async def test_provider_real_opa_eval_disk_unattached() -> None:
    provider = build_demo_findings_provider(
        rules_by_id={"disk.unattached": _disk_rule()},
        policies_root=POLICIES_ROOT,
    )
    findings = await _call(provider, "disk.unattached")
    assert len(findings) == 1
    assert findings[0]["problem"] == "Disk unattached"

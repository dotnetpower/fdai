"""Tests for the Azure security-finding adapters (Defender + WAF, P3-9).

- DefenderFindingProvider: httpx-mocked; Unhealthy assessments map to
  findings with severity from metadata; Healthy/NotApplicable are dropped;
  pagination followed; non-2xx / malformed fail closed.
- map_appgw_waf_findings: pure mapping of WAF firewall-log rows.
- End-to-end: seeded live signals drive the assessment verdict; shadow
  never blocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml

from fdai.core.security.assessment import (
    SecurityVerdict,
    build_security_assessment,
)
from fdai.delivery.azure.security_findings import (
    DefenderFindingConfig,
    DefenderFindingProvider,
    map_appgw_waf_findings,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.security_findings import SecurityFindingProviderError
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.workload_identity import WorkloadIdentity

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_SUB = "00000000-0000-0000-0000-000000000001"
_SA_ID = (
    f"/subscriptions/{_SUB}/resourceGroups/rg/providers/"
    "Microsoft.Storage/storageAccounts/sa"
)


def _vocab() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _identity() -> WorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="tkn",  # noqa: S106 - deterministic test literal
    )


def _config(**overrides: object) -> DefenderFindingConfig:
    base: dict[str, object] = dict(subscription_scope=_SUB)
    base.update(overrides)
    return DefenderFindingConfig(**base)  # type: ignore[arg-type]


def _provider(handler, cfg: DefenderFindingConfig | None = None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DefenderFindingProvider(
        config=cfg or _config(),
        identity=_identity(),
        resource_types=_vocab(),
        http_client=client,
    )
    return provider, client


def _assessment(name: str, code: str, severity: str, arm_id: str) -> dict:
    return {
        "id": f"/subscriptions/{_SUB}/providers/Microsoft.Security/assessments/{name}",
        "name": name,
        "properties": {
            "displayName": f"{name} display",
            "status": {"code": code, "cause": "insecure config"},
            "resourceDetails": {"Source": "Azure", "Id": arm_id},
            "metadata": {"severity": severity},
        },
    }


@pytest.mark.asyncio
async def test_unhealthy_assessments_map_to_findings() -> None:
    arm_id = _SA_ID
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    _assessment("a1", "Unhealthy", "High", arm_id),
                    _assessment("a2", "Healthy", "Low", arm_id),
                    _assessment("a3", "NotApplicable", "Medium", arm_id),
                ]
            },
        )

    provider, client = _provider(handler)
    try:
        findings = await provider.collect(scope=_SUB)
    finally:
        await client.aclose()

    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "defender:a1"
    assert f.severity == "high"
    assert f.resource.ref == arm_id
    assert captured[0].headers["Authorization"] == "Bearer tkn"


@pytest.mark.asyncio
async def test_pagination_is_followed() -> None:
    arm_id = _SA_ID
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "value": [_assessment("a1", "Unhealthy", "High", arm_id)],
                    "nextLink": "https://management.azure.com/next?tok=2",
                },
            )
        return httpx.Response(
            200, json={"value": [_assessment("a2", "Unhealthy", "Medium", arm_id)]}
        )

    provider, client = _provider(handler)
    try:
        findings = await provider.collect(scope=_SUB)
    finally:
        await client.aclose()

    assert {f.rule_id for f in findings} == {"defender:a1", "defender:a2"}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    provider, client = _provider(handler)
    try:
        with pytest.raises(SecurityFindingProviderError, match="HTTP 403"):
            await provider.collect(scope=_SUB)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_value_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    provider, client = _provider(handler)
    try:
        with pytest.raises(SecurityFindingProviderError, match="missing 'value'"):
            await provider.collect(scope=_SUB)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_pagination_cap_fails_closed() -> None:
    arm_id = _SA_ID

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [_assessment("a1", "Unhealthy", "High", arm_id)],
                "nextLink": "https://management.azure.com/next",
            },
        )

    provider, client = _provider(handler, cfg=_config(max_pages=2))
    try:
        with pytest.raises(SecurityFindingProviderError, match="pagination cap"):
            await provider.collect(scope=_SUB)
    finally:
        await client.aclose()


def test_waf_mapping_blocks_and_skips() -> None:
    arm_id = (
        f"/subscriptions/{_SUB}/resourceGroups/rg/providers/"
        "Microsoft.Network/applicationGateways/agw"
    )
    rows = [
        {"action": "Blocked", "ruleId": "942100", "message": "SQLi", "Resource": arm_id},
        {"action": "Detected", "ruleId": "913100", "message": "scanner", "Resource": arm_id},
        {"action": "Allowed", "ruleId": "0", "message": "ok", "Resource": arm_id},
    ]
    findings = map_appgw_waf_findings(rows, resource_types=_vocab())

    assert [f.severity for f in findings] == ["high", "medium"]
    assert findings[0].rule_id == "appgw-waf:942100"
    assert findings[0].resource.ref == arm_id


def test_waf_mapping_skips_rows_without_resource() -> None:
    rows = [{"action": "Blocked", "ruleId": "1", "message": "x"}]
    assert map_appgw_waf_findings(rows) == ()


@pytest.mark.asyncio
async def test_seeded_signals_drive_verdict_and_shadow_never_blocks() -> None:
    arm_id = _SA_ID

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [_assessment("crit", "Unhealthy", "High", arm_id)]}
        )

    provider, client = _provider(handler)
    try:
        findings = list(await provider.collect(scope=_SUB))
    finally:
        await client.aclose()

    shadow = build_security_assessment(
        findings, scope=_SUB, assessed_at=datetime(2026, 7, 12, tzinfo=UTC), mode=Mode.SHADOW
    )
    assert shadow.verdict is SecurityVerdict.ATTENTION
    assert shadow.blocks_action is False  # shadow never blocks

    enforce = build_security_assessment(
        findings, scope=_SUB, assessed_at=datetime(2026, 7, 12, tzinfo=UTC), mode=Mode.ENFORCE
    )
    assert enforce.blocks_action is True


def test_config_rejects_plaintext_endpoint() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(arg_endpoint="http://management.azure.com")


def test_config_rejects_empty_subscription() -> None:
    with pytest.raises(ValueError, match="subscription_scope"):
        _config(subscription_scope="")

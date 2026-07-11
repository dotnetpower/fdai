"""Azure security-finding adapters - Microsoft Defender for Cloud + Application
Gateway WAF signals mapped to CSP-neutral
:class:`~fdai.shared.providers.projection.Finding` values (P3-9).

Design boundaries (mirror :mod:`fdai.delivery.azure.arg_query`)
--------------------------------------------------------------

- ``core/`` never imports this module; it is bound at the composition root.
- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`; HTTP
  transport is an injected :class:`httpx.AsyncClient` (tests use
  :class:`httpx.MockTransport`).
- The ARM resource type on a finding is folded to a CSP-neutral
  ``resource_type`` via the vocabulary reverse map, falling back to a
  derived provider/type string so the finding still carries a non-empty
  type (``build_security_assessment`` treats it as an opaque string).

:class:`DefenderFindingProvider` queries the Microsoft Defender for Cloud
**assessments** REST API and maps every ``Unhealthy`` assessment to a
finding; :func:`map_appgw_waf_findings` is a pure mapper turning Application
Gateway WAF firewall-log rows (already fetched via a Log Analytics query)
into findings, so a fork can feed it from its ``LogQueryProvider`` without
this module owning a second transport.

Fail-closed: a non-2xx response or malformed payload raises
:class:`SecurityFindingProviderError`; the scheduled assessment then
abstains (and shadow never blocks regardless).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import httpx

from fdai.delivery.azure.arg_query import _build_arm_to_neutral_map
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.projection import Finding, ResourceRef, Severity
from fdai.shared.providers.security_findings import SecurityFindingProviderError
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ASSESSMENTS_API_VERSION: Final[str] = "2021-06-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PAGES: Final[int] = 32

# Defender assessment metadata severity -> CSP-neutral severity.
_DEFENDER_SEVERITY: Final[dict[str, Severity]] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}
# WAF firewall-log action -> severity.
_WAF_ACTION_SEVERITY: Final[dict[str, Severity]] = {
    "blocked": "high",
    "block": "high",
    "matched": "medium",
    "detected": "medium",
}


@dataclass(frozen=True, slots=True)
class DefenderFindingConfig:
    """Configuration for the Defender-for-Cloud finding provider."""

    subscription_scope: str
    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    api_version: str = _DEFAULT_ASSESSMENTS_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_pages: int = _DEFAULT_MAX_PAGES

    def __post_init__(self) -> None:
        if not self.subscription_scope:
            raise ValueError("DefenderFindingConfig.subscription_scope MUST be non-empty")
        if not self.arg_endpoint.lower().startswith("https://"):
            raise ValueError(
                "DefenderFindingConfig.arg_endpoint MUST use https:// "
                f"(got {self.arg_endpoint!r})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if self.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")


class DefenderFindingProvider:
    """Map Microsoft Defender for Cloud assessments to security findings."""

    def __init__(
        self,
        *,
        config: DefenderFindingConfig,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final[DefenderFindingConfig] = config
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._arm_to_neutral: Final[Mapping[str, str]] = _build_arm_to_neutral_map(resource_types)

    async def collect(
        self, *, scope: str, since: datetime | None = None, until: datetime | None = None
    ) -> Sequence[Finding]:
        del scope, since, until  # Defender assessments are current-state, not windowed
        url = (
            f"{self._config.arg_endpoint.rstrip('/')}"
            f"/subscriptions/{self._config.subscription_scope}"
            "/providers/Microsoft.Security/assessments"
            f"?api-version={self._config.api_version}"
        )
        token = await self._identity.get_token(self._config.audience)
        headers = {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}

        findings: list[Finding] = []
        for _page in range(self._config.max_pages):
            payload = await self._get(url, headers=headers)
            value = payload.get("value")
            if not isinstance(value, list):
                raise SecurityFindingProviderError("Defender payload missing 'value' array")
            for row in value:
                finding = self._map_assessment(row)
                if finding is not None:
                    findings.append(finding)
            link = payload.get("nextLink")
            if not isinstance(link, str) or not link:
                return tuple(findings)
            url = link
        raise SecurityFindingProviderError(
            f"Defender pagination cap ({self._config.max_pages}) exceeded"
        )

    async def _get(self, url: str, *, headers: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            response = await self._http.get(
                url, headers=headers, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise SecurityFindingProviderError(
                f"Defender request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise SecurityFindingProviderError(
                f"Defender returned HTTP {response.status_code}: {snippet!r}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SecurityFindingProviderError("Defender returned non-JSON") from exc
        if not isinstance(payload, Mapping):
            raise SecurityFindingProviderError("Defender payload is not an object")
        return payload

    def _map_assessment(self, row: Any) -> Finding | None:
        if not isinstance(row, Mapping):
            return None
        props = row.get("properties")
        if not isinstance(props, Mapping):
            return None
        status = props.get("status")
        code = status.get("code") if isinstance(status, Mapping) else None
        # Only actionable (Unhealthy) assessments become findings.
        if str(code) != "Unhealthy":
            return None

        severity = _defender_severity(props.get("metadata"))
        arm_id = _resource_id(props.get("resourceDetails")) or str(row.get("id", ""))
        if not arm_id:
            return None
        resource_type = self._neutral_type(arm_id)
        name = str(row.get("name") or props.get("displayName") or "assessment")
        reason = _defender_reason(props, status)
        return Finding(
            rule_id=f"defender:{name}",
            resource=ResourceRef(resource_type=resource_type, ref=arm_id),
            severity=severity,
            reason=reason[:512],
            evidence_refs=(str(row.get("id", "")),) if row.get("id") else (),
        )

    def _neutral_type(self, arm_id: str) -> str:
        arm_type = _arm_type_from_id(arm_id)
        if arm_type is not None:
            neutral = self._arm_to_neutral.get(arm_type.lower())
            if neutral is not None:
                return neutral
            return arm_type.lower()
        return "azure-resource"


def map_appgw_waf_findings(
    rows: Sequence[Mapping[str, Any]],
    *,
    resource_types: ResourceTypeRegistry | None = None,
) -> tuple[Finding, ...]:
    """Map Application Gateway WAF firewall-log rows to security findings (pure).

    ``rows`` are Log-Analytics ``ApplicationGatewayFirewallLog`` records
    (already fetched by a fork's ``LogQueryProvider``). A row whose
    ``action`` is a blocking/matching verb becomes a finding; an
    informational row is skipped. No I/O, deterministic - the WAF
    counterpart of the Defender REST provider, kept pure so it is testable
    without a Log Analytics transport.
    """
    arm_to_neutral = _build_arm_to_neutral_map(resource_types) if resource_types else {}
    findings: list[Finding] = []
    for row in rows:
        action = str(row.get("action") or row.get("Action") or "").lower()
        severity = _WAF_ACTION_SEVERITY.get(action)
        if severity is None:
            continue
        arm_id = str(row.get("Resource") or row.get("resourceId") or row.get("_ResourceId") or "")
        if not arm_id:
            continue
        arm_type = _arm_type_from_id(arm_id)
        resource_type = (
            arm_to_neutral.get(arm_type.lower(), arm_type.lower())
            if arm_type
            else "application-gateway"
        )
        rule_ref = str(row.get("ruleId") or row.get("RuleId") or "unknown")
        message = str(row.get("message") or row.get("Message") or "WAF rule match")
        findings.append(
            Finding(
                rule_id=f"appgw-waf:{rule_ref}",
                resource=ResourceRef(resource_type=resource_type, ref=arm_id),
                severity=severity,
                reason=f"{action}: {message}"[:512],
            )
        )
    return tuple(findings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defender_severity(metadata: Any) -> Severity:
    if isinstance(metadata, Mapping):
        raw = str(metadata.get("severity", "")).lower()
        return _DEFENDER_SEVERITY.get(raw, "medium")
    return "medium"


def _resource_id(resource_details: Any) -> str | None:
    if isinstance(resource_details, Mapping):
        rid = resource_details.get("Id") or resource_details.get("id")
        return str(rid) if rid else None
    return None


def _defender_reason(props: Mapping[str, Any], status: Any) -> str:
    display = str(props.get("displayName") or "Defender assessment")
    if isinstance(status, Mapping):
        cause = status.get("cause") or status.get("description")
        if cause:
            return f"{display}: {cause}"
    return display


def _arm_type_from_id(arm_id: str) -> str | None:
    marker = "/providers/"
    idx = arm_id.lower().rfind(marker.lower())
    if idx == -1:
        return None
    tail = arm_id[idx + len(marker) :].split("/")
    if len(tail) < 2:
        return None
    return f"{tail[0]}/{tail[1]}"


__all__ = [
    "DefenderFindingConfig",
    "DefenderFindingProvider",
    "map_appgw_waf_findings",
]

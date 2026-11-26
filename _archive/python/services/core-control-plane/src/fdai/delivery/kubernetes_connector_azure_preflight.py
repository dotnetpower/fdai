"""Azure management evidence for observer deployment constraints.

The reader is read-only and bounded. Each fact is a necessary-condition observation: ARM can show
that Run Command is disabled or that a deny-capable policy needs review, but it never grants a
method. A conclusion that ARM cannot prove stays `unknown` instead of becoming permission.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentFact

from fdai.delivery.azure.arg_projection import to_neutral_id

CLUSTER_API_VERSION = "2026-05-01"
POLICY_API_VERSION = "2022-06-01"
DEFINITION_API_VERSION = "2021-06-01"
FACT_MINUTES = 5
_CLUSTER_ID = re.compile(
    r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[A-Za-z0-9._()-]{1,90}"
    r"/providers/Microsoft\.ContainerService/managedClusters/[A-Za-z0-9][A-Za-z0-9_-]{0,62}"
)
_DEFINITION_ID = re.compile(
    r"(?:/subscriptions/[0-9a-f-]{36}|"
    r"/providers/Microsoft\.Management/managementGroups/[A-Za-z0-9._()-]{1,90})?"
    r"/providers/Microsoft\.Authorization/"
    r"(?:policyDefinitions|policySetDefinitions)/[A-Za-z0-9._-]{1,128}",
    re.IGNORECASE,
)
_PARAMETER = re.compile(r"^\[parameters\('([A-Za-z0-9_]+)'\)\]$")
_IMPACTFUL = frozenset({"deny", "modify", "append", "denyaction"})
_PUBLIC_OUTBOUND = frozenset({"loadbalancer", "managednatgateway", "usernatgateway"})
_MAX_REQUESTS = 512
_CONCURRENCY = 8
_DEADLINE_SECONDS = 180

State = Literal["allowed", "denied", "unknown"]
Resolver = Callable[[str], Awaitable[Sequence[str]]]


class ManagementReader(Protocol):
    """GET one Azure Resource Manager path and return its JSON object."""

    async def get(self, path: str, api_version: str) -> Mapping[str, Any]: ...


class _Budget:
    """Bound requests, share one answer per path, and limit concurrency."""

    def __init__(self, reader: ManagementReader) -> None:
        self._reader, self._left = reader, _MAX_REQUESTS
        self._gate = asyncio.Semaphore(_CONCURRENCY)
        self._answers: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self.paths: list[str] = []

    async def get(self, path: str, api_version: str) -> Mapping[str, Any]:
        key = f"{path.casefold()}?{api_version}"
        if key in self._answers:
            return await asyncio.shield(self._answers[key])
        if self._left <= 0:
            raise ValueError("Azure management preflight request budget exhausted")
        self._left -= 1
        self.paths.append(path)
        future = asyncio.get_running_loop().create_future()
        self._answers[key] = future
        try:
            async with self._gate:
                value = await self._reader.get(path, api_version)
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()
            raise
        future.set_result(value)
        return value


class AzureManagementPreflight:
    """Observe ARM facts for exactly one AKS cluster."""

    def __init__(
        self,
        *,
        cluster_id: str,
        reader: ManagementReader,
        gateway_origin: str,
        run_command_profile_allows: bool,
        now: Callable[[], datetime],
        resolver: Resolver | None = None,
    ) -> None:
        if _CLUSTER_ID.fullmatch(cluster_id) is None:
            raise ValueError("Azure management preflight requires one AKS cluster resource id")
        if urlsplit(gateway_origin).scheme != "https" or not urlsplit(gateway_origin).hostname:
            raise ValueError("Azure management preflight requires an HTTPS gateway origin")
        self._id, self._reader = cluster_id, reader
        self._origin, self._allows = gateway_origin, run_command_profile_allows
        self._now, self._resolver = now, resolver or _system_resolver
        self.target_ref = to_neutral_id(cluster_id)

    async def collect(self) -> tuple[ObserverDeploymentFact, ...]:
        """Return `azure_policy`, `run_command_authorized`, and both egress classifications."""
        observed = connector_time(self._now())
        expires = observed + timedelta(minutes=FACT_MINUTES)
        budget = _Budget(self._reader)
        try:
            async with asyncio.timeout(60):
                cluster = dict(await budget.get(self._id, CLUSTER_API_VERSION))
        except (TimeoutError, ValueError, OSError, KeyError):
            cluster = {}
        properties = cluster.get("properties")
        facts: dict[str, tuple[State, object]] = {}
        if cluster.get("id", "").casefold() != self._id.casefold() or not isinstance(
            properties, dict
        ):
            unknown: tuple[State, object] = ("unknown", {"reason": "cluster_unreadable"})
            facts = {
                name: unknown
                for name in (
                    "azure_policy",
                    "run_command_authorized",
                    "private_egress",
                    "public_egress",
                )
            }
        else:
            facts["run_command_authorized"] = self._run_command(properties)
            facts["azure_policy"] = await self._policy(budget)
            addresses = await self._addresses()
            outbound = str(
                (properties.get("networkProfile") or {}).get("outboundType", "")
            ).casefold()
            facts["private_egress"] = _private_route(addresses)
            facts["public_egress"] = _public_route(addresses, outbound)
        if not observed <= connector_time(self._now()) < expires:
            raise ValueError("Azure management preflight observation window expired")
        return tuple(
            ObserverDeploymentFact(
                target_ref=self.target_ref,
                name=name,  # type: ignore[arg-type]
                state=state,
                source="network_probe" if name.endswith("_egress") else "azure_management",
                evidence_digest=canonical_digest(
                    {"target_ref": self.target_ref, "name": name, "evidence": evidence}
                ),
                observed_at=observed,
                expires_at=expires,
            )
            for name, (state, evidence) in sorted(facts.items())
        )

    def _run_command(self, properties: Mapping[str, Any]) -> tuple[State, object]:
        profile = properties.get("apiServerAccessProfile") or {}
        power = str((properties.get("powerState") or {}).get("code", ""))
        disabled = profile.get("disableRunCommand") is True
        evidence = {
            "disable_run_command": disabled,
            "power_state": power,
            "profile_allows": self._allows,
        }
        if disabled or not self._allows:
            return "denied", evidence
        # An enabled feature and a permitting profile are necessary, not sufficient: the caller's
        # Azure RBAC is proven by the signed install flow itself.
        return ("allowed" if power == "Running" else "unknown"), evidence

    async def _addresses(self) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        host = urlsplit(self._origin).hostname or ""
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            async with asyncio.timeout(10):
                return [ipaddress.ip_address(item) for item in await self._resolver(host)]
        except (TimeoutError, ValueError, OSError):
            return []

    async def _policy(self, budget: _Budget) -> tuple[State, object]:
        try:
            async with asyncio.timeout(_DEADLINE_SECONDS):
                assignments = await _assignments(budget, self._id)
                findings: list[dict[str, object]] = []
                for item in assignments:
                    findings.extend(await _impactful(budget, item))
        except (TimeoutError, ValueError, OSError, KeyError):
            return "unknown", {"reason": "policy_enumeration_incomplete"}
        evidence = {"assignments": len(assignments), "needs_review": findings}
        return ("unknown" if findings else "allowed"), evidence


def _private_route(addresses: Sequence[Any]) -> tuple[State, object]:
    evidence = {"addresses": sorted(str(item) for item in addresses)}
    if not addresses:
        return "unknown", evidence | {"reason": "gateway_unresolved"}
    if all(item.is_private and not item.is_global for item in addresses):
        return "allowed", evidence
    return "denied", evidence


def _public_route(addresses: Sequence[Any], outbound: str) -> tuple[State, object]:
    evidence = {"addresses": sorted(str(item) for item in addresses), "outbound_type": outbound}
    if not addresses:
        return "unknown", evidence | {"reason": "gateway_unresolved"}
    if any(item.is_private or not item.is_global for item in addresses):
        return "denied", evidence
    if outbound in _PUBLIC_OUTBOUND:
        return "allowed", evidence
    return "unknown", evidence | {"reason": "egress_path_needs_review"}


async def _system_resolver(host: str) -> Sequence[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=0)
    return sorted({str(info[4][0]) for info in infos})


async def _assignments(budget: _Budget, cluster_id: str) -> list[Mapping[str, Any]]:
    path = f"{cluster_id}/providers/Microsoft.Authorization/policyAssignments"
    collected: list[Mapping[str, Any]] = []
    for _ in range(8):
        page = await budget.get(path, POLICY_API_VERSION)
        value = page.get("value")
        if not isinstance(value, list):
            raise ValueError("policy assignments response is invalid")
        collected.extend(item for item in value if isinstance(item, dict))
        link = page.get("nextLink")
        if not link:
            return collected
        raise ValueError("policy assignments need more than one page")
    raise ValueError("policy assignments exceed their bound")


async def _impactful(budget: _Budget, assignment: Mapping[str, Any]) -> list[dict[str, object]]:
    """Return policy definitions that may deny or modify a cluster and need a reviewer."""
    properties = assignment.get("properties") or {}
    if properties.get("enforcementMode") == "DoNotEnforce":
        return []
    definition_id = str(properties.get("policyDefinitionId", ""))
    if _DEFINITION_ID.fullmatch(definition_id) is None:
        raise ValueError("policy definition id is invalid")
    values = {key: item.get("value") for key, item in (properties.get("parameters") or {}).items()}
    document = (await budget.get(definition_id, DEFINITION_API_VERSION)).get("properties") or {}
    members: list[tuple[str, Mapping[str, Any], dict[str, Any]]] = []
    if "/policysetdefinitions/" in definition_id.casefold():
        defaults = _defaults(document)
        references = [item for item in document.get("policyDefinitions") or []]
        for reference in references:
            if _DEFINITION_ID.fullmatch(str(reference.get("policyDefinitionId", ""))) is None:
                raise ValueError("policy set member id is invalid")
        fetched = await asyncio.gather(
            *(
                budget.get(str(reference["policyDefinitionId"]), DEFINITION_API_VERSION)
                for reference in references
            )
        )
        for reference, body in zip(references, fetched, strict=True):
            frame = {
                key: _resolve(item.get("value"), [values, defaults])
                for key, item in (reference.get("parameters") or {}).items()
            }
            members.append(
                (str(reference["policyDefinitionId"]), body.get("properties") or {}, frame)
            )
    else:
        members.append((definition_id, document, {}))
    found: list[dict[str, object]] = []
    for member_id, member, frame in members:
        rule = member.get("policyRule") or {}
        if member.get("mode") == "Microsoft.Kubernetes.Data":
            continue
        effect = _resolve(
            (rule.get("then") or {}).get("effect"), [frame, values, _defaults(member)]
        )
        text = str(rule.get("if", "")).casefold()
        if (effect is None or str(effect).casefold() in _IMPACTFUL) and (
            "microsoft.containerservice/managedclusters" in text
        ):
            found.append(
                {
                    "definition": member_id.rsplit("/", 1)[-1],
                    "assignment": str(assignment.get("name", "")),
                    "effect": None if effect is None else str(effect).casefold(),
                }
            )
    return found


def _defaults(definition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.get("defaultValue")
        for key, item in (definition.get("parameters") or {}).items()
        if isinstance(item, dict)
    }


def _resolve(value: Any, frames: Sequence[Mapping[str, Any]]) -> Any:
    """Resolve a policy parameter expression through the supplied frames, or return None."""
    for _ in range(4):
        match = _PARAMETER.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            return value
        name = match.group(1)
        value = next((frame[name] for frame in frames if frame.get(name) is not None), None)
    return None

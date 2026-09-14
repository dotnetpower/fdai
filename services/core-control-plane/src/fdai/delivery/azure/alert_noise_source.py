"""Read-only Azure Monitor evidence for one authorized RG with conservative dependency coverage.

Subscription reads establish known reverse edges, not a complete global source inventory.
Other subscriptions, Prometheus/SmartDetector rules and non-Monitor consumers remain unknown.
No native configuration, RBAC email receiver or deployment policy proves observed ownership.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    AlertGroup,
    AlertRule,
    Audience,
    EvidenceStamp,
    ProcessingRule,
)

from fdai.delivery.azure.alert_noise_history import attach_alert_history, pin_evidence
from fdai.delivery.azure.alert_noise_http import (
    AZURE_ALERT_APIS,
    AlertReadBudget,
    AlertReadUnavailable,
    AzureAlertReader,
)
from fdai.delivery.azure.alert_noise_normalize import (
    NOTIFICATION_FIELDS,
    alert_rule,
    canonical_json,
    list_value,
    native_resource,
    native_scope,
    notification_kind,
    object_value,
    processing_rule,
    rule_groups,
    text,
    within_scope,
)
from fdai.shared.providers.alert_noise import AlertAudienceResolver

_KINDS = {
    "Microsoft.Insights/metricAlerts": "metric",
    "Microsoft.Insights/scheduledQueryRules": "log",
    "Microsoft.Insights/activityLogAlerts": "activity",
}
_GROUPS = "Microsoft.Insights/actionGroups"
_PROCESSING = "Microsoft.AlertsManagement/actionRules"
_HISTORY = "Microsoft.AlertsManagement/alerts"


@dataclass(frozen=True, slots=True)
class AlertScopeBinding:
    """Deployment-owned native scope and purpose-separated pseudonym key."""

    subscription_id: str
    resource_group: str
    tenant_ref: str
    scope_ref: str
    pseudonym_key: bytes = field(repr=False)
    policy_bindings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        subscription, group = text(self.subscription_id), text(self.resource_group)
        if (
            re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", group) is None
            or "/" in subscription
            or group.endswith(".")
        ):
            raise ValueError("alert native scope binding is invalid")
        native_scope(f"/subscriptions/{subscription}/resourceGroups/{group}")
        for reference in (self.tenant_ref, self.scope_ref):
            if (
                not isinstance(reference, str)
                or re.fullmatch(r"[a-z][a-z0-9_.:-]{0,159}", reference) is None
            ):
                raise ValueError("alert scope pseudonym is invalid")
        if not isinstance(self.pseudonym_key, bytes) or not 32 <= len(self.pseudonym_key) <= 256:
            raise ValueError("alert pseudonym key MUST contain 32 to 256 bytes")
        if (
            not isinstance(self.policy_bindings, Mapping)
            or len(self.policy_bindings) > 2000
            or any(
                not isinstance(key, str) or not isinstance(value, Mapping)
                for key, value in self.policy_bindings.items()
            )
        ):
            raise ValueError("alert policy bindings are malformed")


class AzureAlertEvidenceSource:
    """Collect a bounded read profile, preserving missing sources and unknown authority."""

    def __init__(
        self,
        *,
        reader: AzureAlertReader,
        binding: AlertScopeBinding,
        audiences: AlertAudienceResolver | None = None,
    ) -> None:
        self._reader, self._binding, self._audiences = reader, binding, audiences

    def opaque(self, kind: str, value: str) -> str:
        """Key identities by tenant, RG purpose and kind; raw content stays case-sensitive."""
        if (
            re.fullmatch(r"[a-z][a-z-]{0,31}", kind) is None
            or not isinstance(value, str)
            or len(value) > 50_000_000
        ):
            raise ValueError("alert pseudonym input is invalid")
        if kind in {"rule", "group", "resource", "processing"}:
            value = value.casefold()  # ARM identities, not arbitrary content or recipient values.
        context = canonical_json(
            ["alert-noise-v1", self._binding.tenant_ref, self._binding.scope_ref, kind, value]
        )
        digest = hmac.new(self._binding.pseudonym_key, context.encode(), hashlib.sha256)
        return f"{kind}:" + digest.hexdigest()

    def _revision(self, value: object) -> str:
        # Keyed content fingerprints prevent enumerable recipient hashes. These are not ETags.
        return "sha256:" + self.opaque("content", canonical_json(value)).split(":", 1)[1]

    @property
    def _scope(self) -> str:
        return native_scope(
            f"/subscriptions/{self._binding.subscription_id}"
            f"/resourceGroups/{self._binding.resource_group}"
        )

    async def collect(self, *, now: datetime) -> AlertEvidence:
        """Use only ARM GETs; every source and optional resolver shares a finite budget."""
        if now.tzinfo is None:
            raise ValueError("alert evidence cutoff MUST be timezone-aware")
        start = now - timedelta(days=1)
        budget = self._reader.new_budget()
        raw: dict[str, tuple[Mapping[str, Any], ...]] = {}
        failures: dict[str, str] = {}
        failed = set(AZURE_ALERT_APIS)
        reasons = {
            "reverse_source_types_unverified",
            "ownership_unavailable",
            "incident_state_unavailable",
            "delivery_history_unavailable",
        }
        if self._binding.policy_bindings:
            reasons.add("static_policy_not_observed_authority")
        for collection, version in AZURE_ALERT_APIS.items():
            scope = (
                self._scope
                if collection == _HISTORY
                else f"/subscriptions/{self._binding.subscription_id}"
            )
            params = (
                {
                    "customTimeRange": f"{start.isoformat()}/{now.isoformat()}",
                    "includeContext": "false",
                    "includeEgressConfig": "false",
                    "pageCount": "250",
                }
                if collection == _HISTORY
                else None
            )
            try:
                raw[collection] = await self._reader.list(
                    scope + "/providers/" + collection,
                    api_version=version,
                    params=params,
                    budget=budget,
                )
                failed.remove(collection)
            except AlertReadUnavailable as failure:
                raw[collection] = failure.rows
                failures[collection] = str(failure)
                if failure.terminal:
                    reasons.add("collection_attempt_stopped")
                    break
        for collection in failed:
            reasons.add(collection.rsplit("/", 1)[-1].lower() + "_read_incomplete")
        seed = self._revision(
            {
                "api_profile": AZURE_ALERT_APIS,
                "failed": sorted(failed),
                "failures": failures,
                "rows": {
                    key: sorted(self._revision(row) for row in rows) for key, rows in raw.items()
                },
            }
        )
        evidence = await self._normalize(
            raw, now=now, start=start, budget=budget, reasons=reasons, failed=failed, seed=seed
        )
        if _HISTORY not in failed or raw.get(_HISTORY):
            return attach_alert_history(
                evidence,
                raw.get(_HISTORY, ()),
                opaque=self.opaque,
                collection_complete=_HISTORY not in failed,
                authorized_scope=self._scope,
            )
        return pin_evidence(evidence, source_digest=seed)

    def _stamp(self, now: datetime, coverage: str, reasons: set[str], seed: str) -> EvidenceStamp:
        return EvidenceStamp.model_validate(
            {
                "source": "azure-monitor-read-v1",
                "tenant_ref": self._binding.tenant_ref,
                "scope_ref": self._binding.scope_ref,
                "revision": seed,
                "observed_at": now,
                "recorded_at": now,
                "valid_until": now + timedelta(minutes=15),
                "coverage": coverage,
                "reasons": sorted(reasons),
            }
        )

    async def _normalize(
        self,
        raw: Mapping[str, tuple[Mapping[str, Any], ...]],
        *,
        now: datetime,
        start: datetime,
        budget: AlertReadBudget,
        reasons: set[str],
        failed: set[str],
        seed: str,
    ) -> AlertEvidence:
        rules: dict[str, AlertRule] = {}
        targets: dict[str, tuple[str, ...]] = {}
        reverse: dict[str, set[str]] = {}
        seen: set[str] = set()
        for collection, kind in _KINDS.items():
            for item in raw.get(collection, ()):
                try:
                    native = self._native(item, collection)
                    if native in seen:
                        rules.pop(native, None)
                        targets.pop(native, None)
                        raise ValueError("duplicate rule identity")
                    seen.add(native)
                    properties = object_value(item, "properties")
                    bindings = rule_groups(properties, kind)
                    for binding in bindings:
                        reverse.setdefault(self.opaque("group", binding), set()).add(
                            self.opaque("rule", native),
                        )
                    if not within_scope(native, self._scope):
                        continue
                    if len(rules) >= 2000:
                        raise ValueError("rule bound exceeded")
                    rule, exact_targets = alert_rule(
                        item,
                        native=native,
                        kind=kind,
                        bindings=bindings,
                        opaque=self.opaque,
                        revision=self._revision(item),
                        authorized_scope=self._scope,
                        reasons=reasons,
                    )
                    rules[native], targets[native] = rule, exact_targets
                except ValueError:
                    reasons.add("rule_shape_or_scope_incomplete")
        used = {ref for rule in rules.values() for ref in rule.group_refs}
        groups: dict[str, AlertGroup] = {}
        available_groups: dict[str, str] = {}
        audience_rows: dict[str, Audience] = {}
        for item in raw.get(_GROUPS, ()):
            try:
                native = self._native(item, _GROUPS)
                if native in seen:
                    groups.pop(native, None)
                    available_groups.pop(native, None)
                    raise ValueError("duplicate group identity")
                seen.add(native)
                if self.opaque("group", native) not in used and not within_scope(
                    native, self._scope
                ):
                    continue
                if len(groups) >= 1000 or len(audience_rows) >= 2000:
                    raise ValueError("group or audience bound exceeded")
                group, members = await self._group(item, native, budget, reasons)
                if len(audience_rows) + len(members) > 2000:
                    raise ValueError("audience bound exceeded")
                groups[native] = group
                audience_rows.update((member.ref, member) for member in members)
                if (
                    within_scope(native, self._scope)
                    and object_value(item, "properties")["enabled"]
                ):
                    available_groups[native] = group.ref
            except ValueError:
                reasons.add("group_shape_or_scope_incomplete")
        processing_rows: dict[str, ProcessingRule] = {}
        for item in raw.get(_PROCESSING, ()):
            try:
                native = self._native(item, _PROCESSING)
                if native in seen:
                    processing_rows.pop(native, None)
                    raise ValueError("duplicate processing identity")
                seen.add(native)
                normalized = processing_rule(
                    item,
                    native_rules={key: rule.ref for key, rule in rules.items()},
                    native_targets=targets,
                    native_groups=available_groups,
                    authorized_scope=self._scope,
                    opaque=self.opaque,
                    revision=self._revision(item),
                    now=now,
                )
                if normalized is None or len(processing_rows) >= 1000:
                    raise ValueError("processing semantics cannot be represented")
                processing_rows[native] = normalized
                if not normalized.semantics_complete:
                    reasons.add("processing_semantics_unknown")
                for group_ref in normalized.group_refs:
                    reverse.setdefault(group_ref, set()).update(normalized.rule_refs)
            except ValueError:
                reasons.add("processing_semantics_unknown")
        observed = {rule.ref for rule in rules.values()}
        for native, group in groups.items():
            dependencies = reverse.get(group.ref, set())
            if not dependencies.issubset(observed):
                reasons.add("dependencies_outside_scope")
            if len(dependencies) > 2000:
                reasons.add("dependency_bound_exceeded")
            groups[native] = AlertGroup.model_validate(
                {
                    **group.model_dump(),
                    "rule_refs": tuple(sorted(dependencies)[:2000]),
                    "reverse_complete": False,
                }
            )
        if used - {group.ref for group in groups.values()}:
            reasons.add("referenced_groups_unavailable")
        available = bool(rules or groups or processing_rows) or any(
            collection not in failed for collection in AZURE_ALERT_APIS if collection != _HISTORY
        )
        bound_audiences = {ref for group in groups.values() for ref in group.audience_refs}
        return AlertEvidence(
            stamp=self._stamp(now, "partial" if available else "unavailable", reasons, seed),
            window_start=start,
            window_end=now,
            rules=tuple(sorted(rules.values(), key=lambda row: row.ref)),
            groups=tuple(sorted(groups.values(), key=lambda row: row.ref)),
            audiences=tuple(audience_rows[ref] for ref in sorted(bound_audiences)),
            processing_rules=tuple(sorted(processing_rows.values(), key=lambda row: row.ref)),
        )

    def _native(self, raw: Mapping[str, Any], collection: str) -> str:
        native = native_resource(raw, collection)
        if native.split("/")[2] != self._binding.subscription_id.casefold():
            raise ValueError("provider resource is outside the bound subscription")
        return native

    async def _group(
        self, raw: Mapping[str, Any], native: str, budget: AlertReadBudget, reasons: set[str]
    ) -> tuple[AlertGroup, tuple[Audience, ...]]:
        properties = object_value(raw, "properties")
        if (
            type(properties.get("enabled")) is not bool
            or len(text(properties.get("groupShortName"))) > 12
        ):
            raise ValueError("group configuration is malformed")
        can_resolve = properties["enabled"] and within_scope(native, self._scope)
        if not can_resolve:
            reasons.add("group_disabled_or_outside_scope")
        members: list[Audience] = []
        automation: list[str] = []
        names: set[str] = set()
        for key, values in sorted(properties.items()):
            if not key.endswith("Receivers"):
                if key not in {"groupShortName", "enabled"}:
                    reasons.add("receiver_semantics_unknown")
                continue
            for receiver in list_value(values, maximum=128):
                if not isinstance(receiver, Mapping):
                    raise ValueError("group receiver is malformed")
                name = text(receiver.get("name"))
                if name.casefold() in names:
                    raise ValueError("group receiver name is duplicated")
                names.add(name.casefold())
                if len(names) > 128:
                    raise ValueError("group receiver bound exceeded")
                binding = canonical_json([native, key, name])
                if key not in NOTIFICATION_FIELDS:
                    automation.append(self.opaque("automation", binding))
                    reasons.add("automation_semantics_unverified")
                else:
                    members.append(
                        await self._audience(
                            native,
                            key,
                            receiver,
                            binding,
                            budget,
                            reasons,
                            can_resolve,
                        )
                    )
        return AlertGroup(
            ref=self.opaque("group", native),
            revision=self._revision(raw),
            rule_refs=(),
            audience_refs=tuple(sorted(member.ref for member in members)),
            automation_refs=tuple(sorted(automation)),
            reverse_complete=False,
        ), tuple(members)

    async def _audience(
        self,
        native: str,
        key: str,
        receiver: Mapping[str, Any],
        binding: str,
        budget: AlertReadBudget,
        reasons: set[str],
        can_resolve: bool,
    ) -> Audience:
        kind = notification_kind(key, receiver)
        fallback = Audience(
            ref=self.opaque("audience", binding),
            kind=kind,
            coverage="unavailable",
            revision=self._revision([native, key, receiver]),
        )
        if (
            self._audiences is not None
            and can_resolve
            and "audience_resolution_failed" not in reasons
        ):
            try:
                private = canonical_json(
                    {
                        "tenant_ref": self._binding.tenant_ref,
                        "scope_ref": self._binding.scope_ref,
                        "action_group_id": native,
                        "subscription_scope": f"/subscriptions/{self._binding.subscription_id}",
                        "receiver_type": key,
                        "receiver": receiver,
                    }
                )
                budget.consume("pages")  # Also bound zero-member expansion calls.
                timeout = min(5.0, budget.remaining_seconds())
                resolved = await asyncio.wait_for(
                    self._audiences.resolve(
                        binding_ref=fallback.ref,
                        kind=kind,
                        private_value=private,
                    ),
                    timeout=timeout,
                )
                result = Audience.model_validate(resolved.model_dump())
                allowed_kinds = {"role"} if kind == "role" else {"direct", "group"}
                if (
                    result.ref != fallback.ref
                    or result.kind not in allowed_kinds
                    or any(
                        re.fullmatch(r"principal:[a-f0-9]{64}", ref) is None
                        for ref in result.member_refs
                    )
                    or (
                        (result.primary_verified or result.backup_verified)
                        and (result.coverage != "complete" or not result.member_refs)
                    )
                ):
                    raise ValueError("resolved audience binding or evidence mismatch")
                budget.consume("items", len(result.member_refs))
                budget.consume("bytes", len(result.model_dump_json().encode()))
                if result.coverage != "complete":
                    reasons.add("audience_expansion_incomplete")
                if not result.primary_verified or not result.backup_verified:
                    reasons.add("audience_reachability_unverified")
                return Audience.model_validate(
                    {
                        **result.model_dump(),
                        "revision": self._revision(
                            {
                                "binding_revision": fallback.revision,
                                "resolution": result.model_dump(mode="json"),
                            }
                        ),
                    }
                )
            except Exception:
                reasons.add("audience_resolution_failed")  # No raw resolver errors or retry.
        reasons.add("audience_expansion_unavailable")
        return fallback

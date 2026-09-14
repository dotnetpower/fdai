"""Retain native source episodes without inventing linkage, revisions or delivery.

Public AlertsManagement/AlertsManagement/stable/2019-03-01/AlertsManagement.json
defines alertRule as an ARM ID OR a name. Neither essentials nor egressConfig
provides an authoritative historical rule revision. Source episodes retain a null
revision and partial history rather than substituting today's configuration.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.alert_noise import AlertDelivery, AlertEvidence

from fdai.delivery.azure.alert_noise_normalize import (
    canonical_json,
    native_scope,
    object_value,
    text,
    within_scope,
)


def attach_alert_history(
    evidence: AlertEvidence,
    rows: tuple[Mapping[str, Any], ...],
    *,
    opaque: Callable[[str, str], str],
    collection_complete: bool = True,
    authorized_scope: str | None = None,
) -> AlertEvidence:
    """Pin native rows and exact linked source events while retaining unknown rule revisions.

    Only a successful, fully paged empty native collection can establish an empty history.
    Source observations are not notification attempts, deliveries or acknowledgements. Existing
    independently supplied delivery records and their coverage are left intact.
    """
    rule_map = {rule.ref: rule for rule in evidence.rules}
    bound_scope = native_scope(authorized_scope) if authorized_scope is not None else None
    reasons = set(evidence.stamp.reasons)
    complete = collection_complete and not rows
    if rows:
        reasons.add("history_is_instance_snapshot")
    if not collection_complete:
        reasons.add("history_collection_partial")
    fingerprints: list[str] = []
    if len(rows) > 10_000:
        raise ValueError("native alert history exceeds its record bound")
    seen: set[str] = set()
    observations = {row.ref: row for row in evidence.deliveries}
    for row in rows:
        fingerprints.append(opaque("history-content", canonical_json(row)))
        try:
            if not isinstance(row, Mapping):
                raise ValueError("native alert history row is malformed")
            native_id = native_scope(row.get("id"))
            if native_id.split("/")[-3:-1] != ["microsoft.alertsmanagement", "alerts"]:
                raise ValueError("native alert instance identity is malformed")
            if native_id in seen:
                raise ValueError("native alert instance is duplicated")
            seen.add(native_id)
            if (
                "type" in row
                and text(row["type"]).casefold() != "microsoft.alertsmanagement/alerts"
            ):
                raise ValueError("native alert instance type is malformed")
            essentials = object_value(object_value(row, "properties"), "essentials")
            fired_at = _time(essentials.get("startDateTime"))
            condition = text(essentials.get("monitorCondition"))
            if condition not in {"Fired", "Resolved"}:
                raise ValueError("native monitor condition is unsupported")
            times = [fired_at]
            if condition == "Resolved":
                resolved_at = _time(essentials.get("monitorConditionResolvedDateTime"))
                if resolved_at < fired_at:
                    raise ValueError("native alert episode times are reversed")
                times.append(resolved_at)
            if not any(evidence.window_start <= value < evidence.window_end for value in times):
                continue
            complete = False
            target = native_scope(essentials.get("targetResource"))
            if bound_scope is not None and not within_scope(target, bound_scope):
                reasons.add("history_target_outside_scope")
                continue
            native_rule = text(essentials.get("alertRule"))
            if not native_rule.startswith("/"):
                # A unique current name still cannot prove historical identity across rule kinds.
                reasons.add("history_rule_identity_unavailable")
                continue
            rule = rule_map.get(opaque("rule", native_scope(native_rule)))
            if rule is None:
                reasons.add("history_rule_unobserved")
                continue
            if rule.resource_ref != opaque("resource", target):
                reasons.add("history_target_unrepresented")
                continue
            reasons.add("historical_rule_revision_unavailable")
            for at, state in zip(times, ("fired", "resolved"), strict=False):
                if not evidence.window_start <= at < evidence.window_end:
                    continue
                if len(observations) >= 10_000:
                    reasons.add("history_observation_bound_exceeded")
                    break
                event_ref = opaque("event", canonical_json([native_id, state, at.isoformat()]))
                source_event = AlertDelivery.model_validate(
                    {
                        "ref": event_ref,
                        "episode_ref": opaque("episode", native_id),
                        "rule_ref": rule.ref,
                        "rule_revision": None,
                        "condition": state,
                        "state": "source",
                        "event_at": at,
                        "receipt_ref": opaque("receipt", canonical_json(row)),
                    }
                )
                if event_ref in observations and observations[event_ref] != source_event:
                    reasons.add("history_observation_conflict")
                    continue
                observations[event_ref] = source_event
        except ValueError:
            complete = False
            reasons.add("history_shape_invalid")
    result = evidence.model_dump(mode="json")
    result["deliveries"] = [row.model_dump(mode="json") for _, row in sorted(observations.items())]
    result["history_coverage"] = "complete" if complete else ("partial" if rows else "unavailable")
    overflow = "evidence_reason_bound_exceeded"
    result["stamp"]["reasons"] = (
        sorted(reasons)
        if len(reasons) <= 32
        else sorted([*sorted(reasons - {overflow})[:31], overflow])
    )
    if not complete and result["stamp"]["coverage"] == "complete":
        result["stamp"]["coverage"] = "partial"
    return pin_evidence(
        AlertEvidence.model_validate(result),
        source_digest=opaque("history-content", canonical_json(sorted(fingerprints))),
    )


def pin_evidence(evidence: AlertEvidence, *, source_digest: str) -> AlertEvidence:
    """Bind every normalized field and the keyed native-content fingerprint into provenance."""
    result = evidence.model_dump(mode="json")
    previous_revision = result["stamp"].pop("revision")
    digest_input = {
        "previous_revision": previous_revision,
        "source_digest": source_digest,
        "evidence": result,
    }
    result["stamp"]["revision"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json(digest_input).encode(),
        ).hexdigest()
    )
    return AlertEvidence.model_validate(result)


def _time(raw: object) -> datetime:
    value = text(raw)
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
    if re.fullmatch(pattern, value) is None:
        raise ValueError("history timestamp MUST have an explicit offset and supported precision")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

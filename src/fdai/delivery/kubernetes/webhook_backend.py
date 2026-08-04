"""Targeted Kubernetes admission webhook backend absence candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def missing_webhook_backend_findings(
    configurations: Sequence[Mapping[str, Any]],
    service_receipts: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Report only webhook Services confirmed absent by exact targeted reads."""

    if not evidence_complete:
        return ()
    receipts: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for receipt in service_receipts:
        identity = (str(receipt.get("namespace") or ""), str(receipt.get("name") or ""))
        if all(identity):
            receipts.setdefault(identity, []).append(receipt)
    findings: list[dict[str, Any]] = []
    for configuration in sorted(configurations, key=_identity):
        if (
            configuration.get("kind")
            not in {"MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}
            or configuration.get("projection_complete") is not True
        ):
            continue
        for index, webhook in enumerate(_mappings(configuration.get("webhooks"))):
            service = webhook.get("service")
            if webhook.get("projection_complete") is not True or not isinstance(service, Mapping):
                continue
            service_identity = (
                str(service.get("namespace") or ""),
                str(service.get("name") or ""),
            )
            candidates = receipts.get(service_identity, ())
            if (
                not all(service_identity)
                or len(candidates) != 1
                or candidates[0].get("status") != "confirmed_absent"
            ):
                continue
            findings.append(
                {
                    "reason": "admission_webhook_backend_service_missing_candidate",
                    "resource": {
                        "kind": str(configuration.get("kind") or "")[:128],
                        "name": str(configuration.get("name") or "")[:253],
                    },
                    "source_paths": [f"/webhooks/{index}/clientConfig/service"],
                    "webhook_name": str(webhook.get("name") or "")[:253],
                    "failure_policy": str(webhook.get("failure_policy") or "")[:32],
                    "service": {
                        "namespace": service_identity[0][:253],
                        "name": service_identity[1][:253],
                    },
                    "evidence_strength": "targeted_service_absence_receipt",
                    "causality": "candidate_only",
                    "decision": "hold",
                }
            )
    return tuple(findings[:32])


def _identity(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value.get("kind") or ""), str(value.get("name") or "")


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["missing_webhook_backend_findings"]

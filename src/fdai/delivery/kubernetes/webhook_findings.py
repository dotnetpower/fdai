"""Deterministic Kubernetes admission webhook source candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_FAILURE_CLASSES = {
    "admission_webhook_unavailable": ("backend_unavailable", "failurePolicy"),
    "admission_webhook_tls_failure": ("tls_failure", "clientConfig/caBundle"),
    "admission_webhook_timeout": ("timeout", "timeoutSeconds"),
}


def admission_webhook_failure_findings(
    resources: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    namespace: str,
    evidence_complete: bool,
) -> tuple[dict[str, Any], ...]:
    """Correlate failed events to one uniquely named complete webhook candidate."""

    if not evidence_complete:
        return ()
    sources: dict[str, list[tuple[Mapping[str, Any], int, Mapping[str, Any]]]] = {}
    for configuration in resources:
        if (
            configuration.get("kind")
            not in {"MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}
            or configuration.get("projection_complete") is not True
        ):
            continue
        for index, webhook in enumerate(_mappings(configuration.get("webhooks"))):
            name = webhook.get("name")
            if isinstance(name, str) and webhook.get("projection_complete") is True:
                sources.setdefault(name, []).append((configuration, index, webhook))
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        failure_class = _FAILURE_CLASSES.get(str(event.get("code") or ""))
        webhook_name = event.get("webhook_name")
        regarding = event.get("regarding")
        candidates = sources.get(webhook_name, []) if isinstance(webhook_name, str) else []
        if (
            failure_class is None
            or len(candidates) != 1
            or event.get("namespace") != namespace
            or not isinstance(regarding, Mapping)
            or regarding.get("namespace") not in {None, "", namespace}
        ):
            continue
        configuration, index, webhook = candidates[0]
        identity = (
            str(configuration.get("kind") or ""),
            str(configuration.get("name") or ""),
            failure_class[0],
        )
        if identity in seen:
            continue
        seen.add(identity)
        finding: dict[str, Any] = {
            "reason": "admission_webhook_failure_configuration_candidate",
            "resource": {
                "kind": identity[0][:128],
                "name": identity[1][:253],
                "namespace": "",
            },
            "source_paths": [f"/webhooks/{index}/{failure_class[1]}"],
            "failure_class": failure_class[0],
            "webhook_name": webhook_name,
            "failure_policy": str(webhook.get("failure_policy") or "")[:32],
            "affected_resource": {
                "kind": str(regarding.get("kind") or "")[:128],
                "name": str(regarding.get("name") or "")[:253],
                "namespace": namespace,
            },
            "evidence_strength": "event_configuration_identity_match",
            "causality": "candidate_only",
            "decision": "hold",
        }
        service = webhook.get("service")
        if isinstance(service, Mapping):
            finding["service"] = {
                "namespace": str(service.get("namespace") or "")[:253],
                "name": str(service.get("name") or "")[:253],
            }
        findings.append(finding)
    return tuple(findings[:32])


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


__all__ = ["admission_webhook_failure_findings"]

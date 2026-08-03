"""Secret-safe classification of Kubernetes admission failure events."""

from __future__ import annotations

import re
from typing import Final, NamedTuple

_FAILED_REASONS: Final = frozenset({"Failed", "FailedCreate"})
_WEBHOOK_NAME: Final = re.compile(
    r'failed calling webhook "(?P<name>[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?)"',
    re.IGNORECASE,
)
_POD_SECURITY_PROFILE: Final = re.compile(
    r'violates\s+pod\s*security\s+"(?P<profile>baseline|restricted):'
    r'(?P<version>latest|v1\.[0-9]{1,3})"',
    re.IGNORECASE,
)
_POD_SECURITY_VIOLATIONS: Final = {
    "allow_privilege_escalation": ("allowprivilegeescalation != false",),
    "capabilities_drop_all": ("unrestricted capabilities", "capabilities.drop"),
    "run_as_non_root": ("runasnonroot != true",),
    "seccomp_profile": ("seccompprofile",),
}


class AdmissionFailure(NamedTuple):
    code: str
    webhook_name: str = ""
    pod_security_profile: str = ""
    pod_security_version: str = ""
    pod_security_violations: tuple[str, ...] = ()


def classify_admission_failure(*, reason: str, message: str) -> AdmissionFailure | None:
    """Return a bounded failure class only for a failed Kubernetes admission event."""

    if reason not in _FAILED_REASONS:
        return None
    normalized = message.casefold()
    webhook_name = _webhook_name(message)
    if webhook_name and any(
        marker in normalized
        for marker in (
            "certificate signed by unknown authority",
            "certificate is not valid",
            "failed to verify certificate",
            "tls handshake error",
            "x509:",
        )
    ):
        return AdmissionFailure("admission_webhook_tls_failure", webhook_name)
    if webhook_name and any(
        marker in normalized
        for marker in (
            "context deadline exceeded",
            "request did not complete within requested timeout",
        )
    ):
        return AdmissionFailure("admission_webhook_timeout", webhook_name)
    if webhook_name and any(
        marker in normalized
        for marker in ("connection refused", "no endpoints available", "service not found")
    ):
        return AdmissionFailure("admission_webhook_unavailable", webhook_name)
    if "is forbidden" not in normalized:
        return None
    match = _POD_SECURITY_PROFILE.search(message)
    if match is None:
        return None
    violations = tuple(
        code
        for code, markers in _POD_SECURITY_VIOLATIONS.items()
        if any(marker in normalized for marker in markers)
    )
    return AdmissionFailure(
        "pod_security_admission_rejected",
        pod_security_profile=match.group("profile").casefold(),
        pod_security_version=match.group("version").casefold(),
        pod_security_violations=violations,
    )


def _webhook_name(message: str) -> str:
    match = _WEBHOOK_NAME.search(message)
    if match is None:
        return ""
    name = match.group("name")
    return name.casefold() if len(name) <= 253 else ""


__all__ = ["AdmissionFailure", "classify_admission_failure"]

"""Default payload validation for Pantheon runtime bus ingress."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.thor_dispatch_validation import missing_wire_safeguards

_EXECUTABLE_VERDICTS = frozenset({"auto", "hil"})
_VERDICT_EVIDENCE_KEYS = frozenset(
    {"arbitration", "change_assessment", "decision_case", "kind", "risk_verdict", "decision"}
)


def default_payload_validator(topic: str, payload: Any) -> None:
    """Default-on pantheon object payload validator.

    Deployments can disable this only by constructing ``EventBusBridge``
    directly with ``payload_validator=None``; ``PantheonRuntime.build`` keeps
    the authority-bearing validator enabled so live delivery and redrive share
    the same fail-closed boundary.
    """

    if not isinstance(payload, dict):
        raise ValueError("pantheon payload MUST be a mapping")
    if topic == "object.verdict":
        _validate_verdict_payload(payload)
        return
    if topic == "object.action-run":
        if payload.get("kind") == "human_access_execution" and isinstance(
            payload.get("human_access"), dict
        ):
            return
        _require_non_empty_strings(payload, "state", "action_type")
        return
    if topic == "object.approval":
        if payload.get("kind") == "human_assignment" and isinstance(
            payload.get("assignment"), dict
        ):
            return
        if payload.get("kind") == "human_access_execution" and isinstance(
            payload.get("human_access"), dict
        ):
            return
        if not str(payload.get("state") or payload.get("decision") or "").strip():
            raise ValueError("approval payload MUST carry state or decision")


def _validate_verdict_payload(payload: dict[str, Any]) -> None:
    decision = str(payload.get("risk_verdict") or payload.get("decision") or "").strip()
    if not decision and not any(key in payload for key in _VERDICT_EVIDENCE_KEYS):
        raise ValueError("verdict payload MUST carry risk_verdict, decision, or kind")
    enforce_ceiling = str(payload.get("resolved_autonomy_ceiling") or "").strip()
    executable = (
        enforce_ceiling == "enforce_auto"
        or (enforce_ceiling == "enforce_hil" and decision == "hil")
        or payload.get("execution_authority") is True
    )
    if (
        executable
        and decision in _EXECUTABLE_VERDICTS
        and str(payload.get("action_type") or "").strip()
    ):
        missing = missing_wire_safeguards(payload)
        if missing:
            raise ValueError("executable verdict missing safeguard(s): " + ", ".join(missing))


def _require_non_empty_strings(payload: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError("payload missing required field(s): " + ", ".join(missing))


__all__ = ["default_payload_validator"]

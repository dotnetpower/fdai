"""Default payload validation for Pantheon runtime bus ingress."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.action_run_identity import is_action_run_identity
from fdai.agents._framework.thor_dispatch_validation import missing_wire_safeguards
from fdai.agents._framework.vidar_dr import DR_CONTRACT_KIND, DR_OUTCOME_KIND
from fdai.agents._framework.vidar_rehearsal import REHEARSAL_KIND

_EXECUTABLE_VERDICTS = frozenset({"auto", "hil"})
_ROLLBACK_STATES = frozenset({"succeeded", "failed", "refused", "execution_unknown"})
_DR_CONTRACT_DECISIONS = frozenset({"accepted", "held"})
_REHEARSAL_OUTCOMES = frozenset({"passed", "failed", "held"})
_MAX_BOUNDED_STRING = 512
_RULE_KINDS = frozenset(
    {"catalog_review_outcome", "handover_knowledge", "rule_promotion", "rule_state"}
)
_POLICY_KINDS = frozenset({"policy_activation", "policy_promotion", "test_context_revision"})
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
    if topic == "object.rollback":
        _validate_rollback_payload(payload)
        return
    if topic == "object.issue":
        _validate_issue_payload(payload)
        return
    if topic == "object.audit-entry":
        _validate_audit_entry_payload(payload)
        return
    if topic == "object.rule":
        _validate_rule_payload(payload)
        return
    if topic == "object.policy":
        _validate_policy_payload(payload)
        return


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
    _require_bounded_strings(payload, *fields)


def _require_bounded_strings(payload: dict[str, Any], *fields: str) -> None:
    oversized = [
        field
        for field in fields
        if isinstance(payload.get(field), str)
        and len(str(payload.get(field))) > _MAX_BOUNDED_STRING
    ]
    if oversized:
        raise ValueError("payload field(s) exceed bounded size: " + ", ".join(oversized))


def _validate_owned_governance_envelope(payload: dict[str, Any], owner: str) -> None:
    _require_non_empty_strings(
        payload,
        "producer_principal",
        "correlation_id",
        "idempotency_key",
    )
    if payload.get("producer_principal") != owner:
        raise ValueError(f"payload producer_principal MUST be {owner}")


def _validate_rollback_payload(payload: dict[str, Any]) -> None:
    kind = str(payload.get("kind") or "").strip()
    if kind == DR_CONTRACT_KIND:
        _validate_dr_contract_payload(payload)
        return
    if kind == DR_OUTCOME_KIND:
        _validate_dr_outcome_payload(payload)
        return
    if kind == REHEARSAL_KIND:
        _validate_rehearsal_payload(payload)
        return
    _validate_ordinary_rollback_payload(payload)


def _validate_ordinary_rollback_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_strings(
        payload,
        "correlation_id",
        "idempotency_key",
        "action_run_identity",
        "action_type",
        "contract",
        "state",
    )
    if not is_action_run_identity(payload.get("action_run_identity")):
        raise ValueError("rollback payload action_run_identity is malformed")
    state = str(payload.get("state") or "")
    if state not in _ROLLBACK_STATES:
        raise ValueError("rollback payload state is invalid")
    rollback_ref = str(payload.get("rollback_ref") or "").strip()
    if state == "succeeded" and not rollback_ref:
        raise ValueError("rollback payload missing required field(s): rollback_ref")
    if state != "succeeded" and rollback_ref:
        raise ValueError("rollback payload rollback_ref is only valid for succeeded state")


def _validate_dr_contract_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_strings(
        payload,
        "correlation_id",
        "idempotency_key",
        "action_run_identity",
        "action_type",
        "decision",
        "failback_contract",
        "expected_effect_digest",
    )
    if not is_action_run_identity(payload.get("action_run_identity")):
        raise ValueError("DR rollback contract action_run_identity is malformed")
    decision = str(payload.get("decision") or "")
    if decision not in _DR_CONTRACT_DECISIONS:
        raise ValueError("DR rollback contract decision is invalid")
    if not str(payload.get("expected_effect_digest") or "").startswith("sha256:"):
        raise ValueError("DR rollback contract expected_effect_digest is malformed")
    if not isinstance(payload.get("contract_ready"), bool):
        raise ValueError("DR rollback contract_ready MUST be boolean")
    if not isinstance(payload.get("failback_executor_bound"), bool):
        raise ValueError("DR rollback failback_executor_bound MUST be boolean")


def _validate_dr_outcome_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_strings(
        payload,
        "correlation_id",
        "idempotency_key",
        "action_run_identity",
        "action_type",
        "state",
        "effect_verification_ref",
        "execution_closure_ref",
        "expected_effect_digest",
    )
    if not is_action_run_identity(payload.get("action_run_identity")):
        raise ValueError("DR rollback outcome action_run_identity is malformed")
    if payload.get("state") != "succeeded":
        raise ValueError("DR rollback outcome state MUST be succeeded")
    if not str(payload.get("expected_effect_digest") or "").startswith("sha256:"):
        raise ValueError("DR rollback outcome expected_effect_digest is malformed")


def _validate_rehearsal_payload(payload: dict[str, Any]) -> None:
    _require_non_empty_strings(
        payload,
        "correlation_id",
        "idempotency_key",
        "resource_id",
        "action_type",
        "rollback_contract",
        "outcome",
        "recorded_at",
        "rehearsal_version",
        "receipt_digest",
    )
    if payload.get("outcome") not in _REHEARSAL_OUTCOMES:
        raise ValueError("rollback rehearsal outcome is invalid")
    if not str(payload.get("receipt_digest") or "").startswith("sha256:"):
        raise ValueError("rollback rehearsal receipt_digest is malformed")


def _validate_issue_payload(payload: dict[str, Any]) -> None:
    _validate_owned_governance_envelope(payload, "Saga")
    _require_non_empty_strings(payload, "fingerprint")
    issue_number = payload.get("issue_number")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
        raise ValueError("issue payload issue_number MUST be a positive integer")
    if "created" in payload and not isinstance(payload.get("created"), bool):
        raise ValueError("issue payload created MUST be boolean when present")
    if "open" in payload and not isinstance(payload.get("open"), bool):
        raise ValueError("issue payload open MUST be boolean when present")


def _validate_audit_entry_payload(payload: dict[str, Any]) -> None:
    _validate_owned_governance_envelope(payload, "Saga")
    _require_bounded_strings(payload, "action_kind", "audited_topic", "kind")
    audited_topic = str(payload.get("audited_topic") or "").strip()
    action_kind = str(payload.get("action_kind") or "").strip()
    kind = str(payload.get("kind") or "").strip()
    if not audited_topic and not action_kind and not kind:
        raise ValueError("audit-entry payload MUST carry audited_topic, action_kind, or kind")
    if audited_topic and not audited_topic.startswith("object."):
        raise ValueError("audit-entry payload audited_topic is invalid")


def _validate_rule_payload(payload: dict[str, Any]) -> None:
    _validate_owned_governance_envelope(payload, "Mimir")
    kind = str(payload.get("kind") or "").strip()
    if kind and kind not in _RULE_KINDS:
        raise ValueError("rule payload kind is invalid")
    if kind == "handover_knowledge":
        if not isinstance(payload.get("knowledge"), dict):
            raise ValueError("rule payload handover knowledge MUST be a mapping")
        if (
            payload.get("execution_authority") is not False
            or payload.get("may_promote") is not False
        ):
            raise ValueError("rule payload handover knowledge MUST be non-authority")
    elif kind == "catalog_review_outcome":
        _require_non_empty_strings(payload, "outcome")
        _require_optional_non_empty_strings(payload, "candidate_digest", "package_digest")
        mode = payload.get("mode")
        if mode is not None and mode != "shadow":
            raise ValueError("rule payload catalog_review_outcome MUST remain shadow")
    else:
        _require_non_empty_strings(payload, "rule_id", "state")
    if "grants_execution_authority" in payload and not isinstance(
        payload.get("grants_execution_authority"),
        bool,
    ):
        raise ValueError("rule payload grants_execution_authority MUST be boolean")


def _require_optional_non_empty_strings(payload: dict[str, Any], *fields: str) -> None:
    present = [field for field in fields if payload.get(field) is not None]
    if present:
        _require_non_empty_strings(payload, *present)


def _validate_policy_payload(payload: dict[str, Any]) -> None:
    _validate_owned_governance_envelope(payload, "Mimir")
    kind = str(payload.get("kind") or "").strip()
    if kind and kind not in _POLICY_KINDS:
        raise ValueError("policy payload kind is invalid")
    if kind == "policy_activation":
        _require_non_empty_strings(payload, "policy_id", "revision_id")
    elif kind == "policy_promotion":
        _require_non_empty_strings(payload, "policy_id", "state")
    elif kind == "test_context_revision":
        _require_non_empty_strings(payload, "application")
    else:
        _require_non_empty_strings(payload, "policy_id")
    if "grants_execution_authority" in payload and not isinstance(
        payload.get("grants_execution_authority"),
        bool,
    ):
        raise ValueError("policy payload grants_execution_authority MUST be boolean")


__all__ = ["default_payload_validator"]

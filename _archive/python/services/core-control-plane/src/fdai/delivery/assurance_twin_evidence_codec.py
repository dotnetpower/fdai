"""Validation and serialization helpers for retained Assurance Twin evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from fdai.core.assurance_twin.report import build_posture_assessment_report
from fdai.core.assurance_twin.typed_proposal import TypedProposalAssessment
from fdai.delivery.assurance_twin_writers import (
    AssuranceTwinPublishRequest,
    RetainedTwinEvidence,
    RuleFindingAssessment,
    findings_digest,
    rule_set_digest,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    _check_bounded_findings,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef


def decode_evidence(
    raw: Mapping[str, Any],
    *,
    expected_kind: Literal["posture", "review"],
    source_key: str,
    revision: str,
) -> RetainedTwinEvidence:
    request = AssuranceTwinPublishRequest.model_validate(raw.get("request"))
    if (
        request.kind != expected_kind
        or request.source_key != source_key
        or request.source_revision != revision
        or raw.get("source_revision") != revision
        or raw.get("request_status") != "pending"
        or raw.get("complete") is not True
        or not isinstance(raw.get("conflict"), bool)
    ):
        raise ValueError("Assurance Twin retained evidence identity diverges")
    record_raw = raw.get("record")
    if not isinstance(record_raw, Mapping):
        raise ValueError("Assurance Twin retained record is malformed")
    findings = _findings(record_raw.get("findings"))
    generated_at = str(record_raw.get("generated_at") or "")
    record: Any
    if expected_kind == "posture":
        record = build_posture_assessment_report(
            scope=source_key,
            generated_at=generated_at,
            mode=Mode.SHADOW,
            findings=findings,
        )
    else:
        record = IacReview(
            pr_ref=str(record_raw.get("pr_ref") or ""),
            review_key=source_key,
            findings=findings,
            verdict=str(record_raw.get("verdict") or ""),
            mode=Mode.SHADOW,
            generated_at=generated_at,
            metadata=dict(record_raw.get("metadata") or {}),
        )
    rule_raw = raw.get("rule_assessment")
    if not isinstance(rule_raw, Mapping):
        raise ValueError("Assurance Twin Rule assessment is malformed")
    rule_assessment = RuleFindingAssessment(
        source_revision=str(rule_raw.get("source_revision") or ""),
        rule_set_digest=str(rule_raw.get("rule_set_digest") or ""),
        rule_membership_digest=str(rule_raw.get("rule_membership_digest") or ""),
        rule_generation_digest=str(rule_raw.get("rule_generation_digest") or ""),
        inventory_revision=str(rule_raw.get("inventory_revision") or ""),
        evaluated_rule_ids=tuple(rule_raw.get("evaluated_rule_ids") or ()),
        findings_digest=str(rule_raw.get("findings_digest") or ""),
        coverage_refs=tuple(rule_raw.get("coverage_refs") or ()),
        complete=rule_raw.get("complete") is True,
    )
    # A retired proposed-IaC row has no typed readback and stays unavailable.
    typed_raw = raw.get("typed_proposal")
    typed = _typed_proposal(typed_raw) if isinstance(typed_raw, Mapping) else None
    return RetainedTwinEvidence(
        record=record,
        source_revision=revision,
        evidence_digest=str(raw.get("evidence_digest") or ""),
        fresh_until=datetime.fromisoformat(str(raw.get("fresh_until") or "")),
        coverage_refs=tuple(raw.get("coverage_refs") or ()),
        complete=True,
        conflict=raw.get("conflict") is True,
        rule_assessment=rule_assessment,
        typed_proposal=typed,
    )


def rule_assessment_body(
    *,
    source_revision: str,
    findings: tuple[Finding, ...],
    evaluated_rule_ids: tuple[str, ...],
    coverage_refs: tuple[str, ...],
    rule_set_revision: str | None,
    rule_generation_revision: str | None,
    inventory_revision: str | None,
) -> dict[str, Any]:
    """Serialize one complete Rule assessment bound to its exact findings."""

    resolved_rule_set = rule_set_revision or rule_set_digest(evaluated_rule_ids)
    return {
        "source_revision": source_revision,
        "rule_set_digest": resolved_rule_set,
        "rule_membership_digest": rule_set_digest(evaluated_rule_ids),
        "rule_generation_digest": rule_generation_revision or resolved_rule_set,
        "inventory_revision": inventory_revision or source_revision,
        "evaluated_rule_ids": list(evaluated_rule_ids),
        "findings_digest": findings_digest(findings),
        "coverage_refs": list(
            coverage_refs
            if resolved_rule_set in coverage_refs
            else (resolved_rule_set, *coverage_refs)
        ),
        "complete": True,
    }


def validate_common(
    *,
    source_key: str,
    source_revision: str,
    evaluated_rule_ids: tuple[str, ...],
    coverage_refs: tuple[str, ...],
    generated_at: datetime,
    fresh_until: datetime,
    correlation_id: str,
) -> None:
    if (
        not source_key.strip()
        or not valid_digest(source_revision)
        or not evaluated_rule_ids
        or evaluated_rule_ids != tuple(sorted(set(evaluated_rule_ids)))
        or not coverage_refs
        or any(not ref.strip() for ref in coverage_refs)
        or generated_at.tzinfo is None
        or fresh_until.tzinfo is None
        or not generated_at < fresh_until
        or not correlation_id.strip()
    ):
        raise ValueError("Assurance Twin retained evidence is incomplete")


def validate_findings(findings: tuple[Finding, ...], evaluated_rule_ids: tuple[str, ...]) -> None:
    _check_bounded_findings(findings)
    if any(
        finding.rule_id not in evaluated_rule_ids or not finding.evidence_refs
        for finding in findings
    ):
        raise ValueError("Assurance Twin findings exceed complete Rule coverage")


def valid_digest(value: str) -> bool:
    return (
        value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def evidence_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        key: item
        for key, item in value.items()
        if key not in {"revision", "request_status", "writer_status"}
    }
    request = identity.get("request")
    if isinstance(request, Mapping):
        identity["request"] = {
            key: item for key, item in request.items() if key != "correlation_id"
        }
    return identity


def source_conflict_audit(
    request: AssuranceTwinPublishRequest,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "assurance_twin_evidence_source_conflict",
        "producer_principal": "Heimdall" if request.kind == "posture" else "Forseti",
        "request_kind": request.kind,
        "idempotency_key": request.idempotency_key,
        "source_revision": request.source_revision,
        "conflicting_evidence_digest": incoming.get("evidence_digest"),
        "execution_authority": False,
    }


def advance_target_outbox(
    target: Mapping[str, Any],
    *,
    revision: int,
) -> dict[str, Any]:
    outbox = target.get("publication_outbox")
    if outbox is None:
        return {}
    if not isinstance(outbox, Mapping):
        raise ValueError("Assurance Twin target outbox is malformed")
    return {"publication_outbox": {**outbox, "record_revision": revision}}


def _typed_proposal(raw: Mapping[str, Any]) -> TypedProposalAssessment:
    targets = raw.get("targets")
    if not isinstance(targets, list) or any(
        not isinstance(item, list) or len(item) != 2 for item in targets
    ):
        raise ValueError("Assurance Twin typed proposal targets are malformed")
    return TypedProposalAssessment(
        source_revision=str(raw.get("source_revision") or ""),
        proposal_ref=str(raw.get("proposal_ref") or ""),
        action_type=str(raw.get("action_type") or ""),
        action_type_version=str(raw.get("action_type_version") or ""),
        proposal_digest=str(raw.get("proposal_digest") or ""),
        parameters_digest=str(raw.get("parameters_digest") or ""),
        targets=tuple(
            ResourceRef(resource_type=str(item[0]), ref=str(item[1])) for item in targets
        ),
        what_if_digest=str(raw.get("what_if_digest") or ""),
        effect_digest=str(raw.get("effect_digest") or ""),
        change_digest=str(raw.get("change_digest") or ""),
        inventory_revision=str(raw.get("inventory_revision") or ""),
        evidence_refs=tuple(raw.get("evidence_refs") or ()),
        complete=raw.get("complete") is True,
    )


def _findings(raw: object) -> tuple[Finding, ...]:
    if not isinstance(raw, list):
        raise ValueError("Assurance Twin retained findings are malformed")
    return tuple(
        Finding(
            rule_id=str(item["rule_id"]),
            resource=ResourceRef(
                resource_type=str(item["resource_type"]),
                ref=str(item["resource_ref"]),
            ),
            severity=item["severity"],
            reason=str(item["reason"]),
            evidence_refs=tuple(item["evidence_refs"]),
        )
        for item in raw
        if isinstance(item, Mapping)
    )


__all__ = [
    "advance_target_outbox",
    "decode_evidence",
    "evidence_identity",
    "rule_assessment_body",
    "source_conflict_audit",
    "valid_digest",
    "validate_common",
    "validate_findings",
]

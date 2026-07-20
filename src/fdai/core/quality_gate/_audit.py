"""Audit projections for quality-gate decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.core.quality_gate.gate import QualityDecision

_RATIONALE_AUDIT_CAP: int = 500
"""Maximum rubric rationale characters written to an audit entry."""


def quality_decision_audit_fields(
    decision: QualityDecision,
    *,
    include_rationale: bool = False,
) -> dict[str, Any]:
    """Flatten a quality decision into JSON-safe audit fields.

    Rubric rationale is untrusted free text and is excluded by default.
    Callers that opt in remain responsible for secret scanning and
    redaction before persistence.
    """
    fields: dict[str, Any] = {
        "outcome": decision.outcome.value,
        "candidate_action_type": decision.candidate.action_type,
        "candidate_target_resource_ref": decision.candidate.target_resource_ref,
        "aggregate_confidence": decision.aggregate_confidence,
        "reasons": list(decision.reasons),
        "grounded_rule_ids": list(decision.grounded_rule_ids),
        "model_votes": [
            {
                "model_id": vote.model_id,
                "proposed_action_type": vote.proposed_action_type,
                "agreed": vote.agreed,
                **(
                    {
                        "prompt_replay_manifest": _prompt_replay_manifest_fields(
                            vote.prompt_replay_manifest
                        )
                    }
                    if vote.prompt_replay_manifest is not None
                    else {}
                ),
            }
            for vote in decision.model_votes
        ],
        "rubric_verdict": decision.rubric_verdict,
        "rubric_min_score": decision.rubric_min_score,
        "rubric_shadow": decision.rubric_shadow,
        "rubric_scores": [
            {
                "criterion": score.criterion,
                "score": score.score,
                "threshold": score.threshold,
                "passed": score.passed,
                "supporting_rule_ids": list(score.supporting_rule_ids),
                **(
                    {"rationale": score.rationale[:_RATIONALE_AUDIT_CAP]}
                    if include_rationale
                    else {}
                ),
            }
            for score in decision.rubric_scores
        ],
    }
    if decision.escalation_route is not None:
        fields["escalation_route"] = decision.escalation_route
        fields["escalation_reason"] = decision.escalation_reason
    if decision.self_consistency is not None:
        fields["self_consistency"] = decision.self_consistency
    return fields


def _prompt_replay_manifest_fields(manifest: Any) -> dict[str, Any]:
    return {
        "system_text_sha256": manifest.system_text_sha256,
        "token_estimate": manifest.token_estimate,
        "canary_tokens": [
            {"layer_id": layer_id, "token": token} for layer_id, token in manifest.canary_tokens
        ],
        "layer_manifest": [
            {
                "id": layer.id,
                "version": layer.version,
                "layer": layer.layer.value,
                "token_estimate": layer.token_estimate,
            }
            for layer in manifest.layer_manifest
        ],
        "skill_records": [
            {
                "operation": record.operation,
                "name": record.name,
                "version": record.version,
                "raw_markdown_sha256": record.raw_markdown_sha256,
                "body_sha256": record.body_sha256,
                "reference_path": record.reference_path,
                "reference_sha256": record.reference_sha256,
                "status": record.status.value,
                "rejection_reason": record.rejection_reason,
            }
            for record in manifest.skill_records
        ],
        "skill_bundle_records": [
            {
                "operation": record.operation,
                "name": record.name,
                "version": record.version,
                "manifest_sha256": record.manifest_sha256,
                "digest": record.digest,
                "members": [
                    {
                        "name": member.name,
                        "version": member.version,
                        "raw_markdown_sha256": member.raw_markdown_sha256,
                        "body_sha256": member.body_sha256,
                    }
                    for member in record.members
                ],
                "status": record.status.value,
                "rejection_reason": record.rejection_reason,
            }
            for record in manifest.skill_bundle_records
        ],
    }

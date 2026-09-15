"""Review-only removal of exact old duties after a recorded independent IAM effect."""

from __future__ import annotations

from collections.abc import Mapping

import yaml

from fdai.core.human_assignment.coverage import normalize_principal_ref
from fdai.core.human_assignment.model import AssignmentCase, AssignmentState, EffectKind
from fdai.core.human_assignment.ownership import AssignmentOwnershipError, _base_mapping
from fdai.core.stewardship import Duty, StewardshipMap, load_stewardship_from_mapping


def render_revocation_ownership_yaml(
    base: StewardshipMap,
    removal: AssignmentCase,
    *,
    original: AssignmentCase,
    replacements: Mapping[str, AssignmentCase],
) -> str:
    """Render only the pinned old person's duties; preserve all unrelated map entries.

    This function is not an IAM verifier or map writer. The caller resolves Core-owned effect
    evidence and current snapshots. The generated candidate still requires independent PR review
    and an exact signed merge; absent or drifted replacement coverage produces no candidate.
    """
    target = removal.intent.revocation
    if (
        target is None
        or removal.state not in {AssignmentState.IAM_REVOKED, AssignmentState.OWNERSHIP_PR_OPEN}
        or EffectKind.IAM not in removal.effect_kinds
        or original.case_id != target.case_id
        or original.revision != target.revision + 1
        or original.revocation_case_id != removal.case_id
        or original.state is not AssignmentState.DEGRADED
        or original.degraded_reason != "revocation_pending"
        or original.intent.subject != removal.intent.subject
        or original.intent.requested_role is not removal.intent.requested_role
        or original.intent.duty_bindings != removal.intent.duty_bindings
    ):
        raise AssignmentOwnershipError(
            "duty removal requires its exact held original and IAM effect"
        )
    if set(replacements) != set(target.replacement_revisions):
        raise AssignmentOwnershipError("duty removal replacement evidence is incomplete")
    old_subject = normalize_principal_ref(original.intent.subject.subject_id)
    for case_id, replacement in replacements.items():
        if (
            replacement.case_id != case_id
            or replacement.revision != target.replacement_revisions[case_id]
            or replacement.state is not AssignmentState.ACTIVE
            or not replacement.has_required_effects
            or replacement.intent.subject.provider != removal.intent.subject.provider
            or normalize_principal_ref(replacement.intent.subject.subject_id) == old_subject
        ):
            raise AssignmentOwnershipError("duty removal replacement revision or identity drifted")
    raw = _base_mapping(base)
    for binding in original.intent.duty_bindings:
        if binding.scope_ref != "scope:platform":
            raise AssignmentOwnershipError("global duty removal supports only scope:platform")
        stewards = raw["stewardship"]["agents"][binding.agent_name]["stewards"]
        matches = [
            item
            for item in stewards
            if item["kind"] == "user" and normalize_principal_ref(item["id"]) == old_subject
        ]
        if (
            len(matches) != 1
            or matches[0]["responsibility"] != "accountable"
            or matches[0].get("duty") != binding.duty.value
        ):
            raise AssignmentOwnershipError("old duty differs from the reviewed removal target")
        coverage: dict[Duty, set[str]] = {}
        for replacement in replacements.values():
            subject = normalize_principal_ref(replacement.intent.subject.subject_id)
            for duty in replacement.intent.duty_bindings:
                if (duty.agent_name, duty.scope_ref) != (binding.agent_name, binding.scope_ref):
                    continue
                if not any(
                    item["kind"] == "user"
                    and normalize_principal_ref(item["id"]) == subject
                    and item["responsibility"] == "accountable"
                    and item.get("duty") == duty.duty.value
                    for item in stewards
                ):
                    raise AssignmentOwnershipError(
                        "replacement duty is absent from the current map"
                    )
                coverage.setdefault(duty.duty, set()).add(subject)
        primaries = coverage.get(Duty.PRIMARY, set())
        fallback = coverage.get(Duty.BACKUP, set()) | coverage.get(Duty.ESCALATION, set())
        if len(primaries) != 1 or not fallback - primaries:
            raise AssignmentOwnershipError("duty removal needs a primary and distinct fallback")
        stewards.remove(matches[0])
    try:
        load_stewardship_from_mapping(raw, environ={})
    except ValueError as exc:
        raise AssignmentOwnershipError(
            "duty removal would break complete v2 ownership coverage"
        ) from exc
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


__all__ = ["render_revocation_ownership_yaml"]

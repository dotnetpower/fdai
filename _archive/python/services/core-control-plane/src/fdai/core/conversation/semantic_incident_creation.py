"""Project a verified semantic Incident request into a typed draft candidate."""

from __future__ import annotations

from fdai_service_contracts.incident_creation import (
    IncidentCreationArguments,
    IncidentCreationIntent,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def incident_creation_intent_from_judgment(
    judgment: SemanticJudgmentProposal | None,
    *,
    source_input_digest: str,
) -> IncidentCreationIntent | None:
    """Return a typed Incident draft only for one complete accepted judgment."""

    if not source_input_digest.strip():
        raise ValueError("semantic incident creation requires a non-empty source_input_digest")
    facets = (
        {facet.strip().replace("-", "_") for facet in judgment.requested_facets if facet.strip()}
        if judgment is not None
        else set()
    )
    if (
        judgment is None
        or judgment.primary_intent != "action_request"
        or judgment.action_subject != "Incident"
        or judgment.action_posture != "draft_only"
        or "incident_create" not in facets
        or judgment.ambiguous
        or judgment.unresolved_terms
    ):
        return None
    severities = tuple(target for target in judgment.targets if target.kind == "severity")
    resources = tuple(target for target in judgment.targets if target.kind == "resource")
    if len(severities) != 1 or len(resources) != 1:
        raise ValueError("semantic incident creation requires one severity and one Resource")
    severity = (severities[0].canonical_value or severities[0].value).strip().casefold()
    severity = severity.removeprefix("severity.")
    target = (resources[0].canonical_value or resources[0].value).strip()
    return IncidentCreationIntent(
        arguments=IncidentCreationArguments.model_validate(
            {"severity": severity, "target": target}
        ),
        source_input_digest=source_input_digest.strip(),
    )


__all__ = ["incident_creation_intent_from_judgment"]

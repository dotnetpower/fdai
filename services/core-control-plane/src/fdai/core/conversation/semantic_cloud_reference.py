"""Carry already-judged, source-spanned cloud conditions without interpreting prose."""

from __future__ import annotations

from fdai_service_contracts.cloud_knowledge import Applicability
from fdai_service_contracts.ontology_query import SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

_PREFIX = "cloud-reference:"
_FIELDS = {
    "cloud_provider": "provider",
    "cloud_resource_type": "resource_type",
    "cloud_generation": "service_generation",
    "cloud_sku": "skus",
    "cloud_api_version": "api_versions",
    "cloud_region": "regions",
    "cloud_deployment_mode": "deployment_modes",
}
_SINGULAR = frozenset({"provider", "resource_type", "service_generation"})


def cloud_reference_constraints(
    judgment: SemanticJudgmentProposal, *, utterance: str
) -> tuple[str, ...]:
    """Bind only literal source spans; unsupported aliases and incomplete targets remain unknown."""
    constraints = []
    for target in judgment.targets:
        field = _FIELDS.get(target.kind)
        if field is None:
            continue
        if (
            utterance[target.source_start : target.source_end] != target.value
            or target.canonical_value not in {None, target.value}
            or len(_PREFIX + field + "=" + target.value) > 128
        ):
            raise ValueError("cloud applicability requires bounded exact current-turn values")
        constraints.append(_PREFIX + field + "=" + target.value)
    modes = {
        value for value in judgment.requested_facets if value in {"cloud_as_of", "cloud_current"}
    }
    if len(modes) > 1:
        raise ValueError("cloud guidance purpose is ambiguous")
    if modes:
        constraints.append(_PREFIX + "guidance=" + next(iter(modes)).removeprefix("cloud_"))
    return tuple(sorted(set(constraints)))


def cloud_reference_arguments(frame: SemanticProblemFrame) -> dict[str, object]:
    """Decode typed frame constraints into query arguments, never derive them from the utterance."""
    values: dict[str, list[str]] = {}
    for constraint in frame.subject_constraints:
        if not constraint.startswith(_PREFIX):
            continue
        field, separator, value = constraint.removeprefix(_PREFIX).partition("=")
        if not separator or not value or field not in {*_FIELDS.values(), "guidance"}:
            raise ValueError("cloud applicability frame constraint is invalid")
        values.setdefault(field, []).append(value)
    if not values:
        return {}
    guidance = values.pop("guidance", ["reference"])
    if len(guidance) != 1 or guidance[0] not in {"reference", "as_of", "current"}:
        raise ValueError("cloud guidance purpose is invalid")
    arguments: dict[str, object] = {"guidance_mode": guidance[0]}
    if not _SINGULAR.issubset(values):
        # A reference may show dated excerpts, but it cannot claim a compatible target.
        return arguments
    if any(len(values[name]) != 1 for name in _SINGULAR):
        raise ValueError("cloud applicability target is ambiguous")
    target = Applicability.model_validate(
        {field: items[0] if field in _SINGULAR else items for field, items in values.items()}
    )
    arguments["applicability"] = target.model_dump(mode="json")
    return arguments

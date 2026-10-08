"""Reviewed exact T0 Rule bindings layered over the generated WARA catalog.

A ``t0_rule`` binding lets a WARA recommendation take its decisive evidence from an activated
catalog Rule instead of an Azure Resource Graph query. A binding is admitted only when a reviewed
capability matrix proves the Rule and the pinned APRL query agree on the exact resource type, the
observed fields, the eligible set, and the failure semantics. Anything weaker keeps the
recommendation's query or manual evidence path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.rule_catalog.schema.wara_assessment import (
    ResourceTypeDisposition,
    WaraAssessmentCatalog,
    WaraQueryCatalog,
    canonical_digest,
)
from fdai.shared.contracts.models import Rule

_SHA256 = r"^sha256:[a-f0-9]{64}$"
_UUID = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
_GIT_REF = r"^[a-f0-9]{40}$"
_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,255}$"
_SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"


class WaraRuleCapability(BaseModel):
    """The reviewed equivalence evidence between one APRL query and one Rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_resource_type: Annotated[str, Field(min_length=1, max_length=128)]
    child_resource_behavior: Literal["none"]
    inventory_fields: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    inventory_source: Literal["azure_resource_graph_row"]
    parameters: Literal["none"]
    eligible_set: Literal["every_resource_of_type"]
    failure_semantics: Literal["absent_or_not_true_fails"]

    @model_validator(mode="after")
    def _ordered(self) -> WaraRuleCapability:
        if self.inventory_fields != tuple(sorted(set(self.inventory_fields))):
            raise ValueError("WARA Rule capability fields MUST be unique and ordered")
        return self


class WaraRuleBinding(BaseModel):
    """One reviewed exact binding from an APRL recommendation to one Rule revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aprl_guid: Annotated[str, Field(pattern=_UUID)]
    query_digest: Annotated[str, Field(pattern=_SHA256)]
    rule_id: Annotated[str, Field(min_length=1, max_length=256)]
    rule_version: Annotated[str, Field(pattern=_SEMVER)]
    capability: WaraRuleCapability
    reviewer: Annotated[str, Field(pattern=_IDENTIFIER)]
    review_state: Literal["reviewed-exact"]

    @property
    def evaluator_ref(self) -> str:
        """Return the producer identity Rule receipts for this binding carry."""

        return f"t0-rule-evaluator:{self.rule_id}@{self.rule_version}"


class WaraRuleBindingCatalog(BaseModel):
    """Content-addressed overlay of reviewed WARA ``t0_rule`` bindings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    source_revision: Annotated[str, Field(pattern=_GIT_REF)]
    crosswalk_digest: Annotated[str, Field(pattern=_SHA256)]
    bindings: tuple[WaraRuleBinding, ...]
    overlay_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def _identity(self) -> WaraRuleBindingCatalog:
        guids = tuple(binding.aprl_guid for binding in self.bindings)
        if guids != tuple(sorted(set(guids))):
            raise ValueError("WARA Rule bindings MUST be unique and ordered by APRL GUID")
        material = self.model_dump(mode="json")
        material.pop("overlay_digest")
        if self.overlay_digest != canonical_digest(material):
            raise ValueError("WARA Rule binding overlay digest mismatch")
        return self

    def resolve(self, aprl_guid: str, query_digest: str) -> WaraRuleBinding | None:
        """Resolve only an exact APRL GUID and pinned query digest."""

        return next(
            (
                binding
                for binding in self.bindings
                if binding.aprl_guid == aprl_guid and binding.query_digest == query_digest
            ),
            None,
        )


def load_wara_rule_bindings(
    path: Path,
    *,
    catalog: WaraAssessmentCatalog,
    queries: WaraQueryCatalog,
    rules: tuple[Rule, ...],
) -> WaraRuleBindingCatalog:
    """Load the overlay and reject drift from the WARA catalog, its queries, or the Rules."""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    overlay = WaraRuleBindingCatalog.model_validate(raw)
    if overlay.source_revision != catalog.source_revision:
        raise ValueError("WARA Rule bindings source revision mismatch")
    if overlay.crosswalk_digest != catalog.crosswalk_digest:
        raise ValueError("WARA Rule bindings crosswalk digest mismatch")
    records = {record.aprl_guid: record for record in catalog.recommendations}
    query_bodies = {query.aprl_guid: query for query in queries.queries}
    rules_by_id = {rule.id: rule for rule in rules}
    for binding in overlay.bindings:
        record = records.get(binding.aprl_guid)
        query = query_bodies.get(binding.aprl_guid)
        if record is None or query is None or record.query_review is None:
            raise ValueError(f"{binding.aprl_guid}: Rule binding has no generated query")
        if (
            binding.query_digest != record.query_review.body_digest
            or binding.query_digest != query.body_digest
        ):
            raise ValueError(f"{binding.aprl_guid}: Rule binding query digest mismatch")
        if record.applicability.disposition is not ResourceTypeDisposition.CANONICAL:
            raise ValueError(f"{binding.aprl_guid}: Rule binding resource type is not canonical")
        if record.applicability.canonical_resource_type != (
            binding.capability.canonical_resource_type
        ):
            raise ValueError(f"{binding.aprl_guid}: Rule binding resource type mismatch")
        if record.query_review.evaluator_ref is not None:
            raise ValueError(f"{binding.aprl_guid}: generated catalog already binds an evaluator")
        if set(record.query_review.blocked_reasons) != {"missing_exact_evaluator"}:
            raise ValueError(f"{binding.aprl_guid}: Rule binding would hide other blockers")
        rule = rules_by_id.get(binding.rule_id)
        if rule is None or str(rule.version) != binding.rule_version:
            raise ValueError(f"{binding.aprl_guid}: Rule binding names an unavailable revision")
        if rule.resource_type != binding.capability.canonical_resource_type:
            raise ValueError(f"{binding.aprl_guid}: Rule binding Rule type mismatch")
        declared = tuple(
            sorted(
                reference.removeprefix(f"property.{rule.resource_type}.")
                for reference in rule.evaluates
            )
        )
        if declared != binding.capability.inventory_fields:
            raise ValueError(f"{binding.aprl_guid}: Rule binding fields differ from the Rule")
        if rule.parameters:
            raise ValueError(f"{binding.aprl_guid}: parameterized Rules need a parameter review")
    return overlay


__all__ = [
    "WaraRuleBinding",
    "WaraRuleBindingCatalog",
    "WaraRuleCapability",
    "load_wara_rule_bindings",
]

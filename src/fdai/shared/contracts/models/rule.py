"""Rule contract - one normalised, CSP-neutral catalog entry.

``provenance`` is mandatory: a rule without grounded provenance is
rejected at load, matching the discovery-loop rule in
``architecture.instructions.md § Design Principles``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field

from ._base import SemVer, _Base
from .enums import Category, CheckLogicKind, Redistribution, RuleSource, Severity


class CheckLogic(_Base):
    kind: CheckLogicKind
    reference: Annotated[str, Field(min_length=1)]


class Remediation(_Base):
    template_ref: Annotated[str, Field(min_length=1)]
    cost_impact_monthly_usd: float | None = Field(default=None, ge=0)


class Provenance(_Base):
    """Auditable origin of a rule / catalog entry.

    Field names follow the canonical vocabulary in
    ``docs/roadmap/rules-and-detection/rule-catalog-collection.md`` (``resolved_ref``,
    ``retrieved_at``, ``redistribution`` as an enum) so a hand-authored
    YAML lifted from that doc validates against this model without any
    field-name gymnastics.
    """

    source_url: Annotated[str, Field(min_length=1)]
    source_version: Annotated[str, Field(min_length=1)] | None = None
    resolved_ref: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(min_length=1)]
    license: Annotated[str, Field(min_length=1)]
    redistribution: Redistribution
    retrieved_at: datetime
    mapped_by: Annotated[str, Field(min_length=1)] | None = None


class RuleInterface(StrEnum):
    EVALUABLE = "Evaluable"
    REMEDIABLE = "Remediable"


class SubmissionCriterionKind(StrEnum):
    RESOURCE_TYPE_REGISTERED = "resource_type_registered"
    PROPERTY_EXISTS = "property_exists"
    LINK_EXISTS = "link_exists"


class SubmissionCriterion(_Base):
    kind: SubmissionCriterionKind
    value: Annotated[str, Field(min_length=1)]


class Rule(_Base):
    """Normalized, CSP-neutral rule entry.

    ``remediates`` is the ontology dispatch field (M:1) declaring which
    :class:`OntologyActionType` this rule proposes on match; the catalog
    loader cross-checks it against ``rule-catalog/action-types/`` at load
    time. ``alternatives`` is a preference-ordered list of alternate
    ActionType names - T0 always uses ``remediates``; only the T2 quality
    gate may swap in an alternative. See
    ``docs/roadmap/architecture/llm-strategy.md § Rule as Ontology Artifact``.
    """

    schema_version: SemVer
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    version: SemVer
    source: RuleSource
    severity: Severity
    category: Category
    resource_type: Annotated[str, Field(min_length=1)]
    check_logic: CheckLogic
    remediation: Remediation
    remediates: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    alternatives: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]] = Field(
        default_factory=list
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance
    applies_to: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    triggered_by: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=lambda: ["*"])
    evaluates: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=lambda: ["*"])
    required_interfaces: list[RuleInterface] = Field(
        default_factory=lambda: [RuleInterface.EVALUABLE, RuleInterface.REMEDIABLE]
    )
    submission_criteria: list[SubmissionCriterion] = Field(default_factory=list)
    scope_predicates: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CheckLogic",
    "Provenance",
    "Remediation",
    "Rule",
    "RuleInterface",
    "SubmissionCriterion",
    "SubmissionCriterionKind",
]

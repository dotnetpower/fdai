"""Two-phase anchor binding: exact identity reads before compilation.

The model quotes a resource as it was written; it does not know whether that
text is a name or a provider identifier. Core reads both exact properties in one
bounded snapshot and binds the anchor to the single object found, or reports
absence, ambiguity, or incompleteness. Compiled plans then read the exact bound
identity, never the quoted text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.ontology.acl import ProjectionRequest

from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_form import FilterRole, MentionDomain, MentionForm

ANCHOR_CANDIDATE_LIMIT = 7
_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})
_RESOURCE = "Resource"
_IDENTITY_PROPERTIES = ("id", "name")


class AnchorOutcome(StrEnum):
    BOUND = "bound"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AnchorBinding:
    mention_id: str
    outcome: AnchorOutcome
    object_id: str | None = None
    candidates: tuple[str, ...] = ()
    source_generation: str | None = None


@dataclass(frozen=True, slots=True)
class AnchorBindingReceipt:
    """Per-mention binding outcomes pinned to the snapshot generation read."""

    bindings: tuple[AnchorBinding, ...] = ()

    def binding(self, mention_id: str) -> AnchorBinding | None:
        return next((item for item in self.bindings if item.mention_id == mention_id), None)

    @property
    def digest(self) -> str:
        return content_digest(
            [
                {
                    "mention": item.mention_id,
                    "outcome": item.outcome.value,
                    "object_id": item.object_id,
                    "candidates": list(item.candidates),
                    "source_generation": item.source_generation,
                }
                for item in self.bindings
            ]
        )


class AnchorResolver(Protocol):
    async def resolve(self, mention_id: str, text: str) -> AnchorBinding: ...


def anchor_mentions(admission: FormAdmission) -> tuple[str, ...]:
    """Return every instance mention that a goal uses as an anchor or a scope."""

    form = admission.form
    cited: list[str] = []
    for goal in form.goals:
        cited.extend(item.mention for item in goal.filters if item.role is FilterRole.SCOPE)
        if goal.relation is not None and goal.relation.anchor is not None:
            cited.append(goal.relation.anchor)
        if goal.subject is not None:
            cited.append(goal.subject)
    return tuple(
        dict.fromkeys(
            mention_id
            for mention_id in cited
            if form.mention(mention_id).domain is MentionDomain.INSTANCE
            and form.mention(mention_id).form in _ANCHOR_FORMS
        )
    )


async def bind_anchors(
    admission: FormAdmission,
    resolver: AnchorResolver | None,
) -> AnchorBindingReceipt:
    """Bind every anchor mention, or mark it unavailable without a resolver."""

    bindings = []
    for mention_id in anchor_mentions(admission):
        if resolver is None:
            bindings.append(AnchorBinding(mention_id, AnchorOutcome.UNAVAILABLE))
            continue
        bindings.append(await resolver.resolve(mention_id, admission.mention_text[mention_id]))
    return AnchorBindingReceipt(tuple(bindings))


class GatewayAnchorResolver:
    """Resolve anchors through exact secured reads of each identity property."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        projection_request: ProjectionRequest,
        purpose: str,
        as_of: datetime,
    ) -> None:
        self._gateway = gateway
        self._request = projection_request
        self._purpose = purpose
        self._as_of = as_of

    async def resolve(self, mention_id: str, text: str) -> AnchorBinding:
        found: dict[str, None] = {}
        complete = True
        generations: set[str] = set()
        for property_name in _IDENTITY_PROPERTIES:
            definition = ObjectSetDefinition(
                selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=_RESOURCE),
                predicates=(
                    ObjectPredicate(
                        property=property_name,
                        operator=ObjectPredicateOperator.EQUALS,
                        equals=text,
                    ),
                ),
                as_of=self._as_of,
                purpose=self._purpose,
                limit=ANCHOR_CANDIDATE_LIMIT,
                include_relationships=False,
            )
            try:
                secured = await self._gateway.materialize(
                    definition, projection_request=self._request
                )
            except (PermissionError, ValueError):
                return AnchorBinding(mention_id, AnchorOutcome.UNAVAILABLE)
            complete = complete and secured.receipt.complete
            if secured.receipt.source_generation is not None:
                generations.add(secured.receipt.source_generation)
            for record in secured.materialization.graph.objects:
                found[record.id] = None
        generation = next(iter(generations)) if len(generations) == 1 else None
        identities = tuple(found)
        if len(generations) > 1:
            return AnchorBinding(mention_id, AnchorOutcome.INCOMPLETE)
        # An incomplete read can hide a second object with the same text, so it never binds.
        if len(identities) >= ANCHOR_CANDIDATE_LIMIT or not complete:
            return AnchorBinding(
                mention_id,
                AnchorOutcome.INCOMPLETE,
                candidates=identities[: ANCHOR_CANDIDATE_LIMIT - 1],
                source_generation=generation,
            )
        if not identities:
            return AnchorBinding(mention_id, AnchorOutcome.ABSENT, source_generation=generation)
        if len(identities) > 1:
            return AnchorBinding(
                mention_id,
                AnchorOutcome.AMBIGUOUS,
                candidates=identities,
                source_generation=generation,
            )
        return AnchorBinding(
            mention_id,
            AnchorOutcome.BOUND,
            object_id=identities[0],
            source_generation=generation,
        )


__all__ = [
    "ANCHOR_CANDIDATE_LIMIT",
    "AnchorBinding",
    "AnchorBindingReceipt",
    "AnchorOutcome",
    "AnchorResolver",
    "GatewayAnchorResolver",
    "anchor_mentions",
    "bind_anchors",
]

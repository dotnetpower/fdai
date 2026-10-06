"""Two-phase anchor binding: exact identity reads before compilation.

The model quotes a resource as it was written; it does not know whether that
text is a name or a provider identifier. Core reads both properties in one
bounded snapshot, the identifier exactly and the name without regard to case, as
operators type names in any case, and binds the anchor to the single object found,
or reports absence, ambiguity, or incompleteness. One match under incomplete source
coverage binds with its uniqueness unproven, which the answer states, because missing
coverage can hide another object but never the verified one. Two names that differ only in
case are ambiguous and never bind. A quote that touches other characters of
its whitespace-delimited token, such as a particle or a parenthesis, may be the
start or end of a longer name, so every longer exact form within that token is
read too and any match makes the anchor ambiguous. Compiled plans then read the
exact bound identity, never the quoted text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    UnsupportedObjectSetAsOfError,
)
from fdai.shared.ontology.acl import ProjectionRequest

from .semantic_environment_context import resource_group_context
from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_form import FilterRole, MentionDomain, MentionForm

ANCHOR_CANDIDATE_LIMIT = 7
MAX_EXTENSION_CHARS = 16
_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})
_RESOURCE = "Resource"
# The identifier compares exactly; a name compares without regard to case. The exact-case name
# read is pushed to the store, so it still returns its verified match while source coverage is
# incomplete and a case-insensitive scan returns nothing.
_IDENTITY_READS = (
    ("id", ObjectPredicateOperator.EQUALS),
    ("name", ObjectPredicateOperator.EQUALS),
    ("name", ObjectPredicateOperator.EQUALS_IGNORE_CASE),
)


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
    # Why a read left the anchor unbound, as a typed code; never read text.
    reason: str | None = None
    # False when one object matched but incomplete source coverage cannot prove that no
    # other object carries the same text; the answer then states that limitation.
    uniqueness_proven: bool = True
    # The bound Resource's type, read with its identity; it selects reviewed provider paths.
    resource_type: str | None = None


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
                    "reason": item.reason,
                    **({} if item.uniqueness_proven else {"uniqueness_proven": False}),
                    **({"resource_type": item.resource_type} if item.resource_type else {}),
                }
                for item in self.bindings
            ]
        )


class AnchorResolver(Protocol):
    async def resolve(
        self, mention_id: str, text: str, extensions: tuple[str, ...] = ()
    ) -> AnchorBinding: ...


def surface_extensions(utterance: str, start: int, end: int) -> tuple[str, ...]:
    """Return every longer form of the quote inside its whitespace-delimited token.

    This inspects only character positions around the model's quote; it attaches no
    meaning to them. The resolver reads each form as an exact name.
    """

    token_start = start
    while (
        token_start > 0
        and not utterance[token_start - 1].isspace()
        and start - token_start < MAX_EXTENSION_CHARS
    ):
        token_start -= 1
    token_end = end
    while (
        token_end < len(utterance)
        and not utterance[token_end].isspace()
        and token_end - end < MAX_EXTENSION_CHARS
    ):
        token_end += 1
    forms = [
        utterance[left:right]
        for left in range(token_start, start + 1)
        for right in range(end, token_end + 1)
    ]
    return tuple(dict.fromkeys(form for form in forms if form != utterance[start:end]))


def anchor_mentions(admission: FormAdmission) -> tuple[str, ...]:
    """Return every instance mention that a goal uses as an anchor or a scope."""

    form = admission.form
    cited: list[str] = []
    for goal in form.goals:
        cited.extend(item.mention for item in goal.filters if item.role is FilterRole.SCOPE)
        if goal.relation is not None and goal.relation.anchor is not None:
            cited.append(goal.relation.anchor)
        if goal.counterpart is not None:
            cited.append(goal.counterpart)
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
    *,
    utterance: str | None = None,
) -> AnchorBindingReceipt:
    """Bind every anchor mention, or mark it unavailable without a resolver."""

    bindings = []
    for mention_id in anchor_mentions(admission):
        if resolver is None:
            bindings.append(AnchorBinding(mention_id, AnchorOutcome.UNAVAILABLE))
            continue
        span = admission.form.mention(mention_id).span
        extensions = (
            surface_extensions(utterance, span.start, span.end) if utterance is not None else ()
        )
        bindings.append(
            await resolver.resolve(mention_id, admission.mention_text[mention_id], extensions)
        )
    return AnchorBindingReceipt(tuple(bindings))


class GatewayAnchorResolver:
    """Resolve anchors through bounded secured reads of each identity property."""

    def __init__(
        self,
        gateway: SecuredObjectSetQueryGateway,
        *,
        projection_request: ProjectionRequest,
        purpose: str,
        as_of: datetime | Callable[[], datetime],
    ) -> None:
        """Bind reads to ``as_of``; a clock reads the current cutoff at each read.

        A live gateway accepts only an ``as_of`` within seconds of its own cutoff, so a
        resolver used after slow model calls passes the gateway's clock rather than a
        time captured before them.
        """

        self._gateway = gateway
        self._request = projection_request
        self._purpose = purpose
        self._as_of = as_of

    async def environment_context(self) -> dict[str, Any] | None:
        """Read the principal's resource groups as model context, under the same scope."""

        return await resource_group_context(
            self._gateway,
            projection_request=self._request,
            purpose=self._purpose,
            as_of=self._as_of,
        )

    async def resolve(
        self, mention_id: str, text: str, extensions: tuple[str, ...] = ()
    ) -> AnchorBinding:
        found: dict[str, str | None] = {}
        longer: set[str] = set()
        source_complete = True
        truncated = False
        generations: set[str] = set()
        reads = [
            ObjectPredicate(property=property_name, operator=operator, equals=text)
            for property_name, operator in _IDENTITY_READS
        ]
        if extensions:
            try:
                reads.append(
                    ObjectPredicate(
                        property="name", operator=ObjectPredicateOperator.IN, values=extensions
                    )
                )
            except ValueError:
                # Too many longer forms to read exactly, so the quote's boundary stays unproven.
                return AnchorBinding(
                    mention_id, AnchorOutcome.INCOMPLETE, reason="extensions_unread"
                )
        for predicate in reads:
            definition = ObjectSetDefinition(
                selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=_RESOURCE),
                predicates=(predicate,),
                as_of=self._as_of() if callable(self._as_of) else self._as_of,
                purpose=self._purpose,
                limit=ANCHOR_CANDIDATE_LIMIT,
                include_relationships=False,
            )
            try:
                secured = await self._gateway.materialize(
                    definition, projection_request=self._request
                )
            except UnsupportedObjectSetAsOfError:
                return AnchorBinding(mention_id, AnchorOutcome.UNAVAILABLE, reason="as_of_stale")
            except Exception as exc:  # noqa: BLE001 - any failed read leaves the anchor unbound
                reason = f"anchor_read_failed:{type(exc).__name__}"
                return AnchorBinding(mention_id, AnchorOutcome.UNAVAILABLE, reason=reason)
            source_complete = source_complete and secured.receipt.source_complete
            truncated = truncated or secured.receipt.truncated
            if secured.receipt.source_generation is not None:
                generations.add(secured.receipt.source_generation)
            for record in secured.materialization.graph.objects:
                kind = record.properties.get("type")
                found[record.id] = kind if isinstance(kind, str) else None
            if predicate.operator is ObjectPredicateOperator.IN:
                longer = {record.id for record in secured.materialization.graph.objects}
        generation = next(iter(generations)) if len(generations) == 1 else None
        # Sorted identities keep the receipt digest independent of store return order.
        identities = tuple(sorted(found))
        if len(generations) > 1:
            return AnchorBinding(mention_id, AnchorOutcome.INCOMPLETE, reason="generation_changed")
        # A read cut at its bound can hide a second object with the same text, and missing
        # source coverage never proves absence, so neither binds nor reports absence.
        if (
            truncated
            or len(identities) >= ANCHOR_CANDIDATE_LIMIT
            or not (identities or source_complete)
        ):
            return AnchorBinding(
                mention_id,
                AnchorOutcome.INCOMPLETE,
                candidates=identities[: ANCHOR_CANDIDATE_LIMIT - 1],
                source_generation=generation,
                reason="candidate_limit" if identities else "source_incomplete",
            )
        if not identities:
            return AnchorBinding(mention_id, AnchorOutcome.ABSENT, source_generation=generation)
        # A longer exact name in the same token means the quote may have cut that name short.
        if len(identities) > 1 or longer:
            return AnchorBinding(
                mention_id,
                AnchorOutcome.AMBIGUOUS,
                candidates=identities,
                source_generation=generation,
            )
        # One verified positive match binds; under incomplete coverage its uniqueness is
        # unproven, which the answer states instead of claiming no other object exists.
        return AnchorBinding(
            mention_id,
            AnchorOutcome.BOUND,
            object_id=identities[0],
            source_generation=generation,
            uniqueness_proven=source_complete,
            resource_type=found[identities[0]],
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
    "surface_extensions",
]

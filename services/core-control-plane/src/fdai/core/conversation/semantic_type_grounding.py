"""Ground unbound Resource subtype filters by closed choice over the complete catalog.

The judgment copies the operator's subtype words as one source-grounded
``resource_type_filter``. When no reviewed catalog entry states those exact
words, two blind choosers of different model families each see every shard of
the declared Resource.type catalog and choose candidate identifiers. Code accepts
only identifiers the shard presented, requires every candidate to be presented
exactly once, and keeps a binding only where both choosers reach the same values.
An agreed binding is added to this turn's descriptors as candidate evidence for
that exact source span; labels stay context for the choosers and are never
matched by code. Disagreement, a missing chooser, or an exhausted budget leaves
the filter unbound, so the existing clarification applies instead of a guess.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal, SemanticTarget

from .adaptive_call_scope import bind_adaptive_model_budget
from .model_observation import ConversationModelObservation
from .semantic_planning_value_filters import resource_type_filters_are_bound
from .semantic_reasoning_concepts import (
    DEFAULT_SHARD_BYTES,
    ConceptOutcome,
    ConceptRequest,
    ConceptSelectionPlan,
    ConceptSelectionReceipt,
    ConceptShard,
    accept_concept_selection,
    agree_concepts,
    apply_runoff,
    concept_catalogs,
    runoff_requests,
    shard_answer_valid,
    shard_catalog,
)
from .semantic_reasoning_form import MentionDomain, SourceSpan

_LOGGER = logging.getLogger(__name__)
_TYPE_FILTER = "resource_type_filter"
_COLLECTION_INTENTS = frozenset(
    {
        "query.contextual_resources",
        "query.resource_health_inventory",
        "query.resource_state_inventory",
    }
)
_MAX_MENTIONS = 4


class ConceptChooserModel(Protocol):
    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class TypeGroundingResult:
    """Descriptors for the rest of the turn plus content-free accounting."""

    descriptors: tuple[dict[str, Any], ...]
    manifest_descriptors: tuple[dict[str, Any], ...]
    judgment: SemanticJudgmentProposal
    grounded: int = 0
    unresolved: int = 0
    model_calls: int = 0
    observations: tuple[ConversationModelObservation, ...] = ()


class ResourceTypeGrounding:
    """Bind unbound subtype filters where two blind choosers agree on one meaning."""

    def __init__(
        self,
        *,
        chooser: ConceptChooserModel,
        owner_loop: asyncio.AbstractEventLoop,
        timeout_seconds: float = 45.0,
        max_model_calls: int = 16,
        max_shard_bytes: int = DEFAULT_SHARD_BYTES,
    ) -> None:
        if not 0 < timeout_seconds <= 120:
            raise ValueError("type grounding timeout_seconds MUST be in (0, 120]")
        if not 2 <= max_model_calls <= 64:
            raise ValueError("type grounding max_model_calls MUST be in [2, 64]")
        self._chooser = chooser
        self._owner_loop = owner_loop
        self._timeout_seconds = timeout_seconds
        self._max_model_calls = max_model_calls
        self._max_shard_bytes = max_shard_bytes

    def ground(
        self,
        *,
        utterance: str,
        judgment: SemanticJudgmentProposal,
        descriptors: tuple[dict[str, Any], ...],
        manifest_descriptors: tuple[dict[str, Any], ...],
        detached: tuple[SourceSpan, ...] = (),
    ) -> TypeGroundingResult:
        """Return descriptors carrying agreed bindings for every unbound subtype filter.

        ``detached`` spans are named things a blind reader quoted apart from every
        copied span. One that both choosers bind to a specific Resource type is a
        subtype the judgment omitted and becomes its own source-grounded filter.
        """

        unchanged = TypeGroundingResult(descriptors, manifest_descriptors, judgment)
        omitted = {
            utterance[span.start : span.end]: span
            for span in detached
            if judgment.primary_intent in _COLLECTION_INTENTS
        }
        values = tuple(
            dict.fromkeys(
                (
                    *unbound_type_filter_values(
                        judgment, utterance=utterance, descriptors=descriptors
                    ),
                    *omitted,
                )
            )
        )
        if len(values) > _MAX_MENTIONS:
            # A bound never drops a mention silently: the whole grounding is skipped instead.
            _LOGGER.info(
                "semantic_type_grounding_skipped",
                extra={"mention_count": len(values), "reason": "mention_bound"},
            )
            return replace(unchanged, unresolved=len(values))
        if not values:
            return unchanged
        plan = type_selection_plan(values, manifest_descriptors, self._max_shard_bytes)
        if plan is None or 2 * len(plan.requests) > self._max_model_calls:
            _LOGGER.info(
                "semantic_type_grounding_skipped",
                extra={"mention_count": len(values), "reason": "catalog_or_budget"},
            )
            return replace(unchanged, unresolved=len(values))
        collector = _ObservationCollector()
        future = asyncio.run_coroutine_threadsafe(
            _agreed_selection(
                self._chooser, plan, utterance, self._max_model_calls // 2, collector
            ),
            self._owner_loop,
        )
        try:
            receipt = future.result(timeout=self._timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - provider details remain inside the adapter
            future.cancel()
            _LOGGER.warning(
                "semantic_type_grounding_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return replace(
                unchanged, unresolved=len(values), observations=tuple(collector.observations)
            )
        bindings = {
            text: binding.values
            for text, mention_id in zip(values, plan.mention_order, strict=True)
            if (binding := receipt.binding(mention_id)) is not None
            and binding.outcome is ConceptOutcome.ACCEPTED
            and binding.values
        }
        _LOGGER.info(
            "semantic_type_grounding_completed",
            extra={
                "mention_count": len(values),
                "grounded_count": len(bindings),
                "model_calls": receipt.model_calls,
                "receipt_digest": receipt.digest,
            },
        )
        added = tuple(
            SemanticTarget(
                kind=_TYPE_FILTER,
                value=text,
                source_start=omitted[text].start,
                source_end=omitted[text].end,
            )
            for text in bindings
            if text in omitted
        )
        # A phrase a reviewed entry already states needs no turn group; a second group with the
        # same values would make the stated phrase ambiguous.
        injected = {
            text: values
            for text, values in bindings.items()
            if not resource_type_filters_are_bound((text,), descriptors)
        }
        return TypeGroundingResult(
            descriptors=with_grounded_types(descriptors, injected),
            manifest_descriptors=with_grounded_types(manifest_descriptors, injected),
            judgment=(
                judgment.model_copy(update={"targets": (*judgment.targets, *added)})
                if added
                else judgment
            ),
            grounded=len(bindings),
            unresolved=len(values) - len(bindings),
            model_calls=receipt.model_calls,
            observations=tuple(collector.observations),
        )


def unbound_type_filter_values(
    judgment: SemanticJudgmentProposal,
    *,
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return exact source-grounded subtype filter words no reviewed entry states."""

    values = tuple(
        dict.fromkeys(
            target.value
            for target in judgment.targets
            if target.kind == _TYPE_FILTER
            and utterance[target.source_start : target.source_end] == target.value
            and not resource_type_filters_are_bound((target.value,), descriptors)
        )
    )
    return values


def type_selection_plan(
    values: tuple[str, ...],
    descriptors: Sequence[Mapping[str, Any]],
    max_shard_bytes: int,
) -> ConceptSelectionPlan | None:
    """Plan one presentation of every subtype candidate shard for these mentions."""

    catalog = concept_catalogs(descriptors).get(MentionDomain.RESOURCE_TYPE, ())
    if not catalog:
        return None
    try:
        shards = shard_catalog(MentionDomain.RESOURCE_TYPE, catalog, max_bytes=max_shard_bytes)
    except ValueError:
        return None
    mentions = tuple(
        {"mention": f"type-filter-{index}", "text": value} for index, value in enumerate(values)
    )
    return ConceptSelectionPlan(
        requests=tuple(
            ConceptRequest(MentionDomain.RESOURCE_TYPE, mentions, shard) for shard in shards
        ),
        unavailable=(),
        catalog_sizes={MentionDomain.RESOURCE_TYPE: len(catalog)},
        mention_order=tuple(item["mention"] for item in mentions),
    )


def with_grounded_types(
    descriptors: tuple[dict[str, Any], ...],
    bindings: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, Any], ...]:
    """Add one turn-scoped value group per agreed binding to the Resource type domain."""

    if not bindings:
        return descriptors
    grounded: list[dict[str, Any]] = []
    for descriptor in descriptors:
        properties = descriptor.get("properties")
        declaration = properties.get("type") if isinstance(properties, Mapping) else None
        declared = declaration.get("values") if isinstance(declaration, Mapping) else None
        if (
            descriptor.get("kind") != "object"
            or descriptor.get("name") != "Resource"
            or not isinstance(declared, list)
        ):
            grounded.append(descriptor)
            continue
        updated = copy.deepcopy(descriptor)
        type_declaration = updated["properties"]["type"]
        groups = list(type_declaration.get("value_groups") or ())
        for text, values in bindings.items():
            # Only declared values bind; the chooser can name nothing outside the domain.
            members = [value for value in values if value in declared]
            if members:
                groups.append(
                    {
                        "id": f"turn-grounded:{content_digest({'text': text})[7:23]}",
                        "values": members,
                        "terms": [text],
                    }
                )
        type_declaration["value_groups"] = groups
        grounded.append(updated)
    return tuple(grounded)


class _ObservationCollector:
    """Account every chooser call so the turn record shows each model call made."""

    def __init__(self) -> None:
        self.observations: list[ConversationModelObservation] = []

    def reserve(self, input_bytes: int, output_tokens: int, reserved_calls: int) -> int:
        return 0

    def observe(self, reservation: int, observation: ConversationModelObservation) -> None:
        self.observations.append(observation)


async def _agreed_selection(
    chooser: ConceptChooserModel,
    plan: ConceptSelectionPlan,
    utterance: str,
    max_calls: int,
    collector: _ObservationCollector,
) -> ConceptSelectionReceipt:
    async with bind_adaptive_model_budget(collector):
        primary, second = await asyncio.gather(
            _choose_all(chooser, plan, utterance, max_calls, second=False),
            _choose_all(chooser, plan, utterance, max_calls, second=True),
        )
    return agree_concepts(primary, second)


async def _choose_all(
    chooser: ConceptChooserModel,
    plan: ConceptSelectionPlan,
    utterance: str,
    max_calls: int,
    *,
    second: bool,
) -> ConceptSelectionReceipt:
    """Present every shard to one chooser, re-asking once for a malformed answer."""

    async def choose(request: ConceptRequest) -> Mapping[str, Any] | None:
        answer = await chooser.choose_concepts(
            utterance=utterance, mentions=request.mentions, shard=request.shard, second=second
        )
        if not shard_answer_valid(answer, request):
            answer = await chooser.choose_concepts(
                utterance=utterance, mentions=request.mentions, shard=request.shard, second=second
            )
        return answer

    answers = await asyncio.gather(*(choose(request) for request in plan.requests))
    receipt = accept_concept_selection(plan, answers)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_calls:
        return receipt
    runoff_answers = await asyncio.gather(*(choose(request) for request in runoff))
    return apply_runoff(receipt, runoff, runoff_answers)


__all__ = [
    "ConceptChooserModel",
    "ResourceTypeGrounding",
    "TypeGroundingResult",
    "type_selection_plan",
    "unbound_type_filter_values",
    "with_grounded_types",
]

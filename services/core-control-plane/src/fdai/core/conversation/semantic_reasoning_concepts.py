"""Concept selection over complete, sharded manifest catalogs.

Core presents every candidate of a mention's domain in bounded shards, and the
model chooses canonical candidate identifiers inside each shard. Labels are
context for the model and are never matched by code. Core accepts a choice only
when the presented shard contains it and a shard receipt proves that every
candidate was presented exactly once.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import ReviewedPropertyRead
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_MEASURE_CONCEPTS,
)

from .semantic_reasoning_admission import AdmissionDisposition, FormAdmission
from .semantic_reasoning_form import MentionDomain, MentionForm
from .semantic_reasoning_lifecycle import lifecycle_values

DEFAULT_SHARD_BYTES = 12 * 1024
_DECLARATION_KINDS = ("action", "function", "interface", "link", "object")
# Every non-referential mention of a catalog domain grounds; references bind to handles.
_CONCEPT_FORMS = frozenset(
    {MentionForm.CONCEPT, MentionForm.VALUE, MentionForm.NAME, MentionForm.IDENTIFIER}
)
_ANY_RESOURCE = "any:resource"
_RESOURCE_OBJECT_TYPE = "Resource"


class ConceptOutcome(StrEnum):
    ACCEPTED = "accepted"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConceptCandidate:
    """One canonical candidate; ``values`` are the exact identities it binds."""

    id: str
    values: tuple[str, ...]
    labels: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "values": list(self.values), "labels": list(self.labels)}


@dataclass(frozen=True, slots=True)
class ConceptShard:
    domain: MentionDomain
    index: int
    total: int
    candidates: tuple[ConceptCandidate, ...]
    catalog_digest: str

    @property
    def digest(self) -> str:
        return content_digest(self.payload())

    def payload(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "index": self.index,
            "total": self.total,
            "catalog_digest": self.catalog_digest,
            "candidates": [candidate.payload() for candidate in self.candidates],
        }

    def prompt_payload(self) -> dict[str, Any]:
        """Encode every candidate with a shard-local opaque choice reference."""

        return {
            "domain": self.domain.value,
            "index": self.index,
            "total": self.total,
            "catalog_digest": self.catalog_digest,
            "candidate_id_encoding": "shard_position",
            "candidate_columns": ["id", "values", "labels"],
            "candidates": [
                [f"c{index}", list(candidate.values), list(candidate.labels)]
                for index, candidate in enumerate(self.candidates)
            ],
        }


@dataclass(frozen=True, slots=True)
class ConceptBinding:
    mention_id: str
    domain: MentionDomain
    outcome: ConceptOutcome
    candidate_ids: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConceptSelectionReceipt:
    """Bindings plus proof that each domain catalog was presented completely."""

    bindings: tuple[ConceptBinding, ...]
    presented: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    model_calls: int = 0

    def binding(self, mention_id: str) -> ConceptBinding | None:
        return next((item for item in self.bindings if item.mention_id == mention_id), None)

    @property
    def digest(self) -> str:
        return content_digest(
            {
                "bindings": [
                    {
                        "mention": item.mention_id,
                        "domain": item.domain.value,
                        "outcome": item.outcome.value,
                        "candidates": list(item.candidate_ids),
                        "values": list(item.values),
                    }
                    for item in self.bindings
                ],
                "presented": {key: list(value) for key, value in sorted(self.presented.items())},
            }
        )


ConceptChooser = Callable[[str, tuple[dict[str, Any], ...], ConceptShard], Mapping[str, Any] | None]


def concept_catalogs(
    descriptors: Sequence[Mapping[str, Any]],
    *,
    object_labels: Mapping[str, str] | None = None,
    metric_labels: Mapping[str, str] | None = None,
    health_labels: Mapping[str, Sequence[str]] | None = None,
    property_reads: Sequence[ReviewedPropertyRead] = (),
) -> dict[MentionDomain, tuple[ConceptCandidate, ...]]:
    """Return complete candidate catalogs for the domains the manifest declares.

    ``object_labels`` holds reviewed ObjectType descriptions; each follows its name as a
    label, so a chooser can tell Resource from ResourceType by meaning. ``metric_labels``
    holds the reviewed metric concepts the bound metric reader accepts, each with its
    reviewed description. ``health_labels`` holds the reviewed Resource Health concepts the
    bound health reader accepts, each with the provider states it groups. ``property_reads``
    holds the reviewed Property semantics a property measure may read. A label is context
    for the chooser, never a lookup key.
    """

    described = object_labels or {}
    catalogs: dict[MentionDomain, tuple[ConceptCandidate, ...]] = {}
    objects = sorted(
        str(item["name"])
        for item in descriptors
        if item.get("kind") == "object" and item.get("name")
    )
    catalogs[MentionDomain.OBJECT_TYPE] = tuple(
        ConceptCandidate(
            id=f"object:{name}",
            values=(name,),
            labels=(name, described[name]) if described.get(name) else (name,),
        )
        for name in objects
    )
    if metric_labels:
        catalogs[MentionDomain.METRIC] = tuple(
            ConceptCandidate(f"metric:{concept}", (concept,), (concept, description))
            for concept, description in sorted(metric_labels.items())
        )
    if health_labels:
        catalogs[MentionDomain.HEALTH] = tuple(
            ConceptCandidate(f"health:{concept}", (concept,), (concept, *states))
            for concept, states in sorted(health_labels.items())
        )
    kinds = sorted({str(item.get("kind")) for item in descriptors} & set(_DECLARATION_KINDS))
    catalogs[MentionDomain.DECLARATION_KIND] = tuple(
        ConceptCandidate(id=f"kind:{kind}", values=(kind,), labels=(kind,)) for kind in kinds
    )
    resource_types = _resource_type_candidates(descriptors)
    if resource_types:
        # Reviewed type groups are the resource classes a mention can bind today.
        catalogs[MentionDomain.RESOURCE_TYPE] = resource_types
        catalogs[MentionDomain.RESOURCE_CLASS] = resource_types
    states = (*_state_candidates(descriptors), *_lifecycle_candidates(descriptors))
    if states:
        catalogs[MentionDomain.STATE] = states
    regions = _region_candidates(descriptors)
    if regions:
        catalogs[MentionDomain.REGION] = regions
    properties = _property_candidates(descriptors, property_reads)
    if properties:
        catalogs[MentionDomain.PROPERTY] = properties
    return catalogs


def _property_candidates(
    descriptors: Sequence[Mapping[str, Any]], reads: Sequence[ReviewedPropertyRead]
) -> tuple[ConceptCandidate, ...]:
    """Return the readable Resource properties with a declared domain or reviewed semantic."""

    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == _RESOURCE_OBJECT_TYPE
        ),
        None,
    )
    properties = resource.get("properties") if isinstance(resource, Mapping) else None
    if not isinstance(properties, Mapping):
        return ()
    declared = tuple(
        ConceptCandidate(
            f"property:{_RESOURCE_OBJECT_TYPE}.{name}",
            (f"{_RESOURCE_OBJECT_TYPE}.{name}",),
            (name,),
        )
        for name, domain in sorted(properties.items())
        if isinstance(domain, Mapping) and isinstance(domain.get("values"), list)
    )
    reviewed = tuple(
        ConceptCandidate(
            f"property:{read.semantic_id}",
            (read.semantic_id,),
            (
                read.semantic_id,
                *((read.unit,) if read.unit else ()),
                *(f"{kind}.{path}" for kind, path in read.paths),
            ),
        )
        for read in sorted(reads, key=lambda item: item.semantic_id)
    )
    return (*declared, *reviewed)


def _region_candidates(descriptors: Sequence[Mapping[str, Any]]) -> tuple[ConceptCandidate, ...]:
    """Return every reviewed region code of `Resource.location`, labeled by its name."""

    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == _RESOURCE_OBJECT_TYPE
        ),
        None,
    )
    properties = resource.get("properties") if isinstance(resource, Mapping) else None
    domain = properties.get("location") if isinstance(properties, Mapping) else None
    if not isinstance(domain, Mapping) or not isinstance(domain.get("values"), list):
        return ()
    names = {
        str(group["id"]): tuple(str(term) for term in group.get("terms") or ())
        for group in domain.get("value_groups") or ()
        if isinstance(group, Mapping) and isinstance(group.get("id"), str)
    }
    return tuple(
        ConceptCandidate(f"region:{value}", (str(value),), (str(value), *names.get(str(value), ())))
        for value in sorted(str(item) for item in domain["values"])
    )


def _state_candidates(descriptors: Sequence[Mapping[str, Any]]) -> tuple[ConceptCandidate, ...]:
    """Return the reviewed state concepts the declared state inventory function can filter."""

    function = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "function" and item.get("name") == RESOURCE_STATE_FUNCTION_NAME
        ),
        None,
    )
    schema = function.get("output_schema") if isinstance(function, Mapping) else None
    if not isinstance(schema, Mapping) or not isinstance(
        schema.get("x-fdai-measure-concepts"), list
    ):
        return ()
    declared = set(schema["x-fdai-measure-concepts"]) & set(RESOURCE_STATE_MEASURE_CONCEPTS)
    labels: dict[str, tuple[str, ...]] = {}
    for group in schema.get("x-fdai-measure-value-groups") or ():
        if isinstance(group, Mapping) and group.get("concept") in declared:
            terms = tuple(str(item) for item in group.get("terms") or () if str(item).strip())
            labels[str(group["concept"])] = terms
    return tuple(
        ConceptCandidate(f"state:{concept}", (concept,), labels.get(concept) or (concept,))
        for concept in sorted(declared)
    )


def _lifecycle_candidates(
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[ConceptCandidate, ...]:
    """Return each reviewed lifecycle value of an ObjectType, labeled with its type."""

    return tuple(
        ConceptCandidate(
            f"state:{item.concept}",
            (item.concept,),
            (item.value, f"{item.object_type} {item.property_name}"),
        )
        for item in lifecycle_values(descriptors)
    )


def shard_catalog(
    domain: MentionDomain,
    candidates: tuple[ConceptCandidate, ...],
    *,
    max_bytes: int = DEFAULT_SHARD_BYTES,
) -> tuple[ConceptShard, ...]:
    """Split one catalog into ordered shards that each fit the byte budget."""

    if max_bytes < 256:
        raise ValueError("concept shard budget MUST be at least 256 bytes")
    catalog_digest = content_digest([candidate.payload() for candidate in candidates])
    groups: list[list[ConceptCandidate]] = [[]]
    overhead = len(
        json.dumps(
            ConceptShard(
                domain, len(candidates), len(candidates), (), catalog_digest
            ).prompt_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    used = overhead
    for candidate in candidates:
        size = (
            len(
                json.dumps(
                    [f"c{len(candidates)}", list(candidate.values), list(candidate.labels)],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            + 1
        )
        if overhead + size > max_bytes:
            raise ValueError(f"concept candidate {candidate.id} exceeds the shard budget")
        if groups[-1] and used + size > max_bytes:
            groups.append([])
            used = overhead
        groups[-1].append(candidate)
        used += size
    total = len(groups)
    return tuple(
        ConceptShard(domain, index, total, tuple(group), catalog_digest)
        for index, group in enumerate(groups)
    )


@dataclass(frozen=True, slots=True)
class ConceptRequest:
    """One shard presentation: every mention of one domain against one shard."""

    domain: MentionDomain
    mentions: tuple[dict[str, Any], ...]
    shard: ConceptShard


@dataclass(frozen=True, slots=True)
class ConceptSelectionPlan:
    """Every shard request a form needs, planned before any model call."""

    requests: tuple[ConceptRequest, ...]
    unavailable: tuple[ConceptBinding, ...]
    catalog_sizes: Mapping[MentionDomain, int]
    mention_order: tuple[str, ...]


def plan_concept_selection(
    admission: FormAdmission,
    *,
    catalogs: Mapping[MentionDomain, tuple[ConceptCandidate, ...]],
    max_model_calls: int,
    max_shard_bytes: int = DEFAULT_SHARD_BYTES,
) -> ConceptSelectionPlan:
    """Plan complete shard presentations within the reserved call budget."""

    if admission.disposition is not AdmissionDisposition.ADMITTED:
        raise ValueError("concept selection requires an admitted form")
    by_domain: dict[MentionDomain, list[dict[str, Any]]] = {}
    unavailable: list[ConceptBinding] = []
    for mention in admission.form.mentions:
        if mention.form not in _CONCEPT_FORMS or mention.domain is MentionDomain.INSTANCE:
            continue
        if mention.domain not in catalogs:
            unavailable.append(
                ConceptBinding(
                    mention.id,
                    mention.domain,
                    ConceptOutcome.UNAVAILABLE,
                    reason=f"concept_domain_unavailable:{mention.domain.value}",
                )
            )
            continue
        by_domain.setdefault(mention.domain, []).append(
            {"mention": mention.id, "text": admission.mention_text[mention.id]}
        )
    requests: list[ConceptRequest] = []
    for domain in sorted(by_domain, key=lambda item: item.value):
        mentions = tuple(by_domain[domain])
        try:
            shards = shard_catalog(domain, catalogs[domain], max_bytes=max_shard_bytes)
        except ValueError:
            shards = ()
        if not shards or len(requests) + len(shards) > max_model_calls:
            reason = (
                "concept_catalog_unshardable"
                if not shards
                else "concept_selection_budget_exhausted"
            )
            unavailable.extend(
                ConceptBinding(item["mention"], domain, ConceptOutcome.UNAVAILABLE, reason=reason)
                for item in mentions
            )
            continue
        requests.extend(ConceptRequest(domain, mentions, shard) for shard in shards)
    return ConceptSelectionPlan(
        requests=tuple(requests),
        unavailable=tuple(unavailable),
        catalog_sizes={domain: len(catalogs[domain]) for domain in by_domain},
        mention_order=tuple(mention.id for mention in admission.form.mentions),
    )


def accept_concept_selection(
    plan: ConceptSelectionPlan,
    answers: Sequence[Mapping[str, Any] | None],
) -> ConceptSelectionReceipt:
    """Accept only choices that name candidates of the shard each answer covers."""

    if len(answers) != len(plan.requests):
        raise ValueError("concept selection answers MUST cover every planned shard")
    bindings = list(plan.unavailable)
    presented: dict[str, tuple[int, int]] = {}
    domains = sorted({request.domain for request in plan.requests}, key=lambda item: item.value)
    for domain in domains:
        indexed = [
            (request, answer)
            for request, answer in zip(plan.requests, answers, strict=True)
            if request.domain is domain
        ]
        mentions = indexed[0][0].mentions
        chosen: dict[str, list[ConceptCandidate]] = {item["mention"]: [] for item in mentions}
        presented_count = 0
        failed = False
        for request, answer in indexed:
            accepted = _accepted_choices(answer, shard=request.shard, mentions=mentions)
            if accepted is None:
                failed = True
                continue
            presented_count += len(request.shard.candidates)
            for mention_id, candidates in accepted.items():
                chosen[mention_id].extend(candidates)
        total = plan.catalog_sizes[domain]
        presented[domain.value] = (presented_count, total)
        failed = failed or presented_count != total
        for item in mentions:
            mention_id = item["mention"]
            bindings.append(
                ConceptBinding(
                    mention_id,
                    domain,
                    ConceptOutcome.UNAVAILABLE,
                    reason="concept_selection_invalid",
                )
                if failed
                else _binding(mention_id, domain, chosen[mention_id])
            )
    order = {mention_id: index for index, mention_id in enumerate(plan.mention_order)}
    return ConceptSelectionReceipt(
        bindings=tuple(sorted(bindings, key=lambda item: order[item.mention_id])),
        presented=presented,
        model_calls=len(plan.requests),
    )


def runoff_requests(
    plan: ConceptSelectionPlan,
    receipt: ConceptSelectionReceipt,
) -> tuple[ConceptRequest, ...]:
    """Present the finalists of every mention that stayed ambiguous across shards.

    Shards are judged independently, so a mention can match a broad group in one
    shard and an exact type in another. One runoff call per domain shows only
    those finalists together, and the model chooses among them.
    """

    candidates = {
        candidate.id: candidate
        for request in plan.requests
        for candidate in request.shard.candidates
    }
    by_domain: dict[MentionDomain, list[ConceptBinding]] = {}
    for binding in receipt.bindings:
        if binding.outcome is ConceptOutcome.AMBIGUOUS:
            by_domain.setdefault(binding.domain, []).append(binding)
    requests: list[ConceptRequest] = []
    for domain in sorted(by_domain, key=lambda item: item.value):
        bindings = by_domain[domain]
        finalist_ids = sorted({item for binding in bindings for item in binding.candidate_ids})
        finalists = tuple(candidates[item] for item in finalist_ids if item in candidates)
        mention_ids = {binding.mention_id for binding in bindings}
        mentions = tuple(
            item
            for request in plan.requests
            if request.domain is domain
            for item in request.mentions
            if item["mention"] in mention_ids
        )
        unique_mentions = tuple({item["mention"]: item for item in mentions}.values())
        digest = content_digest([candidate.payload() for candidate in finalists])
        requests.append(
            ConceptRequest(domain, unique_mentions, ConceptShard(domain, 0, 1, finalists, digest))
        )
    return tuple(requests)


def apply_runoff(
    receipt: ConceptSelectionReceipt,
    requests: Sequence[ConceptRequest],
    answers: Sequence[Mapping[str, Any] | None],
) -> ConceptSelectionReceipt:
    """Replace ambiguous bindings whose runoff answer names exactly one meaning."""

    if len(requests) != len(answers):
        raise ValueError("concept runoff answers MUST cover every runoff request")
    resolved: dict[str, ConceptBinding] = {}
    for request, answer in zip(requests, answers, strict=True):
        accepted = _accepted_choices(answer, shard=request.shard, mentions=request.mentions)
        if accepted is None:
            continue
        for mention_id, chosen in accepted.items():
            prior = receipt.binding(mention_id)
            # A runoff only narrows a mention's own finalists; another mention's cannot bind.
            if prior is None or not {item.id for item in chosen} <= set(prior.candidate_ids):
                continue
            binding = _binding(mention_id, request.domain, chosen)
            if binding.outcome is ConceptOutcome.ACCEPTED:
                resolved[mention_id] = binding
    return ConceptSelectionReceipt(
        bindings=tuple(resolved.get(item.mention_id, item) for item in receipt.bindings),
        presented=receipt.presented,
        model_calls=receipt.model_calls + len(requests),
    )


def agree_concepts(
    primary: ConceptSelectionReceipt, second: ConceptSelectionReceipt
) -> ConceptSelectionReceipt:
    """Keep each binding on which two blind choosers agree, and clarify every other.

    Agreement compares the values a binding would hand to a plan, so two readers that
    reach one type through a group and through its value still agree. A missing,
    different, or one-sided answer, including one chooser's general resources against
    the other's exact type, becomes an ambiguity that clarifies instead of binding.
    """

    bindings: list[ConceptBinding] = []
    for binding in primary.bindings:
        other = second.binding(binding.mention_id)
        agreed = other is not None and other.outcome is binding.outcome
        if agreed and binding.outcome is ConceptOutcome.ACCEPTED:
            agreed = other is not None and set(other.values) == set(binding.values)
        if agreed:
            bindings.append(binding)
            continue
        candidates = (*binding.candidate_ids, *(other.candidate_ids if other else ()))
        bindings.append(
            ConceptBinding(
                binding.mention_id,
                binding.domain,
                ConceptOutcome.AMBIGUOUS,
                candidate_ids=tuple(dict.fromkeys(candidates)),
                reason=f"concept_disagreement:{binding.domain.value}",
            )
        )
    return ConceptSelectionReceipt(
        bindings=tuple(bindings),
        presented=primary.presented,
        model_calls=primary.model_calls + second.model_calls,
    )


def select_concepts(
    admission: FormAdmission,
    *,
    catalogs: Mapping[MentionDomain, tuple[ConceptCandidate, ...]],
    choose: ConceptChooser,
    utterance: str,
    max_model_calls: int,
    max_shard_bytes: int = DEFAULT_SHARD_BYTES,
) -> ConceptSelectionReceipt:
    """Ground every concept mention by presenting its complete domain catalog."""

    plan = plan_concept_selection(
        admission,
        catalogs=catalogs,
        max_model_calls=max_model_calls,
        max_shard_bytes=max_shard_bytes,
    )
    answers = [choose(utterance, request.mentions, request.shard) for request in plan.requests]
    receipt = accept_concept_selection(plan, answers)
    runoff = runoff_requests(plan, receipt)
    if not runoff or receipt.model_calls + len(runoff) > max_model_calls:
        return receipt
    return apply_runoff(
        receipt,
        runoff,
        [choose(utterance, request.mentions, request.shard) for request in runoff],
    )


def shard_answer_valid(answer: Mapping[str, Any] | None, request: ConceptRequest) -> bool:
    """Return whether one shard answer is well formed for its exact request."""

    return _accepted_choices(answer, shard=request.shard, mentions=request.mentions) is not None


def _accepted_choices(
    proposal: Mapping[str, Any] | None,
    *,
    shard: ConceptShard,
    mentions: tuple[dict[str, Any], ...],
) -> dict[str, list[ConceptCandidate]] | None:
    if not isinstance(proposal, Mapping) or proposal.get("shard_digest") != shard.digest:
        return None
    raw_choices = proposal.get("choices")
    if not isinstance(raw_choices, list):
        return None
    expected = {item["mention"] for item in mentions}
    index = {candidate.id: candidate for candidate in shard.candidates}
    accepted: dict[str, list[ConceptCandidate]] = {}
    for raw in raw_choices:
        if not isinstance(raw, Mapping):
            return None
        mention_id = raw.get("mention")
        candidate_ids = raw.get("candidate_ids")
        if not isinstance(mention_id, str) or mention_id not in expected or mention_id in accepted:
            return None
        if not isinstance(candidate_ids, list) or len(candidate_ids) > len(shard.candidates):
            return None
        if any(not isinstance(item, str) or item not in index for item in candidate_ids):
            return None
        if len(candidate_ids) != len(set(candidate_ids)):
            return None
        accepted[str(mention_id)] = [index[item] for item in candidate_ids]
    if set(accepted) != expected:
        return None
    return accepted


def _binding(
    mention_id: str,
    domain: MentionDomain,
    candidates: list[ConceptCandidate],
) -> ConceptBinding:
    distinct: dict[tuple[str, ...], list[ConceptCandidate]] = {}
    for candidate in candidates:
        distinct.setdefault(tuple(sorted(candidate.values)), []).append(candidate)
    ids = tuple(sorted(candidate.id for candidate in candidates))
    if not distinct:
        return ConceptBinding(
            mention_id, domain, ConceptOutcome.NOT_FOUND, reason=f"concept_not_found:{domain.value}"
        )
    if len(distinct) > 1:
        return ConceptBinding(
            mention_id,
            domain,
            ConceptOutcome.AMBIGUOUS,
            candidate_ids=ids,
            reason=f"concept_ambiguous:{domain.value}",
        )
    values = next(iter(distinct))
    return ConceptBinding(mention_id, domain, ConceptOutcome.ACCEPTED, ids, values)


def _resource_type_candidates(
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[ConceptCandidate, ...]:
    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == _RESOURCE_OBJECT_TYPE
        ),
        None,
    )
    properties = resource.get("properties") if isinstance(resource, Mapping) else None
    domain = properties.get("type") if isinstance(properties, Mapping) else None
    if not isinstance(domain, Mapping) or not isinstance(domain.get("values"), list):
        return ()
    values = sorted(str(item) for item in domain["values"])
    candidates: list[ConceptCandidate] = []
    for group in domain.get("value_groups") or ():
        if not isinstance(group, Mapping) or not isinstance(group.get("id"), str):
            continue
        members = tuple(sorted(str(item) for item in group.get("values") or () if item in values))
        if not members:
            continue
        labels = tuple(str(item) for item in group.get("terms") or ())
        candidates.append(ConceptCandidate(f"group:{group['id']}", members, labels))
    # Every declared value stays selectable on its own, even when it only appears inside a
    # broader group, so the model is never forced to pick a superset.
    exact = {candidate.values[0] for candidate in candidates if len(candidate.values) == 1}
    candidates.extend(
        ConceptCandidate(f"value:{value}", (value,), (value,))
        for value in values
        if value not in exact
    )
    # The unrestricted root: the operator named resources in general, not one kind.
    candidates.append(
        ConceptCandidate(
            _ANY_RESOURCE,
            (),
            ("any resource type", "resources in general", "모든 종류의 리소스", "리소스 전체"),
        )
    )
    return tuple(sorted(candidates, key=lambda item: item.id))


__all__ = [
    "DEFAULT_SHARD_BYTES",
    "ConceptBinding",
    "ConceptCandidate",
    "ConceptChooser",
    "ConceptOutcome",
    "ConceptRequest",
    "ConceptSelectionPlan",
    "ConceptSelectionReceipt",
    "ConceptShard",
    "accept_concept_selection",
    "agree_concepts",
    "apply_runoff",
    "concept_catalogs",
    "plan_concept_selection",
    "runoff_requests",
    "select_concepts",
    "shard_answer_valid",
    "shard_catalog",
]

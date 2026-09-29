"""Ground a kind mention in the sibling kind catalog when its stated catalog fails.

The proposer labels each kind of thing as an ontology ObjectType or as a cloud resource
type, and live runs show it confusing the two in both directions, with the choice
flipping under unrelated prompt wording. Every concept mention is still grounded first in
the catalog of the domain the proposer stated. Only an eligible mention whose stated
lane failed is presented in the sibling lane: a concept that every citing goal uses as
an instance-level collection subject, where both kinds compile, and that no filter,
relation, measure, or qualifier cites.

- When both choosers found nothing in the stated lane and agree on one meaning in the
  sibling lane, the mention takes the sibling domain and that meaning.
- When the stated lane was contested and the sibling lane agrees on one meaning, both
  choosers see the contested finalists beside that meaning once, and the mention binds
  only when both choose the same meaning, whose lane sets its domain.
- Anything else keeps the stated lane's outcome, which clarifies.

A mention's domain and binding change together, and the retyped form is admitted again,
so every later stage reads one grounded form; a retyped form that fails admission keeps
the stated outcome.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from pydantic import ValidationError

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    FormAdmission,
    SpanAccounting,
    admit_question_form,
)
from .semantic_reasoning_concepts import (
    ConceptBinding,
    ConceptCandidate,
    ConceptOutcome,
    ConceptRequest,
    ConceptSelectionReceipt,
    ConceptShard,
    shard_answer_valid,
)
from .semantic_reasoning_form import (
    GoalLevel,
    MentionDomain,
    MentionForm,
    SemanticQuestionForm,
    SubjectScope,
)

KIND_SIBLINGS: Mapping[MentionDomain, MentionDomain] = {
    MentionDomain.OBJECT_TYPE: MentionDomain.RESOURCE_TYPE,
    MentionDomain.RESOURCE_TYPE: MentionDomain.OBJECT_TYPE,
    MentionDomain.RESOURCE_CLASS: MentionDomain.OBJECT_TYPE,
}
_FAILED = frozenset({ConceptOutcome.NOT_FOUND, ConceptOutcome.AMBIGUOUS})

LaneSelect = Callable[[FormAdmission, int], Awaitable[ConceptSelectionReceipt]]
LaneChoose = Callable[
    [tuple[dict[str, Any], ...], ConceptShard, bool], Awaitable[Mapping[str, Any] | None]
]


@dataclass(frozen=True, slots=True)
class KindGrounding:
    """The grounded admission and receipt, and the mentions whose kind changed."""

    admission: FormAdmission
    receipt: ConceptSelectionReceipt
    regrounded: tuple[str, ...] = ()


def eligible_kind_mentions(form: SemanticQuestionForm) -> frozenset[str]:
    """Return the kind concepts that both an ObjectType and a resource type could ground.

    Such a mention is only ever an instance-level collection subject: an ObjectType then
    selects its objects and a resource type selects resources of that type. A filter,
    relation end, qualifier, or measure of another mention reads a kind in one way only,
    so any such citation keeps the stated lane.
    """

    elsewhere: set[str] = set()
    for mention in form.mentions:
        if mention.qualifier is not None:
            elsewhere.update((mention.id, mention.qualifier.mention))
    for goal in form.goals:
        elsewhere.update(item.mention for item in goal.filters)
        if goal.relation is not None:
            elsewhere.update(
                item
                for item in (goal.relation.anchor, goal.relation.counterpart)
                if item is not None
            )
        # Counting a goal's own subject reads no kind of its own.
        if goal.measure is not None and goal.measure.mention not in (None, goal.subject):
            elsewhere.add(str(goal.measure.mention))
    eligible: set[str] = set()
    for mention in form.mentions:
        if mention.form is not MentionForm.CONCEPT or mention.domain not in KIND_SIBLINGS:
            continue
        uses = [goal for goal in form.goals if goal.subject == mention.id]
        if (
            uses
            and mention.id not in elsewhere
            and all(
                goal.level is GoalLevel.INSTANCE and goal.subject_scope is SubjectScope.COLLECTION
                for goal in uses
            )
        ):
            eligible.add(mention.id)
    return frozenset(eligible)


async def ground_kinds(
    admission: FormAdmission,
    receipt: ConceptSelectionReceipt,
    *,
    catalogs: Mapping[MentionDomain, tuple[ConceptCandidate, ...]],
    utterance: str,
    select: LaneSelect,
    choose: LaneChoose,
    budget: int,
) -> KindGrounding:
    """Try the sibling lane for each eligible kind mention whose stated lane failed."""

    stated = {
        mention_id: binding
        for mention_id in sorted(eligible_kind_mentions(admission.form))
        if (binding := receipt.binding(mention_id)) is not None and binding.outcome in _FAILED
    }
    lane = _retyped(admission, stated, utterance) if stated else None
    if lane is None or budget < 2:
        return KindGrounding(admission, receipt)
    sibling = await select(lane, budget)
    spent = sibling.model_calls
    grounded: dict[str, ConceptBinding] = {}
    runoffs: list[tuple[ConceptBinding, ConceptBinding]] = []
    for mention_id, before in stated.items():
        after = sibling.binding(mention_id)
        if after is None or after.outcome is not ConceptOutcome.ACCEPTED:
            continue
        if before.outcome is ConceptOutcome.NOT_FOUND:
            grounded[mention_id] = after
        else:
            runoffs.append((before, after))
    for before, after in runoffs:
        # Each runoff asks both choosers once, so the turn's concept budget is checked each time.
        if budget - spent < 2:
            break
        chosen, calls = await _cross_lane_runoff(
            before, after, catalogs=catalogs, admission=admission, choose=choose
        )
        spent += calls
        if chosen is not None:
            grounded[before.mention_id] = chosen
    if not grounded:
        return KindGrounding(admission, _spent(receipt, spent))
    final = _retyped(admission, grounded, utterance)
    if final is None:
        return KindGrounding(admission, _spent(receipt, spent))
    bindings = tuple(grounded.get(item.mention_id, item) for item in receipt.bindings)
    presented = {**sibling.presented, **receipt.presented}
    merged = ConceptSelectionReceipt(
        bindings=bindings, presented=presented, model_calls=receipt.model_calls + spent
    )
    changed = tuple(
        mention_id
        for mention_id in sorted(grounded)
        if grounded[mention_id].domain is not admission.form.mention(mention_id).domain
    )
    return KindGrounding(final, merged, changed)


def _retyped(
    admission: FormAdmission, bindings: Mapping[str, ConceptBinding], utterance: str
) -> FormAdmission | None:
    """Return the form admitted again with each mention in its binding's lane.

    A binding still in the stated lane asks for that mention's sibling lane instead.
    """

    domains: dict[str, MentionDomain] = {}
    for mention_id, binding in bindings.items():
        stated = admission.form.mention(mention_id).domain
        if binding.outcome is ConceptOutcome.ACCEPTED:
            domains[mention_id] = binding.domain
        else:
            domains[mention_id] = KIND_SIBLINGS[stated]
    payload = admission.form.model_dump(mode="json")
    for mention in payload["mentions"]:
        if mention["id"] in domains:
            mention["domain"] = domains[mention["id"]].value
    try:
        form = SemanticQuestionForm.model_validate(payload)
    except ValidationError:
        # A longer domain can cross the form's byte budget; the stated outcome then stands.
        return None
    # Accounting reads only spans, which a kind never changes; every structural rule reruns.
    retyped = admit_question_form(
        form, utterance=utterance, accounting=SpanAccounting(required=False)
    )
    return retyped if retyped.disposition is AdmissionDisposition.ADMITTED else None


async def _cross_lane_runoff(
    before: ConceptBinding,
    after: ConceptBinding,
    *,
    catalogs: Mapping[MentionDomain, tuple[ConceptCandidate, ...]],
    admission: FormAdmission,
    choose: LaneChoose,
) -> tuple[ConceptBinding | None, int]:
    """Ask both choosers once to pick between a contested lane and an agreed sibling.

    Return the binding both choose, if any, and the model calls made.
    """

    lanes: dict[str, MentionDomain] = {}
    finalists: list[ConceptCandidate] = []
    for binding in (before, after):
        index = {candidate.id: candidate for candidate in catalogs.get(binding.domain, ())}
        for candidate_id in binding.candidate_ids:
            if candidate_id in index and candidate_id not in lanes:
                lanes[candidate_id] = binding.domain
                finalists.append(index[candidate_id])
    if not any(lane is before.domain for lane in lanes.values()):
        return None, 0
    shard = ConceptShard(
        before.domain,
        0,
        1,
        tuple(finalists),
        content_digest([candidate.payload() for candidate in finalists]),
    )
    mentions = ({"mention": before.mention_id, "text": admission.mention_text[before.mention_id]},)
    request = ConceptRequest(before.domain, mentions, shard)
    answers = await asyncio.gather(
        choose(mentions, shard, False), choose(mentions, shard, True), return_exceptions=True
    )
    meanings = []
    for answer in answers:
        if not isinstance(answer, Mapping) or not shard_answer_valid(answer, request):
            return None, 2
        (choice,) = answer["choices"]
        picked = {
            (lanes[item.id], tuple(sorted(item.values)))
            for item in finalists
            if item.id in choice["candidate_ids"]
        }
        if len(picked) != 1:
            return None, 2
        meanings.append(next(iter(picked)))
    if meanings[0] != meanings[1]:
        return None, 2
    domain, values = meanings[0]
    ids = tuple(
        sorted(
            item.id
            for item in finalists
            if lanes[item.id] is domain and tuple(sorted(item.values)) == values
        )
    )
    return ConceptBinding(before.mention_id, domain, ConceptOutcome.ACCEPTED, ids, values), 2


def _spent(receipt: ConceptSelectionReceipt, calls: int) -> ConceptSelectionReceipt:
    return replace(receipt, model_calls=receipt.model_calls + calls)


__all__ = [
    "KIND_SIBLINGS",
    "KindGrounding",
    "LaneChoose",
    "LaneSelect",
    "eligible_kind_mentions",
    "ground_kinds",
]

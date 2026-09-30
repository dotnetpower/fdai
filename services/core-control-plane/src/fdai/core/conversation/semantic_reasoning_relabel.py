"""Give a repaired form's mentions back the labels of the proposal it repairs.

A repair returns the whole form again, and a model may number its mentions afresh,
for example in the order their words appear. A mention id is a label, not meaning,
so a repair is compared with the proposal only after each earlier mention's id is
given back to the one repaired mention that can be it: the same form and domain over
a span that holds the earlier span. The renaming is a bijection applied to every
reference, so the repaired form states exactly what it stated before. When any
earlier mention has no single such counterpart, the labels stay as the model wrote
them and the repair comparison decides. A mention the repair was asked to split has
no single counterpart by design, so it is left out of the matching.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .semantic_reasoning_form import SemanticQuestionForm

_MAX_MENTION_NUMBER = 99


def relabel_mentions(
    previous: SemanticQuestionForm,
    repaired: SemanticQuestionForm,
    *,
    split: frozenset[str] = frozenset(),
) -> SemanticQuestionForm:
    """Return ``repaired`` with each earlier mention's id restored, when unambiguous.

    ``split`` names earlier mentions the repair replaces with narrower parts; their ids
    are never restored onto a part, so a part keeps the label the model gave it unless
    that label belongs to a restored mention.
    """

    restored: dict[str, str] = {}
    for before in previous.mentions:
        if before.id in split:
            continue
        matches = [
            after.id
            for after in repaired.mentions
            if (after.form, after.domain) == (before.form, before.domain)
            and after.span.start <= before.span.start
            and before.span.end <= after.span.end
        ]
        if len(matches) != 1 or matches[0] in restored:
            return repaired
        restored[matches[0]] = before.id
    if all(old == new for old, new in restored.items()):
        return repaired
    renames = _renames(repaired, restored)
    payload = repaired.model_dump(mode="json")
    for mention in payload["mentions"]:
        mention["id"] = renames[mention["id"]]
        if mention.get("qualifier") is not None:
            _rename(mention["qualifier"], "mention", renames)
    for goal in payload["goals"]:
        _rename(goal, "subject", renames)
        for item in goal.get("filters") or ():
            _rename(item, "mention", renames)
        if goal.get("relation") is not None:
            _rename(goal["relation"], "anchor", renames)
            _rename(goal["relation"], "counterpart", renames)
        if goal.get("measure") is not None:
            _rename(goal["measure"], "mention", renames)
    try:
        return SemanticQuestionForm.model_validate(payload)
    except ValidationError:
        # A longer restored label can cross the form's byte budget; the comparison decides.
        return repaired


def _renames(repaired: SemanticQuestionForm, restored: dict[str, str]) -> dict[str, str]:
    """Extend the restored labels to a bijection over every repaired mention."""

    taken = set(restored.values())
    kept = {
        mention.id
        for mention in repaired.mentions
        if mention.id not in restored and mention.id not in taken
    }
    free = (
        label
        for label in (f"m{number}" for number in range(1, _MAX_MENTION_NUMBER + 1))
        if label not in taken and label not in kept
    )
    renames = dict(restored)
    for mention in repaired.mentions:
        if mention.id in renames:
            continue
        renames[mention.id] = mention.id if mention.id in kept else next(free)
    return renames


def _rename(holder: dict[str, Any], key: str, renames: dict[str, str]) -> None:
    value = holder.get(key)
    if isinstance(value, str):
        holder[key] = renames.get(value, value)


__all__ = ["relabel_mentions"]

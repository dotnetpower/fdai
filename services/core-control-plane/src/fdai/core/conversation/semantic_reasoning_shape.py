"""Content-free shape of one question form for development decision traces.

The shape names each mention and goal only by its form-local id and closed values, so a
trace shows how a question was read, such as a kind stated as a qualifier or a count that
cites a measure mention, without any quoted text or bound identity.
"""

from __future__ import annotations

from .semantic_reasoning_form import SemanticQuestionForm, TimeKind

MAX_SHAPE_TOKENS = 24


def form_shape(form: SemanticQuestionForm) -> tuple[str, ...]:
    """Return closed tokens describing the mentions and goals of one form."""

    tokens: list[str] = []
    for mention in form.mentions:
        tokens.append(f"{mention.id}:{mention.domain.value}:{mention.form.value}")
        if mention.qualifier is not None:
            qualifier = mention.qualifier
            tokens.append(f"qualifier:{mention.id}:{qualifier.mention}:{qualifier.sense.value}")
    for goal in form.goals:
        operation = goal.operation.value
        tokens.append(f"{goal.id}:{goal.level.value}:{operation}:{goal.subject_scope.value}")
        if goal.subject is not None:
            tokens.append(f"subject:{goal.id}:{goal.subject}")
        tokens.extend(f"filter:{goal.id}:{item.role.value}:{item.mention}" for item in goal.filters)
        if goal.measure is not None:
            measure = goal.measure
            tokens.append(f"measure:{goal.id}:{measure.kind.value}:{measure.group_by.value}")
            if measure.mention is not None:
                tokens.append(f"measure_mention:{goal.id}:{measure.mention}")
        if goal.relation is not None:
            relation = goal.relation
            tokens.append(f"relation:{goal.id}:{relation.sense.value}:{relation.scope.value}")
            tokens.append(
                f"roles:{goal.id}:{relation.anchor_role.value}:{relation.result_role.value}"
            )
            if relation.anchor is not None:
                tokens.append(f"anchor:{goal.id}:{relation.anchor}")
        if goal.time.kind is not TimeKind.CURRENT:
            tokens.append(f"time:{goal.id}:{goal.time.kind.value}")
    if form.alternatives:
        tokens.append(f"alternatives:{len(form.alternatives)}")
    if form.unsupported_constraints:
        tokens.append(f"unsupported_constraints:{len(form.unsupported_constraints)}")
    return tuple(tokens[:MAX_SHAPE_TOKENS])


__all__ = ["MAX_SHAPE_TOKENS", "form_shape"]

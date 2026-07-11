"""Shared action semantics for the pantheon.

Pantheon members MUST NOT import each other (agent-pantheon.md 1.1), so a
predicate two agents both need lives here under ``_framework/`` where any
member may reach in. Keeping it in one place is a safety property, not
just DRY: if Heimdall flagged an action irreversible but Forseti did not
raise its approval quorum for the same action, the two would disagree on
how dangerous a mutation is - the exact kind of drift this module
prevents.

The upstream heuristic (``delete`` / ``destroy`` in the ActionType id) is
a **wave-3 placeholder**. The authoritative source is the ActionType
schema's ``irreversible: true`` field (``rule-catalog/action-types/``);
when Forseti loads the real ontology it MUST prefer that flag over this
name heuristic. Until then, both agents share one conservative rule.
"""

from __future__ import annotations

from typing import Final

#: Distinct-approver quorum an irreversible action MUST clear before it
#: executes (agent-pantheon.md rule 4.6: irreversible -> HIL with
#: ``quorum_required >= 2``, no self-approval). Var honors this; Forseti
#: sets it on the verdict and Thor propagates it onto the ActionRun.
IRREVERSIBLE_QUORUM: Final[int] = 2

#: Quorum for an ordinary (reversible) HIL action - a single approver.
DEFAULT_QUORUM: Final[int] = 1


def is_irreversible(action_type_id: str) -> bool:
    """Return ``True`` when the ActionType id denotes a one-way mutation.

    Wave-3 heuristic: an id containing ``delete`` or ``destroy`` is treated
    as irreversible. Superseded by the ActionType schema's ``irreversible``
    flag once the real ontology is loaded.
    """
    lowered = action_type_id.lower()
    return "delete" in lowered or "destroy" in lowered


def quorum_for(action_type_id: str) -> int:
    """Return the approval quorum an action requires.

    :data:`IRREVERSIBLE_QUORUM` for a one-way mutation, else
    :data:`DEFAULT_QUORUM`. This is the single place the two-approver rule
    for irreversible actions is derived, so Forseti (which stamps it on the
    verdict) and any other caller stay in lockstep.
    """
    return IRREVERSIBLE_QUORUM if is_irreversible(action_type_id) else DEFAULT_QUORUM


__all__ = ["IRREVERSIBLE_QUORUM", "DEFAULT_QUORUM", "is_irreversible", "quorum_for"]

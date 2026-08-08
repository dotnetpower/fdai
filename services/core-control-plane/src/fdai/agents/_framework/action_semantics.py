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

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from fdai.shared.contracts.models import OntologyActionType

#: Distinct-approver quorum an irreversible action MUST clear before it
#: executes (agent-pantheon.md rule 4.6: irreversible -> HIL with
#: ``quorum_required >= 2``, no self-approval). Var honors this; Forseti
#: sets it on the verdict and Thor propagates it onto the ActionRun.
IRREVERSIBLE_QUORUM: Final[int] = 2

#: Quorum for an ordinary (reversible) HIL action - a single approver.
DEFAULT_QUORUM: Final[int] = 1


@dataclass(frozen=True, slots=True)
class ActionSemanticsCatalog:
    """Authoritative pantheon safety semantics projected from ActionTypes."""

    irreversible_by_id: dict[str, bool]
    rollback_by_id: dict[str, str]

    @classmethod
    def from_action_types(
        cls,
        action_types: Iterable[OntologyActionType],
    ) -> ActionSemanticsCatalog:
        actions = tuple(action_types)
        return cls(
            irreversible_by_id={action.name: action.irreversible for action in actions},
            rollback_by_id={action.name: action.rollback_contract.value for action in actions},
        )

    def irreversible(self, action_type_id: str) -> bool:
        return self.irreversible_by_id.get(action_type_id, False)

    def rollback_contract(self, action_type_id: str) -> str:
        return self.rollback_by_id.get(action_type_id, "state_forward_only")


#: Verb substrings that denote a one-way (irreversible) mutation. Chosen to
#: err toward safety: including a verb over-flags at most a reversible action
#: (extra approver, harmless friction), while MISSING one under-flags an
#: irreversible action (single-approver HIL clearance - the real hazard).
#: Deliberately excludes ambiguous verbs (``remove`` / ``drop``) that are
#: often reversible (remove-tag, drop-privilege). Superseded by the
#: ActionType schema's ``irreversible`` flag once the real ontology loads.
_IRREVERSIBLE_VERBS: Final[tuple[str, ...]] = (
    "delete",
    "destroy",
    "purge",
    "terminate",
    "decommission",
    "wipe",
)


def is_irreversible(
    action_type_id: str,
    catalog: ActionSemanticsCatalog | None = None,
) -> bool:
    """Return ``True`` when the ActionType id denotes a one-way mutation.

    Wave-3 heuristic: an id containing any :data:`_IRREVERSIBLE_VERBS`
    substring is treated as irreversible. Superseded by the ActionType
    schema's ``irreversible`` flag once the real ontology is loaded.
    """
    if catalog is not None:
        return catalog.irreversible(action_type_id)
    lowered = action_type_id.lower()
    return any(verb in lowered for verb in _IRREVERSIBLE_VERBS)


def quorum_for(
    action_type_id: str,
    catalog: ActionSemanticsCatalog | None = None,
) -> int:
    """Return the approval quorum an action requires.

    :data:`IRREVERSIBLE_QUORUM` for a one-way mutation, else
    :data:`DEFAULT_QUORUM`. This is the single place the two-approver rule
    for irreversible actions is derived, so Forseti (which stamps it on the
    verdict) and any other caller stay in lockstep.
    """
    return IRREVERSIBLE_QUORUM if is_irreversible(action_type_id, catalog) else DEFAULT_QUORUM


def rollback_contract_for(
    action_type_id: str,
    catalog: ActionSemanticsCatalog | None = None,
) -> str:
    """Return the catalog rollback contract or the conservative legacy default."""
    if catalog is None:
        return "state_forward_only"
    return catalog.rollback_contract(action_type_id)


# Terminal ActionRun ``state`` values (Thor's vocabulary) mapped to the
# ``result`` vocabulary the discovery-loop outcome learner scores. Only
# outcome-defining terminal states appear here: intermediate states
# (verdicted / executing / hil_pending) and non-execution terminals
# (rejected / deny_dropped) have no learnable outcome and map to ``None``.
_TERMINAL_OUTCOME: Final[dict[str, str]] = {
    "succeeded": "success",
    "failed": "failure",
    "rolled_back": "rollback",
    "rollback_failed": "failure",
    "reverted": "rollback",
}

#: The canonical learnable-outcome vocabulary produced by
#: :func:`outcome_result`. Saga validates a directly-stamped ``result``
#: against this before republishing, so an audit-entry always carries a
#: canonical value regardless of which producer wrote it.
RESULT_VALUES: Final[frozenset[str]] = frozenset(_TERMINAL_OUTCOME.values())


def outcome_result(state: str) -> str | None:
    """Map a terminal ActionRun ``state`` to a learnable outcome ``result``.

    Returns ``success`` / ``failure`` / ``rollback`` for an outcome-defining
    terminal state, or ``None`` for an intermediate / non-execution state.
    Shared so Saga (which republishes an outcome as an audit-entry) and Norns
    (which scores it) agree on exactly which states count - the same
    single-source safety argument as :func:`is_irreversible`.
    """
    return _TERMINAL_OUTCOME.get(state.lower())


__all__ = [
    "ActionSemanticsCatalog",
    "IRREVERSIBLE_QUORUM",
    "DEFAULT_QUORUM",
    "RESULT_VALUES",
    "is_irreversible",
    "quorum_for",
    "rollback_contract_for",
    "outcome_result",
]

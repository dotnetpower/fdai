"""Governance effect-transition validation across catalog versions."""

from __future__ import annotations

from fdai.rule_catalog.schema.assignment import Assignment
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.governance_catalog import GovernanceCatalog
from fdai.rule_catalog.schema.governance_transitions import validate_catalog_transition
from fdai.rule_catalog.schema.scope import Scope, ScopeLevel

_SCOPE = Scope(level=ScopeLevel.RESOURCE_GROUP, id="rg-a")


def _assign(
    id_: str,
    effect: Effect,
    *,
    rules: set[str] | None = None,
    overrides=None,
    enforcement: Enforcement = Enforcement.DO_NOT_ENFORCE,
) -> Assignment:
    return Assignment(
        id=id_,
        target_rule_ids=frozenset(rules or {"r.x"}),
        scope=_SCOPE,
        effect=effect,
        effect_overrides=overrides or {},
        enforcement=enforcement,
    )


def _cat(*assignments: Assignment) -> GovernanceCatalog:
    return GovernanceCatalog(assignments=tuple(assignments))


def test_no_change_is_clean() -> None:
    a = _assign("a1", Effect.AUDIT)
    assert validate_catalog_transition(previous=_cat(a), current=_cat(a)) == []


def test_new_assignment_at_audit_is_clean() -> None:
    issues = validate_catalog_transition(previous=_cat(), current=_cat(_assign("a1", Effect.AUDIT)))
    assert issues == []


def test_new_assignment_at_enforce_needs_promotion() -> None:
    curr = _cat(_assign("a1", Effect.DENY))
    issues = validate_catalog_transition(previous=_cat(), current=curr)
    assert len(issues) == 1
    assert issues[0].assignment_id == "a1"
    # approving the promotion clears it
    ok = validate_catalog_transition(
        previous=_cat(), current=curr, promotions_approved=frozenset({"a1"})
    )
    assert ok == []


def test_audit_to_deny_needs_promotion() -> None:
    prev = _cat(_assign("a1", Effect.AUDIT))
    curr = _cat(_assign("a1", Effect.DENY))
    assert len(validate_catalog_transition(previous=prev, current=curr)) == 1
    assert (
        validate_catalog_transition(
            previous=prev, current=curr, promotions_approved=frozenset({"a1"})
        )
        == []
    )


def test_disallowed_transition_rejected() -> None:
    # deny -> remediate is not in the table (must demote to audit first)
    prev = _cat(_assign("a1", Effect.DENY))
    curr = _cat(_assign("a1", Effect.REMEDIATE))
    issues = validate_catalog_transition(
        previous=prev, current=curr, promotions_approved=frozenset({"a1"})
    )
    assert len(issues) == 1
    assert "not allowed" in issues[0].message


def test_demotion_always_clean() -> None:
    prev = _cat(_assign("a1", Effect.DENY))
    curr = _cat(_assign("a1", Effect.AUDIT))
    assert validate_catalog_transition(previous=prev, current=curr) == []


def test_removed_assignment_needs_no_check() -> None:
    prev = _cat(_assign("a1", Effect.DENY))
    assert validate_catalog_transition(previous=prev, current=_cat()) == []


def test_per_rule_override_promotion_flagged() -> None:
    # existing assignment stays audit top-level, but a per-rule override raises
    # one rule to deny -> that rule's effective transition needs promotion
    prev = _cat(_assign("a1", Effect.AUDIT, rules={"r.x", "r.y"}))
    curr = _cat(_assign("a1", Effect.AUDIT, rules={"r.x", "r.y"}, overrides={"r.y": Effect.DENY}))
    issues = validate_catalog_transition(previous=prev, current=curr)
    assert len(issues) == 1
    assert issues[0].rule_id == "r.y"
    # approved -> clean
    assert (
        validate_catalog_transition(
            previous=prev, current=curr, promotions_approved=frozenset({"a1"})
        )
        == []
    )


# ---- enforcement activation gate ------------------------------------------

_ENF = Enforcement.ENFORCE
_DNE = Enforcement.DO_NOT_ENFORCE


def test_enforcement_activation_on_deny_needs_promotion() -> None:
    # deny(shadow) -> deny(enforce): the go-live flip must be approved
    prev = _cat(_assign("a1", Effect.DENY, enforcement=_DNE))
    curr = _cat(_assign("a1", Effect.DENY, enforcement=_ENF))
    issues = validate_catalog_transition(previous=prev, current=curr)
    assert len(issues) == 1
    assert issues[0].rule_id == "*"
    assert "enforce" in issues[0].message
    ok = validate_catalog_transition(
        previous=prev, current=curr, promotions_approved=frozenset({"a1"})
    )
    assert ok == []


def test_enforcement_activation_on_audit_is_inert() -> None:
    # audit never acts, so flipping its enforcement flag is not gated
    prev = _cat(_assign("a1", Effect.AUDIT, enforcement=_DNE))
    curr = _cat(_assign("a1", Effect.AUDIT, enforcement=_ENF))
    assert validate_catalog_transition(previous=prev, current=curr) == []


def test_new_assignment_born_enforcing_needs_promotion() -> None:
    # a brand-new deny + enforce assignment activates from the shadow default
    curr = _cat(_assign("a1", Effect.DENY, enforcement=_ENF))
    issues = validate_catalog_transition(previous=_cat(), current=curr)
    # both the effect raise (audit->deny) and the enforcement activation flag
    assert any(i.rule_id == "*" for i in issues)
    assert (
        validate_catalog_transition(
            previous=_cat(), current=curr, promotions_approved=frozenset({"a1"})
        )
        == []
    )


def test_enforcement_staying_enforce_is_clean() -> None:
    # already enforcing (approved earlier) - no re-approval on an unrelated edit
    prev = _cat(_assign("a1", Effect.DENY, enforcement=_ENF))
    curr = _cat(_assign("a1", Effect.DENY, enforcement=_ENF))
    assert validate_catalog_transition(previous=prev, current=curr) == []

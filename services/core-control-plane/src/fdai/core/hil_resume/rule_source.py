"""Resolve exact catalog or server-built operator rule context without interpreting prose."""

from collections.abc import Mapping

from fdai.shared.contracts.models import Action, Rule


def resolve_parked_rule(
    parked: Mapping[str, object], *, action: Action, rules_by_id: Mapping[str, Rule]
) -> Rule | None:
    """Return known catalog context or a matching original server-validated operator rule only."""
    rule_id = str(parked.get("rule_id") or "")
    catalog_rule = rules_by_id.get(rule_id)
    if catalog_rule is not None:
        return catalog_rule
    if rule_id != f"operator.request.{action.action_type}":
        return None
    try:
        parked_rule = Rule.model_validate(parked.get("rule"))
    except ValueError:
        return None
    if (
        parked_rule.id != rule_id
        or parked_rule.remediates != action.action_type
        or parked_rule.check_logic.reference != "server-validated-operator-request"
    ):
        return None
    return parked_rule


__all__ = ["resolve_parked_rule"]

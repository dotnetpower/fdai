"""Fail-fast runtime binding for the investigation intent catalog."""

from __future__ import annotations

from pathlib import Path

import yaml

from fdai.core.read_investigation.intent_spec import READ_INVESTIGATION_INTENT_SPECS
from fdai.rule_catalog.schema.investigation_intent import (
    InvestigationIntentRegistry,
    InvestigationOwner,
    InvestigationWorkClass,
    load_investigation_intents_from_mapping,
)
from fdai.shared.providers.read_investigation import ReadInvestigationIntent


class ReadInvestigationCatalogBindingError(ValueError):
    """Raised when catalog intent authority differs from runtime bindings."""


def load_bound_investigation_intents(repo_root: Path) -> InvestigationIntentRegistry:
    """Load the shipped catalog and verify its fixed runtime ownership boundary."""

    path = repo_root / "rule-catalog" / "vocabulary" / "investigation-intents.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry = load_investigation_intents_from_mapping(raw)
    validate_investigation_intent_bindings(registry)
    return registry


def validate_investigation_intent_bindings(registry: InvestigationIntentRegistry) -> None:
    """Require exact enum coverage, Heimdall read ownership, and unique plans."""

    expected = {intent.value for intent in ReadInvestigationIntent}
    observed = set(registry.intents)
    if observed != expected:
        missing = ",".join(sorted(expected - observed)) or "none"
        extra = ",".join(sorted(observed - expected)) or "none"
        raise ReadInvestigationCatalogBindingError(
            f"investigation intent catalog mismatch: missing={missing}; extra={extra}"
        )
    invalid_owners = tuple(
        intent_id
        for intent_id, definition in registry.intents.items()
        if definition.work_class is not InvestigationWorkClass.READ
        or definition.owner_agent is not InvestigationOwner.HEIMDALL
    )
    if invalid_owners:
        raise ReadInvestigationCatalogBindingError(
            "read investigation intents require Heimdall read ownership: "
            + ",".join(sorted(invalid_owners))
        )
    plan_ids = tuple(definition.plan_id for definition in registry.intents.values())
    if len(set(plan_ids)) != len(plan_ids):
        raise ReadInvestigationCatalogBindingError(
            "read investigation intent plan_id values MUST be unique"
        )
    mismatched_plans = tuple(
        intent.value
        for intent, spec in READ_INVESTIGATION_INTENT_SPECS.items()
        if registry.intents[intent.value].plan_id != spec.plan_id
    )
    if mismatched_plans:
        raise ReadInvestigationCatalogBindingError(
            "read investigation catalog plan_id does not match runtime spec: "
            + ",".join(sorted(mismatched_plans))
        )


__all__ = [
    "ReadInvestigationCatalogBindingError",
    "load_bound_investigation_intents",
    "validate_investigation_intent_bindings",
]

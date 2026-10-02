"""Forseti-owned baseline evaluation materialization.

Forseti judges the Rule outcome for each eligible Resource. Saga remains the
audit owner: callers must provide an audit binder before final
``BaselineEvaluationOutcome`` records are written.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCompletion,
    BaselineEvaluationOutcome,
    BaselineEvaluationTerminalOutcome,
    baseline_evaluation_completion_digest,
    baseline_evaluation_outcome_digest,
)

from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t0_deterministic.models import RegoEvaluationReceipt
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_store import StateStore

BASELINE_EVALUATION_OUTCOME_PREFIX = "baseline-evaluation:outcomes:"
BASELINE_EVALUATION_COMPLETION_PREFIX = "baseline-evaluation:completions:"
_SIGNAL_TYPE = "inventory.resource_observed"
_MAX_DENOMINATOR = 10_000_000


@dataclass(frozen=True, slots=True)
class BaselineEvaluationAuditReference:
    """Saga-owned append-only audit identity bound to one evaluation record."""

    ref: str
    digest: str


BaselineEvaluationAuditBinder = Callable[
    [Mapping[str, Any]], Awaitable[BaselineEvaluationAuditReference]
]


async def record_baseline_evaluation(
    *,
    observation: PromotedInventoryObservation,
    engine: T0Engine,
    rules: tuple[Rule, ...],
    catalog_revision: str,
    audit_binder: BaselineEvaluationAuditBinder,
    state_store: StateStore,
    evaluated_at: datetime,
    evidence_fresh_after: datetime | None = None,
) -> BaselineEvaluationCompletion:
    """Evaluate a complete inventory generation and write terminal records.

    The function is idempotent by deterministic outcome and completion keys. It
    never appends audit directly; the injected ``audit_binder`` is the Saga
    boundary used to obtain a replayable audit reference.
    """

    _validate_inputs(
        observation=observation,
        rules=rules,
        catalog_revision=catalog_revision,
        evaluated_at=evaluated_at,
        evidence_fresh_after=evidence_fresh_after,
    )
    rules_by_id = {rule.id: rule for rule in rules}
    outcomes: list[BaselineEvaluationOutcome] = []
    resources = tuple(sorted(observation.resources, key=lambda item: item.resource_id))
    for resource in resources:
        verdict = engine.evaluate(
            event_id=_event_ref(observation=observation, resource=resource),
            signal_id=observation.generation,
            resource_id=resource.resource_id,
            resource_type=resource.type,
            resource_props=dict(resource.props),
            signal_type=_SIGNAL_TYPE,
        )
        hint = verdict.audit_hint
        if hint is None:
            continue
        finding_by_rule = {finding.rule_id: finding for finding in verdict.findings}
        receipt_by_rule = dict(zip(hint.citing_rule_ids, hint.evaluation_receipts, strict=False))
        for rule_id in hint.citing_rule_ids:
            rule = rules_by_id[rule_id]
            outcome, reason = _terminal_outcome(
                rule_id=rule_id,
                resource=resource,
                finding_by_rule=finding_by_rule,
                abstained_rule_ids=hint.abstained_rule_ids,
                evidence_fresh_after=evidence_fresh_after,
            )
            evaluation_ref, evaluation_digest = _evaluation_receipt_identity(
                observation=observation,
                resource=resource,
                rule=rule,
                outcome=outcome,
                reason=reason,
                receipt=receipt_by_rule.get(rule_id),
            )
            outcome_values: dict[str, object] = {
                "generation_id": _bounded_ref("generation", observation.generation),
                "generation_digest": _generation_digest(observation),
                "inventory_observation_digest": _inventory_observation_digest(observation),
                "resource_ref": _resource_ref(resource),
                "resource_digest": _resource_digest(resource),
                "catalog_revision": catalog_revision,
                "rule_ref": _bounded_ref("rule", rule.id),
                "rule_revision": _rule_revision(rule),
                "expected_denominator": 1,
                "outcome": outcome,
                "reason_code": reason,
                "evaluation_receipt_ref": evaluation_ref,
                "evaluation_receipt_digest": evaluation_digest,
                "evaluated_at": evaluated_at,
                "execution_authority": False,
            }
            audit_body = _json_mapping(outcome_values)
            audit = await audit_binder({"kind": "baseline_evaluation.outcome", **audit_body})
            outcome_values["saga_audit_ref"] = audit.ref
            outcome_values["saga_audit_digest"] = audit.digest
            outcome_values["outcome_digest"] = baseline_evaluation_outcome_digest(**outcome_values)
            outcome_record = BaselineEvaluationOutcome.model_validate(outcome_values)
            await _write_outcome(state_store, outcome_record)
            outcomes.append(outcome_record)

    completion = await _completion_record(
        observation=observation,
        catalog_revision=catalog_revision,
        outcomes=tuple(outcomes),
        evaluated_at=evaluated_at,
        audit_binder=audit_binder,
        state_store=state_store,
    )
    return completion


async def _completion_record(
    *,
    observation: PromotedInventoryObservation,
    catalog_revision: str,
    outcomes: tuple[BaselineEvaluationOutcome, ...],
    evaluated_at: datetime,
    audit_binder: BaselineEvaluationAuditBinder,
    state_store: StateStore,
) -> BaselineEvaluationCompletion:
    counts = {
        BaselineEvaluationTerminalOutcome.COMPLIANT: 0,
        BaselineEvaluationTerminalOutcome.VIOLATED: 0,
        BaselineEvaluationTerminalOutcome.ABSTAINED: 0,
    }
    for outcome in outcomes:
        counts[outcome.outcome] += 1
    outcome_set_digest = _digest_json(tuple(outcome.outcome_digest for outcome in outcomes))
    completion_values: dict[str, object] = {
        "generation_id": _bounded_ref("generation", observation.generation),
        "generation_digest": _generation_digest(observation),
        "inventory_observation_digest": _inventory_observation_digest(observation),
        "catalog_revision": catalog_revision,
        "expected_denominator": len(outcomes),
        "compliant_count": counts[BaselineEvaluationTerminalOutcome.COMPLIANT],
        "violated_count": counts[BaselineEvaluationTerminalOutcome.VIOLATED],
        "abstained_count": counts[BaselineEvaluationTerminalOutcome.ABSTAINED],
        "outcome_set_digest": outcome_set_digest,
        "completion_receipt_ref": _bounded_ref(
            "completion",
            f"{observation.generation}:{catalog_revision}:{outcome_set_digest}",
        ),
        "completion_receipt_digest": _digest_json(
            {
                "generation": observation.generation,
                "catalog_revision": catalog_revision,
                "outcomes": [outcome.outcome_digest for outcome in outcomes],
            }
        ),
        "completed_at": evaluated_at,
        "complete": True,
        "projection_authority": False,
        "execution_authority": False,
    }
    completion_audit_body = _json_mapping(completion_values)
    audit = await audit_binder({"kind": "baseline_evaluation.completion", **completion_audit_body})
    completion_values["saga_audit_ref"] = audit.ref
    completion_values["saga_audit_digest"] = audit.digest
    completion_values["completion_digest"] = baseline_evaluation_completion_digest(
        **completion_values
    )
    completion = BaselineEvaluationCompletion.model_validate(completion_values)
    await state_store.write_state(_completion_key(completion), completion.model_dump(mode="json"))
    return completion


def _terminal_outcome(
    *,
    rule_id: str,
    resource: ResourceRecord,
    finding_by_rule: Mapping[str, object],
    abstained_rule_ids: tuple[str, ...],
    evidence_fresh_after: datetime | None,
) -> tuple[BaselineEvaluationTerminalOutcome, str | None]:
    if rule_id in abstained_rule_ids:
        return BaselineEvaluationTerminalOutcome.ABSTAINED, "unsupported_evidence"
    if resource.props.get("_truncated") is True:
        return BaselineEvaluationTerminalOutcome.ABSTAINED, "unsupported_evidence"
    if evidence_fresh_after is not None:
        observed_at = _resource_seen_at(resource)
        if observed_at is None:
            return BaselineEvaluationTerminalOutcome.ABSTAINED, "missing_evidence"
        if observed_at < evidence_fresh_after:
            return BaselineEvaluationTerminalOutcome.ABSTAINED, "stale_evidence"
    if rule_id in finding_by_rule:
        return BaselineEvaluationTerminalOutcome.VIOLATED, None
    return BaselineEvaluationTerminalOutcome.COMPLIANT, None


async def _write_outcome(state_store: StateStore, outcome: BaselineEvaluationOutcome) -> None:
    await state_store.write_state(_outcome_key(outcome), outcome.model_dump(mode="json"))


def _validate_inputs(
    *,
    observation: PromotedInventoryObservation,
    rules: tuple[Rule, ...],
    catalog_revision: str,
    evaluated_at: datetime,
    evidence_fresh_after: datetime | None,
) -> None:
    if not observation.complete:
        raise ValueError("baseline evaluation requires a complete inventory generation")
    if observation.recorded_at is None or observation.recorded_at.tzinfo is None:
        raise ValueError("baseline evaluation requires a recorded inventory generation")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("baseline evaluation evaluated_at MUST be timezone-aware")
    if evidence_fresh_after is not None and (
        evidence_fresh_after.tzinfo is None or evidence_fresh_after.utcoffset() is None
    ):
        raise ValueError("baseline evaluation freshness cutoff MUST be timezone-aware")
    if not _valid_digest(catalog_revision):
        raise ValueError("baseline evaluation catalog revision MUST be a canonical digest")
    rule_ids = tuple(rule.id for rule in rules)
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("baseline evaluation rules MUST be unique")
    if len(rules) * len(observation.resources) > _MAX_DENOMINATOR:
        raise ValueError("baseline evaluation denominator exceeds the bounded maximum")


def _evaluation_receipt_identity(
    *,
    observation: PromotedInventoryObservation,
    resource: ResourceRecord,
    rule: Rule,
    outcome: BaselineEvaluationTerminalOutcome,
    reason: str | None,
    receipt: object,
) -> tuple[str, str]:
    payload = (
        asdict(receipt)
        if isinstance(receipt, RegoEvaluationReceipt)
        else {
            "generation": observation.generation,
            "resource": _resource_digest(resource),
            "rule": _rule_revision(rule),
            "outcome": outcome.value,
            "reason": reason,
        }
    )
    digest = _digest_json(payload)
    return _bounded_ref("evaluation", digest), digest


def _event_ref(*, observation: PromotedInventoryObservation, resource: ResourceRecord) -> str:
    identity = observation.generation + ":" + resource.resource_id
    return f"baseline-evaluation:{_sha256_text(identity)}"


def _resource_seen_at(resource: ResourceRecord) -> datetime | None:
    if resource.last_seen is None:
        return None
    try:
        parsed = datetime.fromisoformat(resource.last_seen.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _outcome_key(outcome: BaselineEvaluationOutcome) -> str:
    return BASELINE_EVALUATION_OUTCOME_PREFIX + outcome.outcome_digest.removeprefix("sha256:")


def _completion_key(completion: BaselineEvaluationCompletion) -> str:
    return BASELINE_EVALUATION_COMPLETION_PREFIX + completion.completion_digest.removeprefix(
        "sha256:"
    )


def _generation_digest(observation: PromotedInventoryObservation) -> str:
    return _digest_json({"generation": observation.generation})


def _inventory_observation_digest(observation: PromotedInventoryObservation) -> str:
    return _digest_json(
        {
            "generation": observation.generation,
            "resources": [
                {
                    "resource_id": resource.resource_id,
                    "type": resource.type,
                    "props": dict(resource.props),
                    "provider_ref": resource.provider_ref,
                    "last_seen": resource.last_seen,
                }
                for resource in sorted(observation.resources, key=lambda item: item.resource_id)
            ],
        }
    )


def _resource_ref(resource: ResourceRecord) -> str:
    return _bounded_ref("resource", resource.resource_id)


def _resource_digest(resource: ResourceRecord) -> str:
    return _digest_json(
        {
            "resource_id": resource.resource_id,
            "type": resource.type,
            "props": dict(resource.props),
            "provider_ref": resource.provider_ref,
            "last_seen": resource.last_seen,
        }
    )


def _rule_revision(rule: Rule) -> str:
    return _digest_json(rule.model_dump(mode="json"))


def _bounded_ref(prefix: str, value: str) -> str:
    candidate = f"{prefix}:{value}"
    normalized = candidate.replace(":", "").replace(".", "").replace("-", "").replace("_", "")
    if len(candidate) <= 160 and normalized.isalnum() and candidate[0].islower():
        return candidate
    return f"{prefix}:{_sha256_text(value)[:32]}"


def _valid_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _digest_json(value: object) -> str:
    encoded = json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"))
    return "sha256:" + _sha256_text(encoded)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaselineEvaluationTerminalOutcome):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _json_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    return {key: _json_ready(item) for key, item in value.items()}


__all__ = [
    "BASELINE_EVALUATION_COMPLETION_PREFIX",
    "BASELINE_EVALUATION_OUTCOME_PREFIX",
    "BaselineEvaluationAuditBinder",
    "BaselineEvaluationAuditReference",
    "record_baseline_evaluation",
]

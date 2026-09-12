"""Export normalized W7 observations from authoritative PostgreSQL audit records."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .campaign_import import _canonical_digest, load_cost_campaign_import_policy
from .review_targets import load_cost_readiness_targets
from .validation import CostReadinessTargetKind

_ACTION_OUTCOME = "measurement.action_outcome.v1"
_RISK_DECISION = "risk_gate.unified"
class NoCompleteCostObservationsError(ValueError):
    """The bounded source window contains no complete observation quartet."""


@dataclass(frozen=True, slots=True)
class CostReleaseQualification:
    """Digest-sealed deterministic prerequisites for one active package release."""

    source_revision: str
    revision_pin_digest: str
    ontology_competency_passed: bool
    parity_explained: bool
    evidence_refs: tuple[str, ...]
    digest: str


class PostgresCostCampaignObservationSource:
    """Read complete Cost Governance action and disclosure audit evidence."""

    def __init__(self, *, dsn: str, operator_dsn: str) -> None:
        if not dsn or not operator_dsn:
            raise ValueError("Cost campaign export DSNs MUST be configured")
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        self._operator_dsn = operator_dsn.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    async def observations(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        action_type_ids: tuple[str, ...],
        workflow_ids: frozenset[str],
        qualification: CostReleaseQualification,
        maximum_episodes: int,
    ) -> tuple[dict[str, object], ...]:
        """Return normalized observations after complete lineage joins."""

        if not start_at < end_at:
            raise ValueError("campaign export window MUST be positive")
        if not 1 <= maximum_episodes <= 1_000:
            raise ValueError("campaign export episode bound MUST be in [1, 1000]")
        async with await psycopg.AsyncConnection.connect(
            self._operator_dsn,
            row_factory=dict_row,
            connect_timeout=10,
        ) as operator_connection:
            await operator_connection.execute(
                "SELECT set_config('statement_timeout', '30000', true)"
            )
            disclosure_cursor = await operator_connection.execute(
                """
                SELECT COUNT(*) AS delivered_count,
                       COUNT(*) FILTER (WHERE NOT authorized) AS unauthorized_count
                                    FROM cost_disclosure_audit AS audit
                                    JOIN cost_disclosure_audit_retention AS retention
                                        ON retention.decision_id = audit.decision_id
                                 WHERE audit.occurred_at >= %s AND audit.occurred_at <= %s
                                     AND retention.purged_at IS NULL
                """,
                (start_at, end_at),
            )
            disclosure = await disclosure_cursor.fetchone()
        if disclosure is None:
            raise RuntimeError("Cost disclosure audit coverage is unavailable")
        if int(disclosure["delivered_count"]) < 1:
            raise NoCompleteCostObservationsError(
                "Cost campaign export has no retained disclosure audit coverage"
            )
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=10,
        ) as connection:
            await connection.execute("SELECT set_config('statement_timeout', '30000', true)")
            cursor = await connection.execute(
                """
                WITH outcomes AS (
                    SELECT DISTINCT ON (entry->>'action_id')
                           seq, entry, created_at
                      FROM audit_log
                     WHERE action_kind = %s
                       AND created_at >= %s
                       AND created_at <= %s
                       AND entry->>'execution_mode' = 'shadow'
                       AND entry->>'action_type_id' = ANY(%s)
                     ORDER BY entry->>'action_id', seq DESC
                     LIMIT %s
                )
                SELECT outcome.seq AS outcome_seq,
                       outcome.entry AS outcome_entry,
                       outcome.created_at AS outcome_created_at,
                       risk.seq AS risk_seq,
                       risk.entry AS risk_entry,
                       intent.seq AS intent_seq,
                       intent.entry AS intent_entry,
                       terminal.seq AS terminal_seq,
                       terminal.entry AS terminal_entry,
                       process.workflow_ref,
                       plan_state.value AS plan_entry
                  FROM outcomes AS outcome
                  JOIN LATERAL (
                      SELECT seq, entry
                        FROM audit_log
                       WHERE seq < outcome.seq
                         AND entry->>'action_id' = outcome.entry->>'action_id'
                         AND entry->>'audit_phase' = 'terminal'
                       ORDER BY seq DESC
                       LIMIT 1
                  ) AS terminal ON TRUE
                                    JOIN LATERAL (
                                            SELECT seq, entry
                                                FROM audit_log
                                             WHERE seq < terminal.seq
                                                    AND entry->>'action_id' =
                                                            outcome.entry->>'action_id'
                                                 AND entry->>'audit_phase' = 'intent'
                                             ORDER BY seq DESC
                                             LIMIT 1
                                    ) AS intent ON TRUE
                                    JOIN LATERAL (
                                            SELECT seq, entry
                                                FROM audit_log
                                             WHERE seq < intent.seq
                                                 AND action_kind = %s
                                                AND created_at >= %s
                                                AND entry->>'action_id' =
                                                        outcome.entry->>'action_id'
                                             ORDER BY seq DESC
                                             LIMIT 1
                                    ) AS risk ON TRUE
                  LEFT JOIN process_runtime AS process
                    ON process.process_id = terminal.entry #>> '{workflow_action,process_id}'
                                    LEFT JOIN state_kv AS plan_state
                                        ON plan_state.value->>'kind' =
                                             'operational_planning.kinetic_proposal'
                                     AND plan_state.value->>'correlation_id' =
                                             risk.entry->>'correlation_id'
                 ORDER BY outcome.created_at, outcome.seq
                """,
                (
                    _ACTION_OUTCOME,
                    start_at,
                    end_at,
                    list(action_type_ids),
                    maximum_episodes,
                    _RISK_DECISION,
                    start_at,
                ),
            )
            rows = tuple(await cursor.fetchall())
            gate_cursor = await connection.execute(
                """
                WITH decisions AS (
                    SELECT DISTINCT ON (entry->>'action_id')
                           seq, entry, created_at
                      FROM audit_log
                     WHERE action_kind = %s
                       AND created_at >= %s
                       AND created_at <= %s
                       AND entry->>'action_type_id' = ANY(%s)
                       AND entry->>'decision' IN ('deny', 'hil')
                     ORDER BY entry->>'action_id', seq DESC
                     LIMIT %s
                )
                SELECT decision.seq AS risk_seq,
                       decision.entry AS risk_entry,
                       decision.created_at AS risk_created_at,
                       process.workflow_ref,
                       plan_state.value AS plan_entry
                  FROM decisions AS decision
                  LEFT JOIN process_runtime AS process
                    ON process.process_id =
                       decision.entry #>> '{workflow_action,process_id}'
                  LEFT JOIN state_kv AS plan_state
                    ON plan_state.value->>'kind' =
                       'operational_planning.kinetic_proposal'
                   AND plan_state.value->>'correlation_id' =
                       decision.entry->>'correlation_id'
                 WHERE NOT EXISTS (
                     SELECT 1
                       FROM audit_log AS later
                      WHERE later.seq > decision.seq
                        AND later.entry->>'action_id' =
                            decision.entry->>'action_id'
                        AND (
                            later.entry->>'audit_phase' = 'terminal'
                            OR later.action_kind = %s
                        )
                 )
                 ORDER BY decision.created_at, decision.seq
                """,
                (
                    _RISK_DECISION,
                    start_at,
                    end_at,
                    list(action_type_ids),
                    maximum_episodes,
                    _ACTION_OUTCOME,
                ),
            )
            gate_rows = tuple(await gate_cursor.fetchall())
        unauthorized = int(disclosure["unauthorized_count"])
        normalized = [
            _normalize_observation(
                row,
                workflow_ids=workflow_ids,
                qualification=qualification,
                unauthorized_disclosure=unauthorized > 0,
            )
            for row in rows
        ]
        normalized.extend(
            _normalize_gate_observation(
                row,
                workflow_ids=workflow_ids,
                qualification=qualification,
                unauthorized_disclosure=unauthorized > 0,
            )
            for row in gate_rows
        )
        return tuple(
            sorted(
                normalized,
                key=lambda item: (str(item["observed_at"]), str(item["episode_id"])),
            )[:maximum_episodes]
        )


def _normalize_observation(
    row: Mapping[str, Any],
    *,
    workflow_ids: frozenset[str],
    qualification: CostReleaseQualification,
    unauthorized_disclosure: bool,
) -> dict[str, object]:
    outcome = _mapping(row["outcome_entry"], "outcome")
    risk = _mapping(row["risk_entry"], "risk")
    intent = _mapping(row["intent_entry"], "intent")
    terminal = _mapping(row["terminal_entry"], "terminal")
    action_id = _same_action_id(outcome, risk, intent, terminal)
    action_type_id = _required_text(outcome, "action_type_id")
    if terminal.get("action_kind") != action_type_id:
        raise ValueError("terminal audit ActionType does not match outcome")
    risk_decision = _required_text(risk, "decision")
    execution_mode = _required_text(outcome, "execution_mode")
    _required_text(outcome, "decision")
    policy_escape = not _decision_is_consistent(
        risk_decision=risk_decision,
        execution_mode=execution_mode,
    )
    workflow_ref = row.get("workflow_ref")
    target_refs = [action_type_id]
    if isinstance(workflow_ref, str) and workflow_ref in workflow_ids:
        target_refs.append(workflow_ref)
    settlement = _settlement(_required_text(outcome, "label"))
    rollback_succeeded = outcome.get("rollback_succeeded")
    outcome_kind = _outcome_kind(
        risk_decision=risk_decision,
        execution_mode=execution_mode,
        execution_outcome=_required_text(outcome, "execution_outcome"),
        settlement_label=_required_text(outcome, "label"),
        rollback_succeeded=rollback_succeeded,
    )
    hard_dependencies_complete = _hard_dependencies_complete(risk, terminal)
    safeguards_complete = _safeguards_complete(intent, terminal)
    protected_objectives_complete = _protected_objectives_complete(
        row.get("plan_entry"),
        action_type_id=action_type_id,
        outcome=outcome,
    )
    verification_passed = outcome.get("verification_passed") is True
    decision_correct = (
        not policy_escape
        and outcome.get("label") != "mismatch"
        and (verification_passed or risk_decision in {"deny", "hil"})
    )
    evidence_refs = tuple(
        dict.fromkeys(
            (
                *_string_list(outcome.get("evidence_refs"), "outcome evidence_refs"),
                f"audit:{int(row['risk_seq'])}",
                f"audit:{int(row['intent_seq'])}",
                f"audit:{int(row['terminal_seq'])}",
                f"audit:{int(row['outcome_seq'])}",
                *qualification.evidence_refs,
                f"qualification:{qualification.digest}",
            )
        )
    )
    observed_at = outcome.get("observed_at") or outcome.get("recorded_at")
    if not isinstance(observed_at, str):
        created_at = row.get("outcome_created_at")
        if not isinstance(created_at, datetime):
            raise ValueError("outcome observation time is unavailable")
        observed_at = created_at.astimezone(UTC).isoformat()
    return {
        "audit_complete": True,
        "decision_correct": decision_correct,
        "effect_path_complete": True,
        "episode_id": f"action-{action_id}",
        "evidence_refs": list(evidence_refs),
        "hard_dependencies_complete": hard_dependencies_complete,
        "objective_regression": outcome.get("label") == "mismatch",
        "observed_at": observed_at,
        "ontology_competency_passed": qualification.ontology_competency_passed,
        "outcome": outcome_kind,
        "parity_explained": qualification.parity_explained,
        "policy_escape": policy_escape,
        "policy_excluded": False,
        "protected_objectives_complete": protected_objectives_complete,
        "reason": f"observed.{_required_text(outcome, 'verification_reason')}",
        "recovery_attempts": _recovery_attempts(
            terminal,
            rollback=outcome_kind == "rollback",
        ),
        "rollback_evidence_complete": (
            outcome_kind != "rollback" or rollback_succeeded is True
        ),
        "safeguards_complete": safeguards_complete,
        "settlement_statuses": [settlement],
        "target_refs": target_refs,
        "topic_owner_correct": (
            risk.get("producer_principal") == "Forseti"
            and terminal.get("actor") == "fdai.core.executor.shadow"
            and outcome.get("actor") == "fdai.measurement"
        ),
        "unauthorized_disclosure": unauthorized_disclosure,
    }


def _normalize_gate_observation(
    row: Mapping[str, Any],
    *,
    workflow_ids: frozenset[str],
    qualification: CostReleaseQualification,
    unauthorized_disclosure: bool,
) -> dict[str, object]:
    risk = _mapping(row["risk_entry"], "risk")
    action_id = _required_text(risk, "action_id")
    action_type_id = _required_text(risk, "action_type_id")
    decision = _required_text(risk, "decision")
    if decision not in {"deny", "hil"}:
        raise ValueError("gate-only campaign observation MUST be deny or hil")
    workflow_ref = row.get("workflow_ref")
    target_refs = [action_type_id]
    if isinstance(workflow_ref, str) and workflow_ref in workflow_ids:
        target_refs.append(workflow_ref)
    gate_reasons = _string_list(risk.get("gate_reasons"), "gate_reasons")
    reason = gate_reasons[0] if gate_reasons else decision
    created_at = row.get("risk_created_at")
    if not isinstance(created_at, datetime):
        raise ValueError("risk decision observation time is unavailable")
    evidence_refs = (
        f"audit:{int(row['risk_seq'])}",
        *qualification.evidence_refs,
        f"qualification:{qualification.digest}",
    )
    return {
        "audit_complete": True,
        "decision_correct": False,
        "effect_path_complete": True,
        "episode_id": f"action-{action_id}",
        "evidence_refs": list(dict.fromkeys(evidence_refs)),
        "hard_dependencies_complete": _risk_dependencies_complete(risk),
        "objective_regression": False,
        "observed_at": created_at.astimezone(UTC).isoformat(),
        "ontology_competency_passed": qualification.ontology_competency_passed,
        "outcome": "deny" if decision == "deny" else "approval",
        "parity_explained": qualification.parity_explained,
        "policy_escape": False,
        "policy_excluded": False,
        "protected_objectives_complete": _protected_objectives_complete(
            row.get("plan_entry"),
            action_type_id=action_type_id,
            outcome=None,
        ),
        "reason": f"gate.{reason}",
        "recovery_attempts": 0,
        "rollback_evidence_complete": True,
        "safeguards_complete": True,
        "settlement_statuses": [],
        "target_refs": target_refs,
        "topic_owner_correct": risk.get("producer_principal") == "Forseti",
        "unauthorized_disclosure": unauthorized_disclosure,
    }


def export_cost_campaign_batch(
    *,
    campaign_id: str,
    revision_pin_digest: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Seal one canonical normalized source batch."""

    if not observations:
        raise NoCompleteCostObservationsError(
            "Cost campaign export contains no complete observations"
        )
    ordered = sorted(
        (dict(item) for item in observations),
        key=lambda item: (str(item["observed_at"]), str(item["episode_id"])),
    )
    body = {
        "campaign_id": campaign_id,
        "observations": ordered,
        "revision_pin_digest": revision_pin_digest,
        "schema_version": "1.0.0",
    }
    return {**body, "batch_digest": _canonical_digest(body)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--start-at", required=True)
    parser.add_argument("--end-at", required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    operator_dsn = os.environ.get("FDAI_OPERATOR_STORE_DSN", "").strip()
    if not dsn or not operator_dsn:
        raise ValueError("FDAI_STATE_STORE_DSN and FDAI_OPERATOR_STORE_DSN MUST be configured")
    from .validation_cli import read_current_activation

    revision_pin, enabled, activation_effective_at = await read_current_activation(dsn)
    if not enabled:
        raise ValueError("Cost Governance package MUST be enabled for campaign export")
    end_at = _timestamp(args.end_at)
    start_at = max(_timestamp(args.start_at), activation_effective_at)
    if start_at >= end_at:
        raise NoCompleteCostObservationsError(
            "Cost campaign export window predates the active release"
        )
    qualification = load_cost_release_qualification(
        args.qualification,
        source_revision=revision_pin.source_revision,
        revision_pin_digest=revision_pin.digest,
    )
    policy = load_cost_campaign_import_policy(args.policy)
    targets = load_cost_readiness_targets(args.catalog_root)
    action_type_ids = tuple(
        item.target_id for item in targets if item.kind is CostReadinessTargetKind.ACTION_TYPE
    )
    workflow_ids = frozenset(
        item.target_id for item in targets if item.kind is CostReadinessTargetKind.WORKFLOW
    )
    observations = await PostgresCostCampaignObservationSource(
        dsn=dsn,
        operator_dsn=operator_dsn,
    ).observations(
        start_at=start_at,
        end_at=end_at,
        action_type_ids=action_type_ids,
        workflow_ids=workflow_ids,
        qualification=qualification,
        maximum_episodes=policy.maximum_batch_episodes,
    )
    return export_cost_campaign_batch(
        campaign_id=args.campaign_id,
        revision_pin_digest=revision_pin.digest,
        observations=observations,
    )


def _same_action_id(*entries: Mapping[str, Any]) -> str:
    values = {_required_text(entry, "action_id") for entry in entries}
    if len(values) != 1:
        raise ValueError("campaign audit records contain mixed action identity")
    return next(iter(values))


def _decision_is_consistent(
    *,
    risk_decision: str,
    execution_mode: str,
) -> bool:
    if risk_decision == "shadow":
        return execution_mode == "shadow"
    return risk_decision == "auto" and execution_mode == "enforce"


def _hard_dependencies_complete(
    risk: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    authority = risk.get("authority")
    inputs = authority.get("ceiling_inputs") if isinstance(authority, Mapping) else None
    return bool(
        isinstance(inputs, Mapping)
        and inputs.get("system_degraded") is False
        and terminal.get("safeguard_bundle_digest")
        and terminal.get("rollback_kind")
    )


def _risk_dependencies_complete(risk: Mapping[str, Any]) -> bool:
    authority = risk.get("authority")
    inputs = authority.get("ceiling_inputs") if isinstance(authority, Mapping) else None
    return bool(
        isinstance(inputs, Mapping)
        and inputs.get("system_degraded") is False
        and inputs.get("kill_switch_engaged") is False
    )


def _safeguards_complete(
    intent: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> bool:
    return bool(
        intent.get("dry_run_passed") is True
        and intent.get("dry_run_receipt")
        and intent.get("dry_run_receipt") == terminal.get("dry_run_receipt")
        and terminal.get("safeguard_bundle_digest")
        and terminal.get("stop_condition")
        and isinstance(terminal.get("blast_radius"), Mapping)
        and terminal.get("idempotency_key")
        and terminal.get("rollback_kind")
    )


def _protected_objectives_complete(
    value: object,
    *,
    action_type_id: str,
    outcome: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    plan = value.get("operational_plan")
    if not isinstance(plan, Mapping) or plan.get("complete") is not True:
        return False
    decision_case = plan.get("decision_case")
    selection = plan.get("selection")
    proposal = value.get("proposal")
    mutation_plan = proposal.get("plan") if isinstance(proposal, Mapping) else None
    if (
        not isinstance(decision_case, Mapping)
        or not isinstance(selection, Mapping)
        or not isinstance(mutation_plan, Mapping)
        or (
            outcome is not None
            and mutation_plan.get("plan_id") != outcome.get("prediction_id")
        )
    ):
        return False
    protected = _bounded_text_set(decision_case.get("protected_objective_ids"), maximum=32)
    selected_id = selection.get("selected_option_id")
    options = decision_case.get("options")
    if not protected or not isinstance(selected_id, str) or not isinstance(options, list):
        return False
    selected = next(
        (
            option
            for option in options
            if isinstance(option, Mapping) and option.get("option_id") == selected_id
        ),
        None,
    )
    if not isinstance(selected, Mapping) or selected.get("action_type") != action_type_id:
        return False
    effects = selected.get("effects")
    if not isinstance(effects, list) or not effects:
        return False
    objective_ids: set[str] = set()
    metrics: set[str] = set()
    for effect in effects:
        if not isinstance(effect, Mapping):
            return False
        objective_id = effect.get("objective_id")
        metric = effect.get("metric")
        if not isinstance(objective_id, str) or not isinstance(metric, str):
            return False
        if effect.get("expected_min") is None or effect.get("expected_max") is None:
            return False
        objective_ids.add(objective_id)
        metrics.add(metric)
    return protected <= objective_ids and (
        outcome is None or outcome.get("metric") in metrics
    )


def load_cost_release_qualification(
    path: Path,
    *,
    source_revision: str,
    revision_pin_digest: str,
) -> CostReleaseQualification:
    """Load strict qualification evidence for exactly the active release pin."""

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Cost release qualification is unavailable or too large")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cost release qualification is invalid") from exc
    expected_fields = {
        "evidence_refs",
        "ontology_competency_passed",
        "parity_explained",
        "qualification_digest",
        "revision_pin_digest",
        "schema_version",
        "source_revision",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ValueError("Cost release qualification fields are invalid")
    expected_digest = _canonical_digest(
        {key: item for key, item in value.items() if key != "qualification_digest"}
    )
    if (
        value.get("schema_version") != "1.0.0"
        or value.get("source_revision") != source_revision
        or value.get("revision_pin_digest") != revision_pin_digest
        or value.get("qualification_digest") != expected_digest
    ):
        raise ValueError("Cost release qualification identity does not match the active release")
    competency = value.get("ontology_competency_passed")
    parity = value.get("parity_explained")
    if not isinstance(competency, bool) or not isinstance(parity, bool):
        raise ValueError("Cost release qualification results MUST be boolean")
    evidence_refs = _bounded_text_tuple(value.get("evidence_refs"), maximum=16)
    if not evidence_refs or any(
        not item.startswith("sha256:")
        or len(item) != 71
        or any(character not in "0123456789abcdef" for character in item[7:])
        for item in evidence_refs
    ):
        raise ValueError("Cost release qualification evidence refs MUST be SHA-256 digests")
    return CostReleaseQualification(
        source_revision=source_revision,
        revision_pin_digest=revision_pin_digest,
        ontology_competency_passed=competency,
        parity_explained=parity,
        evidence_refs=evidence_refs,
        digest=expected_digest,
    )


def _bounded_text_tuple(value: object, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError("Cost qualification values MUST be a bounded array")
    if any(
        not isinstance(item, str) or not item or not item.isascii() or len(item) > 512
        for item in value
    ):
        raise ValueError("Cost qualification values MUST be bounded ASCII")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError("Cost qualification values MUST be unique")
    return result


def _bounded_text_set(value: object, *, maximum: int) -> set[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        return set()
    if any(not isinstance(item, str) or not item or len(item) > 512 for item in value):
        return set()
    return set(value)


def _settlement(label: str) -> str:
    return {
        "verified": "verified",
        "mismatch": "failed",
        "unscorable": "unscorable",
    }[label]


def _outcome_kind(
    *,
    risk_decision: str,
    execution_mode: str,
    execution_outcome: str,
    settlement_label: str,
    rollback_succeeded: object,
) -> str:
    if rollback_succeeded is True:
        return "rollback"
    if risk_decision == "hil":
        return "approval"
    if risk_decision == "deny":
        return "deny"
    if any(token in execution_outcome for token in ("fail", "unknown", "hold")):
        return "hold-unresolved"
    if risk_decision == "shadow" or execution_mode == "shadow":
        return "no-op"
    return "beneficial-action" if settlement_label == "verified" else "execute"


def _recovery_attempts(terminal: Mapping[str, Any], *, rollback: bool) -> int:
    workflow_action = terminal.get("workflow_action")
    attempt = workflow_action.get("attempt") if isinstance(workflow_action, Mapping) else 1
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 8:
        raise ValueError("workflow recovery attempt MUST be in [1, 8]")
    return max(attempt - 1, 1 if rollback else 0)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} audit entry MUST be an object")
    return value


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or not item.isascii() or len(item) > 512:
        raise ValueError(f"campaign {key} MUST be bounded non-empty ASCII")
    return item


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or not item.isascii() or len(item) > 512
        for item in value
    ):
        raise ValueError(f"{label} MUST be a bounded ASCII array")
    return tuple(value)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("campaign export time MUST be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("campaign export time MUST include a timezone")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    """Export one bounded campaign artifact without promotion authority."""

    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
        args.output.write_text(
            json.dumps(result, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
    except NoCompleteCostObservationsError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (KeyError, OSError, ValueError, RuntimeError, psycopg.Error) as exc:
        print(f"Cost campaign export failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CostReleaseQualification",
    "NoCompleteCostObservationsError",
    "PostgresCostCampaignObservationSource",
    "export_cost_campaign_batch",
    "load_cost_release_qualification",
    "main",
]
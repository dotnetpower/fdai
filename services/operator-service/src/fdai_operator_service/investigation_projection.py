"""Read-only projection of adaptive investigation Process events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

_MAX_ROUNDS = 8
_MAX_HYPOTHESES = 32
_MAX_REFS = 128


def project_adaptive_investigation(
    *,
    process_id: str,
    workflow_ref: str,
    workflow_version: str,
    process_revision: int,
    events: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Return a bounded redacted Investigation Room for one Process journal."""

    if workflow_ref != "adaptive-investigation":
        return None
    created = [
        _payload(event)
        for event in events
        if _payload(event).get("record_type") == "adaptive_created"
    ]
    if len(created) != 1:
        raise ValueError("adaptive investigation projection requires one creation event")
    raw_rounds = [
        _payload(event)
        for event in events
        if _payload(event).get("record_type") == "adaptive_iteration"
    ]
    rounds = [_project_round(item) for item in raw_rounds]
    if len(rounds) > _MAX_ROUNDS:
        raise ValueError("adaptive investigation projection exceeds the round limit")
    if [item["round_index"] for item in rounds] != list(range(1, len(rounds) + 1)):
        raise ValueError("adaptive investigation projection rounds are not contiguous")
    terminals = [
        _payload(event)
        for event in events
        if _payload(event).get("record_type") == "adaptive_terminal"
    ]
    if len(terminals) > 1:
        raise ValueError("adaptive investigation projection has multiple terminal events")
    closures = [
        _payload(event)
        for event in events
        if _payload(event).get("record_type") in {"adaptive_failed", "adaptive_cancelled"}
    ]
    if len(closures) > 1 or (closures and terminals):
        raise ValueError("adaptive investigation projection has conflicting closures")
    creation = created[0]
    _validate_round_lineage(creation, raw_rounds)
    budget = _budget(creation.get("budget"))
    terminal = _project_terminal(terminals[0], rounds, budget) if terminals else None
    if terminals:
        _validate_terminal_lineage(terminals[0], raw_rounds, creation)
        _validate_persisted_result(
            terminals[0],
            raw_rounds,
            creation,
            process_id=process_id,
        )
    return {
        "read_only": True,
        "mutation_controls": False,
        "process_revision": process_revision,
        "process_id": process_id,
        "workflow_version": workflow_version,
        "incident_id": _text(creation, "incident_id"),
        "initial_frame_digest": _digest(creation, "initial_frame_digest"),
        "initial_active_set_receipt_digest": _digest(
            creation,
            "initial_active_set_receipt_digest",
        ),
        "initial_cost_model_digest": _digest(
            creation,
            "initial_cost_model_digest",
        ),
        "active_strategy_digest": _digest(creation, "active_strategy_digest"),
        "challenger_strategy_digest": _optional_digest(
            creation,
            "challenger_strategy_digest",
        ),
        "budget": budget,
        "rounds": rounds,
        "round_count": len(rounds),
        "terminal": terminal,
        "closure": (
            {
                "record_type": _text(closures[0], "record_type"),
                "reason": _text(closures[0], "reason"),
            }
            if closures
            else None
        ),
    }


def _project_round(payload: Mapping[str, object]) -> dict[str, object]:
    active_ids = _strings(payload.get("active_hypothesis_ids"), "active_hypothesis_ids")
    if not 1 <= len(active_ids) <= _MAX_HYPOTHESES:
        raise ValueError("adaptive investigation active hypothesis count is invalid")
    execution = _optional_mapping(payload.get("execution"), "execution")
    revision = _optional_mapping(payload.get("revision"), "revision")
    if execution is not None:
        if execution.get("frame_digest") != payload.get("frame_digest") or execution.get(
            "selection_digest"
        ) != payload.get("selection_digest"):
            raise ValueError("adaptive investigation execution lineage is broken")
        candidate_digest = _digest(execution, "candidate_digest")
        if payload.get("selected_candidate_id") != (
            f"observation-candidate-{candidate_digest[7:39]}"
        ):
            raise ValueError("adaptive investigation selected candidate lineage is broken")
    if revision is not None:
        if execution is None:
            raise ValueError("adaptive investigation revision requires execution evidence")
        if (
            revision.get("prior_frame_digest") != payload.get("frame_digest")
            or revision.get("prior_active_set_receipt_digest")
            != payload.get("active_set_receipt_digest")
            or revision.get("observation_result_digest") != execution.get("result_digest")
        ):
            raise ValueError("adaptive investigation hypothesis lineage is broken")
    return {
        "round_index": _integer(payload, "round_index", minimum=1, maximum=_MAX_ROUNDS),
        "iteration_digest": _digest(payload, "iteration_digest"),
        "frame_digest": _digest(payload, "frame_digest"),
        "evidence_cutoff": _text(payload, "evidence_cutoff"),
        "graph_revision": _text(payload, "graph_revision"),
        "active_hypothesis_ids": active_ids,
        "active_set_receipt_digest": _digest(payload, "active_set_receipt_digest"),
        "selection_digest": _digest(payload, "selection_digest"),
        "selected_candidate_id": _optional_text(payload, "selected_candidate_id"),
        "separated_pair_count": _integer(
            payload,
            "separated_pair_count",
            minimum=0,
            maximum=496,
        ),
        "total_pair_count": _integer(
            payload,
            "total_pair_count",
            minimum=0,
            maximum=496,
        ),
        "hold_reason": _optional_text(payload, "hold_reason"),
        "shadow_comparison_digest": _optional_digest(
            payload,
            "shadow_comparison_digest",
        ),
        "execution": (
            {
                "candidate_digest": _digest(execution, "candidate_digest"),
                "verification_receipt_digest": _digest(
                    execution,
                    "verification_receipt_digest",
                ),
                "plan_digest": _digest(execution, "plan_digest"),
                "result_digest": _digest(execution, "result_digest"),
                "execution_digest": _digest(execution, "execution_digest"),
                "query_status": _text(execution, "query_status"),
                "evidence_refs": _refs(execution.get("evidence_refs")),
                "reserved_cost_units": _integer(
                    execution,
                    "reserved_cost_units",
                    minimum=0,
                ),
                "actual_cost_units": _optional_integer(
                    execution,
                    "actual_cost_units",
                ),
            }
            if execution is not None
            else None
        ),
        "revision": (
            {
                "revision_digest": _digest(revision, "revision_digest"),
                "active_hypothesis_ids": _strings(
                    revision.get("active_hypothesis_ids"),
                    "revision.active_hypothesis_ids",
                ),
                "active_set_receipt_digest": _digest(
                    revision,
                    "active_set_receipt_digest",
                ),
                "disposition": _text(revision, "disposition"),
                "complete": _boolean(revision, "complete"),
                "truncated": _boolean(revision, "truncated"),
                "evidence_refs": _refs(revision.get("evidence_refs")),
            }
            if revision is not None
            else None
        ),
    }


def _project_terminal(
    payload: Mapping[str, object],
    rounds: Sequence[Mapping[str, object]],
    budget: Mapping[str, object],
) -> dict[str, object]:
    iteration_digests = _strings(payload.get("iteration_digests"), "iteration_digests")
    if iteration_digests != [str(item["iteration_digest"]) for item in rounds]:
        raise ValueError("adaptive investigation terminal lineage does not match rounds")
    used_queries = _integer(payload, "used_queries", minimum=0, maximum=8)
    used_cost_units = _integer(payload, "used_cost_units", minimum=0)
    execution_count = sum(item.get("execution") is not None for item in rounds)
    actual_cost = sum(
        (
            int(execution["actual_cost_units"])
            if execution.get("actual_cost_units") is not None
            else int(execution["reserved_cost_units"])
        )
        for item in rounds
        if isinstance((execution := item.get("execution")), Mapping)
    )
    if used_queries != execution_count:
        raise ValueError("adaptive investigation terminal query count does not match rounds")
    if used_cost_units != actual_cost:
        raise ValueError("adaptive investigation terminal cost does not match rounds")
    if used_queries > _integer(budget, "max_queries", minimum=1, maximum=8):
        raise ValueError("adaptive investigation terminal query count exceeds budget")
    if used_cost_units > _integer(budget, "max_cost_units", minimum=0):
        raise ValueError("adaptive investigation terminal cost exceeds budget")
    return {
        "result_digest": _digest(payload, "result_digest"),
        "disposition": _text(payload, "disposition"),
        "terminal_frame_digest": _digest(payload, "terminal_frame_digest"),
        "terminal_active_set_receipt_digest": _digest(
            payload,
            "terminal_active_set_receipt_digest",
        ),
        "used_queries": used_queries,
        "used_cost_units": used_cost_units,
    }


def _validate_round_lineage(
    creation: Mapping[str, object],
    rounds: Sequence[Mapping[str, object]],
) -> None:
    for round_payload in rounds:
        if round_payload.get("frame_digest") != _frame_digest(
            incident_id=_text(creation, "incident_id"),
            graph_revision=_text(round_payload, "graph_revision"),
            evidence_cutoff=_instant(round_payload.get("evidence_cutoff")),
            active_hypothesis_ids=_strings(
                round_payload.get("active_hypothesis_ids"),
                "active_hypothesis_ids",
            ),
            active_set_receipt_digest=_digest(
                round_payload,
                "active_set_receipt_digest",
            ),
            cost_model_digest=_digest(round_payload, "cost_model_digest"),
        ):
            raise ValueError("adaptive investigation frame digest is invalid")
    if rounds and (
        rounds[0].get("frame_digest") != creation.get("initial_frame_digest")
        or rounds[0].get("active_set_receipt_digest")
        != creation.get("initial_active_set_receipt_digest")
        or rounds[0].get("cost_model_digest") != creation.get("initial_cost_model_digest")
    ):
        raise ValueError("adaptive investigation initial frame lineage is broken")
    for previous, current in zip(rounds, rounds[1:], strict=False):
        revision = _mapping(previous.get("revision"), "revision")
        if revision.get("disposition") != "continue":
            raise ValueError("adaptive investigation advanced after a terminal revision")
        if (
            current.get("active_set_receipt_digest") != revision.get("active_set_receipt_digest")
            or current.get("graph_revision") != revision.get("graph_revision")
            or _instant(current.get("evidence_cutoff")) != _instant(revision.get("evidence_cutoff"))
            or current.get("active_hypothesis_ids") != revision.get("active_hypothesis_ids")
        ):
            raise ValueError("adaptive investigation round-to-round lineage is broken")


def _validate_terminal_lineage(
    terminal: Mapping[str, object],
    rounds: Sequence[Mapping[str, object]],
    creation: Mapping[str, object],
) -> None:
    if not rounds:
        if terminal.get("terminal_frame_digest") != creation.get(
            "initial_frame_digest"
        ) or terminal.get("terminal_active_set_receipt_digest") != creation.get(
            "initial_active_set_receipt_digest"
        ):
            raise ValueError("adaptive investigation empty terminal lineage is invalid")
        return
    last = rounds[-1]
    revision = _optional_mapping(last.get("revision"), "revision")
    disposition = terminal.get("disposition")
    if disposition in {"converged", "all_refuted"}:
        if revision is None or revision.get("disposition") != disposition:
            raise ValueError("adaptive investigation terminal revision is missing")
        if terminal.get("terminal_frame_digest") != last.get("frame_digest"):
            raise ValueError("adaptive investigation terminal frame lineage is broken")
        expected_frame = last.get("frame_digest")
    elif revision is not None and revision.get("disposition") == "continue":
        expected_frame = _frame_digest(
            incident_id=_text(creation, "incident_id"),
            graph_revision=_text(revision, "graph_revision"),
            evidence_cutoff=_instant(revision.get("evidence_cutoff")),
            active_hypothesis_ids=_strings(
                revision.get("active_hypothesis_ids"),
                "revision.active_hypothesis_ids",
            ),
            active_set_receipt_digest=_digest(
                revision,
                "active_set_receipt_digest",
            ),
            cost_model_digest=_digest(last, "cost_model_digest"),
        )
    else:
        expected_frame = last.get("frame_digest")
    expected_active_set = (
        revision.get("active_set_receipt_digest")
        if revision is not None
        else last.get("active_set_receipt_digest")
    )
    if expected_frame is not None and terminal.get("terminal_frame_digest") != expected_frame:
        raise ValueError("adaptive investigation terminal frame lineage is broken")
    if terminal.get("terminal_active_set_receipt_digest") != expected_active_set:
        raise ValueError("adaptive investigation terminal active-set lineage is broken")


def _validate_persisted_result(
    terminal: Mapping[str, object],
    rounds: Sequence[Mapping[str, object]],
    creation: Mapping[str, object],
    *,
    process_id: str,
) -> None:
    result = _mapping(terminal.get("result"), "terminal result")
    nested_iterations = result.get("iterations")
    if not isinstance(nested_iterations, list) or len(nested_iterations) != len(rounds):
        raise ValueError("adaptive investigation persisted iteration count is invalid")
    iteration_digests: list[str] = []
    for nested_value, round_payload in zip(
        nested_iterations,
        rounds,
        strict=True,
    ):
        nested = _mapping(nested_value, "persisted iteration")
        frame = _mapping(nested.get("frame"), "persisted frame")
        selection = _mapping(nested.get("selection"), "persisted selection")
        execution = _optional_mapping(
            nested.get("execution"),
            "persisted execution",
        )
        revision = _optional_mapping(
            nested.get("revision"),
            "persisted revision",
        )
        expected_frame_digest = _frame_digest(
            incident_id=_text(frame, "incident_id"),
            graph_revision=_text(frame, "graph_revision"),
            evidence_cutoff=_instant(frame.get("evidence_cutoff")),
            active_hypothesis_ids=_strings(
                frame.get("active_hypothesis_ids"),
                "persisted active_hypothesis_ids",
            ),
            active_set_receipt_digest=_digest(
                frame,
                "active_set_receipt_digest",
            ),
            cost_model_digest=_digest(frame, "cost_model_digest"),
        )
        if frame.get("frame_digest") != expected_frame_digest:
            raise ValueError("adaptive investigation persisted frame digest is invalid")
        selection_digest = _content_digest(
            {
                "schema_version": "1.0.0",
                "frame_digest": selection.get("frame_digest"),
                "method_version": selection.get("method_version"),
                "disposition": selection.get("disposition"),
                "candidate_digests": selection.get("candidate_digests"),
                "rejected_candidates": selection.get("rejected_candidates"),
                "total_pair_count": selection.get("total_pair_count"),
                "separated_pair_count": selection.get("separated_pair_count"),
                "selected_candidate_id": selection.get("selected_candidate_id"),
                "hold_reason": selection.get("hold_reason"),
            }
        )
        if selection.get("selection_digest") != selection_digest:
            raise ValueError("adaptive investigation persisted selection digest is invalid")
        execution_digest = _persisted_execution_digest(execution)
        revision_digest = _persisted_revision_digest(revision)
        iteration_digest = _content_digest(
            {
                "round_index": nested.get("round_index"),
                "frame_digest": frame.get("frame_digest"),
                "selection_digest": selection.get("selection_digest"),
                "execution_digest": execution_digest,
                "revision_digest": revision_digest,
                "shadow_comparison_digest": nested.get("shadow_comparison_digest"),
            }
        )
        if (
            nested.get("iteration_digest") != iteration_digest
            or round_payload.get("iteration_digest") != iteration_digest
            or round_payload.get("frame_digest") != frame.get("frame_digest")
            or round_payload.get("selection_digest") != selection.get("selection_digest")
        ):
            raise ValueError("adaptive investigation persisted iteration digest is invalid")
        raw_execution = _optional_mapping(
            round_payload.get("execution"),
            "round execution",
        )
        raw_revision = _optional_mapping(
            round_payload.get("revision"),
            "round revision",
        )
        if (raw_execution is None) != (execution is None) or (raw_revision is None) != (
            revision is None
        ):
            raise ValueError("adaptive investigation duplicated round evidence conflicts")
        _validate_compact_round(
            round_payload=round_payload,
            frame=frame,
            selection=selection,
            execution=execution,
            revision=revision,
            iteration_digest=iteration_digest,
            nested_round_index=nested.get("round_index"),
            nested_shadow_comparison_digest=nested.get("shadow_comparison_digest"),
        )
        if (
            execution is not None
            and raw_execution is not None
            and (
                raw_execution.get("execution_digest") != execution.get("execution_digest")
                or raw_execution.get("result_digest") != execution.get("result_digest")
            )
        ):
            raise ValueError("adaptive investigation duplicated execution evidence conflicts")
        if (
            revision is not None
            and raw_revision is not None
            and (
                raw_revision.get("revision_digest") != revision.get("revision_digest")
                or raw_revision.get("active_set_receipt_digest")
                != revision.get("active_set_receipt_digest")
            )
        ):
            raise ValueError("adaptive investigation duplicated revision evidence conflicts")
        if revision is not None and (
            execution is None or execution.get("query_status") != "completed"
        ):
            raise ValueError("adaptive investigation persisted revision lacks completed evidence")
        iteration_digests.append(iteration_digest)
    budget = _mapping(result.get("budget"), "persisted budget")
    creation_budget = _mapping(creation.get("budget"), "creation budget")
    result_digest = _content_digest(
        {
            "session_id": result.get("session_id"),
            "incident_id": result.get("incident_id"),
            "workflow_version": result.get("workflow_version"),
            "reducer_version": result.get("reducer_version"),
            "active_strategy_digest": result.get("active_strategy_digest"),
            "challenger_strategy_digest": result.get("challenger_strategy_digest"),
            "budget": {
                "max_rounds": budget.get("max_rounds"),
                "max_queries": budget.get("max_queries"),
                "max_cost_units": budget.get("max_cost_units"),
                "deadline_at": _instant(budget.get("deadline_at"))
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "policy_digest": budget.get("policy_digest"),
            },
            "iteration_digests": iteration_digests,
            "disposition": result.get("disposition"),
            "terminal_frame_digest": result.get("terminal_frame_digest"),
            "terminal_active_set_receipt_digest": result.get("terminal_active_set_receipt_digest"),
            "used_queries": result.get("used_queries"),
            "used_cost_units": result.get("used_cost_units"),
            "execution_authority": False,
        }
    )
    if (
        result.get("result_digest") != result_digest
        or terminal.get("result_digest") != result_digest
        or result.get("incident_id") != creation.get("incident_id")
        or result.get("session_id") != process_id
        or result.get("workflow_version") != "1.0.0"
        or result.get("reducer_version") != "adaptive-investigation-reducer-v1"
        or result.get("active_strategy_digest") != creation.get("active_strategy_digest")
        or result.get("challenger_strategy_digest") != creation.get("challenger_strategy_digest")
        or result.get("disposition") != terminal.get("disposition")
        or result.get("terminal_frame_digest") != terminal.get("terminal_frame_digest")
        or result.get("terminal_active_set_receipt_digest")
        != terminal.get("terminal_active_set_receipt_digest")
        or result.get("used_queries") != terminal.get("used_queries")
        or result.get("used_cost_units") != terminal.get("used_cost_units")
        or budget.get("max_rounds") != creation_budget.get("max_rounds")
        or budget.get("max_queries") != creation_budget.get("max_queries")
        or budget.get("max_cost_units") != creation_budget.get("max_cost_units")
        or budget.get("policy_digest") != creation_budget.get("policy_digest")
        or _instant(budget.get("deadline_at")) != _instant(creation_budget.get("deadline_at"))
    ):
        raise ValueError("adaptive investigation persisted terminal result is invalid")


def _validate_compact_round(
    *,
    round_payload: Mapping[str, object],
    frame: Mapping[str, object],
    selection: Mapping[str, object],
    execution: Mapping[str, object] | None,
    revision: Mapping[str, object] | None,
    iteration_digest: str,
    nested_round_index: object,
    nested_shadow_comparison_digest: object,
) -> None:
    expected_top = {
        "round_index": nested_round_index,
        "iteration_digest": iteration_digest,
        "frame_digest": frame.get("frame_digest"),
        "graph_revision": frame.get("graph_revision"),
        "cost_model_digest": frame.get("cost_model_digest"),
        "active_hypothesis_ids": frame.get("active_hypothesis_ids"),
        "active_set_receipt_digest": frame.get("active_set_receipt_digest"),
        "selection_digest": selection.get("selection_digest"),
        "selected_candidate_id": selection.get("selected_candidate_id"),
        "separated_pair_count": selection.get("separated_pair_count"),
        "total_pair_count": selection.get("total_pair_count"),
        "hold_reason": selection.get("hold_reason"),
        "shadow_comparison_digest": nested_shadow_comparison_digest,
    }
    if any(round_payload.get(key) != value for key, value in expected_top.items()):
        raise ValueError("adaptive investigation compact round conflicts")
    if _instant(round_payload.get("evidence_cutoff")) != _instant(frame.get("evidence_cutoff")):
        raise ValueError("adaptive investigation compact cutoff conflicts")
    expected_execution = (
        {
            key: execution.get(key)
            for key in (
                "frame_digest",
                "selection_digest",
                "candidate_digest",
                "binding_digest",
                "verification_receipt_digest",
                "plan_digest",
                "result_digest",
                "execution_digest",
                "query_status",
                "evidence_refs",
                "reserved_cost_units",
                "actual_cost_units",
            )
        }
        if execution is not None
        else None
    )
    if round_payload.get("execution") != expected_execution:
        raise ValueError("adaptive investigation compact execution conflicts")
    expected_revision = (
        {
            key: revision.get(key)
            for key in (
                "revision_digest",
                "prior_active_set_receipt_digest",
                "prior_frame_digest",
                "observation_result_digest",
                "scorer_version",
                "graph_revision",
                "evidence_cutoff",
                "active_hypothesis_ids",
                "active_set_receipt_digest",
                "disposition",
                "complete",
                "truncated",
                "evidence_refs",
            )
        }
        if revision is not None
        else None
    )
    if round_payload.get("revision") != expected_revision:
        raise ValueError("adaptive investigation compact revision conflicts")


def _persisted_execution_digest(
    execution: Mapping[str, object] | None,
) -> str | None:
    if execution is None:
        return None
    digest = _content_digest(
        {
            "round_index": execution.get("round_index"),
            "frame_digest": execution.get("frame_digest"),
            "selection_digest": execution.get("selection_digest"),
            "candidate_digest": execution.get("candidate_digest"),
            "binding_digest": execution.get("binding_digest"),
            "verification_receipt_digest": execution.get("verification_receipt_digest"),
            "plan_digest": execution.get("plan_digest"),
            "result_digest": execution.get("result_digest"),
            "query_status": execution.get("query_status"),
            "evidence_refs": execution.get("evidence_refs"),
            "reserved_cost_units": execution.get("reserved_cost_units"),
            "actual_cost_units": execution.get("actual_cost_units"),
            "execution_authority": False,
            "mutation_authority": False,
        }
    )
    if execution.get("execution_digest") != digest:
        raise ValueError("adaptive investigation persisted execution digest is invalid")
    return digest


def _persisted_revision_digest(
    revision: Mapping[str, object] | None,
) -> str | None:
    if revision is None:
        return None
    digest = _content_digest(
        {
            "prior_active_set_receipt_digest": revision.get("prior_active_set_receipt_digest"),
            "prior_frame_digest": revision.get("prior_frame_digest"),
            "observation_result_digest": revision.get("observation_result_digest"),
            "scorer_version": revision.get("scorer_version"),
            "graph_revision": revision.get("graph_revision"),
            "evidence_cutoff": _instant(revision.get("evidence_cutoff"))
            .astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "active_hypothesis_ids": revision.get("active_hypothesis_ids"),
            "active_set_receipt_digest": revision.get("active_set_receipt_digest"),
            "evidence_refs": revision.get("evidence_refs"),
            "complete": revision.get("complete"),
            "truncated": revision.get("truncated"),
            "disposition": revision.get("disposition"),
            "owner_agent": "Forseti",
            "execution_authority": False,
        }
    )
    if revision.get("revision_digest") != digest:
        raise ValueError("adaptive investigation persisted revision digest is invalid")
    return digest


def _content_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _budget(value: object) -> dict[str, object]:
    budget = _mapping(value, "budget")
    return {
        "max_rounds": _integer(budget, "max_rounds", minimum=1, maximum=8),
        "max_queries": _integer(budget, "max_queries", minimum=1, maximum=8),
        "max_cost_units": _integer(budget, "max_cost_units", minimum=0),
        "deadline_at": _text(budget, "deadline_at"),
        "policy_digest": _digest(budget, "policy_digest"),
    }


def _payload(event: Mapping[str, object]) -> dict[str, Any]:
    return _mapping(event.get("payload"), "event payload")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"adaptive investigation {label} MUST be an object")
    return dict(value)


def _optional_mapping(value: object, label: str) -> dict[str, Any] | None:
    return None if value is None else _mapping(value, label)


def _text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"adaptive investigation {key} MUST be bounded text")
    return value


def _optional_text(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    return None if value is None else _text(values, key)


def _digest(values: Mapping[str, object], key: str) -> str:
    value = _text(values, key)
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"adaptive investigation {key} MUST be a SHA-256 digest")
    return value


def _optional_digest(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    return None if value is None else _digest(values, key)


def _integer(
    values: Mapping[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int = 1_000_000_000,
) -> int:
    value = values.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"adaptive investigation {key} MUST be a bounded integer")
    return value


def _boolean(values: Mapping[str, object], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"adaptive investigation {key} MUST be boolean")
    return value


def _optional_integer(
    values: Mapping[str, object],
    key: str,
) -> int | None:
    return None if values.get(key) is None else _integer(values, key, minimum=0)


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or len(item) > 512 for item in value
    ):
        raise ValueError(f"adaptive investigation {label} MUST be bounded strings")
    return value


def _refs(value: object) -> list[str]:
    refs = _strings(value, "evidence_refs")
    if len(refs) > _MAX_REFS:
        raise ValueError("adaptive investigation evidence_refs exceed the limit")
    return refs


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("adaptive investigation evidence cutoff MUST be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("adaptive investigation evidence cutoff MUST be timezone-aware")
    return parsed


def _frame_digest(
    *,
    incident_id: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    active_hypothesis_ids: Sequence[str],
    active_set_receipt_digest: str,
    cost_model_digest: str,
) -> str:
    material = {
        "schema_version": "1.0.0",
        "incident_id": incident_id,
        "graph_revision": graph_revision,
        "evidence_cutoff": evidence_cutoff.astimezone(UTC)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        ),
        "active_hypothesis_ids": list(active_hypothesis_ids),
        "active_set_receipt_digest": active_set_receipt_digest,
        "cost_model_digest": cost_model_digest,
    }
    encoded = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["project_adaptive_investigation"]

"""Atomic authority record for the reviewed human reporting graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from fdai.core.human_reporting.graph import ReportingGraphSnapshot, build_reporting_graph
from fdai.core.human_reporting.model import (
    ReportingLineCase,
    ReportingLineCaseState,
    ReportingLineModelError,
    normalize_principal,
    reporting_instant,
)
from fdai.shared.providers.state_store import StateStore

GRAPH_KEY: Final = "human_reporting:graph"
_MAX_GRAPH_CASES: Final = 5_000


async def activate_reporting_case(
    store: StateStore,
    candidate: ReportingLineCase,
    *,
    actor_ref: str,
    at: datetime,
) -> ReportingGraphSnapshot:
    """Atomically add one approved edge to the authoritative graph case set."""

    if candidate.state is not ReportingLineCaseState.ACTIVE:
        raise ReportingLineModelError("only an active reviewed edge can enter the graph")
    observed_at = reporting_instant(at)
    for _attempt in range(3):
        raw = await store.read_state(GRAPH_KEY)
        revision, cases = _decode_graph_record(raw)
        existing = next((item for item in cases if item.case_id == candidate.case_id), None)
        if existing is not None:
            if existing != candidate:
                raise ReportingLineModelError(
                    "reporting-line graph case id is bound to different evidence"
                )
            return build_reporting_graph(cases, at=observed_at)
        updated_cases = (*cases, candidate)
        _validate_graph_history(
            updated_cases,
            changed=candidate,
            enforce_bound=False,
        )
        retained_cases = _retained_graph_cases(updated_cases, at=observed_at)
        _validate_graph_history(retained_cases)
        graph = build_reporting_graph(retained_cases, at=observed_at)
        record = _graph_record(revision + 1, retained_cases)
        audit = {
            "actor": normalize_principal(actor_ref),
            "action_kind": "human.reporting.graph_activated",
            "case_id": candidate.case_id,
            "edge_digest": candidate.edge_digest,
            "graph_revision": graph.revision,
            "recorded_at": observed_at.isoformat(),
            "mode": "shadow",
            "approval_authority": False,
            "execution_authority": False,
        }
        applied = (
            await store.write_state_with_audit_if_absent(GRAPH_KEY, record, audit)
            if raw is None
            else await store.compare_and_set_state_with_audit(
                GRAPH_KEY,
                record,
                expected_revision=revision,
                audit_entry=audit,
            )
        )
        if applied:
            return graph
    raise ReportingLineModelError("reporting-line graph changed during activation")


async def validate_reporting_case_activation(
    store: StateStore,
    candidate: ReportingLineCase,
    *,
    at: datetime,
) -> ReportingGraphSnapshot:
    """Validate a proposed activation without mutating the graph authority."""

    if candidate.state is not ReportingLineCaseState.ACTIVE:
        raise ReportingLineModelError("only an active reviewed edge can enter the graph")
    observed_at = reporting_instant(at)
    raw = await store.read_state(GRAPH_KEY)
    _revision, cases = _decode_graph_record(raw)
    existing = next((item for item in cases if item.case_id == candidate.case_id), None)
    if existing is not None:
        if existing != candidate:
            raise ReportingLineModelError(
                "reporting-line graph case id is bound to different evidence"
            )
        return build_reporting_graph(cases, at=observed_at)
    updated_cases = (*cases, candidate)
    _validate_graph_history(
        updated_cases,
        changed=candidate,
        enforce_bound=False,
    )
    retained_cases = _retained_graph_cases(updated_cases, at=observed_at)
    _validate_graph_history(retained_cases)
    return build_reporting_graph(retained_cases, at=observed_at)


async def load_reporting_graph(
    store: StateStore,
    *,
    at: datetime,
) -> ReportingGraphSnapshot:
    """Verify record integrity and build the current graph at one effective instant.

    Activation validates every historical boundary before the aggregate CAS. Replaying that
    quadratic validation on each approval read would block the async control-plane hot path.
    """

    raw = await store.read_state(GRAPH_KEY)
    _revision, cases = _decode_graph_record(raw)
    return build_reporting_graph(cases, at=reporting_instant(at))


def _validate_graph_history(
    cases: tuple[ReportingLineCase, ...],
    *,
    changed: ReportingLineCase | None = None,
    enforce_bound: bool = True,
) -> None:
    if enforce_bound and len(cases) > _MAX_GRAPH_CASES:
        raise ReportingLineModelError("reporting-line graph exceeds its case bound")
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ReportingLineModelError("reporting-line graph contains duplicate cases")
    if any(case.state is not ReportingLineCaseState.ACTIVE for case in cases):
        raise ReportingLineModelError("reporting-line graph contains an unreviewed edge")
    boundaries = {case.effective_from for case in cases}
    if changed is not None:
        boundaries = {
            boundary
            for boundary in boundaries
            if changed.effective_from <= boundary < changed.effective_until
        }
        boundaries.add(changed.effective_from)
    for boundary in sorted(boundaries):
        build_reporting_graph(cases, at=boundary)


def _retained_graph_cases(
    cases: tuple[ReportingLineCase, ...],
    *,
    at: datetime,
) -> tuple[ReportingLineCase, ...]:
    superseded = {
        case.supersedes_case_id
        for case in cases
        if case.supersedes_case_id is not None and case.effective_from <= at
    }
    return tuple(
        case for case in cases if case.effective_until > at and case.case_id not in superseded
    )


def _graph_record(
    revision: int,
    cases: tuple[ReportingLineCase, ...],
) -> dict[str, object]:
    material = [case.to_dict() for case in sorted(cases, key=lambda item: item.case_id)]
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "case_set_digest": _case_set_digest(material),
        "cases": material,
    }


def _decode_graph_record(
    value: Mapping[str, Any] | None,
) -> tuple[int, tuple[ReportingLineCase, ...]]:
    if value is None:
        return 0, ()
    revision = value.get("revision")
    cases = value.get("cases")
    if (
        value.get("schema_version") != "1.0.0"
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not isinstance(cases, list)
    ):
        raise ReportingLineModelError("reporting-line graph record is malformed")
    material = [_mapping(item) for item in cases]
    if value.get("case_set_digest") != _case_set_digest(material):
        raise ReportingLineModelError("reporting-line graph case-set digest does not match")
    return revision, tuple(ReportingLineCase.from_dict(item) for item in material)


def _case_set_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportingLineModelError("reporting-line graph case MUST be an object")
    return value


__all__ = [
    "GRAPH_KEY",
    "activate_reporting_case",
    "load_reporting_graph",
    "validate_reporting_case_activation",
]

"""Bounded read-only scoped ownership reporting inside existing assignment reconciliation.

Responsibility: Publish expiring observations of independently reviewed exact scoped artifacts.
Boundary: No case review, map application, IAM, permission, notification or promotion writes.
Authority and state: Core owns only the observation snapshot; it grants no operating authority.
Dependencies: Current catalog and reviewed artifact reader with atomic StateStore audit.
Deployment: Same Core reconciliation callback locally and deployed, without a new daemon.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fdai.core.human_assignment.scoped_duty_case_model import SCOPED_CASE_PREFIX, ScopedDutyCase
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService
from fdai.core.human_assignment.scoped_duty_ownership import ScopedDutyOwnership
from fdai.delivery.identity.scoped_duty_catalog import FileScopedDutyCatalog

SCOPED_OBSERVATION_KEY = "human_assignment:scoped-observation"


@dataclass(frozen=True, slots=True)
class ScopedDutyProjectionPublisher:
    """Fail closed on incomplete scans or conflicts; report observations, never install duties."""

    cases: ScopedDutyCaseService
    catalog: FileScopedDutyCatalog
    ownership: ScopedDutyOwnership | None = None

    async def publish(self) -> None:
        """Perform one bounded pass; whole-pass failure never refreshes an old snapshot."""
        async with asyncio.timeout(120):
            await self._publish()

    async def _publish(self) -> None:
        cases = self.cases
        snapshot = await self.catalog.snapshot()
        existing = await cases.store.read_state(SCOPED_OBSERVATION_KEY)
        admitted = _retained_ids(existing, "admitted_case_ids")
        superseded = _retained_ids(existing, "superseded_case_ids")
        raw_cases, total = await cases.store.read_state_page(SCOPED_CASE_PREFIX, limit=20, offset=0)
        partial = total > len(raw_cases)
        invalid = 0
        candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for raw in raw_cases:
            try:
                case = ScopedDutyCase.model_validate(raw)
            except ValueError:
                invalid += 1
                continue
            if case.state != "ownership_pr_open" or case.case_id in superseded:
                continue
            now = cases.clock()
            targets = {
                (row.agent_name, row.scope_ref)
                for row in case.request.bindings
                if row.effective_from <= now < row.effective_until
            }
            try:
                rows = (
                    await self.ownership.observe(case)
                    if not partial and self.ownership is not None
                    else ()
                )
            except (ValueError, PermissionError, TimeoutError):
                rows = ()
            if rows:
                admitted.add(case.case_id)
                if case.request.supersedes_case_id is not None:
                    superseded.add(case.request.supersedes_case_id)
            elif not partial and case.case_id not in admitted:
                continue
            by_scope = {(str(row["agent_name"]), str(row["scope_ref"])): row for row in rows}
            for pair in targets:
                candidates[pair].append(
                    dict(
                        by_scope.get(
                            pair,
                            {
                                "agent_name": pair[0],
                                "scope_ref": pair[1],
                                "case_id": case.case_id,
                                "held_reasons": ["current_reviewed_artifact_unavailable"],
                            },
                        )
                    )
                )
        if (await self.catalog.snapshot()).revision != snapshot.revision:
            raise ValueError("scoped catalog changed during projection")
        at = cases.clock()
        items: list[dict[str, Any]] = []
        expires = at + timedelta(seconds=60)
        for (agent, scope), alternatives in sorted(candidates.items()):
            alternatives = [row for row in alternatives if row.get("case_id") not in superseded]
            if not alternatives:
                continue
            row = alternatives[0]
            reason = (
                "incomplete_scoped_case_scan"
                if partial or invalid
                else "overlapping_reviewed_cases"
                if len(alternatives) != 1
                else "current_reviewed_artifact_unavailable"
                if row.get("held_reasons")
                else None
            )
            if reason is None:
                end = datetime.fromisoformat(str(row["expires_at"]))
                if end <= at:
                    reason = "scoped_observation_expired"
                else:
                    expires = min(expires, end)
            if reason is not None:
                items.append(
                    {
                        "agent_name": agent,
                        "scope_ref": scope,
                        "state": "held",
                        "held_reasons": [reason],
                        "primary_refs": [],
                        "backup_refs": [],
                        "escalation_refs": [],
                        "execution_authority": False,
                    }
                )
            else:
                items.append({**row, "state": "observed", "execution_authority": False})
        previous_revision = 0 if existing is None else existing.get("revision")
        if type(previous_revision) is not int:
            raise ValueError("scoped observation revision is invalid")
        if len(admitted) > 1000 or len(superseded) > 1000:
            raise ValueError("scoped observation history reached its retention bound")
        value = {
            "schema_version": "1.0.0",
            "revision": previous_revision + 1,
            "source_revision": snapshot.revision,
            "scopes": sorted(snapshot.scopes),
            "observed_at": at.isoformat(),
            "expires_at": expires.isoformat(),
            "items": items,
            "total_cases": total,
            "sampled_cases": len(raw_cases),
            "invalid_cases": invalid,
            "partial": partial,
            "execution_authority": False,
            "projection_authority": False,
            "mode": "shadow",
            "artifact_delivery_available": self.ownership is not None,
            "admitted_case_ids": sorted(admitted),
            "superseded_case_ids": sorted(superseded),
        }
        audit = {
            "actor": "Saga",
            "action_kind": "human.scoped_duty.observed",
            "revision": value["revision"],
            "recorded_at": value["observed_at"],
            "source_revision": snapshot.revision,
            "sampled_cases": len(raw_cases),
            "partial": partial,
            "invalid_cases": invalid,
            "execution_authority": False,
        }
        if existing is None:
            applied = await cases.store.write_state_with_audit_if_absent(
                SCOPED_OBSERVATION_KEY, value, audit
            )
        else:
            if datetime.fromisoformat(str(existing["observed_at"])) > at:
                raise ValueError("scoped observation clock moved backwards")
            applied = await cases.store.compare_and_set_state_with_audit(
                SCOPED_OBSERVATION_KEY,
                value,
                expected_revision=previous_revision,
                audit_entry=audit,
            )
        if not applied:
            raise ValueError("scoped observation changed during publication")


def _retained_ids(existing: Mapping[str, Any] | None, field: str) -> set[str]:
    """Retain historical negative supersession; an expired snapshot grants no positive duty."""
    values = [] if existing is None else existing.get(field, [])
    if not isinstance(values, list) or len(values) > 1000:
        raise ValueError("scoped observation history is malformed or over-bound")
    for value in values:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("scoped observation history contains an invalid case identity")
    return set(values)


__all__ = ["SCOPED_OBSERVATION_KEY", "ScopedDutyProjectionPublisher"]

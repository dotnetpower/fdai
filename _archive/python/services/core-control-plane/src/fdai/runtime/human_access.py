"""Fail-fast Core membership planning; privileged dispatch belongs only to isolated Executor."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

import httpx

from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.rbac.roles import Role
from fdai.delivery.identity import HumanAccessDirectApiExecutor
from fdai.shared.providers.direct_api import DirectApiExecutor
from fdai.shared.providers.state_store import StateStore

_ROUTINE_ROLES = frozenset({Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER})


def build_human_access_direct_api(
    *,
    audit_store: StateStore,
    http_client: httpx.AsyncClient | None,
    environment: Mapping[str, str] = os.environ,
    enabled: bool = True,
) -> DirectApiExecutor | None:
    """Bind read-only planning from the group map without reading any mutation credentials.

    ``http_client`` is retained for caller compatibility and is intentionally unused.
    Neither enabling this capability nor a configured identity raises Core authority.
    """
    del http_client
    if not enabled:
        return None
    raw = environment.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "").strip()
    if not raw:
        return None
    role_group_ids = _parse_role_group_ids(raw)
    cases = AssignmentCaseService(audit_store)
    return HumanAccessDirectApiExecutor(
        HumanAccessPlanner(cases, role_group_ids),
        replacement=ReplacementCoveragePlanner(cases, role_group_ids),
    )


def _parse_role_group_ids(raw: str) -> dict[Role, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON MUST be valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON MUST be an object")
    expected = {role.value for role in _ROUTINE_ROLES}
    if set(payload) != expected:
        raise RuntimeError(
            "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON MUST define Reader, Contributor, "
            "Approver, and Owner"
        )
    values = [
        group_id.strip().casefold() if isinstance(group_id, str) else group_id
        for group_id in payload.values()
    ]
    if any(not isinstance(group_id, str) or not group_id.strip() for group_id in values):
        raise RuntimeError("human access role group ids MUST be non-empty strings")
    if len(set(values)) != len(values):
        raise RuntimeError("human access role group ids MUST be distinct")
    return {
        Role(role_name): str(group_id).strip().casefold() for role_name, group_id in payload.items()
    }


__all__ = ["build_human_access_direct_api"]

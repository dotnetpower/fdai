"""Fail-fast runtime binding for privileged Entra human access."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

import httpx

from fdai.core.human_assignment import AssignmentCaseService, HumanAccessApplyCoordinator
from fdai.core.rbac.roles import Role
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.identity import EntraHumanAccessProvisioner, HumanAccessDirectApiExecutor
from fdai.runtime.bootstrap_bindings import human_access_identity_client_id
from fdai.shared.providers.direct_api import DirectApiExecutor
from fdai.shared.providers.state_store import StateStore

_ROUTINE_ROLES = frozenset({Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER})


def build_human_access_direct_api(
    *,
    audit_store: StateStore,
    http_client: httpx.AsyncClient | None,
    environment: Mapping[str, str] = os.environ,
) -> DirectApiExecutor | None:
    raw = environment.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "").strip()
    if not raw:
        return None
    if http_client is None:
        raise RuntimeError("human access binding requires a shared HTTP client")
    human_access_identity_client_id(environment)
    role_group_ids = _parse_role_group_ids(raw)
    identity = ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        env=environment,
        client_id_env="FDAI_HUMAN_ACCESS_MI_CLIENT_ID",
    )
    provisioner = EntraHumanAccessProvisioner(
        client=http_client,
        identity=identity,
        allowed_group_ids=frozenset(role_group_ids.values()),
    )
    return HumanAccessDirectApiExecutor(
        HumanAccessApplyCoordinator(
            AssignmentCaseService(audit_store),
            provisioner,
            role_group_ids,
        )
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
        group_id.strip() if isinstance(group_id, str) else group_id for group_id in payload.values()
    ]
    if any(not isinstance(group_id, str) or not group_id.strip() for group_id in values):
        raise RuntimeError("human access role group ids MUST be non-empty strings")
    if len(set(values)) != len(values):
        raise RuntimeError("human access role group ids MUST be distinct")
    return {Role(role_name): str(group_id).strip() for role_name, group_id in payload.items()}


__all__ = ["build_human_access_direct_api"]

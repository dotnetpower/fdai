"""Independent automation-hold recheck for the isolated effect boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from fdai_service_contracts.executor import Action

from fdai_executor_service.ports import ExecutorStateStore

_HOLD_KEY_PREFIX = "workflow:automation-hold:"
_AUTHORIZATION_KEY_PREFIX = "workflow:automation-hold-dispatch-authorization:"
_HOLD_SCOPED_AUTHORIZATION = "hold_scoped"
_RELEASED_AUTHORIZATION = "released"


async def automation_hold_refusal(
    action: Action,
    *,
    state_store: ExecutorStateStore,
) -> str | None:
    """Return why the current hold state denies this exact action."""

    target_digest = hashlib.sha256(action.target_resource_ref.encode()).hexdigest()
    hold = await state_store.read_state(f"{_HOLD_KEY_PREFIX}{target_digest}")
    workflow_action = action.workflow_action
    authorization: Mapping[str, object] | None = None
    if workflow_action is not None:
        identity = f"{target_digest}\0{workflow_action.process_id}\0{workflow_action.step_id}"
        authorization_digest = hashlib.sha256(identity.encode()).hexdigest()
        authorization = await state_store.read_state(
            f"{_AUTHORIZATION_KEY_PREFIX}{authorization_digest}"
        )

    if hold is None:
        if authorization is None:
            return None
        return "automation hold authorization exists without matching hold state"
    if hold.get("target_digest") != target_digest or not _positive_int(hold.get("revision")):
        return "automation hold state is malformed"

    state = hold.get("state")
    if state == "active":
        if workflow_action is None:
            return "active automation hold blocks provider invocation"
        revision = hold["revision"]
        if not _active_authorization_matches(
            authorization,
            target_digest=target_digest,
            process_id=workflow_action.process_id,
            step_id=workflow_action.step_id,
            hold_process_id=hold.get("process_id"),
            hold_revision=revision,
        ):
            return "active automation hold lacks exact recovery-step authorization"
        return None

    if state == "released":
        if workflow_action is None or authorization is None:
            return None
        if not _released_authorization_matches(
            authorization,
            hold,
            target_digest=target_digest,
            process_id=workflow_action.process_id,
            step_id=workflow_action.step_id,
        ):
            return "released automation hold lineage does not match this workflow step"
        return None

    return "automation hold state is malformed"


def _active_authorization_matches(
    authorization: Mapping[str, object] | None,
    *,
    target_digest: str,
    process_id: str,
    step_id: str,
    hold_process_id: object,
    hold_revision: object,
) -> bool:
    return bool(
        authorization is not None
        and authorization.get("authorization_kind") == _HOLD_SCOPED_AUTHORIZATION
        and authorization.get("target_digest") == f"sha256:{target_digest}"
        and authorization.get("process_id") == process_id
        and authorization.get("step_id") == step_id
        and hold_process_id == process_id
        and _positive_int(authorization.get("authorized_hold_revision"))
        and authorization.get("authorized_hold_revision") == hold_revision
        and authorization.get("execution_authority") is False
    )


def _released_authorization_matches(
    authorization: Mapping[str, object],
    hold: Mapping[str, object],
    *,
    target_digest: str,
    process_id: str,
    step_id: str,
) -> bool:
    release_receipt = hold.get("release_receipt")
    if not isinstance(release_receipt, Mapping):
        return False
    fencing_generation = hold.get("fencing_generation")
    released_revision = authorization.get("released_hold_revision")
    receipt_digest = authorization.get("release_receipt_digest")
    return bool(
        authorization.get("authorization_kind") == _RELEASED_AUTHORIZATION
        and authorization.get("target_digest") == f"sha256:{target_digest}"
        and authorization.get("process_id") == process_id
        and authorization.get("step_id") == step_id
        and authorization.get("execution_authority") is False
        and _positive_int(released_revision)
        and _positive_int(fencing_generation)
        and authorization.get("fencing_generation") == fencing_generation
        and hold.get("revision") == fencing_generation
        and release_receipt.get("receipt_digest") == receipt_digest
        and release_receipt.get("released_hold_revision") == released_revision
        and release_receipt.get("fencing_generation") == fencing_generation
    )


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


__all__ = ["automation_hold_refusal"]

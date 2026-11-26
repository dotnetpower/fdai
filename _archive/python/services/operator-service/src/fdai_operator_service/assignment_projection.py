"""Join Core-owned assignment effects without treating Operator reviews as convergence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fdai_service_contracts.assignment_transport import AssignmentCaseResult


class AssignmentProjectionSource(Protocol):
    """Read canonical Core namespaces; Operator database permissions prohibit their writes."""

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


async def join_assignment_case(
    source: AssignmentProjectionSource, projected: dict[str, object]
) -> dict[str, object]:
    """Keep accepted commands visible, but only an exact Core snapshot reports effects."""
    operator_id = str(projected["case_id"])
    binding = await source.read_state(f"human_assignment:operator-case:{operator_id}")
    if binding is None:
        return {**projected, "convergence_status": "awaiting_core", "execution_authority": False}
    case_id = binding.get("case_id")
    digest = binding.get("request_digest")
    if not isinstance(case_id, str) or not isinstance(digest, str):
        raise ValueError("assignment Core reference is malformed")
    current = await source.read_state(f"human_assignment:case:{case_id}")
    if current is None:
        return {**projected, "convergence_status": "core_unavailable", "execution_authority": False}
    commands = current.get("command_receipts")
    expected = {"proposal_id": operator_id, "request_digest": digest}
    if not isinstance(commands, list) or expected not in commands:
        raise ValueError("assignment Core snapshot does not match the Operator creation")
    effects = current.get("effect_receipts")
    if not isinstance(effects, list) or any(not isinstance(item, Mapping) for item in effects):
        raise ValueError("assignment Core effects are malformed")
    by_kind = {item.get("kind"): item.get("receipt_ref") for item in effects}
    intent = current.get("intent")
    revoke = isinstance(intent, Mapping) and intent.get("revocation") is not None
    if revoke and current.get("state") == "active":
        raise ValueError("revocation cannot project an active assignment")
    result = AssignmentCaseResult.model_validate(
        {
            **({"schema_version": "1.1.0"} if revoke else {}),
            "proposal_id": operator_id,
            "request_digest": digest,
            "operator_case_id": operator_id,
            "case_id": case_id,
            "state": current.get("state"),
            "revision": current.get("revision"),
            "ownership_effect_ref": by_kind.get("ownership"),
            "iam_effect_ref": by_kind.get("iam"),
        }
    )
    return {
        **projected,
        "state": result.state,
        "revision": result.revision,
        "reviews": current.get("reviews", []),
        "effect_receipts": effects,
        "core_case_id": result.case_id,
        "convergence_status": "core_observed",
        "degraded_reason": current.get("degraded_reason"),
        "superseded_by": current.get("superseded_by"),
        "execution_authority": False,
    }


__all__ = ["AssignmentProjectionSource", "join_assignment_case"]

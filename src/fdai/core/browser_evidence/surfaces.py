"""Evidence-only console and workflow submission surfaces."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fdai.core.browser_evidence.service import BrowserEvidenceCaptureService
from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult
from fdai.core.runbook.models import RunbookStep
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureRequest,
    BrowserEvidenceReceipt,
)


class BrowserEvidenceConsoleTool:
    """Submit a typed capture request without exposing a browser handle."""

    name = "capture_browser_evidence"
    description = "Capture bounded read-only evidence under a server-owned origin policy."
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, service: BrowserEvidenceCaptureService) -> None:
        self._service = service

    async def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        request_id = str(uuid.uuid4())
        receipt = await self._service.capture(
            _request_from_values(
                request_id=request_id,
                correlation_id=f"console:{principal.id}:{request_id}",
                values=arguments,
            )
        )
        return _tool_result(receipt)


class BrowserEvidenceWorkflowStepDispatcher:
    """Dispatch only the dedicated workflow evidence step kind."""

    def __init__(self, service: BrowserEvidenceCaptureService) -> None:
        self._service = service

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        params: Mapping[str, object],
    ) -> BrowserEvidenceReceipt:
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{process_id}:{step.id}"))
        return await self._service.capture(
            _request_from_values(
                request_id=request_id,
                correlation_id=correlation_id,
                values=params,
            )
        )


def _request_from_values(
    *,
    request_id: str,
    correlation_id: str,
    values: Mapping[str, object],
) -> BrowserCaptureRequest:
    policy_id = _string(values, "policy_id")
    source_url = _string(values, "source_url")
    policy_version = _integer(values, "policy_version")
    selectors_raw = values.get("stable_selectors", "main")
    if not isinstance(selectors_raw, str):
        raise TypeError("stable_selectors MUST be a comma-separated string")
    selectors = tuple(item.strip() for item in selectors_raw.split(",") if item.strip())
    if not selectors:
        raise ValueError("stable_selectors MUST contain at least one selector")
    return BrowserCaptureRequest(
        request_id=request_id,
        policy_id=policy_id,
        policy_version=policy_version,
        source_url=source_url,
        stable_selectors=selectors,
        capture_kinds=("screenshot", "visible_text", "aria_snapshot"),
        correlation_id=correlation_id,
    )


def _tool_result(receipt: BrowserEvidenceReceipt) -> ToolResult:
    return ToolResult(
        status="ok" if receipt.status == "captured" else "abstain",
        data={
            "request_id": receipt.request_id,
            "status": receipt.status,
            "artifact_id": receipt.artifact_id,
            "content_digest": receipt.content_digest,
            "custody_ref": receipt.chain_of_custody_audit_ref,
            "reason": receipt.reason,
            "untrusted": True,
            "can_authorize_action": False,
        },
        preview=f"capture_browser_evidence: {receipt.status}",
        evidence_refs=(receipt.artifact_id,) if receipt.artifact_id is not None else (),
    )


def _string(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} MUST be a non-empty string")
    return value


def _integer(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} MUST be an integer")
    return value


__all__ = ["BrowserEvidenceConsoleTool", "BrowserEvidenceWorkflowStepDispatcher"]
